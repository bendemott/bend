# coding: utf-8
"""
The server module contains everything required by the process server.

The server module cannot be run on its own. The indended use for this
module is to be imported from a command-line launcher script, and for
its run_server() method to be called. An example script would be as
such:
	
  from stockpile.processing.server import run_server
	
  if __name__ == "__main__":
    exit(run_server())

Monitor Types:
	PROGRESS (str)
	- Register to monitor a process' progress: {monitor_progress!r}.
	REALTIME (str)
	- Register to monitor a process' real-time output: {monitor_realtime!r}.

Process States:
	STATE_NOTRUNNING (str)
	- The process is not running: {state_notrunning!r}.
	STATE_QUEUED (str)
	- The process is queued to be run: {state_queued!r}.
	STATE_ZOMBIE (str)
	- The process has completed execution, but has not yet been reaped:
	  {state_zombie!r}.
	STATE_STARTING (str)
	- The process is starting up: {state_starting!r}.
	STATE_WORKING(str)
	- The process is performing work: {state_working!r}.
	STATE_FINISHED (str)
	- The process has finished working: {state_finished!r}.
	STATE_TERMINATING (str)
	- The process is currently being terminated: {state_terminating!r}.
	STATE_TERMINATED (str)
	- The process has terminated: {state_terminated!r}.

TODO:
- Support processes in a zombie state. A process is a zombie if it's
  done executing, but it has not yet been reaped. A process is reaped
  once it calls the remote "finish_process" server method. A process
  will not be reaped if the server is shutdown or restarted before the
  process finishes executing. Therefore, when the process server is
  started, it should check for unreaped (zombie) processes and reap them
  accordingly (record process name, instance ID, exit status and time of
  completion).
  - NOTE: The generated run-time directories for processes lie under the
    server variable directory: "{{var_dir}}/processes/{{proc_id}}".
  - Reaping Processes:
    - When the server is started, "{{var_dir}}/processes" should be
      checked for process directories.
    - Any process directory that contains a "process.exit" is a finished
      process that needs to be reaped (a zombie).
      - If a "process.pid" also exists, then the process has finished
        working but hasn't actually stopped so it should be killed.
    - Any process directory that contains a "process.pid" (but no
      "process.exit") is a running process and should be indicated as
      such.
      - We should probably try connecting to the process... processes
        should then have a "process.socket" file?
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import dateutil.parser as _dateutil_parser
import errno as _errno
import os as _os
import re as _re
import signal as _signal
import sqlite3 as _sqlite3
import sys as _sys
import time as _time
import traceback as _traceback

from twisted.internet import defer as _defer, reactor as _reactor, threads as _threads
from twisted.python import failure as _failure
from twisted.spread import pb as _pb

import process as _process

PROGRESS = 'progress'
REALTIME = 'realtime'

STATE_NOTRUNNING = 'not-running'
STATE_QUEUED = 'queued'
STATE_ZOMBIE = 'zombie'
STATE_STARTING = 'starting'
STATE_WORKING = 'working'
STATE_FINISHED = 'finished'
STATE_TERMINATING = 'terminating'
STATE_TERMINATED = 'terminated'

__doc__ = __doc__.format(
	monitor_progress=PROGRESS,
	monitor_realtime=REALTIME,
	state_notrunning=STATE_NOTRUNNING,
	state_queued=STATE_QUEUED,
	state_zombie=STATE_ZOMBIE,
	state_starting=STATE_STARTING,
	state_working=STATE_WORKING,
	state_finished=STATE_FINISHED,
	state_terminating=STATE_TERMINATING,
	state_terminated=STATE_TERMINATED
)

_dir = _os.path.dirname(_os.path.abspath(__file__))

_mon_types = (PROGRESS, REALTIME)
_mon_types_err = ', '.join(('"%s"' % t for t in _mon_types))
_mon_all_types = (PROGRESS,)
_mon_all_types_err = ', '.join(('"%s"' % t for t in _mon_all_types))

_err_pass = lambda r: None
_err_print = lambda r: r.printTraceback(file=_sys.stderr)

_db_procs_tb = 'processes'

_proc_keys = ('name', 'title', 'desc', 'mtime')

_state_funcs = {
	STATE_NOTRUNNING: 'monitor_notrunning',
	STATE_STARTING: 'monitor_starting',
	STATE_WORKING: 'monitor_working',
	STATE_FINISHED: 'monitor_finished',
	STATE_TERMINATING: 'monitor_terminating',
	STATE_TERMINATED: 'monitor_terminated'
}

_start_check = 1.0 # Check starting processes every 1 s.
_start_term = 5.0  # Terminate starting processes after 5 s.
_work_check = 2.0  # Check working processes every 2 s.
_work_term = 30.0  # Terminate working processes after 30 s.

_mon_fin_intvl = 1.0  # Check finished processes every 1 s.
_mon_fin_kill = 2.0   # Kill finished processes after 2 s.
_mon_term_intvl = 1.0 # Check terminating processes every 1 s.
_mon_term_kill = 5.0  # Kill terminating processes after 5 s.
_proc_normal = 1.0    # Check normal processes every second.
_proc_stream = 0.2    # Check streaming processes every 200 ms.
_proc_known = 300.0   # Check processes directory every 5 min.

_re_close_dquote = _re.compile(r'''
(?<!\\)   # Negative lookbehind matching escape.
(?:\\\\)* # Match escaped escapes without capturing.
"         # Match closing double-quote.
''', _re.DOTALL | _re.VERBOSE)

_re_close_sqbracket = _re.compile(r"""
(?<!\\)   # Negative lookbehind matching escape.
(?:\\\\)* # Match escaped escapes without capturing.
\]        # Match closing square bracket.
""", _re.DOTALL | _re.VERBOSE)

_syslog_nil = '-'

def _delete_dirs(dirs):
	"""
	Recursively removes all sub-directories and files from the specified
	directories.
	
	Arguments:
		dirs (list)
		- The list of directories (str) to delete.
	"""
	for clear_dir in dirs:
		for dirpath, dirnames, filenames in _os.walk(clear_dir, topdown=False):
			for filename in filenames:
				try:
					_os.remove(_os.path.join(dirpath, filename))
				except Exception:
					pass
			for dirname in dirnames:
				try:
					path = _os.path.join(dirpath, dirname)
					if _os.path.islink(path):
						_os.remove(path)
					else:
						_os.rmdir(path)
				except Exception:
					pass
		try:
			_os.rmdir(clear_dir)
		except Exception:
			pass
			
def _get_pid(pid_file):
	"""
	Returns the PID from the specified PID file.
	
	Arguments:
		pid_file (str)
		- The PID filepath.
		
	Returns:
		(int)
		- The PID from the file.
	"""
	with open(pid_file) as fh:
		return int(fh.readline().strip())

def _get_processes(process_names):
	"""
	Returns the specified processes.
	
	Arguments:
		process_names (list)
		- The process names (str).
		
	Returns:
		(dict)
		- The either the modified processes class (Process) or config
		  (dict); keyed by process name. If there's an error getting the
		  process, its value will be the reason (`twisted.python.failure.
		  Failure`) for failure.
	"""
	procs = dict.fromkeys(process_names)
	for proc_name in process_names:
		try:
			proc = _process.get_process(proc_name)
		except Exception:
			proc = _failure.Failure()
		procs[proc_name] = proc
	return procs

def _get_processes_modified(processes):
	"""
	Returns the processes that have been modified.
	
	Arguments:
		processes (dict)
		- The process modified UTC times (float); keyed by process name (str).
	
	Returns:
		(dict)
		- Either the modified processes class (Process) or config (dict);
		  keyed by process name. If there's an error getting the process,
		  its value will be the reason (twisted.python.failure.Failure) for
		  failure.
	"""
	err_procs = {}
	get_procs = []
	for proc_name, proc_mtime in processes.iteritems():
		try:
			proc_file, proc_type = _process.find_process(proc_name)
			stat_file = proc_file + "/__init__.py" if proc_type == _process.MODULE else proc_file
			if int(_os.stat(stat_file).st_mtime) > int(proc_mtime):
				get_procs.append(proc_name)
		except Exception:
			err_procs[proc_name] = _failure.Failure()
	if get_procs:
		procs = _get_processes(get_procs)
		procs.update(err_procs)
	else:
		procs = err_procs
	
	return procs

def is_graph(string):
	"""
	Determines whether the string contains only ASCII graphical characters
	or not.
	
	Arguments:
		string (str) -- The string to check.
		
	Returns:
		(bool) -- On success, `True`; otherwise, `False`.
	"""
	return not [0 for char in string if not 0x21 <= ord(char) <= 0x7E]

def parse_syslog(entry):
	"""
	Parses a syslog entry.
	
	Arguments:
		entry (str) -- The syslog entry.
	
	Returns:
		header (dict)
		- Contains the following header information: the priority (int) in
		  'prival'; the version (int) in 'version'; the timestamp (datetime)
		  in 'timestamp'; the host (str) in 'hostname', the application
		  (str) in 'appname'; the process ID (str) in 'procid' (which is not
		  strictly an OS PID); and the message type (str) in 'msgid'.
		data (dict)
		- Contains elements keyed by IDs (str); each element is a dict
		  containing values (unicode) keyed by names (str).
		message (mixed)
		- Either a string of an unspecified encoding (str) or a unicode
		  string (unicode).
	"""

	r"""
	6. Syslog Message Format (http://tools.ietf.org/html/rfc5424#section-6)

	The syslog message has the following ABNF [RFC5234] definition:

	SYSLOG-MSG      = HEADER SP STRUCTURED-DATA [SP MSG]

	HEADER          = PRI VERSION SP TIMESTAMP SP HOSTNAME
			              SP APP-NAME SP PROCID SP MSGID
	PRI             = "<" PRIVAL ">"
	PRIVAL          = 1*3DIGIT ; range 0 .. 191
	VERSION         = NONZERO-DIGIT 0*2DIGIT
	HOSTNAME        = NILVALUE / 1*255PRINTUSASCII

	APP-NAME        = NILVALUE / 1*48PRINTUSASCII
	PROCID          = NILVALUE / 1*128PRINTUSASCII
	MSGID           = NILVALUE / 1*32PRINTUSASCII

	TIMESTAMP       = NILVALUE / FULL-DATE "T" FULL-TIME
	FULL-DATE       = DATE-FULLYEAR "-" DATE-MONTH "-" DATE-MDAY
	DATE-FULLYEAR   = 4DIGIT
	DATE-MONTH      = 2DIGIT  ; 01-12
	DATE-MDAY       = 2DIGIT  ; 01-28, 01-29, 01-30, 01-31 based on
			                      ; month/year
	FULL-TIME       = PARTIAL-TIME TIME-OFFSET
	PARTIAL-TIME    = TIME-HOUR ":" TIME-MINUTE ":" TIME-SECOND
			              [TIME-SECFRAC]
	TIME-HOUR       = 2DIGIT  ; 00-23
	TIME-MINUTE     = 2DIGIT  ; 00-59
	TIME-SECOND     = 2DIGIT  ; 00-59
	TIME-SECFRAC    = "." 1*6DIGIT
	TIME-OFFSET     = "Z" / TIME-NUMOFFSET
	TIME-NUMOFFSET  = ("+" / "-") TIME-HOUR ":" TIME-MINUTE

	STRUCTURED-DATA = NILVALUE / 1*SD-ELEMENT
	SD-ELEMENT      = "[" SD-ID *(SP SD-PARAM) "]"
	SD-PARAM        = PARAM-NAME "=" %d34 PARAM-VALUE %d34
	SD-ID           = SD-NAME
	PARAM-NAME      = SD-NAME
	PARAM-VALUE     = UTF-8-STRING ; characters '"', '\' and
			                           ; ']' MUST be escaped.
	SD-NAME         = 1*32PRINTUSASCII
			              ; except '=', SP, ']', %d34 (")

	MSG             = MSG-ANY / MSG-UTF8
	MSG-ANY         = *OCTET ; not starting with BOM
	MSG-UTF8        = BOM UTF-8-STRING
	BOM             = %xEF.BB.BF
	UTF-8-STRING    = *OCTET ; UTF-8 string as specified
	                         ; in RFC 3629
	                         
	OCTET           = %d00-255
	SP              = %d32
	PRINTUSASCII    = %d33-126
	NONZERO-DIGIT   = %d49-57
	DIGIT           = %d48 / NONZERO-DIGIT
	NILVALUE        = "-"
	"""
	head = {}
	
	# Parse header.
	# header ::= pri version " " timestamp " " hostname " " appname " " procid
	#            " " msgid
	bhead = entry.split(' ', 6)
	bcnt = len(bhead)
	
	# Parse pri.
	# pri ::= "<" 1-3*digit ">" ; range 0-191
	pri = bhead[0]
	if pri[0] != '<':
		raise ValueError("entry[header][pri]:%r does not being with a '<'." % pri)
	end = pri.find('>')
	if end == -1:
		raise ValueError("entry[header][pri]:%r does not end with a '>'." % pri)
	prival = pri[1:end]
	head['prival'] = int(prival)
	
	# Parse version.
	# version ::= nonzero 0-2*digit
	version = pri[end+1:]
	head['version'] = int(version)
	if bcnt <= 1:
		raise ValueError("entry[header][version]:%r does not end with a ' '." % version)
	
	# Parse timestamp.
	# timestamp ::= nil | date "T" time
	# date ::= year "-" month "-" mday
	# year ::= 4*digit
	# month ::= 2*digit ; range 01-12
	# mday ::= 2*digit ; range 01-28 to 01-31 (based on month/year)
	# time ::= hour ":" minute ":" second ["." secfrac] offset
	# hour ::= 2*digit ; range 01-12
	# minute ::= 2*digit ; range 00-59
	# second ::= 2*digit ; range 00-59
	# secfrac ::= 1-6*digit
	# offset ::= "Z" | ("+" | "-") hour ":" minute
	timestamp = bhead[1]
	head['timestamp'] = _dateutil_parser.parse(timestamp) if timestamp != _syslog_nil else None
	if bcnt <= 2:
		raise ValueError("entry[header][timestamp]:%r does not end with a space:%r." % (timestamp, ' '))
	
	# Parse hostname.
	# msgid ::= nil | 1-255*ascii_graph
	hostname = bhead[2]
	if not is_graph(hostname):
		raise ValueError("entry[header][hostname]:%r contains non-print ASCII characters." % hostname)
	elif not hostname or len(hostname) > 255:
		raise ValueError("entry[header][hostname]:%r (len:%r) is not between 1 and 255 characters long." % (hostname, len(hostname)))
	head['hostname'] = hostname if hostname != _syslog_nil else None
	if bcnt <= 3:
		raise ValueError("entry[header][hostname]:%r does not end with a space:%r." % (hostname, ' '))
	
	# Parse appname.
	# appname ::= nil | 1-48*ascii_graph
	appname = bhead[3]
	if not is_graph(appname):
		raise ValueError("entry[header][appname]:%r contains non-print ASCII characters." % appname)
	elif not appname or len(appname) > 48:
		raise ValueError("entry[header][appname]:%r (len:%r) is not between 1 and 48 characters long." % (appname, len(appname)))
	head['appname'] = appname if appname != _syslog_nil else None
	if bcnt <= 4:
		raise ValueError("entry[header][appname]:%r does not end with a space:%r." % (appname, ' '))
		
	# Parse procid.
	# procid ::= nil | 1-128*ascii_graph
	procid = bhead[4]
	if not is_graph(procid):
		raise ValueError("entry[header][procid]:%r contains non-print ASCII characters." % procid)
	elif not procid or len(procid) > 128:
		raise ValueError("entry[header][pricid]:%r (len:%r) is not between 1 and 128 characters long." % (procid, len(procid)))
	head['procid'] = procid if procid != _syslog_nil else None
	if bcnt <= 5:
		raise ValueError("entry[header][procid]:%r does not end with a space:%r." % (procid, ' '))
	
	# Parse msgid.
	# msgid ::= nil | 1-32*ascii_graph
	msgid = bhead[5]
	if not is_graph(msgid):
		raise ValueError("entry[header][msgid]:%r contains non-print ASCII characters." % msgid)
	elif not msgid or len(msgid) > 32:
		raise ValueError("entry[header][msgid]:%r (len:%r) is not between 1 and 32 characters long." % (msgid, len(msgid)))
	head['msgid'] = msgid if msgid != _syslog_nil else None
	if bcnt <= 6:
		raise ValueError("entry[header][msgid]:%r does not end with a space:%r." % (msgid, ' '))
	
	# Parse structured-data.
	# structured-data ::= nil | element+
	data = {}
	bdata = bhead[6]
	blen = len(bdata)
	if bdata == _syslog_nil:
		bstart = len(_syslog_nil)
	else:
		eidx = 0
		bstart = 0
		while 1:
			# element ::= "[" id (" " param)* "]"
			# id ::= 1-32*ascii_graph
			if not bdata[bstart] == '[':
				raise ValueError("entry[structured-data][%i]:%r does not begin with a space:%r." % (eidx, bdata[bstart:], ' '))
			eend = bdata.find(']', bstart)
			if eend == -1:
				raise ValueError("entry[structured-data][%i]:%r does not end with a right-square-bracket:%r." % (eidx, bdata[bstart:], ']'))
			pstart = bdata.find(' ', bstart, eend)
			if pstart == -1:
				eid = bdata[bstart+1:eend]
				edata = None
			else:
				eid = bdata[bstart+1:pstart]
				edata = {} 
				pidx = 0
				while 1:
					# param ::= name "=" '"' value '"'
					# name ::= 1-32*ascii_graph
					# value ::= utf8_string
					psep = bdata.find('=', pstart+1, eend)
					if psep == -1:
						raise ValueError("entry[structured-data][%r][%i]:%r does not contain an equals-sign:%r separating name and value." % (eid, pidx, bdata[pstart+1:], '='))
					pname = bdata[pstart+1:psep]
					if not pname or len(pname) > 32:
						raise ValueError("entry[structured-data][%r][%i][name]:%r (len:%r) is not between 1 and 32 characters long." % (eid, pidx, pname, len(pname)))
					if bdata[psep+1] != '"':
						raise ValueError("entry[structured-data][%r][%i][value]:%r does not begin with a double-quote:%r." % (eid, pidx, bdata[psep+1:], '"'))
					res = _re_close_dquote.search(bdata, psep+2)
					if not res:
						raise ValueError("entry[structured-data][%r][%i][value]:%r does not end with a double-quote:%r." % (eid, pidx, bdata[psep+1:], '"'))
					pend = res.end(0)
					pvalue = bdata[psep+2:pend-1]
					edata[pname] = unicode(pvalue, 'utf-8')
					pidx += 1

					pstart = pend
					if bdata[pstart] == ' ':
						# If the next byte is a space, we have another parameter for
						# this element.
						if pstart > eend:
							eend = bdata.find(']', pstart)
							if eend == -1:
								raise ValueError("entry[structured-data][%r]:%r does not end with a right-square-bracket:%r." % (eid, bdata[bstart+1:], ']'))
					elif bdata[pstart] == ']':
						# If the next byte is a right-square-bracket, we're done with this
						# element.
						bstart = pstart+1
						break
					else:
						raise ValueError("entry[structured-data][%r][%i]:%r is not followed by a space:%r or right-square-bracket:%r." % (eid, pidx, bdata[psep+1:], ' ', ']'))
					
				
				data[eid] = edata
				eidx += 1
				
				if bstart >= blen or bdata[bstart] == ' ':
					# Since the byte after the end of the previous element either
					# points beyond the data or is a space, we're done with the
					# data elements.
					break
		
	# Parse msg.
	# msg ::= msg_any | msg_utf8
	# msg_any ::= octet+ ; no starting BOM.
	# msg_utf8 ::= 0xEFBBBF utf8_string
	if bstart >= blen:
		msg = ''
	else:
		if bdata[bstart] != ' ':
			raise ValueError("entry[message]:%r does not begin with a space:%r." % (bdata[bstart:], ' '))
		msg = bdata[bstart+1:]
		if msg[:3] == '\xEF\xBB\xBF':
			msg = unicode(msg[3:], 'utf-8')
	
	# Return header, structured-data and message.
	return head, data, msg

def print_failure(reason):
	"""
	Prints the failure to stderr.
	
	Arguments:
		reason (twisted.python.failure.Failure) -- The reason for failure.
	"""
	_sys.stderr.write(reason.getErrorMessage() + '\n')
	reason.printTraceback(_sys.stderr)

def run_server(args=None):
	"""
	The default function for running the process server from the command
	line.
	
	Optional Arguments:
		args (list)
		- The command line arguments to use (including the command-line name
		  in the first index); default is `sys.argv`.
	
	Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
	"""
	import optparse
	
	if not args:
		args = _sys.argv
		
	# Parse options.
	prog = _os.path.basename(args[0])
	parser = optparse.OptionParser(prog=prog)
	parser.add_option('-n', '--name', dest='name', help='The name of the Process Server; default is %r.' % _process.SERVER)
	parser.add_option('-p', '--client-port', dest='port', help='The port on which the Process Server listens for clients; default is `%r`.' % _process.CLIENT_PORT)
	parser.add_option('-r', '--run-prefix', dest='run', help='The run-time file data directory prefix (e.g., %r); default is %r.' % (_process.PREFIX_USR_RUN, _process.PREFIX_LOCAL_RUN))
	parser.add_option('-t', '--tmp-prefix', dest='tmp', help='The temporory file data directory prefix; default is %r.' % _process.PREFIX_TMP)
	parser.add_option('-v', '--var-prefix', dest='var', help='The variable file data directory prefix (e.g., %r); default is %r.' % (_process.PREFIX_USR_VAR, _process.PREFIX_LOCAL_VAR))
	parser.add_option('-d', '--debug', dest='debug', help="Enable server debugging.", action='store_true')
	options, args = parser.parse_args(args[1:])
	
	# Get options.
	name = options.name
	port = options.port
	run = options.run
	tmp = options.tmp
	var = options.var
	debug = options.debug
	
	# Start server.
	server = ProcessServer(app_name=name, client_port=port, run_prefix=run, tmp_prefix=tmp, var_prefix=var, debug=debug)
	return server.main()


class ProcessInfo:
	"""
	The Process Info class contains information about a process.
	
	To query data from the process, use bracket notation to get the
	information. The allowed data keys are any public instance attributes
	of a ProcessInfo or ProcessInstance instance.
	
	Instance Attribute:
		_inst (ProcessInstance)
		- When the process is running, its instance.
		_state (str)
		- Set when the process itself (not an instance) has a state that prevents
		  instances from being run.
		name (str)
		- The name of the process.
		title (str)
		- The title of the process.
		desc (str)
		- A description of the process.
		mtime (float)
		- The time (UTC) that the process was last modified (this is used when
		  checking to see if a process needs its information updated).
	"""
	
	def __init__(self, name, title, desc, mtime):
		"""
		Instantiates a Process Info instance.
		
		Arguments:
			name (str)
			- The name of the process.
			title (str)
			- The title of the process.
			desc (str)
			- A description of the process.
			mtime (float)
			- The time (UTC) that the process was last modified.
		"""
		self._inst = None
		self._state = None
		self.name = name
		self.title = title
		self.desc = desc
		self.mtime = mtime
		
	def __contains__(self, key):
		"""
		Returns whether an item is set for the specified key.
		
		Arguments:
		  key (str)
		  - The item key.
			
		Returns:
		  (bool)
		  - If an item is set for the key, `True`; otherwise, `False`.
		"""
		if key and isinstance(key, basestring) and key[0] != '_':
			return key == 'state' or hasattr(self, key) or (self._inst and hasattr(self._inst, key))
		return False
		
	def __getitem__(self, key):
		"""
		Returns the item for the specified key.
		
		Arguments:
			key (str)
			- The item key.
			
		Returns:
			(mixed)
			- The item.
		"""
		if not isinstance(key, basestring):
			raise TypeError("key:%r is not a string." % key)
		if key[0] != '_':
			if key == 'state':
				# Return the process state.
				return self._get_state()
			if hasattr(self, key):
				# Return this process info attribute.
				return getattr(self, key)
			elif self._inst and hasattr(self._inst, key):
				# Return process instance attribute.
				return getattr(self._inst, key)
		raise KeyError("key:%r does not exist." % key)
	
	def _get_state(self):
		"""
		Returns the state of the process.
		
		Returns:
			(str)
			- The state of the process.
		"""
		return (self._state if self._state else self._inst.state if self._inst else None) or STATE_NOTRUNNING


class ProcessInstance:
	"""
	The Process Instance class contains information pertaining to a
	process instance (i.e., a process that's running).
	
	Instance Attributes:
		_ref (twisted.spread.pb.RemoteReference)
		- the reference to the process instance.
		id (int)
		- The process instance ID.
		name (str)
		- The name of the process.
		state (str)
		- The process instance state.
		started (float)
		- The time (UTC) that the process instance was started.
		registered (float)
		- The time (UTC) that the process instance was registered.
		updated (float)
		- The time (UTC) that the process instance's status was last
		  updated.
		pid (int)
		- The OS PID of the process instance.
		progress (float)
		- The progress of the process instance: between 0 and 1.
		
	Temporary Instance Attributes:
		_token (str)
		- The server provided token to use when registering (this is used
		  when the server starts the process).
		_finished (float)
		- The time (UTC) at which the process instance finished working.
		_terminated (float)
		- The time (UTC) at which the process instance was ordered to
		  terminate.
	"""

	def __init__(self, id, name, started):
		"""
		Instantiates a ProcessInstance instance.
		
		Arguments:
			id (int)
			- The process instance ID.
			name (str)
			- The name of the process.
			started (float)
			- The time (UTC) that the process instance was started.
		"""
		self._ref = None
		self.id = id
		self.name = name
		self.state = STATE_STARTING
		self.started = started
		self.registered = None
		self.updated = None
		self.pid = None
		self.progress = 0


class ProcessServer(_pb.Root):
	"""
	The Process Server class manages processes.
	
	Instance Attributes:
		app_name (str)
		- The name of the Process Server Application.
		debug (bool)
		- Whether debugging is enabled or not.
		exit (int)
		- The exit code the server returns when it's stopped.
		var_prefix (str)
		- The variable file data directory prefix (e.g., "/var" or
		  "/var/local").
		tmp_prefix (str)
		- The temporary file data directory previx (e.g., "/tmp").
		run_prefix (str)
		- The run-time file data directory prefix (e.g., "/var/run" or
		  "/var/local/run").
		run_dir (str)
		- The run-time file data directory: "{run_prefix}/{app_name}".
		tmp_dir (str)
		- The temporary directory: "{tmp_prefix}/{app_name}".
		var_dir (str)
		- The variable file data directory: "{var_prefix}/lib/{app_name}".
		log_dir (str)
		- The log files directory: "{var_prefix}/log/{app_name}".
		
		client_port (int)
		- The port on which clients are listened for.
		procs_db (ProcessDatabase)
		- The database that stores information about running processes.
		procs_dbfile (str)
		- The processes database file "{var_dir}/processes.sqlite3"
		procs_socket (str)
		- The UNIX socket file "{run_dir}/{app_name}.socket" that processes
		  connect to.
		
		procs_info (dict)
		- Information (ProcessInfo) pertaining to all known processes; keyed
		  by process name (str).
		procs_id (dict)
		- The IDs of running process instances (starting or registered);
		  keyed by process name (str).
		procs_inst (dict)
		- The process instances (ProcessInstance) that are running (starting
		  or registered); keyed by process instance ID (int).
		procs_start (dict)
		- The process instances (ProcessInstance) that are starting but are
		  not yet registered; keyed by a 2-tuple: the process name (str) and
		  token (str).
		procs_reg (dict)
		- The process instances (ProcessInstance) that are running and
		  registered; keyed by process instance ID (int).
		procs_fin (dict)
		- The process instances (ProcessInstance) that are have finished
		  working up but have not yet stopped; keyed by process instance ID
		  (str).
		procs_term (dict)
		- The process instances (ProcessInstance) that are being terminated
		  but have not yet stopped; keyed by process instance ID (str).
		procs_mon (dict)
		- The processes (dict) being monitored; keyed by monitor type (str).
		  The processes dict contains the list (set) of clients references
		  registered (twisted.spread.pb.RemoteReference) per process,
		  process instance and all processes; keyed by process name (str),
		  process instance ID (int) or '*' (str) for all processes.
		 
		mon_fin_intvl (float)
		- The interval (seconds) at which finished processes are checked to
		  see if they have stopped.
		mon_fin_kill (float)
		- The duration (seconds) after which a finished process is killed
		  if it has not yet stopped.
		mon_term_intvl (float)
		- The interval (seconds) at which terminating processes are checked
		  to see if they have stopped.
		mon_term_kill (float)
		- The duration (seconds) after which a terminating process is killed
		  if it has not yet stopped.
		proc_known_intvl (float)
		- The interval (seconds) at which the known processes list is
		  updated.
		proc_normal_intvl (float)
		- The interval (seconds) at which a registered process that's
		  running normally is told to update the server.
		proc_realtime_intvl (float)
		- The interval (seconds) at which a registered process that's
		  sending real-time updates is told to update the server.
		start_check (float)
		- The interval (seconds) at which starting processes are checked to
		  see if they have registered yet.
		start_term (int)
		- The duration (seconds) after which a starting process is
		  terminated if it has not registered yet.
		work_check (float)
		- The interval (seconds) at which working processes are checked to
		  see if they have updated their status yet.
		work_term (int)
		- The duration (seconds) after which a working process is terminated
		  if it has not updated its status yet.
	"""
	
	def __init__(self, app_name=None, client_port=None, run_prefix=None, tmp_prefix=None, var_prefix=None, debug=False):
		"""
		Initializes a Process Server instance.
		
		Optional Arguments:
			app_name (str)
			- The name of the Process Server Application; default is
			  {server!r}.
			client_port (int)
			- The port on which clients are listened for; default is `{client_port}`.
			run_prefix (str)
			- The run-time file data directory prefix (e.g., "/var/local/run"
			  or "/var/run"); default is {local_run!r}.
			tmp_prefix (str)
			- The temporary file data directory prefix (e.g., "/tmp"); default
			  is {tmp!r}.
			var_prefix (str)
			- The variable file data directory prefix (e.g., "/var/local" or
			  "/var"); default is {local_var!r}.
			debug (bool)
			- Whether debugging should be enabled or not; default is `False`. 
		""".format(
			server=_process.SERVER,
			client_port=_process.CLIENT_PORT,
			local_run=_process.PREFIX_LOCAL_RUN,
			tmp=_process.PREFIX_TMP,
			local_var=_process.PREFIX_LOCAL_VAR
		)
		app_name = _os.path.basename(app_name) if app_name is not None else _process.SERVER
		run_prefix = _os.path.abspath(run_prefix) if run_prefix is not None else _process.PREFIX_LOCAL_RUN
		tmp_prefix = _os.path.abspath(tmp_prefix) if tmp_prefix is not None else _process.PREFIX_TMP
		var_prefix = _os.path.abspath(var_prefix) if var_prefix is not None else _process.PREFIX_LOCAL_VAR
		var_lib = var_prefix + "/lib"
		var_log = var_prefix + "/log"
		# Make sure prefix directories exist and are accessable.
		if not _os.path.isdir(run_prefix):
			raise ValueError("Run-time file data directory %r does not exist." % run_prefix)
		elif not _os.access(run_prefix, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denined to read/write/execute run-time directory %r." % run_prefix)
		if not _os.path.isdir(tmp_prefix):
			raise ValueError("Temporary file data directory %r does not exist." % tmp_prefix)
		elif not _os.access(tmp_prefix, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denined to read/write/execute temporary directory %r." % tmp_prefix)
		if not _os.path.isdir(var_prefix):
			raise ValueError("Variable file data directory %r does not exist." % var_prefix)
		elif not _os.access(var_prefix, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denined to read/write/execute variable directory %r." % var_prefix)
		if not _os.path.isdir(var_lib):
			raise ValueError("Program specific file data directory %r does not exist." % var_lib)
		elif not _os.access(var_lib, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denined to read/write/execute program specific directory %r." % var_lib)
		if not _os.path.isdir(var_log):
			raise ValueError("Log file data directory %r does not exist." % var_log)
		elif not _os.access(var_log, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denined to read/write/execute log directory %r." % var_log)
		# Create directories.
		run_dir = "%s/%s" % (run_prefix, app_name)
		tmp_dir = "%s/%s" % (tmp_prefix, app_name)
		var_dir = "%s/lib/%s" % (var_prefix, app_name)
		log_dir = "%s/log/%s" % (var_prefix, app_name)
		if not _os.path.isdir(run_dir):
			_os.mkdir(run_dir, 0o700)
		if not _os.path.isdir(tmp_dir):
			_os.mkdir(tmp_dir, 0o700)
		if not _os.path.isdir(var_dir):
			_os.mkdir(var_dir, 0o700)
		if not _os.path.isdir(log_dir):
			_os.mkdir(log_dir, 0o700)
		
		client_port = int(client_port) if client_port is not None else _process.CLIENT_PORT
		procs_socket = "%s/processes.socket" % run_dir
		procs_dbfile = "%s/processes.sqlite3" % var_dir
		procs_db = ProcessDatabase(procs_dbfile)
		dirs = (
			tmp_dir + "/processes",
			var_dir + "/processes",
			var_dir + "/shared",
			log_dir + "/processes"
		)
		for dir in dirs:
			if not _os.path.isdir(dir):
				_os.mkdir(dir, 0o700)
		
		self.app_name = app_name
		self.debug = bool(debug)
		self.exit = None
		self.run_prefix = run_prefix
		self.tmp_prefix = tmp_prefix
		self.var_prefix = var_prefix
		self.run_dir = run_dir
		self.tmp_dir = tmp_dir
		self.var_dir = var_dir
		self.log_dir = log_dir
		
		self.client_port = client_port
		self.procs_db = procs_db
		self.procs_dbfile = procs_dbfile
		self.procs_socket = procs_socket
		
		self.procs_info = {}
		self.procs_id = {}
		self.procs_inst = {}
		self.procs_reg = {}
		self.procs_start = {}
		self.procs_fin = {}
		self.procs_term = {}
		self.procs_mon = dict(((t, {'*': set()} if t in _mon_all_types else {}) for t in _mon_types))
		
		self.mon_fin_intvl = _mon_fin_intvl
		self.mon_fin_kill = _mon_fin_kill
		self.mon_term_intvl = _mon_term_intvl
		self.mon_term_kill = _mon_term_kill
		self.proc_known_intvl = _proc_known
		self.proc_normal_intvl = _proc_normal
		self.proc_realtime_intvl = _proc_stream
		self.start_check = _start_check
		self.start_term = _start_term
		self.work_check = _work_check
		self.work_term = _work_term
	
	def clean_process(self, process_inst):
		"""
		Clears the process instance references and deletes the run-time and
		temporary directories.
		
		Arguments:
			process_inst (ProcessInstance)
			- The process instance.
		"""
		proc_id, proc_name = process_inst.id, process_inst.name
		
		if self.debug:
			print "Clean process %s:%i..." % (proc_name, proc_id),
		
		# Clean process instance references: info, id, instances, starting,
		# registered, finished and terminating.
		if proc_name in self.procs_info:
			self.procs_info[proc_name]._inst = None
		if proc_name in self.procs_id and self.procs_id[proc_name] == proc_id:
			del self.procs_id[proc_name]
		if proc_id in self.procs_inst:
			del self.procs_inst[proc_id]
		if hasattr(process_inst, '_token'):
			if (proc_name, process_inst._token) in self.procs_start:
				del self.procs_start[(proc_name, process_inst._token)]
		if proc_id in self.procs_reg:
			del self.procs_reg[proc_id]
		if proc_id in self.procs_fin:
			del self.procs_fin[proc_id]
		if proc_id in self.procs_term:
			del self.procs_term[proc_id]
				
		# Clear process monitors.
		for mon_procs in self.procs_mon.itervalues():	
			if proc_id in mon_procs:
				del mon_procs[proc_id]
				
		# Delete process run-time and temporary directories.
		# - NOTE: The process run-time directory is under the process server
		#   variable (not run-time) directory so that a process can continue
		#   running regardless of the server.
		tmp_dir = "%s/processes/%i" % (self.tmp_dir, proc_id)
		run_dir = "%s/processes/%i" % (self.var_dir, proc_id)
		d = _threads.deferToThread(_delete_dirs, (run_dir, tmp_dir))
		d.addErrback(_err_print)
		
		if self.debug:
			print "cleaned."
		
	def dead_monitors(self, monitor_type, process_key, refs):
		"""
		Cleans up the dead process monitors.
		
		Arguments:
			monitor_type (str)
			- The monitor type.
			process_key (mixed)
			- The process key can be a process instance ID (int), a process name (str)
			  or the special '*' (str) for all processes.
			refs (set)
			- The dead monitor references.
		"""
		mon_procs = self.procs_mon[monitor_type]
		mon_procs[process_key] -= set(refs)
		if monitor_type == REALTIME and process_key != '*':
			# If we removed the last real-time monitor for a process, tell its
			# instance to stop sending real-time updates.
			if isinstance(process_key, int):
				proc_id = process_key
				proc_inst = self.procs_inst[proc_id]
				proc_name = proc_inst.name
			else:
				proc_name = process_key
				if proc_name in self.procs_id:
					proc_id = self.procs_id[proc_name]
					proc_inst = self.procs_inst[proc_id]
				else:
					proc_id = proc_inst = None
			if proc_id and not mon_procs[proc_id] and not mon_procs[proc_name]:
				try:
					d = proc_inst._ref.callRemote('set_update_interval', self.proc_normal_intvl)
					d.addErrback(_err_pass)
					print "Stop real-time updates from process instance %s:%i." % (proc_name, proc_id)
				except _pb.DeadReferenceError:
					self.dead_process(proc_inst)
			
	def dead_process(self, process_inst):
		"""
		Cleans up the specified dead process.
		
		Arguments:
			process_inst (ProcessInstance)
			- The process instance information.
		"""
		# Since the process is dead clear its remote reference and terminate
		# it.
		process_inst._ref = None
		self.terminate_process(process_inst)
			
	def err_init_db(self, reason):
		"""
		Called if the database could not be initialized.
		
		Arguments:
			reason (twisted.python.failure.Failure) -- The reason for failure.
		"""
		print_failure(reason)
		self.stop(1)
		
	def finish_process(self, process_inst, process_exit):
		"""
		Finishes up the specified process instance with an exit status.
		
		This method finishes up the instance by recording in the database
		that this process is done.
		
		Arguments:
			process_inst (ProcessInstance)
			- The process to finish.
			process_exit (int)
			- The exit status of the process.
		"""
		proc_id = process_inst.id
		
		# Update instance state and add to list of processes being finished.
		process_inst.state = STATE_FINISHED
		proc_fin = process_inst._finished = _time.time()
		self.procs_fin[proc_id] = process_inst
		
		# Update database that process is finished.
		d = _threads.deferToThread(self.procs_db.finish_process, proc_id, proc_fin, process_exit)
		d.addErrback(_err_print)
		
		# Notify process instance monitors about state.
		self.notify_instance_state(STATE_FINISHED, proc_id, args=(process_inst.name, proc_id, proc_fin, process_exit))
		
	def list_processes(self):
		"""
		Returns the list of processes.
		
		Returns:
			(list)
			- The list of process names (str).
		"""
		return list(self.procs_info.iterkeys())
		
	def main(self):
		"""
		Starts the Twisted reactor.
		
		Returns:
			(int)
			- On success, `0`; otherwise, a non-zero integer.
		"""
		factory = _pb.PBServerFactory(self)
		_reactor.listenTCP(self.client_port, factory)
		_reactor.listenUNIX(self.procs_socket, factory)
		_reactor.callLater(0, self.monitor_processes_directory)
		_reactor.callLater(0, self.monitor_process_progresses)
		_reactor.callLater(0, self.monitor_working_processes)
		_reactor.callLater(0, self.monitor_starting_processes)
		_reactor.callLater(0, self.monitor_finished_processes)
		_reactor.callLater(0, self.monitor_terminating_processes)
		_reactor.run()
		return self.exit
			
	def monitor_finished_processes(self):
		"""
		Monitors processes that have finished (but not yet stopped) by
		allowing them a short duration to stop after which they will be
		killed without hesitation.
		"""
		# Call this methods again later.
		_reactor.callLater(self.mon_fin_intvl, self.monitor_finished_processes)
		# Iterate over list of processes stopping (finished).
		now = _time.time()
		clean = []
		for proc_id, proc_inst in self.procs_fin.iteritems():
			elapsed = now - proc_inst._finished
			if elapsed >= self.mon_fin_kill:
				# Since the process is taking its good ol time to stop, kill it.
				try:
					_os.kill(proc_inst.pid, _signal.SIGKILL)
				except Exception as e:
					if not isinstance(e, OSError) or e.errno != _errno.ESRCH:
						_traceback.print_exc(file=_sys.stderr)
				# Add process to clean-up list.
				clean.append(proc_inst)
			else:
				# Check to see if the process is still running.
				try:
					_os.kill(proc_inst.pid, 0)
				except Exception as e:
					if isinstance(e, OSError) and e.errno == _errno.ESRCH:
						# Since the process stopped, add it to the clean-up list.
						clean.append(proc_inst)
					else:
						_traceback.print_exc(file=_sys.stderr)
		# Clean-up processes that finished and notify instance monitors.
		for proc_inst in clean:
			self.notify_instance_state(STATE_NOTRUNNING, proc_inst.id, args=(proc_inst.name,))
			self.clean_process(proc_inst)
	
	@_defer.inlineCallbacks
	def monitor_processes_directory(self):
		"""
		Updates the known processes list regularly.
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		before = _time.time()
		# Get process list.
		try:
			known_procs = yield _threads.deferToThread(_process.list_processes)
			
			# Determine which processes need to be recorded, updated and
			# removed.
			current_procs = set(self.procs_info.iterkeys())
			new_procs = known_procs - current_procs
			update_procs = known_procs & current_procs
			remove_procs = current_procs - known_procs
			
			# Record, update and remove processes.
			d_list = []
			if remove_procs:
				d_list.append(_defer.maybeDeferred(self.remove_processes, remove_procs))
			if update_procs:
				d_list.append(_defer.maybeDeferred(self.update_processes, update_procs))
			if new_procs:
				d_list.append(_defer.maybeDeferred(self.record_processes, new_procs))
			if d_list:
				result = yield _defer.DeferredList(d_list, consumeErrors=True)
				for success, value in result:
					if not success:
						value.printTraceback(file=_sys.stderr)
		except Exception:
			_traceback.print_exc(file=_sys.stderr)	
		# Update known processes again later.			
		now = _time.time()
		next = self.proc_known_intvl - now + before
		_reactor.callLater(max(next, 0), self.monitor_processes_directory)

	def monitor_process_progresses(self):
		"""
		Updates process progress monitors regularly.
		"""
		for proc_key, proc_mons in self.procs_mon[PROGRESS].iteritems():
			if not proc_mons:
				# Since this process has no monitors, skip it.
				continue
			if proc_key == '*':
				# Since we have the special "all-processes" process, update
				# progress monitors for all processes.
				dead_refs = []
				for proc_mon in proc_mons:
					for proc_inst in self.procs_inst.itervalues():
						try:
							d = proc_mon.callRemote('monitor_update', proc_inst.name, proc_inst.id, proc_inst.progress)
							d.addErrback(_err_pass)
						except _pb.DeadReferenceError:
							dead_refs.append(proc_mon)
							if self.debug:
								print "Dead %r monitor reference to all processes from %r." % (PROGRESS, proc_mon)
							# Since this process monitor reference is dead, add it to
							# the list of dead references and continue to the next
							# process monitor.
							break
				if dead_refs:
					# If there are any dead progress monitors, remove them.
					self.dead_monitors(PROGRESS, proc_key, dead_refs)
				# Continue onto the next process.
				continue
			elif isinstance(proc_key, int):
				proc_id = proc_key
				proc_inst = self.procs_inst[proc_id]
				proc_name = proc_inst.name
			else:
				proc_name = proc_key
				proc_id = self.procs_id[proc_name]
				proc_inst = self.procs_inst[proc_id]
			if proc_inst.started:
				# Update progress monitor.
				dead_refs = []
				for proc_mon in proc_mons:
					try:
						d = proc_mon.callRemote('monitor_update', proc_name, proc_id, proc_inst.progress)
					except _pb.DeadReferenceError:
						dead_refs.append(proc_mon)
						if self.debug:
							if proc_key == proc_id:
								print "Dead %r monitor reference to process instance %s:%i from %r." % (PROGRESS, proc_name, proc_id, proc_mon)
							else:
								print "Dead %r monitor reference to process %r from %r." % (PROGRESS, proc_name, proc_mon)
					else:
						d.addErrback(_err_pass)
				if dead_refs:
					# If there are any dead progress monitors, remove them.
					self.dead_monitors(PROGRESS, proc_key, dead_refs)
		# Update progress monitors again later.
		_reactor.callLater(self.proc_normal_intvl, self.monitor_process_progresses)

	def monitor_starting_processes(self):
		"""
		Monitors processes that are starting by making sure that they
		register shortly after their creation.
		"""
		# Call this method again later.
		_reactor.callLater(self.start_check, self.monitor_starting_processes)
		# Get time.
		now = _time.time()
		terminate = []
		for proc_inst in self.procs_start.itervalues():
			if self.debug:
				print "Check process %s:%i (%s)..." % (proc_inst.name, proc_inst.id, proc_inst._token),
			elapsed = now - proc_inst.started
			if elapsed > self.start_term:
				# Termination the process because it was not registered before
				# the termination deadline.
				terminate.append(proc_inst)
			elif self.debug:
				print "wait."
		# Terminate naughty processes.
		for proc_inst in terminate:
			print "Terminate starting process %s:%i (%s) due to lack of registration." % (proc_inst.name, proc_inst.id, proc_inst._token)
			d = _defer.maybeDeferred(self.terminate_process, proc_inst)
			d.addErrback(_err_print)
	
	def monitor_terminating_processes(self):
		"""
		Monitors processes that are being terminated by allowing them a
		short duration to stop after which they will be kill mercilessly.
		"""
		# Call this method again later.
		_reactor.callLater(self.mon_term_intvl, self.monitor_terminating_processes)
		# Iterate over list of processes being terminated
		now = _time.time()
		clean = []
		for proc_id, proc_inst in self.procs_term.iteritems():
			elapsed = now - proc_inst._terminated
			if elapsed >= self.mon_term_kill:
				# Since the process is taking its sweet time to stop, kill it.
				try:
					_os.kill(proc_inst.pid, _signal.SIGKILL)
				except OSError as e:
					if e.errno != _errno.ESRCH:
						_traceback.print_exc()
				# Add process to clean-up list.
				clean.append(proc_inst)
			else:
				# Check to see if the process is still running.
				try:
					_os.kill(proc_inst.pid, 0)
				except OSError as e:
					if e.errno == _errno.ESRCH:
						# Since the process stopped, add it to the clean-up list.
						clean.append(proc_inst)
					else:
						_traceback.print_exc()
		# Clean-up processes that either terminated or were killed and
		# notify process instance monitors.
		for proc_inst in clean:
			self.notify_instance_state(STATE_TERMINATED, proc_inst.id, args=(proc_inst.name, proc_inst.id))
			self.clean_process(proc_inst)
		
	def monitor_working_processes(self):
		"""
		Monitors working processes by making sure that they are regularly
		updating their status.
		"""
		# Call this method again later.
		_reactor.callLater(self.work_check, self.monitor_working_processes)
		# Get time.
		# self.work_term
		now = _time.time()
		terminate = []
		for proc_inst in self.procs_reg.itervalues():
			if self.debug:
				print "Check process %s:%i..." % (proc_inst.name, proc_inst.id),
			elapsed = now - (proc_inst.updated or proc_inst.registered) 
			if elapsed > self.work_term:
				# Termination the process because it was not updated before the
				# termination deadline.
				terminate.append(proc_inst)
			elif self.debug:
				print "okay."
		# Terminate naughty processes.
		for proc_inst in terminate:
			print "Terminate process %s:%i due to lack of updates." % (proc_inst.name, proc_inst.id)
			d = _defer.maybeDeferred(self.terminate_process, proc_inst)
			d.addErrback(_err_print)
	
	def check_process(self, process_name):
		"""
		Checks to see if the process exists.
		
		Arguments:
			process_name (str)
			- The name of the process.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: whether the process exists (bool).
		"""
		if process_name in self.procs_info:
			return True
		_process.validate_process_name(process_name)
		return False
		
	def notify_process_state(self, state, process_name, args=None, kwargs=None):
		"""
		Notifies process monitors about the state of the process.
		
		Arguments:
			process_name (str)
			- The name of the process.
			state (str)
			- The process state.
			
		Optional Arguments:
			args (list)
			- Any positional arguments to send to the monitors.
			kwargs (dict)
			- Any keyword arguments to send to the monitors.
		"""
		if not args:
			args = ()
		if not kwargs:
			kwargs = {}
		func = _state_funcs[state]
		# Notify process monitors.
		for proc_key in (process_name, '*'):
			for mon_type, mon_procs in self.procs_mon.iteritems():
				if proc_key in mon_procs:
					dead_refs = []
					for proc_mon in mon_procs[proc_key]:
						try:
							d = proc_mon.callRemote(func, *args, **kwargs)
							d.addErrback(_err_pass)
						except _pb.DeadReferenceError:
							if self.debug:
								if proc_key != '*':
									print "Dead %r monitor reference to process %r from %r." % (mon_type, process_name, proc_mon)
								else:
									print "Dead %r monitor reference to all processes from %r." % (mon_type, proc_mon)
					if dead_refs:
						# If there are any dead process or all-processes monitors, remove
						# them.
						self.dead_monitors(mon_type, proc_key, dead_refs)
		
	def notify_instance_state(self, state, process_id, args=None, kwargs=None):
		"""
		Notifies process instance monitors about the state of the process.
		
		Arguments:
			state (str)
			- The process state.
			process_id (str)
			- The process instance ID.
			
		Optional Arguments:
			args (list)
			- Any positional arguments to send to the monitors.
			kwargs (dict)
			- Any keyword arguments to send to the monitors.
		"""
		if not args:
			args = ()
		if not kwargs:
			kwargs = {}
		proc_name = self.procs_inst[process_id].name
		func = _state_funcs[state]
		# Notify process instance monitors.
		for proc_key in (process_id, proc_name, '*'):
			for mon_type, mon_procs in self.procs_mon.iteritems():
				if proc_key in mon_procs:
					dead_refs = []
					for proc_mon in mon_procs[proc_key]:
						try:
							d = proc_mon.callRemote(func, *args, **kwargs)
							d.addErrback(_err_pass)
						except _pb.DeadReferenceError:
							dead_refs.append(proc_mon)
							if self.debug:
								if proc_key == process_id:
									print "Dead %r monitor reference to process instance %s:%i from %r." % (mon_type, proc_name, process_id, proc_mon)
								elif proc_key != '*':
									print "Dead %r monitor reference to process %r from %r." % (mon_type, proc_name, proc_mon)
								else:
									print "Dead %r monitor reference to all processes from %r." % (mon_type, proc_mon)
					if dead_refs:
						# If there are any dead process or all-processes monitors, remove
						# them.
						self.dead_monitors(mon_type, proc_key, dead_refs)
		
	def query_process(self, process_name, keys):
		"""
		Queries the specified process for information.
		
		Arguments:
			process_name (str)
			- The name of the process to inquire.
			keys (list)
			- The keys (str) to return.
			
		Returns:
			(dict)
			- The queried information. If no data exists for a given key, its
			  value will be `None`.
		"""
		proc_info = self.procs_info[process_name]
		result = dict(((k, proc_info[k] if k in proc_info else None) for k in keys))
		return result
		
	def query_processes(self, process_names, keys):
		"""
		Queries the specified processes for information.
		
		Arguments:
			process_names (list)
			- The list of process names (str) to inquire.
			keys (list)
			- The keys (str) to return.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- The queried information per process; keyed by process name
			  (str). If a process does not exist, its value will be `None`. If
			  no data exists for a given key, its value will be `None`.
		"""
		results = dict.fromkeys(process_names)
		procs_info = self.procs_info
		for proc_name in process_names:
			if proc_name in procs_info:
				proc_info = procs_info[proc_name]
				results[proc_name] = dict(((k, proc_info[k] if k in proc_info else None) for k in keys))
			else:
				results[proc_name] = None
		return results
	
	@_defer.inlineCallbacks
	def record_processes(self, process_names):
		"""
		Record the specified processes.
		
		Arguments:
			process_names (list)
			- The names (str) of the processes to add.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		procs = yield _threads.deferToThread(_get_processes, process_names)
		got = []
		for proc_name, proc in procs.iteritems():
			if isinstance(proc, _failure.Failure):
				proc.printTraceback(file=_sys.stderr)
			else:
				args = dict((kv for kv in (proc if isinstance(proc, dict) else proc.__dict__).iteritems() if kv[0] in _proc_keys)) 
				self.procs_info[proc_name] = ProcessInfo(**args)
				got.append(proc_name)
				# Notify all-processes monitors about new processes.
				for mon_type, mon_procs in self.procs_mon.iteritems():
					if '*' in mon_procs:
						proc_mons = mon_procs['*']
						dead_refs = []
						for proc_mon in proc_mons:
							try:
								d = proc_mon.callRemote('monitor_new', STATE_NOTRUNNING, proc_name)
								d.addErrback(_err_pass)
							except _pb.DeadReferenceError:
								dead_refs.append(proc_mon)
								if self.debug:
									print "Dead %r monitor reference to all processes from %r." % (mon_type, proc_mon)
						if dead_refs:
							# If there are any dead progress monitors, remove them.
							self.dead_monitors(mon_type, '*', dead_refs)
		# Setup process monitor place holders.
		holders = dict.fromkeys(got, set())
		for mon_procs in self.procs_mon.itervalues():
			mon_procs.update(holders)
		
		if self.debug:
			print "Added %i processes: %r" % (len(process_names), list(process_names))
	
	def register_instance_monitor(self, process_id, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to the process instance.
		
		Arguments:
			process_id (str)
			- The instance ID of the process to monitor.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		proc_inst = self.procs_inst[process_id]
		proc_name = proc_inst.name
		# Notify the process instance monitor about the state of the
		# instance.
		# - NOTE: Do not try to catch a potential Dead Reference Error
		#   because the process instance monitor is being registered and if
		#   the monitor reference is dead, allow the error to propagate back
		#   to the client.
		proc_state = proc_inst.state
		if proc_state == STATE_STARTING:
			args = (proc_inst.started,)
		elif proc_state == STATE_WORKING:
			args = (proc_inst.registered,)
		elif proc_state == STATE_FINISHED:
			args = (proc_inst._finished,)
		elif proc_state == STATE_TERMINATING:
			args = (proc_inst._terminated,)
		else:
			args = ()
		d = monitor_ref.callRemote('monitor_new', proc_state, proc_name, process_id, *args)
		d.addErrback(_err_pass)
		# If this is the first real-time monitor for this process, tell the
		# process instance to start sending real-time updates.
		proc_ref = proc_inst._ref
		mon_procs = self.procs_mon[monitor_type]
		if proc_ref and monitor_type == REALTIME:
			if not mon_procs[process_id] and not mon_procs[proc_name]:
				try:
					d = proc_ref.callRemote('set_update_interval', self.proc_realtime_intvl)
				except _pb.DeadReferenceError:
					self.dead_process(proc_inst)
				else:
					d.addErrback(_err_pass)
					print "Start real-time updates from process instance %s:%i." % (proc_name, process_id)
		# Add process instance monitor.
		mon_procs[process_id].add(monitor_ref)
		
	@_defer.inlineCallbacks
	def register_process(self, process_name, process_pid, process_ref, process_token=None):
		"""
		Registers the specified process.
		
		Arguments:
			process_name (str)
			- The name of the process.
			process_pid (int)
			- The OS PID of the process.
			process_ref (twisted.spread.pb.RemoteReference)
			- A remote reference to the process.
			
		Optional Arguments:
			process_token (str)
			- The server provided token to use when registering (this is used when the
			  server starts the process).
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the new ID (int) for the registered process.
		"""
		if self.debug:
			print "Register process %r (pid:%r)..." % (process_name, process_pid),
		if process_token is not None:
			# Since a process token was provided, this process instance was
			# started by the server and thus should be in the starting list.
			if (process_name, process_token) in self.procs_start:
				# Since this process instance was starting, register it.
				proc_id = self.procs_id[process_name]
				proc_inst = self.procs_inst[proc_id]
				# Clean up process start-up data.
				del self.procs_start[(process_name, process_token)]
				del proc_inst._token
				if self.debug:
					print "id:%i (%s)..." % (proc_id, process_token),
			elif process_name in self.procs_id:
				# Since the process is already running, raise an AlreadyRunning
				# exception to be received by the client.
				if self.debug:
					print "AlreadyRunning %s:%i." % (process_name, proc_id)
				raise _process.AlreadyRunning("Process %s:%i is already running." % (process_name, proc_id))
			else:
				# There is no record that this process was started so tell the
				# process to terminated by raising a TerminateProcess exception
				# to be received by the process.
				if self.debug:
					 print "terminating (%r)." % process_token
				else:
					print "Terminating process %r (token:%r)." % (process_name, process_token)
				raise _process.TerminateProcess("Unrecognized process %r token %r." % (process_name, process_token))
		else:
			# Since a process token was not provided, this process instance
			# was not started by the server.
			if process_name not in self.procs_id:
				# Since the process is not running at all, record the new process.
				proc_inst = yield _threads.deferToThread(self.procs_db.new_process, process_name)
				proc_id = self.procs_id[process_name] = proc_inst.id
				self.procs_inst[proc_id] = proc_inst
				if self.debug:
					print "new id:%i..." % proc_id,
				# Setup process instance monitors.
				for mon_procs in self.procs_mon.itervalues():
					mon_procs[proc_id] = set()
			else:
				# Since the process is already running, raise an AlreadyRunning
				# exception to be received by the process.
				if self.debug:
					print "AlreadyRunning %s:%i." % (process_name, proc_id)
				raise _process.AlreadyRunning("Process %s:%i is already running." % (process_name, proc_id))
		
		# Setup registered process.
		proc_inst.state = STATE_WORKING
		proc_inst.pid = process_pid
		proc_inst._ref = process_ref
		proc_inst.registered = _time.time()
		self.procs_reg[proc_id] = proc_inst
		if not self.debug:
			print "Registered process %s:%i." (process_name, proc_id)
			
		# If there are any real-time monitors, tell the process instance to
		# start sending real-time updates.
		mon_procs = self.procs_mon[REALTIME]
		if mon_procs[proc_id] or mon_procs[process_name]:
			try:
				d = process_ref.callRemote('set_update_interval', self.proc_realtime_intvl)
				d.addErrback(_err_pass)
			except _pb.DeadReferenceError:
				self.dead_process(proc_inst)
				raise _process.TerminateProcess("Process %s:%i reference %r is dead." % (process_name, proc_id, process_ref))
			
		# Notify process instance monitors that the process is now working.
		self.notify_instance_state(STATE_WORKING, proc_id, args=(process_name, proc_id, proc_inst.registered))
		
		# Return the process ID.
		if self.debug:
			print "working."
			
		_defer.returnValue(proc_id)
	
	def register_process_monitor(self, process_name, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to the process.
		
		Arguments:
			process_name (str)
			- The name of the process to monitor.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		# Notify the process monitor about the state of the instance.
		# - NOTE: Do not try to catch a potential Dead Reference Error
		#   because the process monitor is being registered and if the
		#   monitor reference is dead, allow the error to propagate back to
		#   the client.
		proc_info = self.procs_info[process_name]
		proc_inst = proc_info._inst
		if proc_inst:
			proc_state = proc_inst.state
			if proc_state == STATE_STARTING:
				args = (proc_inst.id, proc_inst.started,)
			elif proc_state == STATE_WORKING:
				args = (proc_inst.id, proc_inst.registered,)
			elif proc_state == STATE_FINISHED:
				args = (proc_inst.id, proc_inst._finished,)
			elif proc_state == STATE_TERMINATING:
				args = (proc_inst.id, proc_inst._terminated,)
			else:
				args = (proc_inst.id,)
		else:
			proc_state = proc_info._state or STATE_NOTRUNNING
			args = ()
		d = monitor_ref.callRemote('monitor_new', proc_state, process_name, *args)
		d.addErrback(_err_pass)
		# If this is the first real-time monitor for this process, tell the
		# process instance to start sending real-time updates.
		mon_procs = self.procs_mon[monitor_type]
		if proc_inst:
			proc_ref = proc_inst._ref
			if proc_ref and monitor_type == REALTIME:
				proc_id = proc_inst.id
				if not mon_procs[proc_id] and not mon_procs[process_name]:
					try:
						d = proc_inst._ref.callRemote('set_update_interval', self.proc_realtime_intvl)
						d.addErrback(_err_pass)
						print "Start real-time updates from process instance %s:%i." % (process_name, proc_id)
					except _pb.DeadReferenceError:
						self.dead_process(proc_inst)
		# Add process monitor.
		mon_procs[process_name].add(monitor_ref)
	
	def register_processes_monitor(self, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to all processes.
		
		Arguments:
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		if self.debug:
			print "Register all-procs %r monitor %r..." % (monitor_type, monitor_ref),
		# Notify the all-processes monitor about all processes and any that are
		# running.
		# - NOTE: Do not try to catch any potential Dead Reference Errors because
		#   the all-processes monitor is being registered and if the monitor
		#   reference is dead, allow the error to propagate back to the client.
		if self.debug and self.procs_info:
			print "notify %i" % len(self.procs_info),
		for proc_name, proc_info in self.procs_info.iteritems():
			proc_inst = proc_info._inst
			if proc_inst:
				proc_state = proc_inst.state
				if proc_state == STATE_STARTING:
					args = (proc_inst.id, proc_inst.started,)
				elif proc_state == STATE_WORKING:
					args = (proc_inst.id, proc_inst.registered,)
				elif proc_state == STATE_FINISHED:
					args = (proc_inst.id, proc_inst._finished,)
				elif proc_state == STATE_TERMINATING:
					args = (proc_inst.id, proc_inst._terminated,)
				else:
					args = (proc_inst.id,)
			else:
				proc_state = proc_info._state or STATE_NOTRUNNING
				args = ()
			d = monitor_ref.callRemote('monitor_new', proc_state, proc_name, *args)
			d.addErrback(_err_pass)
			if self.debug:
				_sys.stdout.write('.')
		# Add all-processes monitor.
		self.procs_mon[monitor_type]['*'].add(monitor_ref)
		if self.debug:
			print "done"
		
	@_defer.inlineCallbacks
	def remote_command(self, command):
		"""
		Processes the specified command.
		
		Arguments:
			command (str) -- The command.
		"""
		if not isinstance(command, basestring):
			raise TypeError("command:%r is not a string." % command)
		parts = command.split()
		if not parts:
			raise ValueError("command:%r is empty." % command)
		if parts[0] == 'list':
			if len(parts) > 1:
				if parts[1] in ('processes', 'procs'):
					procs = _process.list_processes()
					_defer.returnValue(procs.join('\n'))
			_defer.returnValue("processes, procs")
		elif parts[0] == 'start':
			if len(parts) > 1:
				result = yield self.run_process(parts[1])
				_defer.returnValue(result)
			_defer.returnValue("{process}")
		elif parts[0] == 'help':
			_defer.returnValue("exec\nlist")
	
	@_defer.inlineCallbacks
	def remote_finish_process(self, process_id, process_exit):
		"""
		Finishes the specified process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			process_exit (int) -- The exit status of the process.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if process_id not in self.procs_reg:
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
			
		proc_inst = self.procs_inst[process_id]
		if self.debug:
			print "Finish process %s:%i (exit:%r)..." % (proc_inst.name, process_id, process_exit),
			
		yield _defer.maybeDeferred(self.finish_process, proc_inst, process_exit)
		
		if self.debug:
			print "finished."
		else:
			print "Finished process %s:%i exit %r" % (proc_inst.name, process_id, process_exit)
			
				
	@_defer.inlineCallbacks
	def remote_list_processes(self):
		"""
		Returns the list of processes.
		
		Returns:
			(twsited.internet.defer.Deferred)
			- A deferred containing: the list (list) of process names (str).
		"""
		proc_names = yield _defer.maybeDeferred(self.list_processes)
		_defer.returnValue(proc_names)
		
	@_defer.inlineCallbacks
	def remote_query_process(self, process_name, keys):
		"""
		Queries the specified process for information.
		
		Arguments:
			process_name (str)
			- The name of the process to inquire.
			keys (list)
			- The keys (str) to return.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the queried information (dict). If no data exist
			  for a given key, its value will be `None`.
		"""
		exists = yield _defer.maybeDeferred(self.check_process, process_name)
		if not exists:
			raise _process.InvalidProcess("Process %r does not exist." % process_name, process_name)
		if not hasattr(keys, '__iter__'):
			raise TypeError("keys:%r is not iterable." % keys)
		bad = [repr(k) for k in keys if not isinstance(k, basestring)]
		if bad:
			raise TypeError("keys contains %i non-string key(s): %s." % (len(bad), ", ".join(bad)))
		# Query process.
		proc_query = yield _defer.maybeDeferred(self.query_process, process_name, keys)
		_defer.returnValue(proc_query)
		
	@_defer.inlineCallbacks
	def remote_query_processes(self, process_names, keys):
		"""
		Queries the specified processes for information.
		
		Arguments:
			process_names (list)
			- The list of process names (str) to inquire.
			keys (list)
			- The keys (str) to return.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the queried information (dict) per process; keyed
			  by process name (str). If a process does not exist, its value will be
			  `None`. If no data exists for a given key, its value will be `None`.
		"""
		_process.validate_process_names(process_names)
		if not hasattr(keys, '__iter__'):
			raise TypeError("keys:%r is not iterable." % keys)
		bad = [repr(k) for k in keys if not isinstance(k, basestring)]
		if bad:
			raise TypeError("keys contains %i non-string key(s): %s." % (len(bad), ", ".join(bad)))
		# Query processes.
		procs_query = yield _defer.maybeDeferred(self.query_processes, process_names, keys)
		_defer.returnValue(procs_query)
		
	@_defer.inlineCallbacks
	def remote_register_instance_monitor(self, process_id, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to the process instance.
		
		Arguments:
			process_id (int)
			- The instance ID of the process to monitor.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if not isinstance(process_id, int):
			raise ValueError("process_id:%r is not an int." % process_id)
		if process_id not in self.procs_inst:
			raise _process.InvalidProcessInstance("Process instance %r does not exist." % process_id, process_id)
		if monitor_type not in _mon_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Register process instance monitor.
		yield _defer.maybeDeferred(self.register_instance_monitor, process_id, monitor_type, monitor_ref)
		
	@_defer.inlineCallbacks
	def remote_register_process(self, process_name, process_pid, process_ref, process_token=None):
		"""
		Register the specified process with this server.
		
		NOTE: If a TerminateProcess exception is raised, the registering process
		should terminate.
		
		Arguments:
			process_name (str)
			- The name of the process.
			process_pid (int)
			- The OS PID of the process.
			process_ref (twisted.spread.pb.RemoteReference)
			- A remote reference to the process.
			
		Optional Arguments:
			process_token (str)
			- The server provided token to use when registering (this is used when the
			  server starts the process).
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the new ID (int) for the registered process.
		"""
		if not isinstance(process_name, basestring):
			raise TypeError("process_name:%r is not a string." % process_name)
		if not isinstance(process_pid, int):
			raise TypeError("process_pid:%r is not an int." % process_pid)
		if not isinstance(process_ref, _pb.RemoteReference):
			raise TypeError("process_ref:%r is not a twisted.spread.pb.RemoteReference." % process_ref)
		# Register process.
		proc_id = yield _defer.maybeDeferred(self.register_process, process_name, process_pid, process_ref, process_token=process_token)
		_defer.returnValue(proc_id)
	
	@_defer.inlineCallbacks
	def remote_register_process_monitor(self, process_name, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to the process.
		
		Arguments:
			process_name (str)
			- The name of the process to monitor.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if not isinstance(process_name, basestring):
			raise TypeError("process_name:%r is not a string." % process_name)
		elif not process_name:
			raise ValueError("process_name:%r cannot be empty." % process_name)
		exists = yield _defer.maybeDeferred(self.check_process, process_name)
		if not exists:
			raise _process.InvalidProcess("Process %r does not exist." % process_name, process_name)
		if monitor_type not in _mon_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Register process monitor.
		yield _defer.maybeDeferred(self.register_process_monitor, process_name, monitor_type, monitor_ref)
	
	@_defer.inlineCallbacks
	def remote_register_processes_monitor(self, monitor_type, monitor_ref):
		"""
		Registeres the specified process monitor to all processes.
		
		Arguments:
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if monitor_type not in _mon_all_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_all_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Register process monitor.
		yield _defer.maybeDeferred(self.register_processes_monitor, monitor_type, monitor_ref)
		
	@_defer.inlineCallbacks
	def remote_run_process(self, process_name, process_args=None, process_monitor=None, process_debug=False):
		"""
		Runs the specified process.
		
		Arguments:
			process_name (str) -- The name of the process.
		
		Optional Arguments:
			process_args (str)
			- The arguments for the process; default is an empty string.
			process_monitor (2-tuple)
			- A 2-tuple containing: the monitor type (str) to register, and the
			  monitor reference (twisted.spread.pb.RemoteReference); default is
			  `None`. 
			process_debug (bool)
			- Whether process debugging should be enabled or not; default is `False`.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the process instance ID (int).
		"""
		if not isinstance(process_name, basestring):
			raise TypeError("process_name:%r is not a string." % process_name)
		elif not process_name:
			raise ValueError("process_name:%r cannot be empty." % process_name)
		exists = yield _defer.maybeDeferred(self.check_process, process_name)
		if not exists:
			raise _process.InvalidProcess("Process %r does not exist." % process_name, process_name)
		if process_args is not None:		
			process_args = str(process_args)
		if process_monitor is not None:
			if not isinstance(process_monitor, tuple):
				process_monitor = tuple(process_monitor)
			if len(process_monitor) != 2:
				raise TypeError("process_monitor:%r is not a 2-tuple." % process_monitor)
			mon_type, mon_ref = process_monitor
			if mon_type not in _mon_types:
				raise ValueError("process_monitor[0]:%r (type) is not %s." % (mon_type, _mon_types_err))
			if not isinstance(mon_ref, _pb.RemoteReference):
				raise TypeError("process_monitor[1]:%r (reference) is not a twisted.spead.pb.RemoteReference." % mon_ref)
		# Run process.
		try:
			proc_id = yield _defer.maybeDeferred(self.run_process, process_name, process_args=process_args, process_monitor=process_monitor, process_debug=process_debug)
		except Exception as e:
			if not isinstance(e, _process.ProcessError):
				if process_name in self.procs_id:
					self.clean_process(self.procs_inst[self.procs_id[process_name]])
			raise
		_defer.returnValue(proc_id) 
		
	@_defer.inlineCallbacks
	def remote_terminate_process(self, process_id):
		"""
		Terminates the specified process instance.e process instance.
		
		Arguments:
			process_id (int)
			- The process instance ID of the process to terminate.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if not isinstance(process_id, int):
			raise ValueError("process_id:%r is not an int." % process_id)
		if process_id not in self.procs_inst:
			raise _process.InvalidProcessInstance("Process instance %r does not exist." % process_id, process_id)
		# Terminate process instance.
		proc_inst = self.procs_inst[process_id]
		yield _defer.maybeDeferred(self.terminate_process, proc_inst)
	
	@_defer.inlineCallbacks
	def remote_unregister_instance_monitor(self, process_id, monitor_type, monitor_ref):
		"""
		Unregisteres the specified process monitor to the process instance.
		
		Arguments:
			process_id (str)
			- The instance ID of the process.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if not isinstance(process_id, int):
			raise ValueError("process_id:%r is not an int." % process_id)
		if process_id not in self.procs_inst:
			raise _process.InvalidProcessInstance("Process instance %r does not exist." % process_id, process_id)
		if monitor_type not in _mon_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Unregister process instance monitor.
		yield _defer.maybeDeferred(self.unregister_instance_monitor, process_id, monitor_type, monitor_ref)
	
	@_defer.inlineCallbacks
	def remote_unregister_process_monitor(self, process_name, monitor_type, monitor_ref):
		"""
		Unregisters the specified process monitor from the process.
		
		Arguments:
			process_name (str)
			- The name of the process.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if not isinstance(process_name, basestring):
			raise TypeError("process_name:%r is not a string." % process_name)
		elif not process_name:
			raise ValueError("process_name:%r cannot be empty." % process_name)
		exists = yield _defer.maybeDeferred(self.check_process, process_name)
		if not exists:
			raise _process.InvalidProcess("Process %r does not exist." % process_name, process_name)
		if monitor_type not in _mon_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Unregister process monitor.
		yield _defer.maybeDeferred(self.unregister_process_monitor, monitor_type, monitor_ref)
		
	@_defer.inlineCallbacks
	def remote_unregister_processes_monitor(self, monitor_type, monitor_ref):
		"""
		Unregisters the specified process monitor from all process.
		
		Arguments:
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if monitor_type not in _mon_all_types:
			raise ValueError("monitor_type:%r is not %s." % (monitor_type, _mon_all_types_err))
		if not isinstance(monitor_ref, _pb.RemoteReference):
			raise TypeError("monitor_ref:%r is not a twisted.spead.pb.RemoteReference." % monitor_ref)
		# Unregister all process monitor.
		yield _defer.maybeDeferred(self.unregister_processes_monitor, monitor_type, monitor_ref)
	
	def remote_update_process(self, process_id, process_buffers):
		"""
		Updates the status about the specified process.
		
		The data specified in stdlog must use the syslog format specified by RFC
		5424 (http://tools.ietf.org/html/rfc5424). In addition, each line of log
		output must contain fully qualified syslog messages ending with an EOL (this
		means that processes must buffer incomplete messages until the EOL is
		encoutered). As a consequence of messages being delimited by EOLs, all EOLs
		(preferably, all control characters) within the messages MUST BE ESCAPED;
		otherwise, all log output will be severly broken.
		
		The log data must contain the element ID 'status@ridersdiscount'. The status
		element must contain the 'progress' parameter which is a number (int or
		float) in the range of 0.0 and 1.0 (`1` indicates that the process is done).
		
		Arguments:
			process_id (int)
			- The ID of the process.
			process_buffers (dict)
			- The output buffers from the process: 1 is stdout, 2 is the stderr and 3
			  is the stdlog.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		if process_id not in self.procs_reg:
			raise _process.NotRegistered("Process ID %r is not registered." % process_id)
		if not isinstance(process_buffers, dict):
			raise TypeError("process_buffers:%r is not a dict." % process_buffers)
			
		proc_inst = self.procs_reg[process_id]
		proc_name = proc_inst.name
		if self.debug:
			print "Update process %s:%i buffers %r..." % (proc_name, process_id, dict(((b,len(d)) for b,d in process_buffers.iteritems()))),
		
		# Parse log output.
		try:
			log = process_buffers[3]
			if log:
				lines = log.splitlines()
				head, data, msg = parse_syslog(lines[-1])
				progress = float(data['status@ridersdiscount']['progress'])
				# Update process progress.
				proc_inst.updated = _time.time()
				proc_inst.progress = progress
				if self.debug:
					print "progress:%.3f" % progress
			elif self.debug:
				print "progress:%r" % None
			err_info = None
		except Exception as e:
			print "Bad process instance %s:%i log; reason: %r." % (proc_name, process_id, e)
			err_info = _sys.exc_info()
		
		# Forward output to realtime monitors.
		mon_procs = self.procs_mon[REALTIME]
		for proc_key in (process_id, proc_name):
			if proc_key in mon_procs:
				proc_mons = mon_procs[proc_key]
				dead_refs = []
				for proc_mon in proc_mons:
					try:
						d = proc_mon.callRemote('monitor_update', proc_name, process_id, proc_inst.progress, process_buffers)
						d.addErrback(_err_pass)
					except _pb.DeadReferenceError:
						dead_refs.append(proc_mon)
						if self.debug:
							if proc_key == process_id:
								print "Dead %r monitor reference to process instance %s:%i from %r." % (REALTIME, proc_name, process_id, proc_mon)
							elif proc_key == proc_name:
								print "Dead %r monitor reference to process %r from %r." % (REALTIME, proc_name, proc_mon)
							elif proc_key == '*':
								print "Dead %r monitor reference to all processes from %r." % (REALTIME, proc_mon)
				if dead_refs:
					# If there are any dead real-time monitors, remove them.
					self.dead_monitors(REALTIME, proc_key, dead_refs)
		
		if err_info:
			# Since there was an exception while parsing the log output, re-raise the
			# exception to be received by the process.
			raise err_info[1], None, err_info[2]

	def remove_processes(self, process_names):
		"""
		Removes the specified processes.
		
		Arguments:
			process_names (list)
			- The list of process names (str) to remove.
		"""
		procs_info = self.procs_info
		for proc_name in process_names:
			# Remove process info.
			if proc_name in procs_info:
				del procs_info[proc_name]
			# Remove process monitors.
			for mon_type, mon_procs in self.procs_mon.iteritems():
				if proc_name in mon_procs:
					# Notify process monitors about process removal.
					for proc_mon in mon_procs[proc_name]:
						try:
							d = proc_mon.callRemote('monitor_deleted', proc_name)
							d.addErrback(_err_pass)
						except _pb.DeadReferenceError:
							# Ignore any dead monitor references because they are being
							# removed anyway.
							pass
					# Remove monitors.
					del mon_procs[proc_name]
				# Notify all-process monitors about process removal.
				if '*' in mon_procs:
					dead_refs = []
					for proc_mon in mon_procs['*']:
						try:
							d = proc_mon.callRemote('monitor_deleted', proc_name)
							d.addErrback(_err_pass)
						except _pb.DeadReferenceError:
							dead_refs.append(proc_mon)
							if self.debug:
								print "Dead %r monitor reference to all processes from %r." % (mon_type, proc_mon)
					if dead_refs:
						# If there are any dead all-processes monitors, remove them.
						self.dead_monitors(mon_type, '*', dead_refs)
		if self.debug:
			print "Removed %i processes: %r" % (len(process_names), list(process_names))
		
	@_defer.inlineCallbacks
	def run_process(self, process_name, process_args=None, process_monitor=None, process_debug=False):
		"""
		Starts the specified process.
		
		Arguments:
			process_name (str) -- The name of the process.
		
		Optional Arguments:
			process_args (str)
			- The arguments for the process; default is an empty string.
			process_monitor (tuple)
			- A 2-tuple describing how to monitor the process instance: the monitor
			  type (str) to register, and the monitor reference
			  (twisted.spread.pb.RemoteReference); default value is `None`. 
			process_debug (bool)
			- Whether process debugging should be enabled or not; default is `False`.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: the process instance ID (int).
		"""
		proc_info = self.procs_info[process_name]
		if proc_info._state:
			raise _process.ProcessError("Cannot run process %r because its state is %r." % (process_name, proc_info._state))
		
		if self.debug:
			print "Run process %r..." % process_name,
		
		# Escape slashes and single-quotes.
		if process_args:
			process_args = process_args.replace('\\', '\\\\').replace("'", "\\'")
		
		# Generate token.
		proc_token = _os.urandom(12).encode('hex')
		if self.debug:
			print "token:%r..." % proc_token,
		
		# Setup twisted process protocol.
		proc_proto = _process.ProcessProtocol(ready=lambda p: p.transport.write(process_args + '\n') if process_args else None)
		
		# Record starting process.
		proc_inst = yield _threads.deferToThread(self.procs_db.new_process, process_name)
		proc_inst._token = proc_token
		proc_id = self.procs_id[process_name] = proc_inst.id
		self.procs_inst[proc_id] = proc_inst
		self.procs_start[(process_name, proc_token)] = proc_inst
		
		# Setup process instance monitors.
		for mon_procs in self.procs_mon.itervalues():
			mon_procs[proc_id] = set()
		if process_monitor:
			mon_type, mon_ref = process_monitor
			self.procs_mon[mon_type][proc_id].add(mon_ref)
			if self.debug:
				print "%r monitor %r..." % (mon_type, mon_ref),
			
		# Setup process run-time directory.
		# - NOTE: The process run-time directory is under the process server
		#   variable (not run-time) directory so that a process can continue running
		#   regardless of the server.
		run_path = "%s/processes/%i" % (self.var_dir, proc_id)
		tmp_dir = "%s/processes/%i" % (self.tmp_dir, proc_id)
		var_dir = "%s/shared" % self.var_dir
		log_dir = "%s/processes/%i" % (self.log_dir, proc_id)
		tmp_path = "%s/tmp" % run_path
		var_path = "%s/var" % run_path
		log_path = "%s/log" % run_path
		
		# Make directories.
		_os.mkdir(run_path, 0o700)
		_os.mkdir(tmp_dir, 0o700)
		_os.mkdir(log_dir, 0o700)
		
		# Symlink directories.
		_os.symlink(tmp_dir, tmp_path)
		_os.symlink(var_dir, var_path)
		_os.symlink(log_dir, log_path)
		
		# Setup process command.
		cmd = [_os.path.normpath(_dir + "/_serverprocesslauncher.py"), process_name, '-f', self.procs_socket, '-t', proc_token, '-r', run_path]
		if process_debug:
			cmd.append('-d')
		
		# Setup process environment variables.
		env = _os.environ.copy()
		
		# Spawn process.
		_reactor.spawnProcess(proc_proto, cmd[0], cmd, env=env, path=run_path)
		if self.debug:		
			print "starting"
			
		# Notify process instance monitors.
		self.notify_instance_state(STATE_STARTING, proc_id, args=(process_name, proc_id, proc_inst.started))
			
		# Return process instance ID.
		_defer.returnValue(proc_id)
		
	def stop(self, exit=0):
		"""
		Stops the Twisted reactor and sets the server exit code.
		
		Optional Arguments:
			exit (int) -- The exit code to return.
		"""
		self.exit = exit
		_reactor.stop()
	
	@_defer.inlineCallbacks
	def terminate_process(self, process_inst):
		"""
		Terminates the specified process.
		
		Arguments:
			process_inst (ProcessInstance)
			- The process to terminate.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		proc_id, proc_name, proc_ref = process_inst.id, process_inst.name, process_inst._ref
		
		# Update process state.
		process_inst.state = STATE_TERMINATING
		now = process_inst._terminated = _time.time()
		
		# Update database indicating that process was terminated using TERM signal.
		d = _threads.deferToThread(self.procs_db.finish_process, proc_id, now, -_signal.SIGTERM)
		d.addErrback(_err_print)
		
		if proc_ref:
			# Since we're terminating a process that we have a remote reference to,
			# tell it to terminate now.
			try:
				d = proc_ref.callRemote('terminate')
				d.addErrback(_err_pass)
			except _pb.DeadReferenceError:
				if self.debug:
					print "Dead process reference to process %s:%i from %r." % (proc_name, proc_id, proc_ref)
		
		# Check for PID.
		pid = None
		if process_inst.pid:
			pid = process_inst.pid
		else:
			pid_file = "%s/processes/%i/process.pid" % (self.var_dir, proc_id)
			try:
				pid = yield _threads.deferToThread(_get_pid, pid_file)
			except Exception as e:
				if not isinstance(e, EnvironmentError) or e.errno != _errno.ENOENT:
					_traceback.print_exc(file=_sys.stderr)
		if pid:
			# Since we have the PID, add the process instance to the list of
			# terminating processes so that if it does not stop after a short
			# duration, it will be killed.
			process_inst.pid = pid
			self.procs_term[proc_id] = process_inst
			# Notify process monitors that the process instance is being terminated.
			self.notify_instance_state(STATE_TERMINATING, proc_id, args=(proc_name, proc_id, now))
		else:
			# Since we could not get the PID, consider the process terminated
			# so notify process monitors that the process instance has been
			# terminated and clean up its references and output.
			self.notify_instance_state(STATE_TERMINATED, proc_id, args=(proc_name, proc_id)) 
			self.clean_process(process_inst)
			
		if self.debug:
			if hasattr(process_inst, '_token'):
				print "Process %s:%i (%s) terminated." % (proc_name, proc_id, process_inst._token)
			else:
				print "Process %s:%i terminated." % (proc_name, proc_id)
		
	def unregister_instance_monitor(self, process_id, monitor_type, monitor_ref):
		"""
		Unregisteres the specified process monitor to the process instance.
		
		Arguments:
			process_id (str)
			- The instance ID of the process.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		# Remove process instance monitor.
		mon_procs = self.procs_mon[monitor_type]
		mon_procs[process_id].discard(monitor_ref)
		if monitor_type == REALTIME:
			# If this was the last real-time monitor for this process, tell the
			# process instance to stop sending real-time updates.
			proc_inst = self.procs_inst[process_id]
			proc_name = proc_inst.name
			if not mon_procs[process_id] and not mon_procs[proc_name]:
				try:
					d = proc_inst._ref.callRemote('set_update_interval', self.proc_normal_intvl)
					d.addErrback(_err_pass)
					print "Stop real-time updates from process instance %s:%i." % (proc_name, process_id)
				except _pb.DeadReferenceError:
					self.dead_process(proc_inst)
					
	def unregister_process_monitor(self, process_name, monitor_type, monitor_ref):
		"""
		Unregisters the specified process monitor from the process.
		
		Arguments:
			process_name (str)
			- The name of the process.
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		# Remove process monitor.
		mon_procs = self.procs_mon[monitor_type]
		mon_procs[process_name].discard(monitor_ref)
		if monitor_type == REALTIME and process_name in self.procs_id:
			# If this was the last real-time monitor for this process, tell
			# the process instance to stop sending real-time updates.
			proc_id = self.procs_id[process_name]
			if not mon_procs[proc_id] and not mon_procs[process_name]:
				proc_inst = self.procs_inst[proc_id]
				try:
					d = proc_inst._ref.callRemote('set_update_interval', self.proc_normal_intvl)
					d.addErrback(_err_pass)
					print "Stop real-time updates from process instance %s:%i." % (process_name, proc_id)
				except _pb.DeadReferenceError:
					self.dead_process(proc_inst)
					
	def unregister_processes_monitor(self, monitor_type, monitor_ref):
		"""
		Unregisters the specified process monitor from all process.
		
		Arguments:
			monitor_type (str)
			- The monitor type.
			monitor_ref (twisted.spread.pb.RemoteReference)
			- The monitor reference.
		"""
		# Remove all process monitor.
		self.procs_mon[monitor_type]['*'].discard(monitor_ref)
	
	@_defer.inlineCallbacks
	def update_processes(self, process_names):
		"""
		Updates any of the specified processes that are out-of-date.
		
		Arguments:
			process_names (list)
			- The list of process names (str) to update.
			
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred containing: an empty (None) result.
		"""
		procs_info = self.procs_info
		# Get modified processes.
		procs_mtime = dict(((n, procs_info[n].mtime) for n in process_names if n in procs_info))
		procs = yield _threads.deferToThread(_get_processes_modified, procs_mtime)
		# Update modified processes.
		for proc_name, proc in procs.iteritems():
			if isinstance(proc, _failure.Failure):
				proc.printTraceback(file=_sys.stderr)
			elif proc_name in procs_info:
				# Only update the process if it was not removed during the yield.
				attrs = dict((kv for kv in (proc if isinstance(proc, dict) else proc.__dict__).iteritems() if kv[0] in _proc_keys))
				procs_info[proc_name].__dict__.update(attrs)
				# Notify process monitors about modified processes.
				for proc_key in (proc_name, '*'):
					for mon_type, mon_procs in self.procs_mon.iteritems():
						if proc_key in mon_procs:
							dead_refs = []
							for proc_mon in mon_procs[proc_key]:
								try:
									d = proc_mon.callRemote('monitor_modified', proc_name)
									d.addErrback(_err_pass)
								except _pb.DeadReferenceError:
									dead_refs.append(proc_mon)
									if self.debug:
										if proc_key != '*':
											print "Dead %r monitor reference to process %r from %r." % (mon_type, proc_name, proc_mon)
										else:
											print "Dead %r monitor reference to all processes from %r." % (mon_type, proc_mon)
							if dead_refs:
								# If there are any dead progress monitors, remove them.
								self.dead_monitors(mon_type, proc_key, dead_refs)
		if self.debug and procs:
			print "Updated %i processes: %r" % (len(procs), list(procs.iterkeys()))
			

class ProcessDatabase:
	"""
	The Process Database provides access to the process server database.
	
	NOTE: Most (if not every) method inside this class is blocking (including the
	constructor).
	
	Instance Attributes:
		path (str)
		- The path to the sqlite3 database file for the process server.
		procs_tb (str)
		- The processes table.
	"""
	
	def __init__(self, path):
		"""
		BLOCKING: Initializes a Process Database instance.
		
		Arguments:
			path (str) -- The path to the sqlite3 database file for the process server.
		"""
		if not isinstance(path, basestring):
			raise TypeError("path:%r is not a string." % path)
		elif not path:
			raise ValueError("path:%r is empty." % path)
			
		self.path = path
		self.procs_tb = _db_procs_tb
		
		conn = _sqlite3.connect(self.path)
		try:
			with conn: # Auto-commit/rollback
				conn.execute("""
					CREATE TABLE IF NOT EXISTS %s
					-- This table contains basic information about each time a process was run.
					(
						id INTEGER PRIMARY KEY ASC AUTOINCREMENT,
						-- The primary key used to identify this running instance of the process.
						name TEXT,
						-- The name of the process.
						started REAL,
						-- The time (UTC) that the process was started.
						finished REAL,
						-- The time (UTC) that the process finished.
						exit INTEGER
						-- The exit status of the process: 0 is success; otherwise, error.
					);
				""" % self.procs_tb)
		finally:
			conn.close()
	
	def delete_process(self, process_id):
		"""
		BLOCKING: Deletes an existing database entry for a process.
		
		Arguments:
			process_id (int) -- The ID of the process entry to delete.
		"""
		conn = _sqlite3.connect(self.path)
		try:
			with conn: # Auto-commit/rollback
				conn.execute("""DELETE FROM %s WHERE id = ?;""" % self.procs_tb, (process_id,))
		finally:
			conn.close()
		
	def finish_process(self, process_id, process_finished, process_exit):
		"""
		BLOCKING: Finishes the specified process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			process_finishes (float) -- The time (UTC) that the process finished. 
			process_exit (int) -- The exit status of the process.
		"""
		conn = _sqlite3.connect(self.path)
		try:
			with conn: # Auto-commit/rollback
				conn.execute("""UPDATE %s SET finished = ?, exit = ? WHERE id = ?;""" % self.procs_tb, (process_finished, process_exit, process_id))
		finally:
			conn.close()
	
	def new_process(self, process_name):
		"""
		BLOCKING: Creates a new entry for a process.
		
		Returns:
			(ProcessInstance) -- The new process info.
		"""
		conn = _sqlite3.connect(self.path)
		started = _time.time()
		try:
			with conn: # Auto-commit/rollback
				proc_id = conn.execute("""INSERT INTO %s (name, started) VALUES (?, ?);""" % self.procs_tb, (process_name, started)).lastrowid
		finally:
			conn.close()
		proc_inst = ProcessInstance(proc_id, process_name, started)
		return proc_inst


def main():
	print __doc__.strip()
	return 0

if __name__ == "__main__":
	exit(main())

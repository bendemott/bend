# coding: utf-8
"""
The server module contains everything required by the process server.

The server module cannot be run on its own. The indended use for this module is
to be imported from a command-line launcher script, and for its run_server()
method to be called. An example script would be as such:
	
	from stockpile.processing.server import run_server
	
	if __name__ == "__main__":
		exit(run_server())
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.6"
__status__ = "Development"
__project__ = "stockpile"

import dateutil.parser as _dateutil_parser
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

_dir = _os.path.dirname(_os.path.abspath(__file__))
_db_path = _dir + "/run/processes.sqlite3"
_db_procs_tb = 'processes'

_start_check = 1.0
_start_miss = 1.0
_start_term = 5 // _start_check
_update_check = 2.0
_update_miss = 5.0
_update_term = 30 // _update_check
_proc_normal = 2.0
_proc_stream = 0.2

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

def is_graph(string):
	"""
	Determines whether the string contains only ASCII graphical characters or not.
	
	Arguments:
		string (str) -- The string to check.
		
	Returns:
		(bool) -- On success, `True`; otherwise, `False`.
	"""
	return not [1 for char in string if not (0x21 <= ord(char) <= 0x7E)]

def parse_syslog(entry):
	"""
	Parses a syslog entry.
	
	Arguments:
		entry (str) -- The syslog entry.
	
	Returns:
		header (dict)
		- Contains the following header information: the priority (int) in 'prival';
			the version (int) in 'version'; the timestamp (datetime) in 'timestamp';
			the host (str) in 'hostname', the application  (str) in 'appname'; the
			process ID (str) in 'procid' (which is not strictly an OS PID); and the
			message type (str) in 'msgid'.
		data (dict)
		- Contains elements keyed by IDs (str); each element is a dict containing
			values (unicode) keyed by names (str).
		message (mixed)
		- Either a string of an unspecified encoding (str) or a unicode string
			(unicode).
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
						# If the next byte is a space, we have another parameter for this
						# element.
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
					# Since the byte after the end of the previous element either points
					# beyond the data or is a space, we're done with the data elements.
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
	The default function for running the process server from the command-line.
	
	Optional Arguments:
		args (list)
		- The command line arguments to use (including the command-line name in the
		  first index); default is `sys.argv`.
	
	Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
	"""
	import optparse
	
	if not args:
		args = _sys.argv
		
	# Parse arguments.
	prog = _os.path.basename(args[0])
	parser = optparse.OptionParser(prog=prog)
	parser.add_option('-d', '--debug', dest='debug', help="Enable server debugging.", action='store_true')
	options, args = parser.parse_args(args[1:])
	
	# Get/check options.
	debug = options.debug
	
	# Start server.
	server = ProcessServer(debug=debug)
	return server.run()

class ProcessInfo:
	"""
	The Process Info class contains information pertaining to a process	that's
	running.
	
	Instance Attributes:
		id (int)
		- The ID of the process.
		name (str)
		- The name of the process.
		started (float)
		- The time (UTC) that the process was started.
		registered (float)
		- The time (UTC) that the process was registered.
		updated (float)
		- The time (UTC) that the process's status was last updated.
		missed (float)
		- The time (UTC) that the process's status update was last missed.
		misses (int)
		- The number of consecutive times the process's status update was missed.
		ref (twisted.spread.pb.RemoteReference)
		- A reference to the process.
		progress (float)
		- The progress of the process: between 0 and 1.
		
	Temporary Instance Attributes:
		_token (str)
		- The server provided token to use when registering (this is used when the
		  server starts the process).
	"""

	def __init__(self, id, name, started):
		"""
		Instantiates the process info with the specified arguments.
		
		Arguments:
			id (int) -- The ID of the process.
			name (str) -- The name of the process.
			started (float) -- The time (UTC) that the process was started.
		"""
		self.id = id
		self.name = name
		self.started = started
		self.registered = None
		self.updated = None
		self.missed = None
		self.misses = 0
		self.ref = None
		self.progress = 0


class ProcessServer(_pb.Root):
	"""
	The Process Server class manages processes.
	
	Instance Attributes:
		debug (bool)
		- Whether debugging is enabled or not.
		exit (int)
		- The exit code the server returns when it's stopped.
		db (ProcessDatabase)
		- The database that stores information about running processes.
		running (dict)
		- Maps the names (string) of running processes to their IDs (int).
		processes (dict)
		- The running processes (ProcessInfo); keyed by their running process ID
			(int).
		registered (dict)
		- The processes (ProcessInfo) that are registered; keyed by process ID
		  (int).
		starting (dict)
		- The processes (ProcessInfo) that are starting but are not yet registered;
		  keyed by a 2-tuple: the process name (str) and token (str).
		listeners (dict)
		- The list (list) of clients listening (twisted.internet.pb.RemoteReference)
			to each process; keyed by process ID (int).
		streamers(dict)
		- The list (list) of clients streaming (twisted.internet.pb.RemoteReference)
			each process; keyed by process ID (int).
		start_term (int)
		- The number of consecutive times that a process can miss registering before
		 being terminated.
		start_check (float)
		- The interval (seconds) at which starting processes are monitored.
		start_miss (float)
		- The time (seconds) after which a process that is starting is considered to
		  have missed registering (i.e., the process is taking too long to start up
		  and still hasn't registered).
		update_term (int)
		- The number of consecutive times that a process can miss updating its
		  status before being terminated.
		update_check (float)
		- The interval (seconds) at which registered processes are monitored.
		update_miss (float)
		- The time (seconds) after which a registered process is considered to have
			missed its status update (i.e., the process has not provided a status
			update within the required amount of time).
		process_normal (float)
		- The interval (seconds) at which a registered process that's running
		  normally is told to update the server.
		process_stream (float)
		- The interval (seconds) at which a registered process that's streaming its
			updates is told to update the server.
	"""
	
	def __init__(self, debug=False):
		"""
		Initializes a Process Server instance.
		
		Optional Arguments:
			debug (bool)
			- Whether debugging should be enabled or not; default is `False`. 
		"""
		self.debug = bool(debug)
		self.exit = None
		self.db = None
		self.running = {}
		self.processes = {}
		self.registered = {}
		self.starting = {}
		self.listeners = {}
		self.streamers = {}
		self.start_term = _start_term
		self.start_check = _start_check
		self.start_miss = _start_miss
		self.update_term = _update_term
		self.update_check = _update_check
		self.update_miss = _update_miss
		self.process_normal = _proc_normal
		self.process_stream = _proc_stream
		
		d = _threads.deferToThread(ProcessDatabase, _os.path.abspath(_db_path))
		d.addCallbacks(lambda db: setattr(self, 'db', db), self.err_init_db)
		
	def err_init_db(self, reason):
		"""
		Called if the database could not be initialized.
		
		Arguments:
			reason (twisted.python.failure.Failure) -- The reason for failure.
		"""
		print_failure(reason)
		self.stop(1)
		
	def finish_process(self, process_info, process_exit):
		"""
		Finishes up the specified process with an exit status.
		
		Arguments:
			process_info (ProcessInfo) -- The process to finish.
			process_exit (int) -- The exit status of the process.
		"""
		if not isinstance(process_info, ProcessInfo):
			raise TypeError("process_info:%r is not a ProcessInfo." % process_info)
		if not isinstance(process_exit, int):
			raise TypeError("process_exit:%r is not an int." % process_info)
			
		proc_id, proc_name = process_info.id, process_info.name
			
		# Update database that process is finished.
		d = _threads.deferToThread(self.db.finish_process, proc_id, process_exit)
		d.addErrback(print_failure)
		
		# Clean the finished process; remove reference: running, processes,
		# registered, starting, listeners, streamers.
		if proc_name in self.running and self.running[proc_name] == proc_id:
			del self.running[proc_name]
		if proc_id in self.processes:
			del self.processes[proc_id]
		if proc_id in self.registered:
			del self.registered[proc_id]
		if hasattr(process_info, '_token'):
			if (proc_name, process_info._token) in self.starting:
				del self.starting[(proc_name, process_info._token)]
		if proc_id in self.listeners:
			for listener in self.listeners[proc_id]:
				try:
					d = listener.callRemote('listen_done', process_exit)
				except _pb.DeadReferenceError:
					if self.debug:
						print "Dead listener reference to process %r:%r from %r." % (proc_id, proc_name, listener)
				else:
					d.addErrback(print_failure)
			del self.listeners[proc_id]
		if proc_id in self.streamers:
			for streamer in self.streamers[proc_id]:
				try:
					d = streamer.callRemote('stream_done', process_exit)
				except _pb.DeadReferenceError:
					if self.debug:
						print "Dead streamer reference to process %r:%r from %r." % (proc_id, proc_name, streamer)
				else:
					d.addErrback(print_failure)
			del self.streamers[proc_id]
		
	def monitor_registered_processes(self):
		"""
		Monitors registerd processes by making sure that they are regularly updating
		their statuses.
		"""
		now = _time.time()
		missed = now - self.update_miss
		terminate = []
		for proc_info in self.registered.itervalues():
			if self.debug:
				print "Check process %r:%r..." % (proc_info.id, proc_info.name),
			if (proc_info.updated or proc_info.registered) < missed:
				# Record that the process status was not updated by the update
				# deadline.
				proc_info.missed = now
				proc_info.misses += 1
				if self.debug:
					print "missed status update %r times." % proc_info.misses
				if proc_info.misses >= self.update_term:
					print "Terminating process %r:%r." % (proc_info.id, proc_info.name)
					deadline = self.update_miss * self.update_term
					elapsed = _time.time() - (proc_info.updated or proc_info.registered)
					reason = _failure.Failure(_process.TerminateProcess("Failed to update %i consecutive times over the past %.3f seconds; last updated %.3f seconds ago." % (proc_info.misses, deadline, elapsed)))
					# Add process to a termination list.
					# - NOTE: This is required because defer.execute() calls the callback
					#   immediately (i.e., before returning) which results in a
					#   RunTimeError exception because the self.terminate_process() method
					#   modifies the `self.registered` dict (which is the dict we're
					#   iterating over).
					terminate.append(proc_info)
			else:
				proc_info.misses = 0
				if self.debug:
					print "okay."
		# Terminate naughty processes.
		for proc_info in terminate:
			try:
				self.terminate_process(proc_info)
			except Exception as e:
				_sys.stderr.write(repr(e) + '\n')
				_traceback.print_exc(file=_sys.stderr)
		# Call this method later.
		_reactor.callLater(self.update_check, self.monitor_registered_processes)

	def monitor_starting_processes(self):
		"""
		Monitors processes that are starting by making sure that they register
		shortly after their creation.
		"""
		now = _time.time()
		missed = now - self.start_miss
		terminate = []
		for proc_info in self.starting.itervalues():
			if self.debug:
				print "Check process %r:%r (%r)..." % (proc_info.id, proc_info.name, proc_info._token),
			if proc_info.started < missed:
				# Record that the process was not registered before the registration
				# deadline.
				proc_info.missed = now
				proc_info.misses += 1
				if self.debug:
					print "missed registration %r times." % proc_info.misses
				if proc_info.misses >= self.start_term:
					# Don't pass a reason because calling the term_process method in this
					# instance will not actually terminate the process but put it in a
					# list of processes that are going to be terminated. Then if the
					# process does finally try registering, it will be told to terminate
					# and a reason will be given then.
					if self.debug:
						print "Terminate starting process %r:%r (%r) due to lack of registration." % (proc_info.id, proc_info.name, proc_info._token)
					# Add process to a termination list.
					# - NOTE: This is required because defer.execute() calls the callback
					#   immediately (i.e., before returning) which results in a
					#   RunTimeError exception because the self.terminate_process() method
					#   modifies the `self.starting` dict (which is the dict we're
					#   iterating over).
					terminate.append(proc_info)
			else:
				proc_info.misses = 0
				if self.debug:
					print "wait."
		# Terminate naughty processes.
		for proc_info in terminate:
			try:
				self.terminate_process(proc_info)
			except Exception as e:
				_sys.stderr.write(repr(e) + '\n')
				_traceback.print_exc(file=_sys.stderr)
		# Call this method later.
		_reactor.callLater(self.start_check, self.monitor_starting_processes)
		
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
				result = yield self.start_process(parts[1])
				_defer.returnValue(result)
			_defer.returnValue("{process}")
		elif parts[0] == 'help':
			_defer.returnValue("exec\nlist")
	
	def remote_finish_process(self, process_id, process_status):
		"""
		Finishes the specified process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			process_status (int) -- The exit status of the process.
		"""
		if self.debug:
			print "Finish process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
		proc_info = self.processes[process_id]
		self.finish_process(proc_info, process_status)
		if self.debug:
			print "%r exit:%r" % (proc_info.name, process_status)
		else:
			print "Finishing process %r:%r exit %r" % (process_id, proc_info.name, process_status)
		
	def remote_listen_process(self, process_id, listener):
		"""
		Register the client's specified listener to the process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			listener (twisted.internet.pb.RemoteReference) -- The listener callbacks.
		"""
		if self.debug:
			print "Listen process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
		if not isinstance(listener, _pb.RemoteReference):
			if self.debug:
				print "TypeError: listener:%r not RemoteReference." % listener
			raise TypeError("listener:%r is not a twisted.internet.pb.RemoteReference." % listener)
		self.listeners[process_id].append(listener)
		if self.debug:
			print "%r from %r." % (self.process[process_id].name, listener)
		else:
			print "Listening process %r:%r from %r." % (process_id, self.processes[process_id].name, listener)
	
	@_defer.inlineCallbacks
	def remote_register_process(self, process_name, process_ref, process_token=None):
		"""
		Register the specified process with this server.
		
		NOTE: If a TerminateProcess exception is raised, the registering process
		should terminate.
		
		Arguments:
			process_name (str)
			- The name of the process.
			process_ref (twisted.spread.pb.RemoteReference)
			- A remote reference to the process.
			
		Optional Arguments:
			process_token (str)
			- The server provided token to use when registering (this is used when the
			  server starts the process).
		
		Returns:
			(Deferred)
			- A deferred containing the new ID (int) for the registered process.
		"""
		if self.debug:
			print "Register process %r..." % process_name,
		if not isinstance(process_name, basestring):
			if self.debug:
				print "TypeError name:%r not string." % process_name
			raise TypeError("process_name:%r is not a string." % process_name)
		if not isinstance(process_ref, _pb.RemoteReference):
			if self.debug:
				print "TypeError ref:%r not RemoteRefernce." % process_ref
			raise TypeError("process_ref:%r is not a twisted.internet.pb.RemoteReference." % process_ref)
		
		if process_token is not None:
			# Since a process token was provided, this process instance was started by
			# the server and thus should be in the starting list.
			if (process_name, process_token) in self.starting:
				# Since this process instance was starting and is now registering,
				# finish registering.
				proc_id = self.running[process_name]
				proc_info = self.processes[proc_id]
				# Clean up process start-up data.
				del self.starting[(process_name, process_token)]
				del proc_info._token
				if self.debug:
					print "started %r (%r)." % (proc_id, process_token)
			elif process_name in self.running:
				# Since the process is already running, raise an AlreadyRunning
				# exception to be received by the client.
				if self.debug:
					print "AlreadyRunning %r:%r." % (proc_id, process_name)
				raise _process.AlreadyRunning("Process %r:%r is already running." % (proc_id, process_name))
			else:
				# This process instance was starting but since its process name/token
				# pair was not in the starting list it should be terminated because it
				# did not register within the allotted time frame. Therefore, terminate
				# the process by raising a TerminateProcess exception to be received by
				# the process.
				# NOTE: Any processes that are queued to be terminated are completely
				# cleaned so only this reference needs to be removed.
				if self.debug:
					 print "terminating (%r)." % process_token
				else:
					print "Terminating process %r (%r)." % (process_name, process_token)
				deadline = self.start_miss * self.start_term
				elapsed = _time.time() - proc_info.started
				raise _process.TerminateProcess("Failed to register in %.3f seconds: %.3f seconds elapsed." % (deadline, elapsed))
		else:
			# Since a process token was not provided, this process instance was not
			# started by the server.
			if process_name not in self.running:
				# Since the process is not running at all, record the new process.
				proc_info = yield _threads.deferToThread(self.db.new_process, process_name)
				proc_id = self.running[process_name] = proc_info.id
				self.processes[proc_id] = proc_info
				self.listeners[proc_id] = []
				self.streamers[proc_id] = []
				if self.debug:
					print "new %r." % proc_id
			else:
				# Since the process is already running, raise an AlreadyRunning
				# exception to be received by the process.
				if self.debug:
					print "AlreadyRunning %r:%r." % (proc_id, process_name)
				raise _process.AlreadyRunning("Process %r:%r is already running." % (proc_id, process_name))
		
		# Setup registered process.
		proc_info.ref = process_ref
		proc_info.registered = _time.time()
		self.registered[proc_id] = proc_info
		
		if not self.debug:
			print "Registered process %r:%r." (proc_id, process_name)
		
		# Return the process ID.
		_defer.returnValue(proc_id)
		
	def remote_run_process(self, process_name, process_args=None, process_listener=None, process_streamer=None, process_debug=False):
		"""
		Runs the specified process.
		
		Arguments:
			process_name (str) -- The name of the process.
		
		Optional Arguments:
			process_args (str)
			- The arguments for the process; default is an empty string.
			process_listener (twisted.spread.pb.RemoteReference)
			- Register this listener to the process; default is `None`.
			process_streamer (twisted.spread.pb.RemoteReference)
			- Register this streamer to the process; default is `None`.
			process_debug (bool)
			- Whether process debugging should be enabled or not; default is `False`.
		"""
		return self.start_process(process_name, process_args, process_listener, process_streamer, process_debug)
		
	def remote_stream_process(self, process_id, streamer):
		"""
		Register the client's specified streamer to the process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			streamer (twisted.internet.pb.RemoteReference) -- The streamer callbacks.
		"""
		if self.debug:
			print "Stream process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
		if not isinstance(streamer, _pb.RemoteReference):
			if self.debug:
				print "TypeError: streamer:%r not RemoteReference." % streamer
			raise TypeError("streamer:%r is not a twisted.internet.pb.RemoteReference." % streamer)
			
		if self.debug:
			print "to %r." % streamer
		else:
			print "Streaming process %r:%r to %r." % (process_id, self.processes[process_id].name, streamer)
			
		# If this is the first streamer, tell the process to start streaming status
		# updates.
		if not self.streamers[process_id]:
			print "Start streaming process %r:%r." % (process_id, self.processes[process_id].name)
			d = self.streamers[process_id].ref.callRemote('set_update_interval', self.process_stream)
			d.addErrback(print_failure)
		# Add streamer to list.
		self.streamers[process_id].append(streamer)
	
	def remote_unregister_listener(self, process_id, listener):
		"""
		Unregister the specified listener from the process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			listener (twisted.internet.pb.RemoteReference) -- The listener callbacks.
		"""
		if self.debug:
			print "Unlisten process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
		if not isinstance(listener, _pb.RemoteReference):
			if self.debug:
				print "TypeError: ref:%r not RemoteReference" % listener
			raise TypeError("listener:%r is not a twisted.internet.pb.RemoteReference." % listener)
		# Remove the listener from the list.
		idx = self.listeners[process_id].index(listener)
		if idx != -1:
			del self.listeners[process_id][idx]
		if self.debug:
			print "%r from %r" % (self.processes[process_id].name, listener)
		else:
			print "Unregister process %r:%r listener %r." % (process_id, self.processes[process_id].name, listener)
	
	def remote_unregister_streamer(self, process_id, streamer):
		"""
		Unregister the specified streamer from the process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			streamer (twisted.internet.pb.RemoteReference) -- The streamer callbacks.
		"""
		if self.debug:
			print "Unstream process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
		if not isinstance(streamer, _pb.RemoteReference):
			if self.debug:
				print "TypeError: streamer:%r not RemoteReference." % streamer
			raise TypeError("streamer:%r is not a twisted.internet.pb.RemoteReference." % streamer)
			
		if self.debug:
			print "%r from %r." % (self.processes[process_id].name, streamer)
		else:
			print "Unregister process %r:%r streamer %r." % (process_id, self.processes[process_id].name, streamer)
		
		# Remove the streamer from the list.
		idx = self.streamers[process_id].index(streamer)
		if idx != -1:
			del self.streamers[process_id][idx]
		# If there are no more streamers, tell the process to update at normal
		# intervals.
		if not self.streamers[process_id]:
			print "Stop streaming process %r:%r." % (process_id, self.processes[process_id].name)
			self.processes[process_id].ref.callRemote('set_update_interval', self.process_normal)
		
	def remote_update_status(self, process_id, process_buffers):
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
		"""
		if self.debug:
			print "Update process %r..." % process_id,
		if process_id not in self.registered:
			if self.debug:
				print "NotRegistered."
			raise _process.NotRegistered("Process ID:%r is not registered." % process_id)
			
		proc_info = self.registered[process_id]
		if self.debug:
			print "%r buffers %r..." % (proc_info.name, dict(((b,len(d)) for b,d in process_buffers.iteritems()))),
		
		# Parse log output.
		try:
			log = process_buffers[3]
			if log:
				lines = log.splitlines()
				head, data, msg = parse_syslog(lines[-1])
				progress = float(data['status@ridersdiscount']['progress'])
				# Update process progress.
				proc_info.updated = _time.time()
				proc_info.progress = progress
				if self.debug:
					print "status:%.3f" % progress
			elif self.debug:
				print "status:%r" % None
			err_info = None
		except Exception as e:
			print "Bad process %r:%r log; reason: %r." % (process_id, proc_info.name, e)
			err_info = _sys.exc_info()
		
		# Forward output to streamers.
		streamers = self.streamers[process_id]
		dead = []
		for i, streamer in enumerate(streamers):
			try:
				d = streamer.callRemote('stream_update', proc_info.progress, process_buffers)
			except _pb.DeadReferenceError:
				dead.append(i)
				if self.debug:
					print "Dead streamer reference to process %r:%r from %r." % (proc_info.id, proc_info.name, streamer)
			else:
				d.addErrback(print_failure)
		if dead:
			# If there are any dead streamers, remove them.
			for i in reversed(dead):
				del streamers[i]
		
		if err_info:
			# Since there was an exception while parsing the log output, re-raise the
			# exception to be received by the process.
			raise err_info[1], None, err_info[2]
		
	def run(self):
		"""
		Starts the Twisted _reactor.
		"""
		_reactor.listenTCP(_process.PORT, _pb.PBServerFactory(self))
		_reactor.callLater(0, self.monitor_registered_processes)
		_reactor.callLater(0, self.monitor_starting_processes)
		_reactor.callLater(0, self.update_process_listeners)
		_reactor.run()
		return self.exit

	@_defer.inlineCallbacks
	def start_process(self, process_name, process_args=None, process_listener=None, process_streamer=None, process_debug=False):
		"""
		Starts the specified process.
		
		Arguments:
			process_name (str) -- The name of the process.
		
		Optional Arguments:
			process_args (str)
			- The arguments for the process; default is an empty string.
			process_debug (bool)
			- Whether process debugging should be enabled or not; default is `False`.
		"""
		if self.debug:
			print "Starting process %r..." % process_name,
		if isinstance(process_args, basestring) or process_name is None:
			if process_args:
				# Escape slashes and single-quotes.
				process_args = process_args.replace('\\', '\\\\').replace("'", "\\'")
		else:
			if self.debug:
				print "TypeError args:%r not string."
			raise TypeError("process_args:%r is not a string." % process_args)
		if process_listener is not None and not isinstance(process_listener, _pb.RemoteReference):
			if self.debug:
				print "TypeError listener not RemoteReference."
			raise TypeError("process_listener:%r not a twisted.spread.pb.RemoteReference or None." % process_listener)
		if process_streamer is not None and not isinstance(process_streamer, _pb.RemoteReference):
			if self.debug:
				print "TypeError listener not RemoteReference."
			raise TypeError("process_streamer:%r not a twisted.spread.pb.RemoteReference or None." % process_streamer)
		
		# Get server info.
		#TODO: The server should determine this when it starts.
		host = 'localhost'
		server = '%s:%i' % (host, _process.PORT)
		
		# Generate token.
		proc_token = _os.urandom(12).encode('base64').strip()
		if self.debug:
			print "%r..." % proc_token,
		
		# Setup process.
		cmd = [_os.path.normpath(_dir + "/_serverprocesslauncher.py"), process_name, '-t', server, '--server-token', proc_token]
		if process_debug:
			cmd.append('-d')
		env = _os.environ.copy()
		run_path = _dir + "/run"
		
		proc_proto = _process.ProcessProtocol(ready=lambda p: p.transport.write(process_args + '\n'))
		# recv=lambda p,f,d: echo(_process.color_worker_output(f, d)
		
		# Record starting process.
		proc_info = yield _threads.deferToThread(self.db.new_process, process_name)
		proc_info._token = proc_token
		proc_id = self.running[process_name] = proc_info.id
		self.processes[proc_id] = proc_info
		self.starting[(process_name, proc_token)] = proc_info
		self.listeners[proc_id] = [process_listener] if process_listener else []
		self.streamers[proc_id] = [process_streamer] if process_streamer else []
		if self.debug:
			print "%r..." % proc_id,
			if process_listener:
				print "listener %r..." % process_listener,
			if process_streamer:
				print "streamer %r..." % process_streamer,
		
		# Spawn process.
		_reactor.spawnProcess(proc_proto, cmd[0], cmd, env=env, path=run_path)
		
		if self.debug:		
			print "started"
		
	def stop(self, exit=0):
		"""
		Stops the Twisted reactor and sets the server exit code.
		
		Optional Arguments:
			exit (int) -- The exit code to return.
		"""
		self.exit = exit
		_reactor.stop()
		
	def terminate_process(self, process_info):
		"""
		Terminates the specified process.
		
		Arguments:
			process_info (ProcessInfo)
			- The process to terminate.
		"""
		if not isinstance(process_info, ProcessInfo):
			raise TypeError("process_info:%r is not a ProcessInfo." % process_info)
			
		# Finish the process indicating that it was terminated using the TERM
		# signal.
		self.finish_process(process_info, -_signal.SIGTERM)
		
		if process_info.ref:
			# Since we're terminating a process that we have a remote reference to
			# (i.e., it's registered), tell it to terminate now.
			try:
				d = process_info.ref.callRemote('terminate')
			except _pb.DeadReferenceError:
				if self.debug:
					print "Dead process reference to process %r:%r from %r." % (process_info.id, process_info.name, process_info.ref)
			else:
				d.addErrback(lambda r: None)
			
		if self.debug:
			print "Process %r:%r%s terminated." % (process_info.id, process_info.name, (" (%r)" % process_info._token) if hasattr(process_info, '_token') else "")

	def update_process_listeners(self):
		"""
		Updates process listeners regularly.
		"""
		for proc_id, listeners in self.listeners.iteritems():
			proc_info = self.processes[proc_id]
			if proc_info.started:
				progress = proc_info.progress
				dead = []
				for i, listener in enumerate(listeners):
					try:
						d = listener.callRemote('listen_update', progress)
					except _pb.DeadReferenceError:
						dead.append(i)
						if self.debug:
							print "Dead streamer reference to process %r:%r from %r." % (proc_info.id, proc_info.name, listener)
					else:
						d.addErrback(print_failure)
				if dead:
					# If there are any dead listeners, remove them.
					for i in reversed(dead):
						del listeners[i]
		_reactor.callLater(self.process_normal, self.update_process_listeners)


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
						status INTEGER
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
		
	def finish_process(self, process_id, process_status):
		"""
		BLOCKING: Finishes the specified process.
		
		Arguments:
			process_id (int) -- The ID of the process.
			process_status (int) -- The exit status of the process.
		"""
		finished = _time.time()
		conn = _sqlite3.connect(self.path)
		try:
			with conn: # Auto-commit/rollback
				conn.execute("""UPDATE %s SET finished = ?, status = ? WHERE id = ?;""" % self.procs_tb, (finished, process_status, process_id))
		finally:
			conn.close()
	
	def new_process(self, process_name):
		"""
		BLOCKING: Creates a new entry for a process.
		
		Returns:
			(ProcessInfo) -- The new process info.
		"""
		conn = _sqlite3.connect(self.path)
		started = _time.time()
		try:
			with conn: # Auto-commit/rollback
				proc_id = conn.execute("""INSERT INTO %s (name, started) VALUES (?, ?);""" % self.procs_tb, (process_name, started)).lastrowid
		finally:
			conn.close()
		proc_info = ProcessInfo(proc_id, process_name, started)
		return proc_info


def main():
	print __doc__.strip()
	return 0

if __name__ == "__main__":
	exit(main())

# coding: utf-8
"""
The process module is the base for processes.

The process module cannot be ran on its own. The intended use for this
module is as a base for running and implementing processes. The
run_process() function is implemented in such a way that a command-line
process launcher could import this module and call the function. An
example script would be as such:
	
  from stockpile.processing.process import run_process
	
  if __name__ == "__main__":
    exit(run_process())

Processes can be implemented two separate ways. The simplest way is as a
Configurable Process. A Configurable Process is simply a JSON file
describing the process under the "processing/processes/configs"
directory. The file's name must begin with an alphanumeric character and
any proceeding characters must be either alphanumeric or underscores. It
must be suffixed with the ".json" extension. The file must contain only
a dict (object). The dict must have the "title", "desc" and "cmd" keys
set. "title" is the title (str) of the process. "desc" is a description
(str) of the process. "cmd" is the command (str) to execute. An example
Process Config would be developed as such:

  {{"#": "processing/processes/configs/myprocess.json",
    "title": "My Process",
    "desc": "This process runs my command.",
    "cmd": "/path/to/my/command"
  }}

A process can also be implemented in a more complicated way as a Process
Module. A Process Module is a folder (python package module) with an
"__init__.py" script under the "processing/processes/modules" directory.
The folder's name must begin with an alphanumeric character and any
proceeding characters must be either alphanumeric or underscores. The
script must define a class that subclasses the `Process` class and that
either is or is referenced by the `process` module attribute. This class
must set the `title`, `desc` and `worker` class attributes. `title` is
the title (str) of the process. `desc` is a description (str) of the
process. `worker` is an instance of the `Worker` class (or subclass
there of). An example Process Module would be developed as such:

  #processing/processes/modules/myprocess/__init__.py
  from stockpile.processing.process import Process, Worker

  class MyProcess(Process):
    title = "My Process"
    desc = "This process runs my command."
    worker = Worker('/path/to/my/command')

  process = MyProcess

Process Modules and Configuration can be organized a hierarchical folder
structures under their respective directories: "processing/processes/
modules" for modules; and "processing/processes/configs" for configs.
All folders must being with an alphanumeric character and any proceeding
characters must be either alphanumeric or underscores. NOTE: Process
Modules take precedence over Process Configs; therefore, if a Process
Module and a Process Config both were to share the same effective name,
then the Process Module would be used.

  E.g.,
	
    Process Module: 
      file = "processing/processes/modules/myprocess/__init__.py"
      name = "myprocess"
			
    Process Config:
      file = "processing/processes/configs/myprocess.json"
      name = "myprocess"
			
    The results of find_process() or get_process() would return results
    pertaining to the Process Module named "myprocess" not the Process
    Config. 
	

Constants:
  CLIENT_PORT (int)
  - The default port that the Process Server listens for clients on:
    `{client_port!r}`.
  SERVER (str)
  - The default name of the Process Server: {server!r}.
  STDIN_FD (int)
  - The FD used by STDIN: `{stdin!r}`.
  STDOUT_FD (int)
  - The FD used by STDOUT: `{stdout!r}`.
  STDERR_FD (int)
  - The FD used by STDERR: `{stderr!r}`.
  STDLOG_FD (int)
  - The FD used by a process to monitor log/status output from its
    underlying worker: `{stdlog}`.
	  
Path Prefixes:
  PREFIX_LOCAL_RUN (str)
  - The path to the local run-time data file directory: {local_run!r}.
  PREFIX_LOCAL_VAR (str)
  - The path to the local variable data file directory: {local_var!r}.
  PREFIX_USR_RUN (str)
  - The path to the run-time date file directory: {usr_run!r}
  PREFIX_USR_VAR (str)
  - The path to the variable data file directory: {usr_var!r}.
  PREFIX_TMP (str)
  - The path to the temporary data file directory: {tmp!r}.
	  
Process Types:
  MODULE (str)
  - The process is defined by a Process Module: {module!r}.
  CONFIG (str)
  - The process is defined by a Process Config: {config!r}.
	
TODO:
- When the server root object raises a DeadReferenceError, stop trying
  to update the server, try re-connecting and re-registering to the
  server, and if the server cannot be connected to, then give up on the
  server but continue running normally.
"""

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import atexit as _atexit
import errno as _errno
import imp as _imp
import inspect as _inspect
import json as _json
import os as _os
import re as _re
import shlex as _shlex
import signal as _signal
import sys as _sys
import time as _time
import traceback as _traceback

from twisted.internet import defer as _defer, error as _error, protocol as _protocol, reactor as _reactor
from twisted.spread import pb as _pb

import _daemon

CLIENT_PORT = 8087
SERVER = "processserver"
STDIN_FD = 0
STDOUT_FD = 1
STDERR_FD = 2
STDLOG_FD = 3

PREFIX_LOCAL_RUN = "/var/local/run"
PREFIX_LOCAL_VAR = "/var/local"
PREFIX_USR_RUN = "/var/run"
PREFIX_USR_VAR = "/var"
PREFIX_TMP = "/tmp"

MODULE = 'module'
CONFIG = 'config'

_dir = _os.path.dirname(_os.path.abspath(__file__))
_mod_dir = "%s/processes/modules" % _dir
_conf_dir = "%s/processes/configs" % _dir

__doc__ = __doc__.format(
	dir=_dir,
	client_port=CLIENT_PORT,
	server=SERVER,
	stdin=STDIN_FD,
	stdout=STDOUT_FD,
	stderr=STDERR_FD,
	stdlog=STDLOG_FD,
	local_run=PREFIX_LOCAL_RUN,
	local_var=PREFIX_LOCAL_VAR,
	usr_run=PREFIX_USR_RUN,
	usr_var=PREFIX_USR_VAR,
	tmp=PREFIX_TMP,
	module=MODULE,
	config=CONFIG
)

_connect_tmo = 1

_worker_check = 1.0
_worker_delay = 1.0

_proc_dir_perm = 0o755

_re_proc_basename = _re.compile(r'''
^          # Match beginning of string.
[\w][\w_]* # A word (alphanumeric followed by alphanumeric/underscore).
$          # Match until end of string.
''', _re.VERBOSE)
_re_proc_fullname = _re.compile(r'''
^            # Match beginning of string.
[\w][\w_]*   # A word (alphanumeric followed by alphanumeric/underscore).
(?:          # Optionally, followed by:
	\.         # a period
	[\w][\w_]* # and another word
)*           # any number of times.
$            # Match until end of string.
''', _re.VERBOSE)

_help = """
Usage: %prog [options] [<<< 'ARGS']

Arguments:
  process  The name of the process to run.

Worker Arguments:
  To send arguments to the underlying process worker, arguments must be
  piped or redirected into the standard input stream (stdin).
  
  A bash here-doc/string can be used to send data into stdin:
  i.e., %prog [options] <<< 'ARGS'
  
  - E.g., %prog [options] <<< '-my args'
  
  The output from a command can be piped into the stdin:
  i.e., COMMAND | %prog [options]
    
  - E.g., echo '-my args' | %prog [options]
  
  The contents of a file can also be redirected to stdin:
  i.e., %prog [options] [< FILE]
    
  - E.g., %prog [options] < my_args.file
""".strip()

def _import_process_module(filepath, fullname):
	"""
	Returns the specified process module.
	
	Arguments:
		filepath (str)
		- The file path to process module.
		fullname (str)
		- The fully qualified name of the process module:
		  i.e., {processing}.processes.modules.{process_name}
	
	Returns:
		(module) -- The process module.
	"""
	mod_dir, mod_name = _os.path.split(filepath)
	fh, path, desc = _imp.find_module(mod_name, [mod_dir])
	try:
		_imp.acquire_lock()
		try:
			proc_mod = _imp.load_module(fullname, fh, path, desc)
		finally:
			_imp.release_lock()
	finally:
		if fh:
			fh.close()
	return proc_mod

def _read_process_config(filepath):
	"""
	Returns the specified process config.

	Arguments:
		filepath (str)
		- The file path to process config.
		
	Returns:
		(dict) -- The process config.
	"""
	with open(filepath) as fh:
		proc_conf = _json.load(fh)
	return proc_conf
	
def check_process_basename(basename):
	"""
	Checks to see if the process basename is an alphanumeric/underscored
	basename.
	
	Arguments:
		basename (str)
		- A process basename.
	
	Returns:
		(bool)
		- If the basename is valid, `True`; otherwise, `False`.
	"""
	if not isinstance(basename, basestring):
		raise TypeError("Process basename:%r is not a string." % basename)
	return bool(_re_proc_basename.match(basename))

def check_process_name(fullname):
	"""
	Checks to see if the process name is a string of alphanumeric/
	underscored basenames separated by periods.
	
	Arguments:
		fullname (str)
		- The name of the process.
	
	Returns:
		(bool)
		- If the name is valid, `True`; otherwise, `False`.
	"""
	if not isinstance(fullname, basestring):
		raise TypeError("Process name:%r is not a string." % fullname)
	return bool(_re_proc_fullname.match(fullname))

def get_process(process_name):
	"""
	Returns the specified process.
	
	Arguments:
	  process_name (str)
	  - The name of the process to get.
		
	Returns:
	  (mixed)
	  - If the process is a module, the process class (Process); if the
	    process is a configuration, the process config (dict); otherwise,
	    an InvalidProcess exception is raised.
	"""
	proc_file, proc_type = find_process(process_name)
	if proc_type == MODULE:
		# Get modified time.
		mtime = _os.stat(proc_file + "/__init__.py").st_mtime
		# Import process module.
		mod_full = "%s.modules.%s" % (__package__ + ".processes" if __package__ else 'processes', process_name)
		proc_mod = _import_process_module(proc_file, mod_full)
		# Get process class.
		proc_cls = proc_mod.process
		proc_cls.name = process_name
		proc_cls.mtime = mtime
		validate_process_class(process_name, proc_cls)
		return proc_cls
	elif proc_type == CONFIG:
		# Get modified time.
		mtime = _os.stat(proc_file).st_mtime
		# Read process config.
		proc_conf = _read_process_config(proc_file)
		proc_conf['name'] = process_name
		proc_conf['mtime'] = mtime
		validate_process_config(process_name, proc_conf)
		return proc_conf
	raise LogicError("Process:%r type:%r is not %r." % (process_name, proc_type, ", ".join((MODULE, CONFIG))))

def find_process(process_name):
	"""
	Searches for the specified process and returns it's file path and
	type.
	
	Arguments:
		process_name (str)
		- The name of the process to find.
		
	Returns:
		(tuple)
		- A 2-tuple containing: the process file (str), and process type
		  (str).
	"""
	if not isinstance(process_name, basestring):
		raise TypeError("process_name:%r is not a string." % process_name)
	elif not process_name:
		raise ValueError("process_name:%r cannot be empty." % process_name)
	validate_process_name(process_name)
	proc_rel = _os.path.normpath(process_name.replace('.', '/'))
	if proc_rel[0] == '.' or proc_rel[0] == '/':
		raise LogicError("Process:%r relative path:%r cannot begin with a period or slash." % (process_name, proc_rel))
	# Find process module.
	mod_path = "%s/%s" % (_mod_dir, proc_rel)
	if _os.path.isdir(mod_path):
		files = _os.listdir(mod_path)
		if "__init__.py" in files:
			return mod_path, MODULE
	# Find process config.
	conf_path = "%s/%s.json" % (_conf_dir, proc_rel)
	if _os.path.isfile(conf_path):
		return conf_path, CONFIG
	# Since the process could not be found, raise an exception.
	raise InvalidProcess("Process %r does not exist." % process_name, process_name)

def list_processes():
	"""
	Returns the list of processes.
	
	Returns:
		(set) -- The list of processes.
	"""
	procs = []
	# Scan process modules.
	offset = len(_mod_dir) + 1
	for path, dirs, files in _os.walk(_mod_dir): 
		# Skip any sub-directories that do not match the folder naming
		# convention.
		dirs[:] = [d for d in dirs if _re_proc_basename.match(d)]
		# Check to see if this directory is a python package.
		if "__init__.py" not in files:
			continue
		filename = path + "/__init__.py"
		# Since this is a python package, check its script's size.
		try:
			size = _os.stat(filename).st_size
		except Exception:
			continue
		if size > 2:
			# Since the python package script is not empty (consider files
			# with a single "\n" or a "\r\n" as empty; i.e., 1 or 2 bytes),
			# trim the process modules directory path and proceeding slash off
			# the process module path.
			proc_name = path[offset:].replace('/', '.')
			procs.append(proc_name)
			
	# Scan process configs.
	offset = len(_conf_dir) + 1
	for path, dirs, files in _os.walk(_conf_dir):
		# Skip any sub-directories that do not match the folder naming
		# convention.
		dirs[:] = [d for d in dirs if _re_proc_basename.match(d)]
		# Check to see if any files match the config naming convention.
		for filename in files:
			base, ext = _os.path.splitext(filename)
			if ext.lower() == ".json" and _re_proc_basename.match(base): 
				# Since we have a process config, add it to the list.
				proc_name = path[offset:].replace('/', '.')
				proc_name += '.' + base if proc_name else base
				procs.append(proc_name)
				
	# Returns processes (removing duplicates).
	return set(procs)

def run_process(args=None):
	"""
	The default function for running a process from the command-line.
	
	Optional Arguments:
		args (list)
		- The command line arguments to use (including the command-line
		  program name in the first index); default is `sys.argv`.
	
	Returns:
		(int) -- On success, `0`; otherwise, a non-zero integer.
	"""
	import optparse
	
	if not args:
		args = _sys.argv
	
	# Parse options.
	prog = _os.path.basename(args[0]) + " process"
	parser = optparse.OptionParser(prog=prog, usage=_help)
	parser.add_option('-s', '--server-name', dest='name', help="The name of the Process Server application; default is %r; mutually exclusive with '--server-socket' and '--no-server'." % SERVER, metavar="NAME")
	parser.add_option('-f', '--server-socket', dest='socket', help="The Process Server socket file; default is %r then %r; mutually exclusive with '--server-name' and '--no-server'." % ("%s/{server_name}/processes.socket" % PREFIX_LOCAL_RUN, "%s/{server_name}/processes.socket" % PREFIX_USR_RUN), metavar="FILE")
	parser.add_option('-n', '--no-server', dest='no_server', help="Run the process stand-alone without a Process Server; mutually exclusive with '--server-name', '--server-socket' and '--server-token'.", action='store_true')
	parser.add_option('-t', '--server-token', dest='token', help="The server provided token to use when registering (this is used when the server starts the process); mutually exclusive with '--no-server'.", metavar="TOKEN")
	parser.add_option('-r', '--run-path', dest='run', help="The run-time data file directory for the process; default is %r." % '.', metavar="PATH")	
	parser.add_option('-d', '--debug', dest='debug', help="Enable process debugging.", action='store_true')
	parser.add_option('-i', '--inline', dest='inline', help="Run the process inline instead of daemonizing it (this is mainly useful for debugging processes).", action='store_true')	
	options, args = parser.parse_args(args[1:])
	
	# Get arguments/options.
	proc_name = args[0] if len(args) else None
	if proc_name is None:
		parser.print_help()
		return 0
	name = options.name
	socket = options.socket
	token = options.token
	no_server = options.no_server
	run = options.run
	debug = options.debug
	inline = options.inline
	
	# Check arguments/options.
	if no_server is not None:
		if name is not None:
			raise ValueError("no_server:%r is mutually exclusive with server_name:%r." % (no_server, name))
		elif socket is not None:
			raise ValueError("no_server:%r is mutually exclusive with server_socket:%r." % (no_server, socket))
		elif token is not None:
			raise ValueError("no_server:%r is mutually exclusive with server_token:%r." % (no_server, token))
	elif name is not None and socket is not None:
		raise ValueError("server_name:%r and server_token:%r are mutually exclusive." % (name, socket))
	
	# Read stdin.
	stdin = _sys.stdin.readline() if not _sys.stdin.isatty() else None
	
	# Setup process keyword arguments.
	proc_kw = {
		'use_server': not no_server,
		'server_name': name,
		'server_socket': socket,
		'server_token': token,
		'args': stdin,
		'path': run,
		'debug': debug
	}
	
	# Get and instantiate process.
	proc = get_process(proc_name)
	if _inspect.isclass(proc) and issubclass(proc, Process):
		proc = proc(**proc_kw)
	elif isinstance(proc, dict):
		proc = ConfigurableProcess(proc, **proc_kw)
	else:
		raise LogicError("get_process:%r returned a process:%r that is not a Process subclass or dict." % (get_process, proc))
	
	# Run process.
	daemon = _daemon.RunDaemon(lambda: proc.main())
	return daemon.run() if inline else daemon.start()

def validate_process_class(process_name, process_class):
	"""
	Validates the process class (or instance).
	
	Arguments:
		process_name (str)
		- The name of the process class.
		process_class (mixed)
		- The process class (class) or instance (Process) to validate.
	"""
	if not hasattr(process_class, 'name'):
		raise AttributeError("%s.name is not set." % process_name)
	elif not isinstance(process_class.name, basestring):
		raise TypeError("%s.name is not a string." % (process_name, process_class.name))
	elif not process_class.name:
		raise ValueError("%s.name:%r cannot be an empty string." % (process_name, process_class.name))
	elif not _re_proc_fullname.match(process_class.name):
		raise ValueError("%s.name:%r is not a string of alphanumeric/underscored basenames separated by periods." % (process_name, process_class.name))
	elif process_class.name != process_name:
		raise ValueError("%s.name:%r does not match said process:%r." % (process_class.name, process_name))
		
	if not hasattr(process_class, 'title'):
		raise AttributeError("%s.title is not set." % process_name)
	elif not isinstance(process_class.title, basestring):
		raise TypeError("%s.title:%r is not a string." % (process_name, process_class.title))
	elif not process_class.title:
		raise ValueError("%s.title:%r cannot be an empty string." % (process_name, process_class.title))
		
	if not hasattr(process_class, 'desc'):
		raise AttributeError("%s.desc is not set." % process_name)
	elif not isinstance(process_class.desc, basestring):
		raise TypeError("%s.desc:%r is not a float." % (process_name, process_class.desc))
		
	if not hasattr(process_class, 'mtime'):
		raise AttributeError("%s.mtime is not set." % process_name)
	elif not isinstance(process_class.mtime, float):
		raise TypeError("%s.mtime:%r is not a float." % (process_name, process_class.mtime))
		
	if not hasattr(process_class, 'worker'):
		raise AttributeError("%s.worker is not set." % process_name)
	elif not isinstance(process_class.worker, IWorker):
		raise TypeError("%s.worker:%r is not a IWorker instance." % (process_name, process_class.worker))
		
def validate_process_config(process_name, process_config):
	"""
	Validates the process config.
	
	Arguments:
		process_name (str)
		- The name of the process class.
		process (dict)
		- The process config.
	"""
	if 'name' not in process_config:
		raise KeyError("%s[name] is not set." % process_name)
	elif not isinstance(process_config['name'], basestring):
		raise TypeError("%s[name] is not a string." % (process_name, process_config['name']))
	elif not process_config['name']:
		raise ValueError("%s[name]:%r cannot be an empty string." % (process_name, process_config['name']))
	elif not _re_proc_fullname.match(process_config['name']):
		raise ValueError("%s[name]:%r is not a string of alphanumeric/underscored basenames separated by periods." % (process_name, process_config['name']))
	elif process_config['name'] != process_name:
		raise ValueError("%s[name]:%r does not match said process:%r." % (process_config['name'], process_name))
		
	if 'title' not in process_config:
		raise KeyError("%s[title] is not set." % process_name)
	elif not isinstance(process_config['title'], basestring):
		raise TypeError("%s[title]:%r is not a string." % (process_name, process_config['title']))
	elif not process_config['title']:
		raise ValueError("%s[title]:%r cannot be an empty string." % (process_name, process_config['title']))
		
	if 'desc' not in process_config:
		raise KeyError("%s[desc] is not set." % process_name)
	elif not isinstance(process_config['desc'], basestring):
		raise TypeError("%s[desc]:%r is not a string." % (process_name, process_config['desc']))
		
	if 'mtime' not in process_config:
		raise KeyError("%s[mtime] is not set." % process_name)
	elif not isinstance(process_config['mtime'], float):
		raise TypeError("%s[mtime]:%r is not a float." % (process_name, process_config['mtime']))
	
	if 'cmd' not in process_config:
		raise KeyError("%s[cmd] is not set." % process_name)
	elif not isinstance(process_config['cmd'], basestring):
		raise TypeError("%s[cmd]:%r is not a string." % (process_name, process_config['cmd']))
	elif not process_config['cmd']:
		raise ValueError("%s[cmd]:%r cannot be an empty string." % (process_name, process_config['cmd']))

def validate_process_basename(basename):
	"""
	Validates a process basename by raising an exception if it is not an
	alphanumeric/underscored basename.
	
	Arguments:
		basename (str)
		- The basename of a process.
	"""
	if not isinstance(basename, basestring):
		raise TypeError("Process basename:%r is not a string." % basename)
	elif not _re_proc_basename.match(basename):
		raise ValueError("Process basename:%r is not an alphanumeric/underscored basename." % basename)

def validate_process_name(fullname):
	"""
	Validates the specified process name by raising an exception if it is
	not a list of alphanumeric/underscored basenames separated by periods.
	
	Arguments:
		fullname (str)
		- The name of the process.
	"""
	if not isinstance(fullname, basestring):
		raise TypeError("Process name:%r is not a string." % fullname)
	elif not _re_proc_fullname.match(fullname):
		raise ValueError("Process name:%r is not a string of alphanumeric/underscored basenames separated by periods." % fullname)

def validate_process_names(fullnames):
	"""
	Validates the specified process names by raising an exception if any
	of them	are not a string of alphanumeric/underscored basenames
	separated by periods.
	
	Arguments:
		fullnames (list)
		- The list of process names to validate.
	"""
	if not hasattr(fullnames, '__iter__'):
		raise TypeError("Process names list:%r is not iterable." % fullnames)
	bad = [repr(n) for n in fullnames if not isinstance(n, basestring)]
	if bad:
		raise TypeError("Process names list contains %i non-string name(s): %s." % (len(bad), ", ".join(bad)))
	bad = [repr(n) for n in fullnames if not _re_proc_fullname.match(n)]
	if bad:
		raise TypeError("Process names list contains %i name(s) that are not strings of alphanumeric/underscored basenames separated by periods: %s." % (len(bad), ", ".join(bad)))

def color_worker_output(fd, output):
	"""
	Returns colored output for the worker.
	
	Arguments:
		fd (int) -- The file descriptor the output is from.
		output (str) -- The output to color.
		
	Returns:
		(str) -- The colored output.
	"""
	if fd == 1:
		return "\033[34m" + output + "\033[0m"
	elif fd == 2:
		return "\033[31m" + output + "\033[0m"
	elif fd == 3:
		return "\033[35m" + output + "\033[0m"	
	return "\033[36m" + output + "\033[0m"


class ProcessError(Exception):
	"""
	The Process Exception class is the base class that all process
	exceptions will inherit from.
	"""
	
	
class DebugError(ProcessError):
	"""
	The Debug Error exception is raised for debugging.
	"""
	
	
class LogicError(ProcessError):
	"""
	The Logic Error exception is raised when a condition is met that
	should be impossible if the logic is actually correct.
	"""


class AlreadyRunning(ProcessError):
	"""
	The Already Running exception is raised when a process tries
	registering but a process exists that is already running (starting or
	registered).
	"""
	

class InvalidProcess(ProcessError):
	"""
	The Invalid Process exception is raised when client tries accessing a
	process that does not exist.
	
	Instance Attributes:
		args (tuple) -- The exception arguments.
		message (str) -- The error message.
		process_name (str) -- The name of the invalid process. 
	"""
	
	def __init__(self, message, process_name):
		"""
		Initializes an InvalidProcess exception.
		
		Arguments:
			message (str) -- The error message.
			process_name (str) -- The name of the invalid process. 
		"""
		self.args = (message, process_name)
		self.message = message
		self.process_name = process_name
		
	def __str__(self):
		"""
		Converts this exception into a string.
		
		Returns:
			(str) -- The exception message.
		"""
		return self.message


class InvalidProcessInstance(ProcessError):
	"""
	The Invalid Process Instance exception is raised when client tries
	accessing a process instance that is not running.
	
	Instance Attributes:
		args (tuple) -- The exception arguments.
		message (str) -- The error message.
		process_id (str) -- The instance ID of the process. 
	"""
	
	def __init__(self, message, process_id):
		"""
		Initializes an InvalidProcess exception.
		
		Arguments:
			message (str) -- The error message.
			process_id (str) -- The instance ID of the process. 
		"""
		self.args = (message, process_id)
		self.message = message
		self.process_id = process_id
		
	def __str__(self):
		"""
		Converts this exception into a string.
		
		Returns:
			(str) -- The exception message.
		"""
		return self.message

	
class NotRegistered(ProcessError):
	"""
	The Not Registered exception is raised when a process tries
	performaing an action on the server before its registering.
	"""


class TerminateProcess(ProcessError):
	"""
	The Terminate Process exception is raised when the server wants to
	terminate the process for being a naughty little school girl.
	"""


class ProcessProtocol(_protocol.ProcessProtocol):
	"""
	The Process Protocol class handles the interaction between a Process
	and a Worker instance.
	
	Instance Attributes:
		ready (callable)
		- Called when the sub-process starts and is ready to received input
		  on stdin; called with arguments: the process protocol
		  (ProcessProtocol).
		done (callable)
		- Called when the sub-process is done executing and either was
		  killed by a signal or returned with an exit status; called with
		  arguments: the process protocol (ProcessProtocol) and the exit
		  status (int). If the sub-process was killed by a signal, the exit
		  status will be the additive inverse of the signal's integer value
		  (i.e., the signal's opposite or negative value).
		recv (dict)
		- Called when data is received from the sub-process; called with
		  arguments: the process protocol (ProcessProtocol), the file
		  descriptor (int) the data was received from, and the data received
		  (str).
	"""
	
	def __init__(self, ready=None, done=None, recv=None):
		"""
		Instantiates a Process Protocol instance.
		
		Arguments:
			ready (callable)
			- Called when the sub-process starts and is ready to received
			  input on stdin; called with arguments: the process protocol
			  (ProcessProtocol).
			done (callable)
			- Called when the sub-process is done executing and either was
			  killed by a signal or returned with an exit status; called with
			  arguments: the process protocol (ProcessProtocol) and the exit
			  status (int). If the sub process was killed by a signal, the
			  exit status will be the additive inverse of the signal's integer
			  value (i.e., the signal's opposite or negative value).
			recv (callable)
			- Called when data is received from the sub-process; called with
			  arguments: the process protocol (ProcessProtocol), the file
			  descriptor (int) the data was received from, and the data
			  received (str).
		"""
		if ready is not None and not callable(ready):
			raise TypeError("ready:%r is not callable." % ready)
		if done is not None and not callable(done):
			raise TypeError("done:%r is not callable." % done)
		if recv is not None and not callable(recv):
			raise TypeError("recv:%r is not callable." % recv)
			
		self.ready = ready
		self.done = done
		self.recv = recv
		
	def connectionMade(self):
		"""
		Called when a connection is made between the process and sub-process
		(i.e., it's started).
		
		This method is called once the sub-process is started. This is the
		ideal place to write to the stdin pipe. Closing stdin is a common
		way to indicate an EOF to the sub-process.
		"""
		if self.ready:
			try:
				self.ready(self)
			except Exception:
				_traceback.print_exc()
		self.transport.closeStdin()
		
	def childDataReceived(self, childFD, data):
		"""
		Called when output from the sub-process is received.
		
		Arguments:
			childFD (int) -- The file descriptor the data was received from.
			data (str) -- The output data.
		"""
		if self.recv:
			try:
				self.recv(self, childFD, data)
			except Exception:
				_traceback.print_exc()
		
	def processEnded(self, status):
		"""
		Called when process is finished.

		Arguments:
			status (twisted.python.failure.Failure)
			- On success, the status will have a `twisted.internet.error.
			  ProcessDone` instance stored in its `value` attribute;
			  otherwise, the status will have a `twisted.internet.error.
			  ProcessTerminiated` instance (with an `exitCode` attribute)
			  stored in its `value` attribute.
		"""
		if self.done:
			# Ignore the provided status and instead use the process transport
			# exit status. The exit status is a 16-bit integer whose low byte
			# is the signal that killed the process and whose high byte is the
			# returned exit status.
			# - See: http://docs.python.org/library/os.html#os.waitpid
			status = self.transport.status
			exit = status >> 8 if status > 0xFF else -(status & 0xFF)
			try:
				self.done(self, exit)
			except Exception:
				_traceback.print_exc()


class Process(_pb.Referenceable):
	"""
	The Process class manages inter-process communication between itself,
	its worker and the Process Server, and its stateful and run-time
	information.
	
	Abstract Class Attributes:
		name (str)
		- The name of the process.
		mtime (float)
		- The time (UTC) that the process was last modified.
		worker (IWorker)
		- The worker to execute for this process.
	
	Instance Attributes:
		debug (bool)
		- Whether process debugging is enabled or not.
		exit (int)
		- The exit code the process returns when it stops.
		pid (int)
		- The OS PID (not available until main() is run).
		run_dir (str)
		- The run-time data files directory path.
		tmp_dir (str)
		- The temporary data files directory path.
		var_dir (str)
		- The variable data files directory path.
		log_dir (str)
		- The log data files directory path.
		pid_file (str)
		- The PID file path.
		exit_file (str)
		- The file that the process's exit status is written to.
		out_file (str)
		- The file that the process's stdout (fd1) is written to.
		err_file (str)
		- The file that the process's stderr (fd2) is written to.
		log_file (str)
		- The file that the process's stdlod (fd3) is written to.
		
		use_server (bool)
		- Whether the process should connect to the Process Server or simply
		  run stand-alone.
		server_error (bool)
		- Whether there was an error connecting/registering with the server
		  or not.
		server_factory (twisted.spread.pb.PBClientFactory)
		- The process server PB factory.
		server_id (int)
		- If this process is registered, the process ID assigned by the
		  server; otherwise, `None`.
		server_socket (str)
		- The Process Server's UNIX socket file that processes connect to.
		server (twisted.spread.pb.RemoteReference):
		- The Process Server root reference.
		
		worker_args (list)
		- The process worker arguments.
		worker_buffs (dict)
		- The buffered output from the worker keyed by the output file
		  descriptors.
		worker_check (float)
		- The interval (seconds) at which the current worker is signaled for
		  its status.
		worker_delay (float)
		- The initial duration (seconds) at which the current worker will
		  not be signaled for its status.
		worker_exit (int)
		- The worker exit status when the worker is done executing;
		  otherwise, `None`.
		worker_last (int)
		- The time (seconds) that the worker last responded with its status.
		worker_trans (twisted.internet.interfaces.IProcessTransport)
		- The transport interface to the worker.
		
	Temporary Instance Attributes:
		_server_token (str)
		- The server provided token to use when registering (this is used
		  when the server starts the process).
		_spawn_args (list)
		- The position arguments to use for spawning the sub-process
		  (worker).
		_spawn_kw (dict)
		- The keyword arguments to use for spawning the sub-process
		  (worker).
	"""
	
	def __init__(self, use_server=None, server_name=None, server_socket=None, server_token=None, args=None, path=None, debug=False):
		"""
		Initializes a process instance.
		
		Optional Arguments:
			use_server (bool)
			- Whether the process should connect to the Process Server or
			  simply run stand-alone; default is `True`.
			server_name (str)
			- The name of the Process Server; default is {server_name!r}.
			server_socket (str)
			- The process server UNIX socket file; default is {local_socket!r}
			  then {usr_socket!r}.
			server_token (str)
			- The server provided token to use when registering (this is used
			  when the server starts the process); default is `None`.
			args (mixed)
			- The arguments (list or string) for this process. If args is a
			  string, the arguments will be parsed to a list using the shlex
			  module; default is `None`.
			path (str)
			- The run-time data file directory; default is ".".
			debug (bool)
			- Whether process debugging should be enabled or not; default is
			  `False`.
		""".format(
			server_name=SERVER,
			local_socket=("%s/%s/processes.socket" % (PREFIX_LOCAL_RUN, "{server_name}")),
			usr_socket=("%s/%s/processes.socket" % (PREFIX_USR_RUN, "{server_name}"))
		)
		# Validate self.
		validate_process_class(getattr(self, 'name', "%s.%s" % (self.__class__.__module__, self.__class__.__name__)), self)
		
		# Check constructor arguments.
		use_server = bool(use_server) if use_server is not None else True
		if use_server:
			if server_name is not None and server_socket is not None:
				raise ValueError("server_name:%r and server_socket:%r are mutually exclusive." % (server_name, server_socket))
		
			if server_name is not None:
				if not isinstance(server_name, basestring):
					raise TypeError("server_name:%r is not a string." % server_name)
				elif not server_name:
					raise ValueError("server_name:%r cannot be an empty string." % server_name)
			else:
				server_name = SERVER
				
			if server_socket is not None:
				if not isinstance(server_socket, basestring):
					raise TypeError("server_socket:%r is not a string." % server_socket)
				elif not server_socket:
					raise ValueError("server_socket:%r cannot be an empty string." % server_socket)
				server_socket = _os.path.abspath(server_socket)
				if not _os.path.exists(server_socket):
					raise ValueError("server_socket:%r does not exist." % server_socket)
			else:
				usr_socket = "%s/%s/processes.socket" % (PREFIX_USR_RUN, server_name)
				if _os.path.isfile(usr_socket):
					server_socket = usr_socket
				else:
					local_socket = "%s/%s/processes.socket" % (PREFIX_LOCAL_RUN, server_name)
					if not _os.path.isfile(local_socket):
						raise ValueError("Process Server %r sockets %r and %r do not exist." % (server_name, usr_socket, local_socket))
		else:				
			if server_name is not None:
				raise ValueError("server_name:%r cannot be set when use_server:%r is `True`." % server_name)
			elif server_socket is not None:
				raise ValueError("server_socket:%r cannot be set when use_server:%r is `True`." % server_socket)
			elif server_token is not None:
				raise ValueError("server_token:%r cannot be set when use_server:%r is `True`." % server_token)
		
		if args is None:
			args = []
		elif not isinstance(args, list):
			if isinstance(args, basestring):
				try:
					args = _shlex.split(args)
				except Exception as e:
					raise ValueError("Failed to parse args:%r; reason: %s" % e)
			else:
				args = list(args)
		
		if path is None:
			path = '.'
		elif not isinstance(path, basestring):
			raise TypeError("path:%r is not a string." % path)
		elif not path:
			raise ValueError("path:%r cannot be an empty string." % path)
				
		run_dir = _os.path.abspath(path)
		tmp_dir = run_dir + "/tmp"
		var_dir = run_dir + "/var"
		log_dir = run_dir + "/log"
		pid_file = run_dir + "/process.pid"
		exit_file = run_dir + "/process.exit"
		out_file = log_dir + "/stdout"
		err_file = log_dir + "/stderr"
		log_file = log_dir + "/stdlog"
		
		# Make sure the run-time, temporary, variable and log directories exist and
		# are accessable.
		if not _os.path.isdir(run_dir):
			_os.mkdir(run_dir, 0o700)
		elif not _os.access(run_dir, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute run-time directory %r." % run_dir)
		if not _os.path.isdir(tmp_dir):
			_os.mkdir(tmp_dir, 0o700)
		elif not _os.access(tmp_dir, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute temporary directory %r." % tmp_dir)
		if not _os.path.isdir(var_dir):
			_os.mkdir(var_dir, 0o700)
		elif not _os.access(var_dir, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute variable directory %r." % var_dir)
		if not _os.path.isdir(log_dir):
			_os.mkdir(log_dir, 0o700)
		elif not _os.access(log_dir, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute run-time directory %r." % log_dir)
		
		# Set instance attributes.
		self.debug = bool(debug)
		self.exit = None
		self.run_dir = run_dir
		self.tmp_dir = tmp_dir
		self.var_dir = var_dir
		self.log_dir = log_dir
		self.pid_file = pid_file
		self.exit_file = exit_file
		self.out_file = out_file
		self.err_file = err_file
		self.log_file = log_file
		
		self.use_server = use_server
		if use_server:
			self.server_socket = server_socket
			self._server_token = server_token
		else:
			self.server_socket = None
		self.server_error = False
		self.server_factory = None
		self.server_id = None
		self.server = None
			
		self.worker_args = args
		self.worker_buffs = {1: "", 2: "", 3: ""}
		self.worker_check = _worker_check
		self.worker_delay = _worker_delay
		self.worker_exit = None
		self.worker_last = None
		self.worker_trans = None
		
	def close_fh(self, fh):
		"""
		Closes the specifed file handle.
		
		Arguments:
			fh (file)
			- The file handle to close.
		"""
		try:
			fh.close()
		except Exception:
			pass

	def delete_pid(self):
		"""
		Deletes the process PID file.
		"""
		try:
			_os.remove(self.pid_file)
		except Exception:
			pass
			
	def delete_tmp(self):
		"""
		Deletes the process temporary directory and all of its contents.
		"""
		for path, dirs, files in _os.walk(self.tmp_dir, topdown=False):
			for filename in files:
				try:
					_os.remove(filename)
				except Exception:
					pass
			for dirname in dirs:
				try:
					_os.rmdir(dirname)
				except Exception:
					pass
		try:
			if _os.path.islink(self.tmp_dir):
				_os.remove(self.tmp_dir)
			else:
				_os.rmdir(self.tmp_dir)
		except Exception:
			pass
			
	def err_server(self, reason):
		"""
		Called if there's an error connecting to the Process Server.
		
		Arguments:
			(twisted.python.failure.Failure)
			- The reason for failure.
		"""
		self.server_error = True
		# Since we could not connect to the server, spawn the process.
		args = self.__dict__.pop('_spawn_args')
		kw = self.__dict__.pop('_spawn_kw')
		self.worker_trans = _reactor.spawnProcess(*args, **kw)
		# Print the failure.
		_sys.stderr.write(repr(reason) + '\n')
		reason.printTraceback(file=_sys.stderr)
					
	@_defer.inlineCallbacks
	def finish(self):
		"""
		Finishes the process by updating the server with the worker exit
		status and any buffered data; once the server is updated, the
		reactor is stopped.
		"""
		try:
			if self.server_id:
				buffs, self.worker_buffs = self.worker_buffs, {1: "", 2: "", 3: ""}
				try:
					yield self.server.callRemote('update_process', self.server_id, buffs)
				except Exception:
					_traceback.print_exc(file=_sys.stderr)
				yield self.server.callRemote('finish_process', self.server_id, self.worker_exit)
		except Exception:
			_traceback.print_exc(file=_sys.stderr)
		finally:
			# Stop the process.
			self.stop(self.worker_exit)
		
	def main(self):
		"""
		Run the process's main loop.
		
		Returns:
			(int) -- On success, returns `0`; otherwise, a non-zero integer.
		"""
		# Check for a PID file.
		if _os.path.isfile(self.pid_file):
			# Since the PID file exists, read it.
			with open(self.pid_file, 'r') as pid_fh:
				pid = int(pid_fh.readline().strip())
			# Check to see if it's running.
			if pid and _daemon.check_pid(pid):
				try:
					with open("/proc/%i/cmdline" % pid, 'r') as fh:
						cmdline = fh.read().strip()
				except IOError:
					_traceback.print_exc(file=_sys.stderr)
					cmdline = None
				if cmdline and self.name in cmdline:
					# Since the process is running, raise an error.
					raise ProcessError("This process:%r is already running as %r pid:%r." % (self.name, cmdline, pid))
			# Since we can be pretty sure that the process is not running (its
			# PID file exists but either its PID isn't valid or its
			# corresponding command line doesn't contain the process name), we
			# can safely delete the PID file.
			try:
				_os.remove(self.pid_file)
			except Exception:
				pass
				
		# Create PID file.
		pid = self.pid = _os.getpid()
		_atexit.register(self.delete_pid)
		with open(self.pid_file, 'w') as pid_fh:
			pid_fh.write("%i\n" % pid)
			
		# Create output files.
		out_fh = self.out_fh = open(self.out_file, 'wb')
		err_fh = self.err_fh = open(self.err_file, 'wb')
		log_fh = self.log_fh = open(self.log_file, 'wb')
		_atexit.register(lambda: self.close_fh(out_fh))
		_atexit.register(lambda: self.close_fh(err_fh))
		_atexit.register(lambda: self.close_fh(log_fh))
			
		# Connect to server.
		if self.use_server:
			self.server_factory = _pb.PBClientFactory()
			_reactor.connectUNIX(self.server_socket, self.server_factory, timeout=_connect_tmo)
			d = self.server_factory.getRootObject()
			d.addCallbacks(self.on_server, self.err_server)
			self.server_connecting = True
		
		# Setup spawn arguments.
		proto = ProcessProtocol(ready=self.on_worker_ready, done=self.on_worker_done, recv=self.on_worker_recv)
		
		cmd = self.worker.command
		if cmd[:2] == "./" or cmd[:3] == "../":
			cmd = _os.path.abspath("%s/%s" % (_os.path.dirname(_sys.modules[self.__class__.__module__].__file__), cmd))
		else:
			cmd = _os.path.normpath(cmd)
			
		cmd = [cmd]
		cmd.extend(self.worker_args)
		env = _os.environ.copy()
		env['PROCESS_TMP'] = self.tmp_dir
		env['PROCESS_VAR'] = self.var_dir
		env['PROCESS_LOG'] = self.log_dir
		fds = {0: 'w', 1: 'r', 2: 'r', 3: 'r'}
		
		# Spawn the worker now if the process is running stand-alone;
		# otherwise, the worker will be spawned once the process is registered.
		args = (proto, cmd[0])
		kw = {'args': cmd, 'env': env, 'path': self.tmp_dir, 'childFDs': fds}
		if self.use_server:
			self._spawn_args = args 
			self._spawn_kw = kw
		else:
			self.worker_trans = _reactor.spawnProcess(*args, **kw)
		
		# Start twisted reactor.
		_reactor.run()
		return self.exit
		
	def monitor_worker(self):
		"""
		Monitors the currently active worker by periodically sending signals
		to it.
		"""
		if self.server_id:
			buffs, self.worker_buffs = self.worker_buffs, {1: "", 2: "", 3: ""}
			if self.debug:
				print "Buffers: %r" % dict(((b,len(d)) for b,d in buffs.iteritems()))
			try:
				d = self.server.callRemote('update_process', self.server_id, buffs)
			except _pb.DeadReferenceError:
				print "Dead reference to server:%r." % self.server_socket
			else:
				d.addErrback(lambda r: r.raiseException())
		try:
			self.worker_trans.signalProcess(_signal.SIGINT)
		except _error.ProcessExitedAlready:
			pass
		else:
			_reactor.callLater(self.worker_check, self.monitor_worker)
	
	@_defer.inlineCallbacks
	def on_server(self, result):
		"""
		Called when the server root object is received or if there was an
		error ving it.
		
		Arguments:
			result (mixed)
			- On success, the server root (`twisted.internet.pb.
			  RemoteReference`); otherwise, the reason (`twisted.python.
			  failure.Failure`) for failure.
		"""
		try:
			server = self.server = result
			token = self.__dict__.pop('_server_token')
			self.server_id = yield server.callRemote('register_process', self.name, self.pid, self, process_token=token)
		except TerminateProcess:
			self.terminate()
		# Now spawn the process regardless if we could register with the
		# server.
		args = self.__dict__.pop('_spawn_args')
		kw = self.__dict__.pop('_spawn_kw')
		self.worker_trans = _reactor.spawnProcess(*args, **kw)
		
	def on_worker_done(self, proto, exit):
		"""
		Called when the worker is finished executing and exited with a
		status code.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
			exit (int) -- The worker's exit status.
		"""
		print "Worker exited with: %r" % exit
		self.worker_exit = exit
		self.finish()
		
	def on_worker_recv(self, proto, fd, data):
		"""
		Called when output data from the worker is received.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
			fd (int) -- The file-descriptor the data was received from.
			data (str) -- The output data.
		"""
		# Write output to files.
		try:
			if fd == 1:
				self.out_fh.write(data)
			elif fd == 2:
				self.err_fh.write(data)
			elif fd == 3:
				self.log_fh.write(data)
		except Exception:
			_traceback.print_exc(file=_sys.stderr)
		# Buffer output for server.
		if fd in self.worker_buffs:
			self.worker_buffs[fd] += data
			if fd == 3:
				# Since we received log output, store the time it was received.
				self.worker_last = _time.time()
		# Output data.
		_sys.stdout.write(color_worker_output(fd, data) if self.debug else data)
				
	def on_worker_ready(self, proto):
		"""
		Called when the worker is ready to receive input on stdin.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
		"""
		print "Worker started: %r" % self.worker.command
		# Start monitoring the worker.
		_reactor.callLater(self.worker_delay, self.monitor_worker)
		
	def remote_terminate(self, _=None):
		"""
		Called when the server wants the process to terminate.
		
		Optional Arguments:
			_ (None)
			- A place holder to satisfy twisted's need to have all callbacks
			  accept at least one argument.
		"""
		self.terminate()
				
	def remote_set_update_interval(self, interval):
		"""
		Sets the status update interval of this process.
		
		Arguments:
			interval (float) -- The interval between status updates.
		"""
		if not isinstance(interval, (int, float)):
			raise TypeError("interval:%r is not numeric." % interval)
		elif interval <= 0:
			raise ValueError("interval:%r must be greater than 0." % interval)
			
		self.worker_check = interval
		
	def stop(self, exit=None):
		"""
		Stops the Twisted reactor and sets the process exit code.
		
		Optional Arguments:
			exit (int) -- The exit code to return; default is `0`.
		"""
		self.exit = exit if exit is not None else 0
		_reactor.stop()
		self.write_exit(exit)
		self.delete_tmp()
		
	def terminate(self):
		"""
		Terminates the process.
		"""
		try:
			# Stop worker.
			if self.worker_trans:
				self.worker_trans.signalProcess(_signal.SIGTERM)
		except Exception as e:
			if not isinstance(e, _error.ProcessExitedAlready):
				_sys.stderr.write(repr(e) + '\n')
				_traceback.print_exc(file=_sys.stderr)
		finally:
			# Stop the process.
			self.stop(_signal.SIGTERM)
	
	def write_exit(self, exit):
		"""
		Writes the exit return code to the exit file.
		
		Arguments:
			exit (int) -- The exit return code.
		"""
		try:
			with open(self.exit_file, 'w') as fh:
				fh.write("%i\n" % exit)
		except Exception:
			_traceback.print_exc(file=_sys.stderr)


class ConfigurableProcess(Process):
	"""
	The Configurable Process class allows Processes to be run.
	
	Instance Attributes:
		name (str)
		- The name of the process.
		worker (Worker)
		- The worker to execute.
	"""
	
	def __init__(self, config, *args, **kwargs):
		"""
		Initializes a Configurable Process instance.
		
		Arguments:
			config (dict)
			- The process configuration.
		
		Variadic Arguments:
			args (list)
			- The positional arguments to send to the Process constructor.
			kwargs (dict)
			- The keyword arguments to send to the Process constructor.
		"""
		if 'name' not in config:
			raise KeyError("config[name] is not set.")
			
		# Validate config.
		validate_process_config(config['name'], config)

		# Set required attributes.
		self.name = config['name']
		self.title = config['title']
		self.desc = config['desc']
		self.mtime = config['mtime']
		self.worker = Worker(config['cmd'])
		
		# Call Process constructor.
		Process.__init__(self, *args, **kwargs)
		

class IOutput:
	"""
	The IOutput class interface handles the final output of a process.
	
	The purpose of this class is to handle the final output of a process.
	Any temperary files will be deleted from the output directory. Files
	that must persist will be moved from the output directory to the data
	directory.
	"""
	pass
	#TODO: How am I supposed to use the Output class again?


class IWorker:
	"""
	The worker interface that all workers must inherit.
	
	Abstract Attributes:
		command (str)
		- The command to execute.
	"""


class Worker(IWorker):
	"""
	A worker that executes a command.
	
	Instance Attributes:
		command (str)
		- The command to execute.
	"""
	
	def __init__(self, command):
		"""
		Initializes a Command Worker instance.
		
		Arguments:
			command (str) -- The command to execute.
		"""
		if not isinstance(command, basestring):
			raise TypeError("command:%r is not a string." % command)
		elif not command:
			raise ValueError("command:%r cannot be an empty string." % command)
		self.command = command


def main():
	print __doc__.strip()
	return 0
	
if __name__ == "__main__":
	exit(main())

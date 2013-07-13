# coding: utf-8
"""
The process module is the base for processes.

The process module cannot be ran on its own. The intended use for this module is
as a base for running and implementing custom processes. An example process
would be developed as such:

	from stockpile.processing.process import Process, Worker

	class MyProcess(Process):
		name = 'my_process'
		worker = Worker('/path/to/my/command')
	
	process = MyProcess
	
Also, a run_process() function is implemented in such a way that a command-line
process launcher could import this module and call the function. An example
script would be as such:
	
	from stockpile.processing.process import run_process
	
	if __name__ == "__main__":
		exit(run_process())

Constants:
	PORT (int)
	- The port used by processes to connect to a process server: 8087.
	STDIN_FD (int)
	- The FD used by STDIN: 0.
	STDOUT_FD (int)
	- The FD used by STDOUT: 1.
	STDERR_FD (int)
	- The FD used by STDERR: 2.
	STDLOG_FD (int)
	- The FD used by a process to monitor log/status output from its underlying
	  worker: 3.

TODO:
	When the server root object raises a DeadReferenceError, stop trying to update
	the server, try re-connecting and re-registering to the server, and if the
	server cannot be connected to, then give up on the server but continue running
	normally.
"""

__author__ = "Caleb"
__version__ = "0.6"
__status__ = "Development"
__project__ = "stockpile"

import atexit as _atexit
import errno as _errno
import os as _os
import shlex as _shlex
import signal as _signal
import sys as _sys
import time as _time
import traceback as _traceback

from twisted.internet import defer as _defer, error as _error, protocol as _protocol, reactor as _reactor
from twisted.python import failure as _failure
from twisted.spread import pb as _pb

import _daemon

PORT = 8087
STDIN_FD = 0
STDOUT_FD = 1
STDERR_FD = 2
STDLOG_FD = 3

_connect_tmo = 1

_worker_check = 1.0
_worker_delay = 1.0

_proc_dir_perm = 0o755

_help = """
Usage: %prog [options] [<<< 'ARGS']

Arguments:
  process  The name of the process to run.

Worker Arguments:
  To send arguments to the underlying process worker, arguments must be piped or
  redirected into the standard input stream (stdin).
  
  A bash here-doc/string can be used to send data into stdin:
  i.e., %prog [options] [<<< 'ARGS']
  
  - E.g., %prog [options] <<< '-my args'
  
  The output from a command can be piped into the stdin:
  i.e., COMMAND | %prog [options]
    
  - E.g., echo '-my args' | %prog [options]
  
  The contents of a file can also be redirected to stdin:
  i.e., %prog [options] [< FILE]
    
  - E.g., %prog [options] < my_args.file
""".strip()

def import_process(process_name):
	"""
	Returns the specified process package.
	
	Arguments:
		process_name (str) -- The name of the process module.
	
	Returns:
		(module) -- The process module.
	"""
	if not isinstance(process_name, basestring):
		raise TypeError("process_name:%r is not a string." % process_name)
	elif not process_name:
		raise ValueError("process_name:%r cannot be empty." % process_name)
		
	mod_name = "processes." + process_name
		
	try:
		# Import the module, but discard it's return value because we want the
		# module at the right most end of the import and not the processes package.
		mod = __import__(mod_name, globals(), fromlist=[''])
	except ImportError:
		# Try to figure out why the process could not be imported.
		names = mod_name.split('.')
		try_name = ''
		try:
			while names:
				try_name += ('.' if try_name else '') + names.pop(0)
				__import__(try_name, globals())
		except Exception as e:
			try_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), try_name.replace('.', '/'))
			guess = ''
			for init in ('/__init__.pyc', '/__init__.py'):
				if _os.path.exists(try_path+init):
					break
			else:
				guess = " missing __init__.py;"
			raise ImportError("Failed to import process %r from stockpile.processing.processes because package %r:%r cannot be imported:%s reason: %r" % (process_name, try_name, try_path, guess, e)), None, _sys.exc_info()[2]
		# In case the exception was not handled, re-raise it.
		raise
	# return the process module.
	return mod

def list_processes():
	"""
	Returns the list of processes.
	
	Returns:
		(list) -- The list of processes.
	"""
	#TODO: This method needs to be re-implemented due to changes in the processes
	# directory: an __init__.py does not necessarily indiciate a process anymore.
	# Instead scan through directories and list all packages containing an
	# __init__.py (excluding directories that don't begin with an alphanumeric
	# character) but if a package contains sub-packages, exclude that package. Or,
	# maybe only packages with a `process` module attribute set.
	raise NotImplementedError("This function needs to be re-implemented.")
	proc_list = []
	offset = len(_procs_path)+1 # Use the offset to trim of the processes path
	for path, dirs, files in _os.walk(_procs_path):
		if '__init__.py' in files:
			# Trim the processes directory path and the preceding slash off of the
			# process package's directory path.
			proc_name = path[offset:].replace('/', '.')
			proc_list.append(proc_name)
			# Clear the list of directories for this current path so no further
			# walking is performed here.
			del dirs[1][:]
	return proc_list

def run_process(args=None):
	"""
	The default function for running a process from the command-line.
	
	Optional Arguments:
		args (list)
		- The command line arguments to use (including the command-line program name
		  in the first index); default is `sys.argv`.
	
	Returns:
		(int) -- On success, `0`; otherwise, a non-zero integer.
	"""
	import optparse
	
	if not args:
		args = _sys.argv
	
	# Parse options.
	prog = _os.path.basename(args[0]) + " process"
	parser = optparse.OptionParser(prog=prog, usage=_help)
	parser.add_option('-d', '--debug', dest='debug', help="Enable process debugging.", action='store_true')
	parser.add_option('-i', '--inline', dest='inline', help="Run the process inline instead of daemonizing it.", action='store_true')
	parser.add_option('-t', '--server-tcp', dest='tcp', help="Process server TCP host and optionally port separated with a colon (mutually exclusive with '--server-unix').", metavar="HOST[:PORT]")
	parser.add_option('-u', '--server-unix', dest='unix', help="UNIX domain socket path for local process server (mutually exclusive with '--server-tcp').", metavar="PATH")
	parser.add_option('--server-token', dest='token', help="The server provided token to use when registering (this is used when the server starts the process).", metavar="TOKEN")
	options, args = parser.parse_args(args[1:])
	proc_name = args[0] if len(args) else None
		
	# Get/check arguments.
	if proc_name is None:
		parser.print_help()
		return 0
	
	proc_pkg = import_process(proc_name)
	proc_cls = proc_pkg.process
	if not issubclass(proc_cls, Process):
		raise TypeError("process:%r class:%r is not a Process subclass." % (proc_name, proc_cls))
	
	if not hasattr(args, '__iter__'):
		raise TypeError("args:%r is not a sequence." % args)
	elif not isinstance(args, (tuple, list)):
		args = list(args)
		
	# Get options.
	inline = options.inline
	tcp = options.tcp
	unix = options.unix
	debug = options.debug
	token = options.token
	
	# Process options.
	if tcp is not None and unix is not None:
		raise ValueError("server-tcp:%r and server-unix:%r are mutually exclusive.")
	elif tcp is not None:
		tcp = tcp.split(':')
		host = tcp[0]
		if not host:
			raise ValueError("server-tcp[0]:%r (host) is empty." % host)
		port = (int(tcp[1]) if len(tcp) > 1 else None) or PORT
		server = TcpAddress(host, port)
	elif unix is not None:
		if not unix:
			raise ValueError("server-unix:%r is empty." % unix)
		server = UnixAddress(unix)
	else:
		server = None
	
	# Read stdin
	stdin = _sys.stdin.readline() if not _sys.stdin.isatty() else None
	
	# Run process.
	proc = proc_cls(server=server, server_token=token, args=stdin, debug=debug)
	daemon = _daemon.RunDaemon(lambda: proc.run())
	return daemon.run() if inline else daemon.start()

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
	The Process Exception class is the base class that all process exceptions will
	inherit from.
	"""
	

class AlreadyRunning(ProcessError):
	"""
	The Already Running exception is raised when a process tries registering
	but a process exists that is already running (starting or registered).
	"""

	
class NotRegistered(ProcessError):
	"""
	The Not Registered exception is raised when a process tries performaing an
	action on the server before its registering.
	"""


class TerminateProcess(ProcessError):
	"""
	The Terminate Process exception is raised when the server wants to terminate
	the process for being a naughty little school girl.
	"""


class ISocketAddress:
	"""
	The Socket Address interface represents an address to the end-point of local
	or network socket.
	"""


class TcpAddress(ISocketAddress, _pb.Copyable, _pb.RemoteCopy):
	"""
	The TCP Address class represents an address to a TCP/IP network socket
	end-point.
	
	Instance Attributes:
		host (str) -- The TCP host.
		port (int) -- The TCP port.
	"""
	
	def __init__(self, host, port):
		"""
		Initializes a TCP Address instance.
		
		Arguments:
			host (str) -- The TCP host.
			port (int) -- The TCP port.
		"""
		self.host = host
		self.port = port
		
	def __repr__(self):
		"""
		Returns the official representation of the instance.
		
		Returns:
			(str) -- The representation of this instance.
		"""
		return "%s(%r,%r)" % (self.__class__.__name__, self.host, self.port)
		
	def __str__(self):
		"""
		Returns the informal string representation of the instance.
		
		Returns:
			(str) -- The representation of this instance.
		"""
		return self.host + ':' + self.port
		
	def setCopyableState(self, state):
		"""
		Restores the instance from a copied state.
		
		Arguments:
			state (tuple) -- The instance state to restore.
		"""
		self.host, self.port = state
	
	def getStateToCopy(self):
		"""
		Returns the serializable representation of the instance.
		
		Returns:
			(tuple) -- The process state.
		"""
		return (self.host, self.port)
	
_pb.setUnjellyableForClass(TcpAddress, TcpAddress)


class UnixAddress(ISocketAddress, _pb.Copyable, _pb.RemoteCopy):
	"""
	The UNIX Address class represents an address to a UNIX domain socket
	end-point.
	
	Instance Attributes:
		path (str) -- The path of the UNIX domain socket file.
	"""

	def __init__(self, path):
		"""
		Initializes a UNIX Address instance.
		
		Arguments:
			path (str) -- The path of the UNIX domain socket file.
		"""
		self.path = path
		
	def __repr__(self):
		"""
		Returns the official representation of the instance.
		
		Returns:
			(str) -- The representation of this instance.
		"""
		return "%s(%r)" % (self.__class__.__name__, self.path)
		
	def __str__(self):
		"""
		Returns the informal string representation of the instance.
		
		Returns:
			(str) -- The representation of this instance.
		"""
		return self.path
		
	def setCopyableState(self, state):
		"""
		Restores the instance from a copied state.
		
		Arguments:
			state (tuple) -- The instance state to restore.
		"""
		self.path = state[0]
	
	def getStateToCopy(self):
		"""
		Returns the serializable representation of the instance.
		
		Returns:
			(tuple) -- The process state.
		"""
		return (self.path,)

_pb.setUnjellyableForClass(UnixAddress, UnixAddress)


class ProcessProtocol(_protocol.ProcessProtocol):
	"""
	The Process Protocol class handles the interaction between a Process and a
	Worker instance.
	
	Instance Attributes:
		ready (callable)
		- Called when the sub-process starts and is ready to received input on
		  stdin; called with arguments: the process protocol (ProcessProtocol).
		done (callable)
		- Called when the sub-process is done executing and either was killed by a
		  signal or returned with an exit status; called with arguments: the process
		  protocol (ProcessProtocol) and the exit status (int). If the sub-process
		  was killed by a signal, the exit status will be the additive inverse of
		  the signal's integer value (i.e., the signal's opposite or negative
		  value).
		recv (dict)
		- Called when data is received from the sub-process; called with arguments:
		  the process protocol (ProcessProtocol), the file-descriptor (int) the data
		  was received from, and the data received (str).
	"""
	
	def __init__(self, ready=None, done=None, recv=None):
		"""
		Instantiates a Process Protocol instance.
		
		Arguments:
			ready (callable)
			- Called when the sub-process starts and is ready to received input on
			  stdin; called with arguments: the process protocol (ProcessProtocol).
			done (callable)
			- Called when the sub-process is done executing and either was killed by a
				signal or returned with an exit status; called with arguments: the
				process protocol (ProcessProtocol) and the exit status (int). If the sub
				process was killed by a signal, the exit status will be the additive
				inverse of the signal's integer value (i.e., the signal's opposite or
				negative value).
			recv (callable)
			- Called when data is received from the sub-process; called with
			  arguments: the process protocol (ProcessProtocol), the file-descriptor
			  (int) the data was received from, and the data received (str).
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
		Called when a connection is made between the process and sub-process (i.e.,
		it's started).
		
		This method is called once the sub-process is started. This is the ideal
		place to write to the stdin pipe. Closing stdin is a common way to indicate
		an EOF to the sub-process.
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
			- On success, the status will have a twisted.internet.error.ProcessDone
				instance stored in its `value` attribute; otherwise, the status will
				have a twisted.internet.error.ProcessTerminiated instance (with an
				`exitCode` attribute) stored in its `value` attribute.
		"""
		if self.done:
			# Ignore the provided status and instead use the process transport's exit
			# status. The exit status is a 16-bit integer whose low byte is the signal
			# that killed the process and whose high byte is the returned exit status.
			# - See: http://docs.python.org/library/os.html#os.waitpid
			status = self.transport.status
			exit = status >> 8 if status > 0xFF else -(status & 0xFF)
			try:
				self.done(self, exit)
			except Exception:
				_traceback.print_exc()


class Process(_pb.Referenceable):
	"""
	The Process class manages inter-process communication between itself and the
	Process Server, its stateful and run-time information.
	
	Abstract Class Attributes:
		name (str)
		- The name of the process (depending upon how the process package is
			layed-out, this could be `__package__` or `__module__`).
		worker (IWorker)
		- The worker to run for this process.
	
	Instance Attributes:
		debug (bool)
		- Whether process debugging is enabled or not.
		path (str)
		- The run-time path where the output and data directories and the files
		  (lock, etc.) will be located.
		lock_path (str)
		- The path of the lock file.
		output_path (str)
		- The process output directory path.
		data_path (str)
		- The process persistant data directory path.
		server_address (ISocketAddress)
		- The address to the server (only TcpAddress and UnixAddress are supported).
		server_error (bool)
		- Whether there was an error connecting/registering with the server or not.
		server_factory (twisted.spread.pb.PBClientFactory)
		- The process server PB factory.
		server_id (int)
		- If this process is registered, the process ID assigned by the server;
			otherwise, `None`.
		server (twisted.spread.pb.RemoteReference):
		- The process server root reference.
		worker_args (list)
		- The process worker arguments.
		worker_buffs (dict)
		- The buffered output from the worker keyed by the output file-descriptors.
		worker_check (float)
		- The interval (seconds) at which the current worker is signaled for its
			status.
		worker_delay (float)
		- The initial duration (seconds) at which the current worker will not be
		  signaled for its status.
		worker_exit (int)
		- The worker exit status when the worker is done executing; otherwise,
		  `None`.
		worker_last (int)
		- The time (seconds) that the worker last responded with its status.
		worker_trans (twisted.internet.interfaces.IProcessTransport)
		- The transport interface to the worker.
		
	Temporary Instance Attributes:
		_server_token (str)
		- The server provided token to use when registering (this is used when the
		  server starts the process).
	"""
	
	def __init__(self, server=None, server_token=None, args=None, path=None, debug=False):
		"""
		Initializes a process instance.
		
		Optional Arguments:
			server (ISocketAddress)
			- The address to the server (only TcpAddress and UnixAddress are
			  supported); default is `None`.
			server_token (str)
			- The server provided token to use when registering (this is used when the
			  server starts the process).
			args (mixed)
			- The arguments (list or string) for this process. If args is a string,
			  the arguments will be parsed to a list using the shlex module; default
			  is `None`.
			path (str)
			- The run-time path where the output and data directories and lock, etc.
			  files will be located; default is ".".
			debug (bool)
			- Whether process debugging should be enabled or not; default is `False`.
		"""
		# Check class attributes.
		cls = self.__class__
		if not hasattr(cls, 'name'):
			raise AttributeError("%s.%s.name is not set." % (cls.__module__, cls.__name__))
		elif not isinstance(cls.name, basestring):
			raise TypeError("%s.%s.name:%r is not a list." % (cls.__module__, cls.__name__, cls.name))
		elif not cls.name:
			raise ValueError("%s.%s.name:%r is empty." % (cls.__module__, cls.__name__, cls.name))
		
		if not hasattr(cls, 'worker'):
			raise AttributeError("%s.%s.worker is not set." % (cls.__module__, cls.__name__))
		elif not isinstance(cls.worker, IWorker):
			raise TypeError("%s.%s.worker:%r is not an IWorker instance." % (cls.__module__, cls.__name__, cls.workers))
		
		# Check constructor arguments.
		if server is not None and not isinstance(server, (TcpAddress, UnixAddress)):
			raise TypeError("server:%r is not a TcpAddress or UnixAddress instance.")
		
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
			raise ValueError("path is empty." % path)
		path = _os.path.abspath(path)
				
		# Make sure the path is accessable.
		if not _os.path.exists(path):
			# Since the directory doesn't exist, try to create it.
			try:
				_os.makedirs(path, _proc_dir_perm)
			except OSError as e:
				raise OSError(e.errno, "Failed to create directory for path:%r: %s." % (path, e.strerror.lower()))
		if not _os.access(path, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute for path:%r." % path)
			
		# Set instance attributes.
		self.debug = debug
		self.path = path
		self.lock_path = "%s/lock" % self.path
		self.output_path = "%s/output" % self.path
		self.data_path = "%s/data" % self.path
		self.server_address = server
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
		if server:
			self._server_token = server_token

	def delete_lock(self):
		"""
		Deletes the process lock file.
		"""
		try:
			_os.unlink(self.lock_path)
		except:
			pass
			
	def delete_output(self):
		"""
		Deletes the process output directory and all of its contents.
		"""
		for path, dirs, files in _os.walk(self.output_path, topdown=False):
			for filename in files:
				try:
					_os.unlink(filename)
				except:
					pass
			for dirname in dirs:
				try:
					_os.rmdir(dirname)
				except:
					pass
					
	@_defer.inlineCallbacks
	def finish(self):
		"""
		Finishes the process by updating the server with the worker exit status and
		any buffered data; once the server is updated, the reactor is stopped.
		"""
		try:
			if self.server_id:
				buffs, self.worker_buffs = self.worker_buffs, {1: "", 2: "", 3: ""}
				try:
					yield self.server.callRemote('update_status', self.server_id, buffs)
				except Exception as e:
					_sys.stderr.write(repr(e) + '\n')
					_traceback.print_exc(file=_sys.stderr)
				yield self.server.callRemote('finish_process', self.server_id, self.worker_exit)
		except Exception as e:
			_sys.stderr.write(repr(e) + '\n')
			_traceback.print_exc(file=_sys.stderr)
		finally:
			# Stop the process.
			self.stop()
		
	def monitor_worker(self):
		"""
		Monitors the currently active worker by periodically sending signals to it.
		"""
		if self.server_id:
			buffs, self.worker_buffs = self.worker_buffs, {1: "", 2: "", 3: ""}
			if self.debug:
				print "Buffers: %r" % dict(((b,len(d)) for b,d in buffs.iteritems()))
			try:
				d = self.server.callRemote('update_status', self.server_id, buffs)
			except _pb.DeadReferenceError:
				print "Dead reference to server:%r." % self.server_address
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
		Called when the server root object is received or if there was an error
		receiving it.
		
		Arguments:
			result (mixed)
			- On success, the server root (twisted.internet.pb.RemoteReference);
			  otherwise, the reason (twisted.python.failure.Failure) for failure.
		"""
		try:
			if isinstance(result, _failure.Failure):
				result.raiseException()
			elif not isinstance(result, _pb.RemoteReference):
				raise TypeError("result:%r is not a twisted.internet.pb.RemoteReference or twisted.python.failure.Failure instance." % result)
			server = self.server = result
			token = self._server_token
			del self._server_token
			self.server_id = yield server.callRemote('register_process', self.__class__.name, self, token)
		except Exception as e:
			# Indicate that there was an error connecting/registering to the server.
			self.server_error = True
			_sys.stderr.write(repr(e) + '\n')
			_traceback.print_exc(file=_sys.stderr)
		finally:
			# If the worker finished before we registered with the server, finish the
			# process.
			# - NOTE: Because of a check in the on_worker_done method, this method
			#   must finish the process if the worker has already finished. This
			#   prevents a race condition where the server is never notified that the
			#   process is done if the process finishes before being registered with
			#   the server.
			if self.worker_exit is not None:
				self.finish()
		
	def on_worker_done(self, proto, exit):
		"""
		Called when the worker is finished executing and exited with a status code.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
			exit (int) -- The worker's exit status.
		"""
		print "Worker exited with: %r" % exit
			
		self.worker_exit = exit
		# If the server is connecting/registering, the on_server method will handle
		# finishing the process.
		# - NOTE: If we end the process now before the process is registered, the
		#   server will not know that the process has ran and finished.
		if not self.server_address or self.server_id is not None or self.server_error:
			self.finish()
		
	def on_worker_recv(self, proto, fd, data):
		"""
		Called when output data from the worker is received.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
			fd (int) -- The file-descriptor the data was received from.
			data (str) -- The output data.
		"""
		# Buffer output for server.
		if fd in self.worker_buffs:
			self.worker_buffs[fd] += data
			if fd == 3:
				# Since we received log output, store the time it was received.
				self.worker_last = _time.time()
		# Output data.
		if self.debug:
			_sys.stdout.write(color_worker_output(fd, data))
		else: 
			_sys.stdout.write(data)
				
	def on_worker_ready(self, proto):
		"""
		Called when the worker is ready to receive input on stdin.
		
		Arguments:
			proto (ProcessProtocol) -- The process/worker protocol.
		"""
		print "Worker started: %r" % self.__class__.worker.command
		# Start monitoring the worker.
		_reactor.callLater(self.worker_delay, self.monitor_worker)
		
	def remote_terminate(self, _=None):
		"""
		Called when the server wants the process to terminate.
		
		Optional Arguments:
			_ (None)
			- A place holder to satisfy twisted's need to have all callbacks accept at
			  least one argument.
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
		
	def run(self):
		"""
		Run the process's main loop.
		
		Returns:
			(int) -- Always returns `0`.
		"""
		# Check for lock file.
		if _os.path.exists(self.lock_path):
			# Since the lock file exists, read it.
			try:
				with open(self.lock_path, 'r') as pid_fh:
					pid = int(pid_fh.readline().strip())
			except IOError:
				pid = None
			# Check to see if it's running.
			if pid and _daemon.check_pid(pid):
				try:
					with open("/proc/%i/cmdline" % pid, 'r') as fh:
						cmdline = fh.read().strip()
				except IOError:
					cmdline = None
				if cmdline and self.name in cmdline:
					# Since the process is running, raise an error.
					raise Exception("This process:%r is already running as %r pid:%r." % (self.name, cmdline, pid))
			# Since we can be pretty sure that the process is not running (its lock
			# file exists but either its PID isn't valid or its corresponding command
			# line doesn't contain the process name), we can safely delete the lock
			# file.
			try:
				_os.unlink(self.lock_path)
			except:
				pass
				
		# Create lock file.
		pid = _os.getpid()
		_atexit.register(self.delete_lock)
		with open(self.lock_path, 'w') as lock_fh:
			lock_fh.write("%i\n" % pid)
			
		# Create output directory if it does not already exist.
		if not _os.path.exists(self.output_path):
			try:
				_os.mkdir(self.output_path, _proc_dir_perm)
			except OSError as e:
				raise OSError(e.errno, "Failed to create output directory at path:%r: %s." % (self.output_path, e.strerror.lower()))
		if not _os.access(self.output_path, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute output directory at path:%r." % self.output_path)
			
		# Create output directory if it does not already exist.
		# - TODO: Once we have the shared drives setup, the data directory should
		#   actually be a symlink to a directory on one of those.
		if not _os.path.exists(self.data_path):
			try:
				_os.mkdir(self.data_path, _proc_dir_perm)
			except OSError as e:
				raise OSError(e.errno, "Failed to create data directory at path:%r: %s." % (self.data_path, e.strerror.lower()))
		if not _os.access(self.output_path, _os.R_OK | _os.W_OK | _os.X_OK):
			raise OSError(_errno.EACCES, "Access denied to read/write/execute data directory at path:%r." % self.data_path)
		
		# Connect to server.
		if self.server_address:
			self.server_factory = _pb.PBClientFactory()
			if isinstance(self.server_address, TcpAddress):
				_reactor.connectTCP(self.server_address.host, self.server_address.port, self.server_factory, timeout=_connect_tmo)
			elif isinstance(self.server_address, UnixAddress):
				_reactor.connectUNIX(self.server_address.path, self.server_factory, timeout=_connect_tmo)
			else:
				raise TypeError("server address:%r is not a TcpAddress or UnixAddress instance." % self.server_address)
			d = self.server_factory.getRootObject()
			d.addBoth(self.on_server)
			self.server_connecting = True
			
		# Start worker.
		proto = ProcessProtocol(ready=self.on_worker_ready, done=self.on_worker_done, recv=self.on_worker_recv)
		cmd = self.__class__.worker.command
		if cmd[:2] == "./" or cmd[:3] == "../":
			cmd = _os.path.abspath("%s/%s" % (_os.path.dirname(_sys.modules[self.__class__.__module__].__file__), cmd))
		cmd = [cmd]
		cmd.extend(self.worker_args)
		env = _os.environ.copy()
		env['PROC_OUTPUT'] = self.output_path
		env['PROC_DATA'] = self.data_path
		fds = {0: 'w', 1: 'r', 2: 'r', 3: 'r'}
		self.worker_trans = _reactor.spawnProcess(proto, cmd[0], cmd, env=env, path=self.output_path, childFDs=fds)
		
		# Start twisted reactor.
		_reactor.run()
		return 0
		
	def stop(self):
		"""
		Stops the process.
		"""
		_reactor.stop()
		self.delete_output()
		
	def terminate(self):
		"""
		Terminates the process.
		"""
		try:
			# Stop worker.
			self.worker_trans.signalProcess(_signal.SIGTERM)
		except Exception as e:
			if not isinstance(e, _error.ProcessExitedAlready):
				_sys.stderr.write(repr(e) + '\n')
				_traceback.print_exc(file=_sys.stderr)
		finally:
			# Stop the process.
			self.stop()
		
		
class IOutput:
	"""
	The IOutput class interface handles the final output of a process.
	
	The purpose of this class is to handle the final output of a process. Any
	temperary files will be deleted from the output directory. Files that must
	persist will be moved from the output directory to the data directory.
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
		self.command = command


def main():
	print __doc__.strip()
	return 0
	
if __name__ == "__main__":
	exit(main())

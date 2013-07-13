"""
Provides the Daemon class which performs the UNIX double-fork magic when the
daemonize method is called.

See:
- Sevens' "Advanced Programming in the UNIX Environment" for details (ISBN
  0201563177) http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
"""
import atexit
import os
import signal
import sys
import time

__author__ = "Caleb"
__version__ = "0.5"
__credits__ = "Ben"
__status__ = "Development"
	
def check_pid(pid):
	"""
	Checks to see if a process is running with the specified PID.
	
	Arguments:
	pid (int) -- The PID to check.
	
	Returns:
	(bool) -- If the process is running, `True`; otherwise, `False`.
	
	References:
	- http://docs.python.org/library/os.html#os.kill
	- http://linux.die.net/man/2/kill
	- http://stackoverflow.com/questions/568271/check-if-pid-is-not-in-use-in-python/568285#568285
	"""
	try:
		os.kill(pid, 0)
	except OSError:
		return False
	return True

def check_pid_windows(pid):
	"""
	Checks to see if a process is running with the specified PID.
	
	Arguments:
	pid (int) -- The PID to check.
	
	Returns:
	(bool) -- If the process is running, `True`; otherwise, `False`.
	
	References:
	- http://mail.python.org/pipermail/python-win32/2003-December/001482.html
	- http://stackoverflow.com/questions/568271/check-if-pid-is-not-in-use-in-python/568589#568589
	"""
	# Since windows does not support the os.kill method so we have to use the
	# pywin32 plugin.
	wmi = win32com.client.GetObject('winmgmts:')
	processes = wmi.InstanceOf('Win32_Process')
	pids = [process.Properties_('ProcessID').Value for process in processes]
	return pid in pids
	
class Daemon(object):
	"""
	A generic daemon class.
	"""
	
	def __init__(self, pid_path=None, stdin=None, stdout=None, stderr=None):
		"""
		Initializes a daemon instance.
		
		Optional Arguments:
		pid_path (str) -- The pid file path; default is `None`.
		stdin (str) -- The path to the standard in stream; default is `os.devnull`.
		stdout (str) -- The path to the standard out stream; default is `os.devnull`.
		stderr (str) -- The path to the standard error stream; default is `os.devnull`.
		"""
		if pid_path is not None:
			if not isinstance(pid_path, basestring):
				raise TypeError("pid_path:%r is not a string." % pid_path)
			elif not pid_path:
				raise ValueError("pid_path:%r is empty." % pid_path)
		
		self.pid_path = os.path.abspath(pid_path) if pid_path else None
		self.stdin_path = stdin or os.devnull
		self.stdout_path = stdout or os.devnull
		self.stderr_path = stderr or os.devnull
	
	def daemonize(self):
		"""
		Daemonizes the process.
		
		Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
		"""
		print "Daemonizing..."
		
		# Fork process.
		try:
			pid = os.fork()
			if pid:
				# Return to parent with success.
				return 0
		except OSError as e:
			# Return to parent with error.
			sys.stderr.write("Failed first fork: %d %s\n" % (e.errno, e.strerror))
			return 1
		
		# Decouple from the parent environment.
		os.chdir("/")
		os.setsid()
		os.umask(0)
		
		# Perform second fork.
		try:
			pid = os.fork()
			if pid:
				# Exit second parent with success.
				sys.exit(0)
		except OSError as e:
			# Exit second parent with error.
			sys.stderr.write("Failed second fork: %d %s\n" % (e.errno, e.strerror))
			sys.exit(1)
		
		# Redirect standard file descriptors.
		sys.stdout.flush()
		sys.stderr.flush()
		stdin = open(self.stdin_path, 'r')
		stdout = open(self.stdout_path, 'a+')
		stderr = open(self.stderr_path, 'a+', 0)
		
		# Duplicate our file descriptors to the standard file descriptors, closing
		# the latter first if necessary.
		os.dup2(stdin.fileno(), sys.stdin.fileno())
		os.dup2(stdout.fileno(), sys.stdout.fileno())
		os.dup2(stderr.fileno(), sys.stderr.fileno())
		
		# Write pid file.
		if self.pid_path:
			atexit.register(self.delete_pid)
			pid = str(os.getpid())
			with open(self.pid_path, 'w') as pid_fh:
				pid_fh.write("%s\n" % pid)
		
		# Now run the daemon.
		return self.run()
		
	def delete_pid(self):
		"""
		Deletes the pid file.
		"""
		try:
			os.unlink(self.pid_path)
		except:
			pass
		
	def restart(self):
		"""
		Restarts the daemon.
		
		Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
		"""
		self.stop()
		return self.start()
	
	def run(self):
		"""
		This method should be overridden when the Daemon class is sub-classed. It
		will be called after the process has been daemonized by the start() or
		restart() methods.
		
		Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
		"""
		raise NotImplementedError("This method must be implemented by Daemon sub-classes.")
	
	def start(self):
		"""
		Starts the daemon.
		
		Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
		"""
		# Check for a pid file to see if the daemon is already running.
		if self.pid_path:
			try:
				with open(self.pid_path, 'r') as pid_fh:
					pid = int(pid_fh.read().strip())
			except IOError:
				pid = None
			
			if pid and check_pid(pid):
				sys.stderr.write("Daemon already running with pid:%r file:%r.\n" % (pid, self.pidfile))
				return 1
		
		# Start the daemon.
		return self.daemonize()
			
	def stop(self):
		"""
		Stops the daemon.
		
		Returns:
		(int) -- On success, 0; otherwise, 1.
		"""
		if not self.pid_path:
			sys.stderr.write("Daemon has no pid file. Impossible to determine if daemon is running.\n")
			return 1
		
		# Get the pid from the pid file.
		try:
			with open(self.pid_path, 'r') as pid_fh:
				pid = int(pid_fh.read().strip())
		except IOError:
			pid = None
		
		if not pid:
			sys.stderr.write("Daemon pid file:%r does not exist. Daemon not running?\n" % self.pidfile)
			return 0
			
		# Try killing the daemon.
		try:
			while 1:
				os.kill(pid, signal.SIGTERM)
				time.sleep(0.1)
		except OSError as e:
			error = str(e)
			if error.lower().find("No such process"):
				os.remove(self.pidfile)
			else:
				# Since the daemon could not be killed, return error.
				sys.stderr.write("Failed to kill daemon process:%r. OSError: %s\n" % (pid, error))
				return 1
				
		# Return success.
		return 0
		

class RunDaemon(Daemon):
	"""
	Runs a callable inside of a daemon.
	"""
	
	def __init__(self, runner, *args, **kwargs):
		"""
		Instantiates a Run Daemon instance.
		
		Arguments:
		runner (callable) -- The callable to run.
		
		Variadic Arguments:
		args (list) -- Any positional arguments to go to the Daemon constructor.
		kwargs (dict) -- Any keyword arguments to go to the Daemon constructor.
		"""
		if not callable(runner):
			raise TypeError("runner:%r is not callable." % runner)
		self.runner = runner
		Daemon.__init__(self, *args, **kwargs)
	
	def run(self):
		"""
		Run the callable.
		
		Returns:
		(int) -- On success, 0; otherwise, non-zero integer.
		"""
		return self.runner()

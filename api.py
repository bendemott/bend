# coding: utf-8
"""
This API module contains the standard Process API.

Constants:
  CLIENT_PORT (int)
  - The default port that the Process Server listens for clients on:
    `{client_port!r}`.

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
"""

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

from twisted.spread import pb as _pb

import dev as _dev
from stockpile.processing import process as _process, server as _server

# Shutup Scribes error checking about unused import.
_dev = _dev

CLIENT_PORT = _process.CLIENT_PORT

PROGRESS = _server.PROGRESS
REALTIME = _server.REALTIME

STATE_NOTRUNNING = _server.STATE_NOTRUNNING
STATE_QUEUED = _server.STATE_QUEUED
STATE_ZOMBIE = _server.STATE_ZOMBIE
STATE_STARTING = _server.STATE_STARTING
STATE_WORKING = _server.STATE_WORKING
STATE_FINISHED = _server.STATE_FINISHED
STATE_TERMINATING = _server.STATE_TERMINATING
STATE_TERMINATED = _server.STATE_TERMINATED

__doc__ = __doc__.format(
	client_port=CLIENT_PORT,
	monitor_progress=PROGRESS,
	monitor_realtime=REALTIME,
	state_notrunning=STATE_NOTRUNNING,
	state_queued=STATE_QUEUED,
	state_zombie=STATE_ZOMBIE,
	state_starting=STATE_STARTING,
	state_working=STATE_WORKING,
	state_finished=STATE_FINISHED,
	state_terminating=STATE_TERMINATING,
	state_terminated=STATE_TERMINATED,
)

class ProcessApi:
	"""
	The Process API class wraps the functionality of Process Server API
	for easy use by clients.
	
	Instance Attributes:
	  root (twisted.spread.pb.RemoteReference)
	  - The Process Server Root object.
	"""
	
	def __init__(self, server):
		"""
		Initializes a ProcessApi instance.
		
		Arguments:
		  server (twisted.spread.pb.RemoteReference)
		  - The Process Server Root object.
		"""
		if not isinstance(server, _pb.RemoteReference):
			raise TypeError("server:%r is not a twisted.spread.pb.RemoteReference.")
		self.root = server
	
	def list(self):
		"""
		Returns the list of processes.
		
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: the list (list) of process names.
		"""
		return self.root.callRemote('list_processes')
	
	def query(self, process_name, keys):
		"""
		Queries the specified process for information.
		
		Arguments:
		  process_name (str)
		  - The name of the process to inquire.
		  keys (list)
		  - The keys (str) to return.
			
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: the queried information (dict). If no
		    data exist for a given key, its value will be `None`.
		"""
		return self.root.callRemote('query_process', process_name, keys)
		
	def query_many(self, process_names, keys):
		"""
		Queries the specified processes for information.
		
		Arguments:
		  process_names (list)
		  - The list of process names (str) to inquire.
		  keys (list)
		  - The keys (str) to return.
			
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: the queried information (dict) per
		    process; keyed by process name (str). If a process does not
		    exist, its value will be `None`. If no data exists for a given
		    key, its value will be `None`.
		"""
		return self.root.callRemote('query_processes', process_names, keys)
	
	def register(self, process_name, monitor_type, monitor_ref):
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
		return self.root.callRemote('register_process_monitor', process_name, monitor_type, monitor_ref)
		
	def register_all(self, monitor_type, monitor_ref):
		"""
		Registeres the specified monitor reference to all processes.
		
		Arguments:
		  monitor_type (str)
		  - The monitor type.
		  monitor_ref (twisted.spread.pb.RemoteReference)
		  - The monitor reference.
			
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: an empty (None) result.
		"""
		return self.root.callRemote('register_processes_monitor', monitor_type, monitor_ref)
		
	def register_instance(self, process_id, monitor_type, monitor_ref):
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
		return self.root.callRemote('register_instance_monitor', process_id, monitor_type, monitor_ref)
		
	def run(self, process_name, process_args=None, process_monitor=None, process_debug=False):
		"""
		Runs the specified process.
		
		Arguments:
		  process_name (str) -- The name of the process.
		
		Optional Arguments:
		  process_args (str)
		  - The arguments for the process; default is an empty string.
		  process_monitor (2-tuple)
		  - A 2-tuple containing: the monitor type (str) to register, and
		    the or reference (twisted.spread.pb.RemoteReference); default is
		    `None`. 
		  process_debug (bool)
		  - Whether process debugging should be enabled or not; default is
		    `False`.
			
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: the process instance ID (int).
		"""
		return self.root.callRemote('run_process', process_name, process_args=process_args, process_monitor=process_monitor, process_debug=process_debug)
	
	def terminate(self, process_id):
		"""
		Terminates the specified process instance.e process instance.
		
		Arguments:
		  process_id (int)
		  - The process instance ID of the process to terminate.
			
		Returns:
		  (twisted.internet.defer.Deferred)
		  - A deferred containing: an empty (None) result.
		"""
		return self.root.callRemote('terminate_process', process_id)
	
	def unregister(self, process_name, monitor_type, monitor_ref):
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
		return self.root.callRemote('unregister_process_monitor', process_name, monitor_type, monitor_ref)
	
	def unregister_all(self, monitor_type, monitor_ref):
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
		return self.root.callRemote('unregister_processes_monitor', monitor_type, monitor_ref)
	
	def unregister_instance(self, process_id, monitor_type, monitor_ref):
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
		return self.root.callRemote('unregister_instance_monitor', process_id, monitor_type, monitor_ref)

#!/usr/bin/env python
# coding: utf-8
"""
This script is the worker for the Wait process.
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import datetime
import fcntl
import os
import signal
import socket
import sys
import time
import traceback

_help = """
Usage: %prog [options] secs

Arguments:
  secs  The number of seconds to wait before exiting.
""".strip()

class Waiter():
	"""
	The Waiter class waits the specified number of seconds when ran.
	"""
	
	def __init__(self, secs):
		"""
		Initializes a Waiter instance.
		
		Arguments:
			secs (float) -- The number of seconds to wait.
		"""
		self.secs = secs
		self.start = 0
		self.stage = 0
		
		if secs <= 0.0:
			raise ValueError("secs:%r is not greater than 0." % secs)
		
		# Setup signal handler.
		signal.signal(signal.SIGINT, self.signal)
		
		# If stdlog (fd3) is not writable, use stdout instead.
		fd = sys.stdout.fileno()
		try:
			if fcntl.fcntl(3, fcntl.F_GETFL) & (os.O_WRONLY | os.O_RDWR):
				fd = 3
		except:
			traceback.print_exc()
		self.fd = fd
		
		# prival = facility * 8 + severity
		# facility = 16 (local0)
		# severity = 6 (info)
		prival = 16 * 8 + 6
		version = 1
		hostname = socket.gethostname() # should use socket.getfqdn()
		appname = os.path.basename(sys.argv[0])
		procid = os.getpid()
		self._header = "<%i>%i {timestamp} %s %s %s {msgid}" % (prival, version, hostname, appname, procid)
		
	def run(self):
		"""
		Starts the waiter.
		
		Returns:
			(int) -- Always return 0.
		"""
		self.start = time.time()
		self.end = self.start + self.secs
		self.stage = 1
		while 1:
			rem = self.end - time.time()
			if rem > 0.0:
				time.sleep(rem)
			else:
				break
		return 0
		
	def signal(self, signum, frame):
		"""
		Called when the waiter receives a signal.
		
		Arguments:
			signum (int) -- The signal number
		"""
		if signum == signal.SIGINT:
			timestamp = datetime.datetime.utcnow().isoformat() + 'Z'
			header = self._header.format(timestamp=timestamp, msgid="status")
			progress = (time.time() - self.start) / self.secs if self.stage == 1 else 0
			data = '[status@ridersdiscount progress="%.3f"]' % progress
			status = header + ' ' + data
			# Write status to stdlog.
			os.write(self.fd, status + '\n')
	

def main(args=None):
	# Temporarily ignore the interupt signal until the Waiter instance is fully
	# initialized.
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	# Disable output buffering.
	sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
	
	import optparse

	if not args:
		args = sys.argv
		
	# Parse options.
	prog = os.path.basename(args[0])
	parser = optparse.OptionParser(prog=prog, usage=_help)
	options, args = parser.parse_args(args[1:])
	
	# Get/check arguments.
	secs = float(args[0]) if args else None
	if secs is None:
		parser.print_help()
		return 0
	
	# Start waiter.
	waiter = Waiter(secs)
	return waiter.run()
	
if __name__ == "__main__":
	exit(main())

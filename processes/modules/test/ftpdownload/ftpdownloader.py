#!/usr/bin/env python
# coding: utf-8
"""
This script is the worker for the FTP Download process.
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.7"
__status__ = "Development"
__project__ = "stockpile"

import datetime
import fcntl
import os
import os.path
import signal
import socket
import sys
import traceback
import zlib

from twisted.internet import defer, error, protocol, reactor, threads
from twisted.protocols import ftp

import dev
from stockpile.processing import progress

_ftp_passive = 1
_ftp_port = 8021
_ftp_timeout = 1

_stage_init = 0
_stage_conn = 1
_stage_size = 2
_stage_check = 3
_stage_down = 4
_stage_verify = 5
_stage_done = 6

_usage = """
Usage: %prog [options] ftp://[user:[pass]@]host[:port]/src [dest]

Arguments:
  user  Optionally, the username to use; default is "anonymous".
  pass  Optionally, the password to use; default is an empty string.
  host  The fully qualified domain name or IP address of the FTP server.
  port  Optionally, the port on the FTP server to connect to; default is `21`.
  src   The path to the remote file.
  dest  The local path to save the file to; default is to use the basename of
        the remote file in current working directory.
""".strip()

def crc_file(path):
	"""
	Calculates the CRC32 checksum of the specified file.
	
	Arguments:
		path (file) -- The file to compute the checksum of.
		
	Returns:
		(int) -- The CRC32 checksum of the file.
	"""
	with open(path, 'rb') as fh:
		return zlib.crc32(fh.read())
	
def size_file(path):
	"""
	Returns the size of the specified file.
	
	Arguments:
		path (fie) -- The file to get the size of.
		
	Returns:
		(int) -- The size of the file.
	"""
	return os.stat(path).st_size

class FtpClient(ftp.FTPClient):
	"""
	The FTP Client class extends the built-in twisted implementation to support
	some missing methods.
	"""
	
	@defer.inlineCallbacks
	def size(self, path):
		"""
		Returns the size of the file.
		
		Arguments:
			path (str) -- The path of the remote file.
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred which will be called with: the size (int) of the file in bytes.
		"""
		result = yield self.queueStringCommand('SIZE ' + self.escapePath(path))
		if result[0][:4] != '213 ':
			raise ftp.BadResponse(result)
		size = int(result[0][4:])
		defer.returnValue(size)
	
	@defer.inlineCallbacks
	def xcrc(self, path):
		"""
		Returns the CRC32 checksum of the file.
		
		Arguments:
			path (str) -- The path of the remote file.
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred which will be called with: the CRC32 checksum (str) of the
				file.
		
		See:
			- http://www.starksoft.com/wiki/index.php/XCRC
		"""
		result = yield self.queueStringCommand('XCRC ' + self.escapePath(path))
		if result[0][:4] != '213 ':
			raise ftp.BadResponse(result)
		crc = int(result[0][4:])
		defer.returnValue(crc)


class FileReceiver(protocol.Protocol):
	"""
	The File Receiver class is a Twisted Protocol sub-class. When data is received
	it's written to a file.
	
	Instance Attributes:
		fh (file)
		- The file handle to the file being written to.
		path (str)
		- The path of the file to write to.
		recv (callable)
		- Called when data is received with: the data (str) received.
	"""
	
	def __init__(self, path, recv=None):
		"""
		Initializes a File Receiver instance.
		
		Arguments:
			path (str) -- The path to the file to write data.
		"""
		self.__dict__.update({'fh': None, 'path': None, 'recv': None, 'size': None})
		self.fh = None
		
		if not isinstance(path, basestring):
			raise TypeError("path:%r is not a string." % path)
		elif not path:
			raise ValueError("path:%r is empty." % path)
		if recv is not None and not callable(recv):
			raise TypeError("recv:%r is not callable." % recv)
		self.path = path
		self.recv = recv
		#XXX:
		print "DEST:%r" % path
		
	def __del__(self):
		"""
		Clean-up the File Receiver instance.
		"""
		if self.fh and not self.fh.closed:
			# Make sure that the file handle was closed.
			self.fh.close()
		
	def connectionMade(self):
		"""
		Called when a connection is made.
		"""
		self.fh = open(self.path, 'wb')
		
	def connectionLost(self, reason=error.ConnectionDone):
		"""
		Called when the connection is closed.
		
		Arguments:
			reason (twisted.python.failure.Failure)
			- The reason the connecton was closed.
		"""
		if self.fh:
			self.fh.close()
		
	def dataReceived(self, data):
		"""
		Called when data is received.
		
		Arguments:
			data (str) -- The data to consume.
		"""
		self.fh.write(data)
		if self.recv:
			self.recv(data)


class FtpDownload:
	"""
	This class downloads files via FTP.
	"""
	
	def __init__(self, host, port=None, username=None, password=None):
		"""
		Initializes an FtpDownload instance.
		threads
		Arguments:
		host (str) -- The FTP host.
		
		Optional Arguments:
			port (int) -- the FTP port; default is 21.
			username (str) -- The FTP login username; default is an empty string.
			password (str) -- The FTP login password; default is an empty string.
		"""
		if not isinstance(host, basestring):
			raise TypeError("host:%r is not a string." % host)
		elif not host:
			raise ValueError("host:%r is empty." % host)
		if port is not None:
			if not isinstance(port, int):
				port = int(port)
			if port <= 0:
				raise ValueError("port:%r is not greater than 0." % port)
		if username is not None and not isinstance(username, basestring):
			raise ValueError("username:%r is not a string." % username)
		if password is not None and not isinstance(password, basestring):
			raise ValueError("password:%r is not a string." % password)
		
		self.host = host
		self.port = port or _ftp_port
		self.username = username or 'anonymous'
		self.password = password or ''
		self.stage = _stage_init
		
	@defer.inlineCallbacks
	def download(self, ftp_path, dest_path, ready=None, recv=None):
		"""
		Downloads the specified file.
		
		Arguments:
			ftp_path (str) -- The path of the file to download.
			dest_path (str) -- The path to save the file to.
		
		Optional Arguments:
			ready (callable)
			- Called when the file is about to be transfered with: the size of the
			  file (int).
			recv (callable)
			- Called periodically while the file is being downloaded with: the data
			  (str) being written.
		
		Returns:
			(twisted.internet.defer.Deferred)
			- A deferred that's fired either when the file is downloaded or when an
				error occurs.
		"""
		# Connect to FTP server.
		self.stage = _stage_conn
		creator = protocol.ClientCreator(reactor, FtpClient, username=self.username, password=self.password, passive=int(bool(_ftp_passive)))
		client = yield creator.connectTCP(self.host, self.port, _ftp_timeout)
		# Get size of file.
		self.stage = _stage_size
		ftp_size = yield client.size(ftp_path)
		#XXX:
		print "FTP-SIZE:%r" % ftp_size
		if callable(ready):
			ready(ftp_size)
		# Get CRC of file.
		self.stage = _stage_check
		ftp_crc = yield client.xcrc(ftp_path)
		#XXX:
		print "FTP-CRC:%r" % ftp_crc
		# Download file.
		self.stage = _stage_down
		consumer = FileReceiver(dest_path, recv=recv)
		yield client.retrieveFile(ftp_path, consumer)
		# Verify file integrity.
		self.stage = _stage_verify
		dest_size = yield threads.deferToThread(size_file, dest_path)
		#XXX:
		print "DEST-SIZE:%r" % dest_size
		if dest_size != ftp_size:
			raise ValueError("The remote file:%r size:%r does not match the saved file:%r size:%r." % (ftp_path, ftp_size, dest_path, dest_size))
		dest_crc = yield threads.deferToThread(crc_file, dest_path)
		#XXX:
		print "DEST-CRC:%r" % dest_crc
		if dest_crc != ftp_crc:
			raise ValueError("The remote file:%r crc:%r does not match the saved file:%r crc:%r." % (ftp_path, ftp_crc, dest_path, dest_crc))
		self.stage = _stage_done


class FtpDownloadClient:
	"""
	The FTP Download Client.
	
	Instance Attributes:
		bytes_recv (int)
		- The bytes received thus far.
		bytes_total (int)
		- The size of the file.
		dest_path (str)
		- The path to where to save the file.
		downloader (FtpDownload)
		- The FtpDownload instance.
		exit (int)
		- The exit status to return from run.
		ftp_path (str)
		- The path to the file to download.
		prog_comp (int)
		- The amount completed.
		prog_total (int)
		- The total amount to complete.
		progress (stockpile.processing.process.StandardProcess)
		- The standard progress instance for outputting progress.
	"""

	def __init__(self, app, host, port, username, password, ftp_path, dest_path):
		self.prog_comp = 0
		self.prog_total = 1
		self.bytes_recv = 0
		self.bytes_total = 0
		self.dest_path = dest_path
		self.exit = 0
		self.ftp_path = ftp_path
		self.downloader = FtpDownload(host, port, username, password)
		self.progress = progress.StandardProgress(app)
		
		# Setup signal handler.
		signal.signal(signal.SIGINT, self.signal)
		
		# If stdlog (fd3) is not writable, use stdout instead.
		fd = sys.stdout.fileno()
		try:
			if fcntl.fcntl(3, fcntl.F_GETFL) & (os.O_WRONLY | os.O_RDWR):
				fd = 3
		except:
			pass
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
		
	@defer.inlineCallbacks
	def download(self):
		"""
		Downloads the file.
		"""
		try:
			yield self.downloader.download(self.ftp_path, self.dest_path, ready=lambda size: setattr(self, 'bytes_total', size), recv=self.recv)
			print "SUCCESS"
		except Exception as e:
			traceback.print_exc()
			self.stop(1)
		self.stop()
		
	def recv(self, data):
		"""
		Called periodically while the file is being downloaded to give its progress.
		
		Arguments:
			data (str) -- Some received data.
		"""
		self.bytes_recv += len(data)
		
	def run(self):
		"""
		Starts the Twisted reactor.
		"""
		reactor.callLater(0, self.download)
		reactor.run()
		return self.exit
		
	def signal(self, signum, frame):
		"""
		Called when the client receives a signal.
		
		Arguments:
			signum (int) -- The signal number
		"""
		if signum == signal.SIGINT:
			stage = self.downloader.stage
			if stage == _stage_conn:
				# Connecting.
				self.progress.progress(complete=0, total=5, write=True)
			elif stage == _stage_size:
				# Getting size.
				self.progress.progress(complete=1, total=5, write=True)
			elif stage == _stage_check:
				# Getting crc.
				self.progress.progress(complete=2, total=5, write=True)
			elif stage == _stage_down:
				# Downloading.
				comp = 3 + self.bytes_recv // 4096
				total = 3 + self.bytes_total // 4096
				self.progress.progress(complete=comp, total=total, write=True)
			elif stage == _stage_verify:
				# Verifying crc.
				comp = 4 + self.bytes_total // 4096
				total = comp + 1
				self.progress.progress(complete=comp, total=total, write=True)
			else: # stage == _stage_done
				total = 5 + self.bytes_total // 4096
				self.progress.progress(complete=total, total=total, write=True)
		
	def stop(self, exit=0):
		"""
		Stops the Twisted reactor.
		
		Optional Arguments:
			exit (int) -- The exit status to return from run; default is `0`.
		"""
		self.exit = 0
		reactor.stop()
		

def main(args=None):
	# Temporarily ignore the interupt signal until the Client instance is fully
	# initialized.
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	# Disable output buffering.
	sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
	
	import optparse
	
	if not args:
		args = sys.argv
		
	# Parse options.
	app = prog = os.path.basename(args[0])
	parser = optparse.OptionParser(prog=prog, usage=_usage)
	parser.add_option('-d', '--debug', dest='debug', help="Enable debugging.", action='store_true')
	options, args = parser.parse_args(args[1:])
	debug = options.debug
	url = args[0] if args else None
	dest_path = args[1] if len(args) > 1 else '.'
	
	# Check arguments.
	if url is None:
		parser.print_help()
		return 0
		
	# Parse url: scheme://user:password@host:port/path
	#                     \___________/ \_______/
	#                        userinfo    hostinfo
	#                     \_____________________/\___/
	#                            authority        path
	#            \____/ \____________________________/
	#            scheme            identity
	url = args[0]
	scheme_ident = url.split(':', 1)
	if len(scheme_ident) > 1:
		scheme, ident = scheme_ident
		if scheme.lower() != 'ftp':
			raise ValueError("url:%r scheme:%r is not 'ftp'." % (url, scheme))
	else:
		ident = scheme_ident[0]
	if ident[:2] == '//':
		# Remove preceding slashes from identifier.
		ident = ident[2:]
	ident = ident.split('/', 1)
	# Parse authority.
	auth = ident[0].split('@', 1)
	if len(auth) > 1:
		userinfo, hostinfo = auth
		# Parse userinfo.
		userinfo = userinfo.split(':', 1)
		username, password = userinfo[0], userinfo[1] if len(userinfo) > 1 else ''
	else:
		hostinfo = auth[0]
		username, password = '', ''
	# Parse hostinfo.
	hostinfo = hostinfo.split(':', 1)
	host, port = hostinfo[0], hostinfo[1] if len(hostinfo) > 1 else _ftp_port
	# Parse path.
	ftp_path = '/' + ident[1] if len(ident) > 1 else ''
	
	# Process save path.
	dest_path = os.path.abspath(dest_path)
	if os.path.isdir(dest_path):
		dest_path = os.path.join(dest_path, os.path.basename(ftp_path))
	
	# Start the FTP download.	
	client = FtpDownloadClient(app, host, port, username, password, ftp_path, dest_path)
	return client.run()

if __name__ == "__main__":
	exit(main())

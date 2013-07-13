 #!/usr/bin/python
"""
This is a Twisted CLI Perspective Broker client shell to the process server.

References:
- test/pbshell.py
"""
from twisted.internet import defer, protocol, reactor, stdio
from twisted.protocols import basic
from twisted.spread import pb

__author__ = "Caleb"
__version__ = "0.1"
__status__ = "Prototype"

_version = (0, 1)

_pb_host = "192.168.1.124"
_pb_port = 8787
_pb_connect_timeout = 1

_sh_delimiter = '\n'
_sh_welcome = "Perspective Broker Shell"

class Terminal(basic.LineReceiver):
	"""
	This class is used to send and received data from the terminal when used with
	the twisted.internet.stdio.StandardIO class.
	
	Class Attributes:
	delimiter (str) -- The line delimiter.
	"""
	delimiter = _sh_delimiter

	def __init__(self, callback=None, lostback=None, recvback=None):
		"""
		Initializes a Terminal instance.
		
		Optional Arguments:
		callback (callable) -- Called when the terminal is connected.
		lostback (callable) -- Called when the connection is lost or closed; called with the reason (Exception) for the closed connection.
		recvback (callable) -- Called when a line of data is received; called with the line (str) of data received.
		"""
		if callback and not callable(callback):
			raise TypeError("callback:%r is not callable." % callback)
		if lostback and not callable(lostback):
			raise TypeError("lostback:%r is not callable." % lostback)
		if recvback and not callable(recvback):
			raise TypeError("recvback:%r is not callable." % recvback)
			
		self._callback = callback
		self._lostback = lostback
		self._recvback = recvback
	
	def connectionLost(self, reason=error.ConnectionDone):
		"""
		Called when the protocol connection is closed/lost. Any references to the
		protocol should be cleared here.
		
		Arguments:
		reason (Exception) -- The reason the connection was closed/lost.
		"""
		if self._lostback:
			self._lostback(reason)
		
	def connectionMade(self):
		"""
		Called when the protocol is connected.
		"""
		if self._callback:
			self._callback()
			
	def lineReceived(self, line):
		"""
		Called when a line of data is received.
		
		Arguments:
		list (str) -- The line received.
		"""
		if self._recvback:
			self._recvback(line)
			
	def prompt(self, prefix=''):
		"""
		Display prompt to the user for input.
		
		Optional Arguments:
		prefix (str) -- What to prefix the prompt with.
		"""
		self.transport.write("%s> " % prefix)
		
	def write(self, data):
		"""
		Writes data to the terminal.
		"""
		self.transport.write(data)
		

class ProcessShell:
	"""
	This is a Perspective Broker Client Shell.
	"""
	
	def __init__(self, host, port):
		self.host = host
		self.port = port
		self.term = Terminal(self.on_term_connect, self.on_term_lost, self.on_term_receive)
		self.server = None
		
	def err_cmd(self, reason):
		"""
		Called when there is an error issuing a command.
		
		Arguments:
		reason (twisted.python.failure.Failure) -- The reason for failure.
		"""
		self.term.sendLine("Error: %s" % reason.getErrorMessage())
		self.term.prompt()
		
	def err_server_root(self, reason):
		"""
		Called if there was an error getting the root server reference.
		
		Arguments:
		reason (twisted.python.failure.Failure) -- The reason for failure.
		"""
		self.term.sendLine("error")
		self.term.sendLine(reason.getErrorMessage())
		self.stop()
		
	def got_server_root(self, root):
		"""
		Called when the root server reference is received.
		
		Arguments:
		root (twisted.spread.pb.RemoteReference) -- The server root reference.
		"""
		self.server = root
		self.term.sendLine("connected")
		self.term.prompt()
		
	def on_cmd(self, result):
		"""
		Called when there is a response for a command.
		"""
		self.term.sendLine("%r" % result)
		self.term.prompt()
		
	def on_term_connect(self):
		"""
		Called when the terminal is connected.
		"""
		self.term.sendLine(_sh_welcome)
		self.term.write("Connecting to %s:%s... " % (self.host, self.port))
		# Connect to PB server.
		factory = pb.PBClientFactory()
		reactor.connectTCP(self.host, self.port, factory, timeout=_pb_connect_timeout)
		d = factory.getRootObject()
		d.addCallbacks(self.got_server_root, self.err_server_root)
		
	def on_term_lost(self, reason):
		"""
		Called when the terminal connection is lost or closed.
		
		Arguments:
		reason (Exception) -- The reason the connection was closed/lost.
		"""
		self.term = None
		self.stop()
		
	def on_term_receive(self, line):
		"""
		Called when a line of data is received.
		
		Arguments:
		list (str) -- The line received.
		"""
		if not self.server:
			# Ignore input until we're connected to the server.
			return
			
		d = self.server.callRemote('command', line)
		d.addCallbacks(self.on_cmd, self.err_cmd)

	def run(self):
		"""
		Starts the Twisted reactor.
		"""
		stdio.StandardIO(self.term)
		reactor.run()
	
	def stop(self):
		"""
		Stops the Twisted reactor.
		"""
		reactor.stop()
		

def main():
	client = ProcessShell(_pb_host, _pb_port)
	client.run()

if __name__ == "__main__":
	main()

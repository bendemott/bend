'''
I'm going to use this as a place to stage tests about PB behavior with the client

whats the best way to deal with a stale broker
what happens to objects when a client disconnects
If we reconnect a client can we re-attach them to a Referenceable object?
how do we handle client-disconnects and notify the Referenceable of the disconnect?
What is the overhead for a referenceable in use?
what is the overhead for a referenceable not in use?
'''

from twisted.spread import pb
from twisted.python import log
from twisted.internet import defer, threads
from twisted.internet.threads import deferToThread as dthread

from pbplugins import EasyReferenceable

class ReferenceTest(EasyReferenceable):
	
	def clientConnectionMade(self, app):
		'''
		Called when the client instantiates this class ...
		Do whatever you want in here.
		It's ok to return deferreds from here.
		'''
		return None
	
	@defer.inlineCallbacks
	def search(self, query={}):
		'''
		'''
		defer.returnValue( False )
	
	def message( self ):
		'''
		Return a test string, letting the client know you're working
		'''
		return "ReferenceTest class working!"

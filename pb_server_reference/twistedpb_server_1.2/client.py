#! /usr/bin/python

'''
This is a client application for a Twisted Perspective Broker Application Server
This client will be a GTK program that will use the Twisted reactor to run
the GTK main loop.

This client should be used with the orderreview server.  This client is designed
to test the functionality around application modularity with Perspective Broker.

To use on windows you must install ZOPE, Twisted, and GTK
Links Here: http://twistedmatrix.com/trac/wiki/Downloads
'''

__author__="Ben"
__date__ ="Jan 12, 2011 6:26:30 PM"
__gtk_title__ = "Twisted Client Example"

#TODO: Test this with twisted...
#gtk.gdk.threads_init()

from twisted.internet import gtk2reactor
gtk2reactor.install()

import gtk
import gtk.gdk
import gobject
import time
import sys
import pprint
from twisted.internet import reactor, defer
from twisted.python import failure, log, util
from twisted.spread import pb
from twisted.cred.credentials import UsernamePassword
from twisted.internet import error as netError
import getpass
USER_NAME = getpass.getuser()


_host = "hol-srv-pydev"
_port = 8081
_application = 'OrderReviewApplication'

class GtkMain:
	ready = False

	def __init__(self):
		#The __init__() method sets up the main program window, and events.
		self.gtkSetup()
		self.label.set_label('Connecting to Server @ %s:%s' % (_host, _port) )
		self.pbSetup().addCallback(self.onClientReady)

	@defer.inlineCallbacks
	def pbSetup(self):
		self.gateway = PbGateway(_host, _port)
		yield self.gateway.connect()
		self.app = yield self.gateway.application(_application)
		pingval = yield self.app.callRemote('ping')
		if(pingval == 'pong'):
			self.label.set_label('Ping Successful - Application READY')
		self.pbOrder = yield self.app.callRemote('new', 'main.orders', 'OrderData')
		defer.returnValue(self.app)


	def gtkSetup(self):
		window = self.window = gtk.Window(type=gtk.WINDOW_TOPLEVEL)
		window.set_title(__gtk_title__) # set the title of the window :)
		window.connect('delete_event', self.delete_event) # Called when window is closed
		window.connect('destroy', self.destroy) # Called when the delete_event signal returns False
		window.set_border_width(0)
		window.set_default_size(400, 200)

		self.label = gtk.Label("No Status")

		button = gtk.Button(label='Do Request')
		button.connect('clicked', lambda *a,**kw: defer.maybeDeferred(self.sendRequest, *a, **kw))
		button.set_focus_on_click(False)
		
		vbox = gtk.VBox()
		hbox = gtk.HBox()
		hbox.pack_start(button)
		vbox.pack_start(hbox, False, False, 2)
		vbox.pack_end(self.label)
		self.hbox = hbox
		window.add(vbox)
		window.show_all()

	def onClientReady(self, app):
		self.ready = True

	@defer.inlineCallbacks
	def sendRequest(self, callref):
		'''		
		Event triggered by signal, sends request to server through the 'app' object

		Args:
			callref[instance] An instance of the object that triggered this signal - usually a gtk.Button 
		'''
		if(not self.ready):
			self.label.set_label("Server Not Ready")
		else:
			self.label.set_label("Sending Request...")

		
		result = yield self.pbOrder.callRemote('query', {})
		for order in result[1]:
			print order
		self.label.set_label("OrderData.query COMPLETE! (result in console) ")

	def delete_event(self, widget, event, data=None):
		"""
		Called when this window is going to be closed (deleted). By returning false,
		the 'destroy' signal will be emitted to this window by GTK.

		If you wanted to perform any cleanup before the app shuts down this would
		be the place.
		"""
		try:
			self.gateway.disconnect()
		except Exception as e:
			print "DISCONNECT: ", e
		reactor.stop()
		return False

	def destroy(self, widget, data=None):
		"""
		Called when the gtk_widget_destroy() method is called on this window, or if
		the 'delete_event' signal callback returned False.
		"""
		pass



class PbGateway():
	'''
	A class to manage client-connectivity
	'''
	CONNECTED = 1
	CONNECTING = 2
	DISCONNECTED = 0
	
	status = DISCONNECTED

	lasterror = None
	errors = []
	factory = None

	def __init__(self, host, port):
		self.host = host
		self.port = port

	@defer.inlineCallbacks
	def connect(self, timeout=10):
		'''
		Connect to the remote
		'''
		self.status = self.CONNECTING
		try:
			self.factory = pb.PBClientFactory()
			self.factoryConnectionLost = self.factory.clientConnectionLost
			self.factory.clientConnectionLost = self.clientConnectionLost
			reactor.connectTCP(self.host, self.port, self.factory, timeout=timeout)
			self.server = yield self.factory.getRootObject()
			self.status = self.CONNECTED
		except Exception as e:
			self.lasterror = e.__class__.__name__+" "+str(e)
			self.errors.append(self.lasterror)
		defer.returnValue( self.server )

	def reconnect(self, asdf):
		#TODO
		# use this to reconnect when connection / broker is lost or stale.
		raise NotImplemented("Todo...")

	@defer.inlineCallbacks
	def application(self, app):
		'''
		Retrieve an application object by name.
		The application must be registered on the server in order to be callable!

		Args:
			app[str] The name of the registered application class

		Returns: app_reference[pb.Referenceable]
		'''
		assert self.status == self.CONNECTED
		
		appinst = yield self.server.callRemote('application', app)
		defer.returnValue(appinst)
		

	def disconnect(self):
		'''
		Disconnect / Clean-Up from the server
		'''
		self.factory.disconnect()

	def clientConnectionLost(self, connector, reason, reconnecting=0):
		'''
		Called when client is disconnected - wraps factory.clientConnectionLost()
		'''
		self.status = self.DISCONNECTED
		self.factoryConnectionLost(connector, reason, reconnecting)

def main():
	app = GtkMain()
	# instead of calling gtk.main() or app.main() we call reactor.run() and it
	# somehow knows what to do and starts the gtk main loop.
	reactor.run()
	


if __name__ == '__main__':
	sys.exit(main())


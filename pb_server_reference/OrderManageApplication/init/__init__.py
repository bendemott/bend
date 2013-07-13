'''
This module handles initializing the gui and its components. Because we want
a client that is very flexible and open to change without having to go in
and change the code, we've created the client in such a way that it needs to
query the server when it's initialized in order to retrieve configuration-type
data that assists in building the GUI. This includes configuration dictionary
structures for all of the ConfigTreeViews in the application, as well as other
data structures that are needed to initialize components(like a structure to
generate the search fields in the SearchPane)
'''

__author__ = "Wesley Hansen"
__date__ = "06/26/2012 02:12:46 PM"

from twisted.spread import pb
from twisted.python import log
from twisted.python.rebuild import updateInstance
from twisted.internet import defer, threads
from twisted.internet.threads import deferToThread
from pbplugins import EasyReferenceable

import imp
import sys
import pprint
sys.path.append( '../OrderManageApplication/init/')


class ClientInit(EasyReferenceable):
	'''
	This class will contain the appropriate methods needed to initialize the
	various gui components.
	'''

	def clientConnectionMade(self, app):
		'''
		Called when the client instantiates this class ...
		Build the config structure that will be sent to the client
		'''
		#Import the server-side config structures

		import configs
		self.configs = {
			'search_treeview': dict(configs.search_treeview_config), #For the MainWindow.search_treeview
			'preview_cart': dict(configs.preview_cart_config),		 #For CustomerPreview.treeview(cart version)
			'preview_orders': dict(configs.orders_config),			 #For CustomerPreview.treeview(orders version)
			'cart_treeview': dict(configs.cart_config),				 #For CustomerRecorWindow.OrderSummaryPage.cart_treeview
			'search_pane_config': dict(configs.search_config)		 #For SearchPane initialization
		}
		print "ClientInit Initialized"

	def get_config(self, *args):
		'''
		Returns a configuration structure that contains the structures named in `args`.
		
		:param *args: Strings that name the config structure that is needed. These
			are the same names that are keys to the `ClientInit.configs`
		:return: The `dict` containing all of the keys defined in args. If a name
			doesn't exist in ClientInit.configs, then `None` is returned for the
			value at the key. This should be used to do error-checking/handling
			on the client.
		'''
		if args == ():
			#If no args are sent, then return all the configs
			config = dict(self.configs)
		else:
			config = {}
			for name in args:
				if name in self.configs.keys():
					config[name] = self.config[name]
				else:
					print 'Warning!: %s is not defined in self.configs' % name
					config[name] = None
		return config


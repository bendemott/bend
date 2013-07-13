#! /usr/bin/python

'''
This is a Twisted Prospective Broker Server Application Server
Prospective Broker is a set of api's to handle remote objects and communication
between client and server.  
This server is an alpha version and will contain logic to test new concepts and
methodologies around Perspective Broker.

Goals:
	-Detach main server functionality from applications. (done)
	-Support multiple applications that can Attach/Detach/Re-attach to the PB
	 server at anytime. (done, additional functionality needs to be defined for reloading apps, etc)
	-Support the reloading of individual applications (...)
	-Properly destroy application references and scope information (??? haven't explored this yet)
	-Provide consistent mechanism to store and represent STATE information 
	 across all connections.
	-Provide central and standardized authentication mechanisms and configs.
	-Provide consistent configuration app configuration interface.
	-Define built-in modules like 'server-status', 'server-admin', 'app-manager'
	 these probably should stem from the root objects methods if they are built
	 in functionality.
	-Define cluster api / PB Cluster functionality.
'''

__author__="Ben"
__date__ ="Jan 12, 2011 6:19:54 PM"

_port = 16030

from twisted.spread import pb
from twisted.internet import reactor
from twisted.web.resource import Resource
from twisted.internet import protocol, defer
from twisted.web.server import NOT_DONE_YET
from twisted.python import log
import sys
log.startLogging(sys.stdout)

sys.path.append("./site-packages")
sys.path.append("../../twisted_pbplugins")
import time
import os
import os.path
from pbplugins0_2 import PbServerRoot, PbServerFactory


#TODO figure out how to tack client-disconnects
#TODO figure out auth model/ldap integration (do we need to extend/modify?)

if __name__ == '__main__':
	print "PBServer Port: %s" % _port
	cpath = os.path.abspath(os.path.dirname(__file__))
	root = PbServerRoot()
	#                 module     path

	root.register_app("ordermanage", os.path.join(cpath, "../OrderManageApplication"))
	root.register_app("order", os.path.join( cpath, "../review/twisted"))
	#root.register_app("ordersearchapp", os.path.join(cpath, "../OrderSearchApplication"))
	print "All applications successfully registered"
	reactor.listenTCP(_port, PbServerFactory(root))
	reactor.run()




# coding: utf-8
"""
This script connects to a Twited Server that has the Order Search
Application registered, and tests it.
"""

__author__ = "Caleb"
__version__ = "0.2"
__status__ = "Prototype"

import argparse
import os.path
import pprint
import site
import sys
import time

from twisted.internet import defer, reactor
from twisted.python import failure

site.addsitedir(os.path.dirname(os.path.abspath(__file__)))

import pbplugins
import pbplugins.stateful

class OrderSearchClient(pbplugins.EasyReferenceable):
	def __init__(self, app):
		self.app = app
		d = self.connect()
		d.addErrback(lambda r: r.printTraceback())
		d.addBoth(lambda _: reactor.stop())
	
	@defer.inlineCallbacks
	def connect(self):
		print "Connecting to OrderSearch application..."
		yield self.app.connect()
		
		print "Getting OrderSearch reference..."
		ref = yield self.app.new('search', 'OrderSearch')
		
		print "Searching..."
		query = {
			'debug': True,
			'search': {
				'query': {
					'address': 'ionia'
				},
			},
			'fields': [
				'address',
				'name',
				'id'
			],
			'pagination': {
				'start_index': 0,
				'page_size': 10
			}
		}
		query_start = time.time()
		result = yield ref.callRemote('search', query)
		query_time = time.time() - query_start
		print "TIME: %f ms" % (query_time * 1000)
		pprint.pprint(result)
		
	
def main(argv):
	parser = argparse.ArgumentParser(prog=argv[0])
	parser.add_argument('host', help="The host to connect to.")
	parser.add_argument('port', help="The port to connect to")
	args = parser.parse_args(argv[1:])
	
	host = args.host
	port = int(args.port)
	
	app = pbplugins.stateful.PbClientApplication('CommerceOrderManagement', host=host, port=port)
	client = OrderSearchClient(app)
	
	reactor.run()
	return 0

if __name__ == '__main__':
	sys.exit(main(sys.argv))

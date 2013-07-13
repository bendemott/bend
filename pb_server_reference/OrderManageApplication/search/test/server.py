# coding: utf-8
"""
This script runs a Twisted Server that has the Order Search Application
registered.
"""

__author__ = "Caleb"
__version__ = "0.2"
__status__ = "Prototype"

import argparse
import os.path
import site
import sys

from twisted.internet import reactor

_dirpath = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(_dirpath)

import pbplugins0_2 as pbplugins

def main(argv):
	parser = argparse.ArgumentParser(prog=argv[0])
	parser.add_argument('port', help="The port to listen on.")
	args = parser.parse_args(argv[1:])

	port = int(args.port)

	root = pbplugins.PbServerRoot()
	root.register_app("ordermanage", os.path.abspath(os.path.join(_dirpath, "../../")))
	
	reactor.listenTCP(port, pbplugins.PbServerFactory(root))
	reactor.run()
	return 0

if __name__ == '__main__':
	sys.exit(main(sys.argv))

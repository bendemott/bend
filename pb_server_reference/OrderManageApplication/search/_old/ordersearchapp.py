# coding: utf-8
"""
This module contains the Perspective Broker Order Search Application.
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.2"
__status__ = "Prototype"

import errno
import json
import math
import os.path
import site

import lucene
import txmongo
from twisted.internet import reactor

_dirpath = os.path.dirname(os.path.abspath(__file__))
site.addsitedir(_dirpath)

import sys
sys.path.append("../../twisted_pbplugins")
import pbplugins0_2 as pbplugins
#import pbplugins

_index_dirpath = os.path.join(_dirpath, "web_orders.idx")
_config_filepath = os.path.join(_dirpath, "ordersearch.json")

class OrderSearchApp(pbplugins.PbApplication):
	"""
	The ``OrderSearchApp`` class is the Perspective Broker Order Search
	Application.
	"""
	
	searcher = None
	"""
	*searcher* (``lucene.IndexSearcher``) is the index searcher.
	"""
	
	config = None
	"""
	*config* (``dict``) is the application's configuration.
	"""
	
	mongo = None
	"""
	*mongo* (``txmongo.MongoAPI``) is the MongoDB connection.
	"""
	
	order_db = None
	"""
	*order_db* (``txmongo.database.Database``) is the MongoDB Orders
	database.
	"""
	
	order_tb = None
	"""
	*order_tb* (``txmongo.collection.Collection``) is the MongoDB Orders
	collection.
	"""
	
	config_filepath = _config_filepath
	index_dirpath = _index_dirpath
	
	@classmethod
	def applicationRegistered(cls, server):
		"""
		Called when the application is first registered (imported) into the
		server.
		
		*server* (``twisted.spread.pb.Root``) is the server root instance.
		"""
		config_filepath = cls.config_filepath
		if not os.path.exists(config_filepath):
			raise OSError(errno.ENOENT, "Config %r does not exist." % config_filepath, config_filepath)
		
		index_dirpath = cls.index_dirpath
		if not os.path.exists(index_dirpath):
			raise OSError(errno.ENOENT, "Index %r does not exist." % index_dirpath, index_dirpath)
		elif not os.path.isdir(index_dirpath):
			raise OSError(errno.ENOTDIR, "Index %r is not a directory." % index_dirpath, index_dirpath)
		
		# Read config.
		with open(config_filepath, 'rb') as fh:
			config = json.load(fh)
		cls.config = config
		
		# Connect to mongo.
		host = config['mongo']['host']
		port = config['mongo'].get('port', None) or 27017
		thread_pool = reactor.getThreadPool()
		pool_size = int(math.ceil((thread_pool.min + thread_pool.max) / 2))
		cls.mongo = txmongo.lazyMongoConnectionPool(host=host, port=port, pool_size=pool_size)
		cls.order_db = cls.mongo[config['mongo']['order_dbname']]
		cls.order_tb = cls.order_db[config['mongo']['order_tbname']]
		
		# Initialize PyLucene.
		lucene.initVM()
		
		# Open index.
		index_dir = lucene.NIOFSDirectory(lucene.File(_index_dirpath))
		#index_dir = lucene.SimpleFSDirectory(lucene.File(_index_dirpath))
		cls.searcher = lucene.IndexSearcher(index_dir)
		
		print "REGISTERED %r" % cls
		
	@classmethod
	def applicationUnregistered(cls):
		"""
		Called when the application is unregistered from the server.
		"""
		pass
		
application = OrderSearchApp

# coding: utf-8
"""
This script reports the number of phone numbers per country.
"""

import pprint
import sys

import pymongo

def main(argv):
	mongo_uri = 'hol-srv-db00'
	
	print "Connecting to %r..." % mongo_uri,; sys.stdout.flush()
	mongo = pymongo.Connection(mongo_uri)
	order_db = mongo['orders']
	order_tb = order_db['mysql_web_orders']
	print "done"
	
	print "Reading...",; sys.stdout.flush()
	cursor = order_tb.find({}, {
		'customer.daytime_phone': 1,
		'customer.evening_phone': 1,
		'shipping.country_text': 1,
		'shipping.country_id': 1
	})
	count = cursor.count()
	report = {}
	for i, doc in enumerate(cursor, 1):
		if not i % 1000:
			print "\rReading %i/%i" % (i, count),; sys.stdout.flush()
		
		country = doc['shipping']['country_text'] or doc['shipping']['country_id'] or None
		
		for phone in (doc['customer']['daytime_phone'], doc['customer']['evening_phone']):
			if country in report:
				report[country] += 1
			else:
				report[country] = 1
		
	print "Reading %i/%i" % (count, count)
	
	pprint.pprint(report)

if __name__ == '__main__':
	sys.exit(main(sys.argv))

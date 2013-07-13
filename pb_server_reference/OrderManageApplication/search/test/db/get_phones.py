# coding: utf-8
"""
This script writes all phone numbers out to a JSON file.
"""

__author__ = "Caleb"
__version__ = "0.1"
__status__ = "Prototype"

import csv
import json
import sys

import pymongo

json_file = 'phones.json'
csv_file = 'phones.csv'

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
	phones = []
	for i, doc in enumerate(cursor, 1):
		if not i % 1000:
			print "\rReading %i/%i" % (i, count),; sys.stdout.flush()
		
		country = doc['shipping']['country_text'] or doc['shipping']['country_id'] or None
		
		phone = doc['customer']['daytime_phone']
		if phone:
			phones.append((phone, country))
			
		phone = doc['customer']['evening_phone']
		if phone:
			phones.append((phone, country))
		
	print "Reading %i/%i" % (count, count)
	
	print "Writing %r..." % json_file,; sys.stdout.flush()
	with open(json_file, 'wb') as fh:
		json.dump(phones, fh)
	print "done"
	
	print "Writing %r..." % csv_file,; sys.stdout.flush()
	with open(csv_file, 'wb') as fh:
		writer = csv.writer(fh)
		writer.writerow(("Phone", "Country"))
		writer.writerows(phones)
	print "done"


if __name__ == '__main__':
	sys.exit(main(sys.argv))

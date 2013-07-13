# coding: utf-8
"""






Using PyLucene with threads
---------------------------

Before PyLucene can be used from within a thread other than the main
thread (where the JVM was initialized), it must be **attached** to the
JVM. An attached thread must also be **detached** from the JVM before it
is destroyed [1]_ [2]_.

.. WARNING: Accessing the JVM from an unattached thread (either before
   attaching or after detaching) can/will crash the whole program. YOU
   HAVE BEEN WARNED.

In order to attach the current thread to the JVM,
*attachCurrentThread()* must be called:: 
	
	jcc_env = lucene.getVMEnv()
	if not jcc_env.isCurrentThreadAttached():
		jcc_env.attachCurrentThread()
		
Attaching the same thread more than once does not appear to cause
problems [3]_ [4]_, but it cannot hurt to check.

In order to detach the current thread from the JVM,
*detachCurrentThread()* must be called::

	jcc_env = lucene.getVMEnv()
	if jcc_env.isCurrentThreadAttached():
		jcc_env.detachCurrentThread()

Detaching the same thread more than once might work, but I have not
tested it yet and would not relay on it without testing. The PyLucene
documentation states that use of *detachCurrentThread()* is "dubious"
[5]_.

.. WARNING: calling *detachCurrentThread()* before all Python references
   to Java objects have been destroyed (garbage collected) can cause the
   program to crash.

.. NOTE: Detaching the current thread NEEDS TO BE TESTED. 

.. [1] http://stackoverflow.com/a/1946360/369450
.. [2] http://docs.oracle.com/javase/6/docs/technotes/guides/jni/spec/invocation.html#wp1060
.. [3] http://mail-archives.apache.org/mod_mbox/lucene-pylucene-dev/201008.mbox/%3Calpine.OSX.2.01.1008302321140.86799%40yuzu.local%3E
.. [4] http://mail-archives.apache.org/mod_mbox/lucene-pylucene-dev/201008.mbox/%3C3DEDA4DF-D48B-4757-910A-C8EB51FB3F11%40twopeasinabucket.com%3E
.. [5] http://lucene.apache.org/pylucene/jcc/features.html#jccs-runtime-api-functions
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.2"
__status__ = "Prototype"

import math
import os
import pprint
import re
import site
import sys
import time

import lucene
import txmongo
from twisted.internet import defer, threads

site.addsitedir(os.path.dirname(os.path.abspath(__file__)))
import pbplugins
from luceneextras.filters.doublemetaphone import DoubleMetaphoneFilter
from luceneextras.filters.wordchar import WordCharFilter
from luceneextras.utils.sequence import stream_to_sequence


def _facet(searcher, analyzer, text, fields, debug=False):
	jcc_env = lucene.getVMEnv()
	print "Attaching thread...",
	if not jcc_env.isCurrentThreadAttached():
		jcc_env.attachCurrentThread()
		print "done" if jcc_env.isCurrentThreadAttached() else "failed"
	else:
		print "already attached."
	
	# Parse query.
	if debug: parse_start = time.time()
	parser = lucene.MultiFieldQueryParser(lucene.Version.LUCENE_CURRENT, fields, analyzer)
	query = lucene.QueryParser.parse(parser, text)
	if debug: parse_time = time.time() - parse_start
	
	# Perform query.
	if debug: search_start = time.time()
	top_docs = searcher.search(query, searcher.maxDoc())
	if debug: search_time = time.time() - search_start
	
	# Facet.
	if debug: iter_start = time.time()
	facets = _facet_func(searcher, top_docs, fields)
	if debug: iter_time = time.time() - iter_start
	
	# Return facets.
	result = {
		'facets': facets
	}
	if debug:
		result['debug'] = {
			'parse_time': parse_time,
			'search_time': search_time,
			'iter_time': iter_time,
		}
	return result

def _facet_func_fast(searcher, top_docs, fields):
	"""
	Facets on the specified documents using the CPP faceting extension.
	
	*searcher* (``lucene.IndexSearcher``) is the index searcher.
	
	*top_docs* (``lucene.TopDocs``) are the documents.
	
	*fields* (``list``) are the fields to facet on.
	
	Returns the facets (``dict``). 
	"""
	# TODO: Use the CPP faceting extension.
	raise NotImplementedError("TODO: Use CPP faceting extension.")
	
def _facet_func_slow(searcher, top_docs, fields):
	"""
	Facets on the specified documents manually in Python.
	
	*searcher* (``lucene.IndexSearcher``) is the index searcher.
	
	*top_docs* (``lucene.TopDocs``) are the documents.
	
	*fields* (``list``) are the fields to facet on.
	
	Returns the facets (``dict``). 
	"""
	facets = {k: {} for k in fields}
	for score_doc in top_docs.scoreDocs:
		doc = searcher.doc(score_doc.doc)
		for field in fields:
			val = doc[field]
			if val is not None:
				field_vals = facets[field]
				if val in field_vals:
					field_vals[val] += 1
				else:
					field_vals[val] = 1
	return facets
	
_facet_func = _facet_func_slow
"""
*_facet_func* (**callable**) is the function called from *_facet()* that
actually performs the faceting. This will be set to either the
*_facet_func_slow()* or *_facet_func_fast()* function.

.. TODO: Change this to *_facet_func_fast()* once it is implemented.

Arguments:

*searcher* (``lucene.IndexSearcher``) is the index searcher.

*top_docs* (``lucene.TopDocs``) are the documents.

*fields* (``list``) are the fields to facet on.

Returns the facets (``dict``). 
"""

def merge_ranges(ranges):
	"""
	Merges adjacent and overlapping ranges.
	
	*ranges* (``list``) contains range ``tuple``s. A range consists of a
	start offset (``int``), and end offset (``int``).
	
	Returns the merged ranges (``list``).
	"""
	ranges = sorted(ranges)
	start, end = ranges[0]
	result = []
	for s, e in ranges[1:]:
		if start <= s <= end:
			if end < e:
				end = e
		else: # end < s
			result.append((start, end))
			start = s
			end = e
	result.append((start, end))
	return result
	
def substr_ranges(value, ranges):
	"""
	Gets the substrings from the specified ranges.
	
	*value* (**string**) is the string to extract the substrings from.
	
	*ranges* (``list``) contains range ``tuple``s. A range consists of a
	start offset (``int``), and end offset (``int``).
	
	The ``list`` of sub-**string**s.
	"""
	return [value[start:end] for start, end in ranges]
	

class BasicSearchAnalyzer(lucene.PythonAnalyzer):
	"""
	The ``BasicSearchAnanlyzer`` class is the PyLucene Analyzer for
	performing basic search over orders.
	"""
	
	def tokenStream(self, field_name, reader):
		"""
		Creates the token stream.
		
		*field_name* (``str``) is the name of the field.
		
		*reader* (``lucene.Reader``) is what provides the text to tokenize.
		
		Returns the token stream (``lucene.TokenStream``).
		"""
		tokens = lucene.WhitespaceTokenizer(lucene.Version.LUCENE_CURRENT, reader)
		tokens = lucene.SpanishLightStemFilter(tokens)
		tokens = lucene.ElisionFilter(lucene.Version.LUCENE_CURRENT, tokens)
		tokens = lucene.ASCIIFoldingFilter(tokens)
		tokens = WordCharFilter(tokens, replace=True)
		tokens = lucene.LowerCaseFilter(lucene.Version.LUCENE_CURRENT, tokens)
		tokens = DoubleMetaphoneFilter(tokens)
		return tokens
		

class AbstractFormatField:
	
	def format(self, data, offsets):
		raise NotImplementedError()
		
	def highlight_substrs(self, value, substrs, filter=None):
		"""
		Highlights the value where the given strings occur.
		
		*value* (**string**) is the value to highlight.
		
		*substrs* (``list``) contains the sub-**string**s to highlight.
		
		*filter* (**string** or ``re.RegexObject``) that matches all valid
		characters for *substrs*. This allows for substrings to match that
		may be separated due to formatting. Default is ``None``.
		
		Returns the highlighted value (**string**).
		"""
		if filter:
			check = ''.join(filter.findall(value) if isinstance(filter, re.RegexObject) else re.findall(filter, value))
			# Map character positions from check (filtered) string to value
			# (original) string.
			pos_map = []
			pos = 0
			for ch in check:
				while ch != value[pos]:
					pos += 1
				pos_map.append(pos)
		else:
			check = value
		
		# Find positions of substrings. If the string was filtered, map
		# check string positions to value string positions.
		ranges = []
		for substr in substrs:
			if not substr:
				continuepre
			off = 0
			while 1:
				pos = check.find(substr, off)
				if pos == -1:
					break
				off = pos + len(substr)
				ranges.append((pos_map[pos], pos_map[off]) if filter else (pos, off))
		
		if ranges:
			# Merge adjacent and overlapping ranges.
			ranges = merge_ranges(ranges)
		
			# Highlight ranges.
			return self.highlight_ranges(value, ranges)
		
		return value
		
	def highlight_ranges(self, value, ranges):
		"""
		Highlights the value at the given ranges.
		
		*value* (**string**) is the value to highlight.
		
		*ranges* (``list``) contains the range ``tuple``s. A range consists
		of a start offset (``int``), and end offset (``int``).
		
		Returns the highlighted value (**string**).
		"""
		highlight = []
		off = 0
		for start, end in ranges:
			highlight.extend([value[off:start], '<b>', value[start:end], "</b>"])
			off = end
		highlight.extend(value[off:])
		highlight = ''.join(highlight)
		return highlight
	
	
class AddressFormatField(AbstractFormatField):
	"""
	The ``AddressFormatField`` class is used to format the Address field.
	"""
	
	data_fields = [
		'shipping.address.city',
		'shipping.address.province_text',
		'shipping.address.country_code',
		'shipping.address.country_text',
		'payments'
	]
	
	offset_fields = [
		'shipping.address.city',
		'shipping.address.province',
		'shipping.address.country',
		'payments.0.billing.city',
		'payments.0.billing.province',
		'payments.0.billing.country'
	]
	
	def format(self, data, offsets):
		# Determine which addresses to markup.
		shipping = data['shipping'].get('address', None)
		if shipping:
			ship_city = shipping['city']
			ship_province = shipping['province_text']
			ship_country = shipping['country_text']
			ship_is_us = shipping['country_code'] == 'usa'
			ship_address = ship_city + ", " + (ship_province if ship_is_us else ship_country)
		else:
			ship_address = None
		
		billing = data['payments'][0].get('billing', None)
		if billing:
			bill_city = billing['city']
			bill_province = billing['province_text']
			bill_country = billing['country_text']
			bill_is_us = billing['country_code'] == 'usa'
			bill_address = bill_city + ", " + (bill_province if bill_is_us else bill_country)
		else:
			bill_address = None
			
		markup_ship = False
		markup_bill = False
		if ship_address and bill_address:
			markup_ship = True
			if ship_address != bill_address:
				markup_bill = True
		elif ship_address:
			markup_ship = True
		elif bill_address:
			mkarup_bill = True
		
		if markup_ship:
			# Markup shipping address.
			city_ranges = offsets.get('shipping.address.city', None) if offsets else None
			city_markup = self.highlight_ranges(ship_city, city_ranges).strip() if city_ranges else ship_city
			if ship_is_us:
				province_ranges = offsets.get('shipping.address.province', None) if offsets else None
				province_markup = self.highlight_ranges(ship_province, [(0, len(ship_province))]).strip() if province_ranges else ship_province
				ship_markup = city_markup + ", " + province_markup
			else:
				country_ranges = offsets.get('shipping.address.country', None) if offsets else None
				country_markup = self.highlight_ranges(ship_country, [(0, len(ship_country))]).strip() if country_ranges else ship_country
				ship_markup = city_markup + ", " + country_markup
		
		if markup_bill:
			# Markup billing address.
			city_ranges = offsets.get('payments.0.billing.city', None) if offsets else None
			city_markup = self.highlight_ranges(bill_city, city_ranges) if city_ranges else bill_city
			if bill_is_us:
				province_ranges = offsets.get('payments.0.billing.province', None) if offsets else None
				province_markup = self.highlight_ranges(bill_province, [(0, len(bill_province))]).strip() if province_ranges else bill_province
				bill_markup = city_markup + ", " + province_markup
			else:
				country_ranges = offsets.get('payments.0.billing.country', None) if offsets else None
				country_markup = self.highlight_ranges(bill_country, [(0, len(bill_country))]).strip() if country_ranges else bill_country
				bill_markup = city_markup + ", " + country_markup
		
		if markup_ship and markup_bill:
			markup = "Billing: %s\nShipping: %s" % (bill_markup, ship_markup)
		elif markup_ship:
			markup = ship_markup
		elif markup_bill:
			markup = bill_markup
		return {'markup': markup}
	
	
class CommentFormatField(AbstractFormatField):
	"""
	The ``CommentFormatField`` class is used to format the Comment field.
	"""
	
	data_fields = [
		'order.comments'
	]
	
	offset_fields = [
		'order.comments'
	]
	
	def format(self, data, offsets):
		comments = data['order'].get('comments', None)
		if comments:
			if not isinstance(comments, basestring):
				comments = "\n".join(comments)
			comment_ranges = offsets.get('order.comments', None) if offsets else None
			markup = self.highlight_ranges(comments, comment_ranges).strip() if comment_ranges else comments
		else:
			markup = ''
		return {'markup': markup}
		

class ContactFormatField(AbstractFormatField):
	"""
	The ``ContactFormatField`` class is used to format the Contact field.
	"""

	digits = re.compile(r'\d+')

	data_fields = [
		'customer.phones',
		
	]
	
	offset_fields = [
		'customer.phones.0.number',
		'customer.phones.1.number'
	]
	
	def format_phone(self, phone, ranges):
		if phone[:2] == '+1':
			number = phone[2:].split('x', 1)
			number, ext = number if len(number) == 2 else (number[0], "")
			number = "".join(self.digits.findall(number))
			if len(number) == 10:
				markup = "(%s) %s-%s" % (number[:3], number[3:6], number[6:])
				if ext:
					markup += " x" + "".join(self.digits.findall(ext))
				if ranges:
					markup = self.highlight_substrs(markup, substr_ranges(phone, ranges), filter=self.digits)
				return markup
		
		return self.highlight_ranges(phone, ranges) if ranges else phone
	
	def format(self, data, offsets):
		# Phone numbers are expected to be in the following format::
		#   phone ::= "+" cc number ("x" extension)?
		# where cc is the country code, followed by the phone number, and
		# optionally with an extension.
		
		markup = []
		phones = data['customer'].get('phones', None)
		if phones:
			for i, phone in enumerate(phones):
				phone_ranges = offsets.get('customer.phones.%i.number' % i, None) if offsets else None
				phone_markup = self.format_phone(phone['number'], phone_ranges)
				markup.append(phone['name'] + ": " + phone_markup)
				
		return {'markup': "\n".join(markup)}


class MarketFormatField:
	
	data_fields = [
		'platform.market_code' 
	]
	
	offset_fields = []
	
	def format(self, data, offsets):
		return {'pixbuf': data['platform']['market_code']}


class NameFormatField(AbstractFormatField):
	"""
	The ``NameFormatField`` class is used to format the Name field.
	"""

	data_fields = [
		'customer.name_first',
		'customer.name_last',
		'payments', # payments.0.billing.recipient
		'shipping.address.recipient'
	]
	
	offset_fields = [
		'customer.name_first',
		'customer.name_last',
		'payments.0.billing.recipient',
		'shipping.address.recipient'
	]
	
	def format(self, data, offsets):
		markup = []
		
		# Customer name.
		customer = data['customer']
		cust_first = customer['name_first']
		cust_last = customer['name_last']
		cust_name = cust_first + ' ' + cust_last
		
		first_ranges = offsets.get('customer.name_first', None) if offsets else None
		first_markup = (self.highlight_ranges(cust_first, first_ranges) if first_ranges else cust_first).strip()
		last_ranges = offsets.get('customer.name_last', None) if offsets else None
		last_markup = (self.highlight_ranges(cust_last, last_ranges) if last_ranges else cust_last).strip()
		markup.append(first_markup + ' ' + last_markup)
		
		# Billing name.
		billing = data['payments'][0].get('billing', None)
		if billing:
			bill_name = billing['recipient']
			if bill_name != cust_name:
				name_ranges = offsets.get('payments.0.billing.recipient', None) if offsets else None
				name_markup = (self.highlight_ranges(bill_name, name_ranges) if name_ranges else bill_name).strip()
				markup.append("Billing: " + name_markup)
			
		# Shipping name.
		shipping = data['shipping'].get('address', None)
		if shipping:
			ship_name = shipping['recipient']
			if ship_name != cust_name:
				name_ranges = offsets.get('shipping.address.recipient', None) if offsets else None
				name_markup = (self.highlight_ranges(ship_name, name_ranges) if name_ranges else ship_name).strip()
				markup.append("Shipping: " + name_markup)
		
		return {'markup': "\n".join(markup)}
		
		
class OrderIdFormatField(AbstractFormatField):
	"""
	The ``OrderIdFormatField`` class is used to format the Order ID field.
	"""
	
	data_fields = [
		'platform.po_number'
	]
	
	offset_fields = [
		'platform.po_number'
	]
	
	def format(self, data, offsets):
		po_ranges = offsets.get('platform.po_number', None) if offsets else None
		markup = self.highlight_ranges(data['platform']['po_number'], po_ranges) if po_ranges else data['platform']['po_number']
		return {'markup': markup}
		

class PaymentFormatField(AbstractFormatField):
	"""
	The ``PaymentFormatField`` class is used to format the Payment field.
	"""
	
	data_fields = [
		'payments'
		# payments.*.method_code
		# payments.*.method_text
		# payments.*.details
		# payments.*.total
		# payments.*.status_text
	]
	
	offset_fields = []
	
	def format(self, data, offsets):
		methods = []
		amounts = []
		
		for payment in data['payments']:
			details = payment['details'] or {}
		
			method = None
			method_code = payment['method_code']
			if method_code == 'creditcard':
				method = details.get('issuer_text', None)
			if not method:
				method = payment['method_text']
			methods.append(method)
			
			amounts.append("$%.2f (%s)" % (payment['amount'], (details.get('status_text', None) or payment['status_text']).upper()))
			
		return ({'markup': "\n".join(methods)}, {'markup': "\n".join(amounts)})
		

class PlacedFormatField(AbstractFormatField):
	"""
	The ``PlacedFormatField`` class is used to format the Placed field.
	"""
	
	data_fields = [
		'order.date'
	]
	
	offset_fields = []
	
	def format(self, data, offsets):
		return {'markup': data['order']['date']}
	
	
class ShippingFormatField:
	
	data_fields = [
		'shipping.status_text'
	]
	
	offset_fields = []
	
	def format(self, data, offsets):
		return {'markup': data['shipping']['status_text']}
	
	
class StatusFormatField:
	
	data_fields = [
		'order.status_text'
	]
	
	offset_fields = []
	
	def format(self, data, offsets):
		return ({'markup': "Current Status"}, {'markup': data['order']['status_text']})


class MainDataFormatter:

	format_fields = {
		'address': AddressFormatField(),
		'comments': CommentFormatField(),
		'contact': ContactFormatField(),
		'id': OrderIdFormatField(),
		'market': MarketFormatField(),
		'name': NameFormatField(),
		'payment': PaymentFormatField(),
		'placed': PlacedFormatField(),
		'shipping': ShippingFormatField(),
		'status': StatusFormatField()
	}

	def get_data_fields(self, fields):
		data_fields = []
		for field in fields:
			if field in self.format_fields:
				data_fields += self.format_fields[field].data_fields
		return data_fields
		
	def format(self, records, fields, offsets=None):
		data = [{field: self.format_fields[field].format(rec, offsets.get(rec['_id'], None) if offsets else None) for field in fields} for rec in records]
	
		# HACK: Pango will not markup a string beginning with a tag.
		for record in data:
			for datum in record.itervalues():
				if isinstance(datum, dict):
					if 'markup' in datum:
						markup = datum['markup']
						if markup and isinstance(markup, basestring) and markup[0] == '<':
							datum['markup'] = ' ' + datum['markup']
				elif isinstance(datum, (tuple, list)):
					for row in datum:
						if 'markup' in row:
							markup = row['markup']
							if markup and isinstance(markup, basestring) and markup[0] == '<':
								datum['markup'] = ' ' + row['markup']
		
		return data
	
	
class DefaultSearchHandler:
	
	data_to_lucene_fields = {
		'customer.phones.0.number': [
			'customer.phones.0.number',
			'customer.phones.0.number.ngram',
			'customer.phones.0.number.phrase',
		],
		'customer.phones.1.number': [
			'customer.phones.1.number',
			'customer.phones.1.number.ngram',
			'customer.phones.1.number.phrase',
		],
		'customer.email': [
			'customer.email',
			'customer.email.ngram'
		],
		'customer.name_first': [
			'customer.name_first',
			'customer.name_first.phonetic'
		],
		'customer.name_last': [
			'customer.name_last',
			'customer.name_last.phonetic'
		],
		'order.comments': [
			'order.comments'
		],
		'payments.0.billing.address': [
			'payments.0.billing.address',
			'payments.0.billing.address.phonetic',
			'payments.0.billing.address.phrase'
		],
		'payments.0.billing.city': [
			'payments.0.billing.city',
			'payments.0.billing.city.phonetic'
		],
		'payments.0.billing.company': [
			'payments.0.billing.company',
			'payments.0.billing.company.phonetic',
			'payments.0.billing.company.phrase'
		],
		'payments.0.billing.country': [
			'payments.0.billing.country',
			'payments.0.billing.country.code',
			'payments.0.billing.country.phonetic',
			#'payments.0.billing.country.synonym'
		],
		'payments.0.billing.postal': [
			'payments.0.billing.postal',
			'payments.0.billing.postal.ngram'
		],
		'payments.0.billing.province': [
			'payments.0.billing.province',
			'payments.0.billing.province.code',
			'payments.0.billing.province.phonetic',
			#'payments.0.billing.province.synonym'
		],
		'payments.0.billing.recipient': [
			'payments.0.billing.recipient',
			'payments.0.billing.recipient.phonetic',
			'payments.0.billing.recipient.phrase'
		],
		'platform.po_number': [
			'platform.po_number',
			'platform.po_number.ngram',
			'platform.po_number.phrase'
		],
		'shipping.address.address': [
			'shipping.address.address',
			'shipping.address.address.phonetic',
			'shipping.address.address.phrase'
		],
		'shipping.address.city': [
			'shipping.address.city',
			'shipping.address.city.phonetic'
		],
		'shipping.address.company': [
			'shipping.address.company',
			'shipping.address.company.phonetic',
			'shipping.address.company.phrase'
		],
		'shipping.address.country': [
			'shipping.address.country',
			'shipping.address.country.code',
			'shipping.address.country.phonetic',
			#'shipping.address.country.synonym'
		],
		'shipping.address.postal': [
			'shipping.address.postal',
			'shipping.address.postal.ngram'
		],
		'shipping.address.province': [
			'shipping.address.province',
			'shipping.address.province.code',
			'shipping.address.province.phonetic',
			#'shipping.address.province.synonym'
		],
		'shipping.address.recipient': [
			'shipping.address.recipient',
			'shipping.address.recipient.phonetic',
			'shipping.address.recipient.phrase'
		],
	}
	
	lucene_to_data_fields = {lucene_field: data_field for data_field, lucene_fields in data_to_lucene_fields.iteritems() for lucene_field in lucene_fields}
	
	search_to_lucene_fields = {
		'address': [field for key in [
			'payments.0.billing.address',
			'payments.0.billing.city',
			'payments.0.billing.province',
			'payments.0.billing.country',
			'payments.0.billing.postal',
			'shipping.address.address',
			'shipping.address.city',
			'shipping.address.province',
			'shipping.address.country',
			'shipping.address.postal'
		] for field in data_to_lucene_fields[key]],
		'comments': [field for key in [
			'order.comments'
		] for field in data_to_lucene_fields[key]],
		'email': [field for key in [
			'customer.email'
		] for field in data_to_lucene_fields[key]],
		'id': [field for key in [
			'platform.po_number'
		] for field in data_to_lucene_fields[key]],
		'name': [field for key in [
			'customer.name_first',
			'customer.name_last',
			'payments.0.billing.recipient',
			'shipping.address.recipient'
		] for field in data_to_lucene_fields[key]],
		'phone': [field for key in [
			'customer.phones.0.number',
			'customer.phones.1.number'
		] for field in data_to_lucene_fields[key]]
	}
	
	search_default_fields = [
		'name',
		'address',
		'phone',
		'email'
	]
	
	# TODO: Update sort<->lucene field names
	
	sort_to_lucene_fields = {
		'address': (
			'shipping.address.country.sort',
			'shipping.address.province.sort',
			'shipping.address.city.sort',
		),
		'contact': (
			'customer.phones.0.number.sort',
		),
		'id': (
			'platform.po_number.sort',
		),
		'market': (
			'platform.market.sort',
		),
		'name': (
			'customer.name_first.sort',
			'customer.name_last.sort',
		),
		'payment': (
			'payments.0.amount.sort',
			'payments.0.method.sort',
		),
		'placed': (
			'order.date.sort',
		),
		'shipping': (
			'shipping.status.sort',
		),
		'status': (
			'order.status.sort',
		)
	}
	
	lucene_sort_field_types = {
		'customer.name_first.sort': lucene.SortField.STRING,
		'customer.name_last.sort': lucene.SortField.STRING,
		'customer.phones.0.number.sort': lucene.SortField.STRING,
		'order.date.sort': lucene.SortField.INT,
		'order.status.sort': lucene.SortField.STRING, # TODO: optimize to int.
		'platform.market.sort': lucene.SortField.STRING, # TODO: optimize to int.
		'platform.po_number.sort': lucene.SortField.STRING,
		'payments.0.method.sort': lucene.SortField.STRING, # TODO: optimize to int.
		'payments.0.amount.sort': lucene.SortField.FLOAT,
		'shipping.address.city.sort': lucene.SortField.STRING,
		'shipping.address.country.sort': lucene.SortField.STRING,
		'shipping.address.province.sort': lucene.SortField.STRING,
		'shipping.status.sort': lucene.SortField.STRING, # TODO: optimize to int.
	}
	

	def __init__(self):
		self.analyzer = BasicSearchAnalyzer()
		self.sort_cache = {}
	
	@defer.inlineCallbacks
	def search(self, searcher, query, pagination, sort=None, reader=None, debug=False):
		"""
		
		searcher
		
		query
		
		pagination (``dict``) contains: *start_index* and *page_size*.
		*start_index* (``int``) is the record (not page) offset. *page_size*
		(``int``) is the number of records per page.
		
		sort (``dict``) is optionally used for sorting the search results.
		Default is ``None``. If this is set, it must contain: *field* and
		*direction*. *field* (``str``) is the field to sort on. *direction*
		(``int``) is the direction to sort: ``1`` for ascending, and ``-1``
		for descending.
		
		
		reader
		
		Returns a deferred (``twisted.internet.defer.Deferred``) containing:
		the search result (``dict``). The search result contains:
		*mongo_ids*, *total_hits*, and optionally *debug* if the *debug*
		argument was set. *mongo_ids* (``list``) contains the Mongo
		``ObjectId``s for the matched records. *total_hits* (``int``) is the
		number of records that matched the query. *debug* (``dict``)
		contains miscellaneous debugging information.
		"""
		start_index = pagination['start_index']
		page_size = pagination['page_size']
		
		if not reader:
			reader = searcher.getIndexReader()
			
		if sort:
			if not isinstance(sort, dict):
				raise TypeError("sort:%r is not a dict." % sort)
			sort_field = sort['field']
			if not isinstance(sort_field, str):
				raise TypeError("sort[field]:%r is not a str." % sort_field)
			elif not sort_field:
				raise ValueError("sort[field]:%r cannot be empty." % sort_field)
			sort_dir = sort['direction']
			if not isinstance(sort_dir, int):
				raise TypeError("sort[direction]:%r is not an int." % sort_dir)
			elif sort_dir != 1 and sort_dir != -1:
				raise ValueError("sort[direction]:%r is not 1 or -1." % sort_dir)
				
			# Create sorter.
			sort_key = tuple([(field, sort_dir == -1) for field in self.sort_to_lucene_fields[sort_field]])
			if sort_key in self.sort_cache:
				sorter = self.sort_cache[sort_key]
			else:
				sorter = self.sort_cache[sort_key] = lucene.Sort([lucene.SortField(field, self.lucene_sort_field_types[field], field_dir) for field, field_dir in sort_key])
		else:
			sorter = None
			
		if query:
			if isinstance(query, basestring):
				search_query = [(query, [lucene_field for data_field in self.search_default_fields for lucene_field in self.search_to_lucene_fields[data_field]])]
			elif isinstance(query, dict):
				search_query = [(search_text, self.search_to_lucene_fields[data_field]) for data_field, search_text in query.iteritems()]
			else:
				raise TypeError("query:%r is not a string, dict or None." % query)
			
			result = yield threads.deferToThread(self._search_dtt,
				searcher=searcher,
				reader=reader,
				analyzer=self.analyzer,
				sorter=sorter,
				query=search_query,
				skip=start_index,
				limit=page_size,
				debug=debug
			)
	
		else:
			result = yield threads.deferToThread(self._search_none_dtt,
				searcher=searcher,
				sorter=sorter,
				skip=start_index,
				limit=page_size,
				debug=debug
			)
		
		result_offsets = result.get('offsets', None)
		if result_offsets:
			# Merge field offsets.
			return_offsets = result['offsets'] = {}
			for mongo_id, lucene_offsets in result_offsets.iteritems():
				field_offsets = return_offsets[mongo_id] = {}
				for lucene_field, offsets in lucene_offsets.iteritems():
					base_field = self.lucene_to_data_fields[lucene_field]
					if base_field in field_offsets:
						field_offsets[base_field] += offsets
					else:
						field_offsets[base_field] = offsets
				for base_field, offsets in field_offsets.iteritems():
					field_offsets[base_field] = merge_ranges(field_offsets[base_field])
			
			# XXX
			if debug:
				print "OFFSETS"
				pprint.pprint(return_offsets)
			
		defer.returnValue(result)
	
	@staticmethod
	def _search_dtt(searcher, reader, analyzer, query, skip, limit, sorter=None, debug=False):
		# Make sure the thread is attached for lucene.
		jcc_env = lucene.getVMEnv()
		if not jcc_env.isCurrentThreadAttached():
			jcc_env.attachCurrentThread()

		# Parse query.
		if debug: parse_start = time.time()
		queries = lucene.BooleanQuery()
		for text, fields in query:
			parser = lucene.MultiFieldQueryParser(lucene.Version.LUCENE_CURRENT, fields, analyzer)
			queries.add(lucene.BooleanClause(lucene.QueryParser.parse(parser, text), lucene.BooleanClause.Occur.SHOULD))
		if debug: parse_time = time.time() - parse_start
		
		# Perform query.
		if debug: search_start = time.time()
		top_docs = searcher.search(queries, skip + limit, sorter) if sorter else searcher.search(queries, skip + limit)
		if debug: search_time = time.time() - search_start
		
		score_docs = top_docs.scoreDocs
		top_score = score_docs[0].score if len(score_docs) else None
		
		# Tokenize each field.
		if debug: token_start = time.time()
		all_fields = []
		field_to_tokens = {}
		for text, fields in query:
			tokens = stream_to_sequence(analyzer.tokenStream(None, lucene.StringReader(text)))
			for field in fields:
				field_to_tokens[field] = tokens[:]
		all_fields = field_to_tokens.keys()
		if debug: token_time = time.time() - token_start
	
		if debug: iter_start = time.time()
		mongo_ids = []
		doc_offsets = {}
		for i in xrange(skip, min(len(score_docs), skip + limit)):
			doc_id = score_docs[i].doc
			
			# Get mongo ID.
			mongo_id = txmongo.ObjectId(searcher.doc(doc_id)['mongo_id'])
			mongo_ids.append(mongo_id)
			
			# Determine where the query matched the document fields.
			# .. TODO: This logic seems to take ~70% (20-60ms for 100 records)
			#    of the time in this loop.
			#
			# .. TODO: I am not getting any offsets from here.
			#
			field_offsets = {}
			for field in all_fields:
				freq_vec = reader.getTermFreqVector(doc_id, field)
				if not freq_vec or not lucene.TermPositionVector.instance_(freq_vec):
					continue
				pos_vec = lucene.TermPositionVector.cast_(freq_vec)
				offsets = [(off.getStartOffset(), off.getEndOffset()) for term in field_to_tokens[field] for off in pos_vec.getOffsets(pos_vec.indexOf(term))]
				if offsets:
					field_offsets[field] = offsets
			doc_offsets[mongo_id] = field_offsets
		
		#mongo_ids = [txmongo.ObjectId(searcher.doc(score_docs[i].doc)['mongo_id']) for i in xrange(skip, min(len(score_docs), skip + limit))]
		if debug: iter_time = time.time() - iter_start
	
		# Return result.
		result = {
			'mongo_ids': mongo_ids,
			'offsets': doc_offsets,
			'total_hits': top_docs.totalHits,
			'top_score': top_score
		}
		if debug:
			result['debug'] = {
				'parse_time': parse_time,
				'search_time': search_time,
				'token_time': token_time,
				'iter_time': iter_time
			}
		return result

	@staticmethod
	def _search_none_dtt(searcher, skip, limit, sorter=None, debug=False):
		# Make sure the thread is attached for lucene.
		jcc_env = lucene.getVMEnv()
		if not jcc_env.isCurrentThreadAttached():
			jcc_env.attachCurrentThread()
		
		if sorter:
			# Perform query.
			if debug: search_start = time.time()
			top_docs = searcher.search(lucene.MatchAllDocsQuery(), skip + limit, sorter) if sorter else searcher.search(lucene.MatchAllDocsQuery(), skip + limit)
			if debug: search_time = time.time() - search_start
		
			score_docs = top_docs.scoreDocs
			total_hits = top_docs.totalHits
		
			# Get mongo IDs.
			if debug: iter_start = time.time()
			mongo_ids = [txmongo.ObjectId(searcher.doc(score_docs[i].doc)['mongo_id']) for i in xrange(skip, min(len(score_docs), skip + limit))]
			if debug: iter_time = time.time() - iter_start
			
		else:
			if debug: search_time = 0
			
			max_doc = searcher.maxDoc()
			total_hits = max_doc
		
			# Get mongo IDs.
			if debug: iter_start = time.time()
			mongo_ids = [txmongo.ObjectId(searcher.doc(i)['mongo_id']) for i in xrange(skip, min(max_doc, skip + limit))]
			if debug: iter_time = time.time() - iter_start
		
		# Return result.
		result = {
			'mongo_ids': mongo_ids,
			'total_hits': total_hits,
			'top_score': None
		}
		if debug:
			result['debug'] = {
				'search_time': search_time,
				'iter_time': iter_time
			}
		return result


class OrderSearch(pbplugins.EasyReferenceable):
	
	search_handlers = {
		'default': DefaultSearchHandler()
	}
	
	data_formatters = {
		'main': MainDataFormatter()
	}
	
	def clientConnectionMade(self, app):
		"""
		Called when a client instantiates this class.
		
		*app* (``PbApplication``) is the application that created us.
		
		Returned value is ignored, but it may be a deferred
		(``twisted.internet.defer.Deferred``).
		"""
		self.searcher = app.search_searcher
		self.reader = self.searcher.getIndexReader()
		self.order_tb = app.search_order_tb
		
	@defer.inlineCallbacks
	def search(self, query):
		"""
		Perform a search.
		
		*query* (``dict``) is the search query.
		
		Returns a deferred (``twised.internet.defer.Deferred``) containing:
		the search result (``dict``).
		"""
		
		'''
		This method needs to do the following:
		- Send query to handler.
		- Fetch data for matched records.
		- Format data.
		- Return response.
		'''
		total_start = time.time()
		if not isinstance(query, dict):
			raise TypeError("query:%r is not a dict." % query)
		
		debug = bool(query.get('debug', False))
			
		pagination = query['pagination']
		if not isinstance(pagination, dict):
			raise TypeError("pagination:%r is not a dict." % pagination)
		start_index = pagination['start_index']
		if not isinstance(start_index, int):
			raise TypeError("pagination[start_index]:%r is not an int." % start_index)
		elif start_index < 0:
			raise ValueError("pagination[start_index]:%r cannot be less than 0." % start_index)
		page_size = pagination['page_size']
		if not isinstance(page_size, int):
			raise TypeError("pagination[page_size]:%r is not an int." % page_size)
		elif page_size < 1:
			raise ValueError("pagination[page_size]:%r cannot be less than 1." % page_size)
		
		sort = query.get('sort', None)
		if sort:
			if not isinstance(sort, dict):
				raise TypeError("sort:%r is not a dict." % sort)
			sort_field = sort['field']
			if not isinstance(sort_field, str):
				raise TypeError("sort[field]:%r is not a str." % sort_field)
			elif not sort_field:
				raise ValueError("sort[field]:%r cannot be empty." % sort_field)
			sort_dir = sort['direction']
			if not isinstance(sort_dir, int):
				raise TypeError("sort[direction]:%r is not an int." % sort_dir)
			elif sort_dir != 1 and sort_dir != -1:
				raise ValueError("sort[direction]:%r is not 1 or -1." % sort_dir)
			
		fields = query['fields']
		
		search = query.get('search', None) or {}
		search_handler = self.search_handlers[search.get('handler', None) or 'default']
		search_query = search.get('query', None)
		
		data_formatter = self.data_formatters['main']
		
		# Send query to handler.
		if debug: search_start = time.time()
		search_result = yield search_handler.search(self.searcher, search_query, pagination, sort=sort, reader=self.reader, debug=debug)
		if debug: search_time = time.time() - search_start
		
		# Get data.
		if debug: data_mongo_start = time.time()
		data_fields = data_formatter.get_data_fields(fields)
		records = yield self.order_tb.find({
			'_id': {'$in': search_result['mongo_ids']}
		}, fields=data_fields)
		if debug: data_mongo_time = time.time() - data_mongo_start
		
		# Send records to formatter.
		if debug: data_format_start = time.time()
		record_order = {oid: pos for pos, oid in enumerate(search_result['mongo_ids'])}
		records = sorted(records, key=lambda x: record_order[x['_id']])
		data = data_formatter.format(records, fields, offsets=search_result.get('offsets', None))
		if debug: data_format_time = time.time() - data_format_start
		
		# Return result.
		top_score = search_result['top_score']
		total_hits = search_result['total_hits']
		page = start_index // page_size + 1
		page_count = int(math.ceil(total_hits / page_size))
		
		result = {
			'data': data,
			'pagination': {
				'page': page, 
				'page_count': page_count,
				'page_size': page_size,
				'start_index': start_index
			},
			'search': {
				'top_score': top_score,
				'total_hits': total_hits
			}
		}
		if debug:
			search_result['debug']['total_time'] = search_time
			result['debug'] = {
				'data': {
					'mongo_time': data_mongo_time,
					'format_time': data_format_time,
					'total_time': data_mongo_time + data_format_time
				},
				'search': search_result['debug'],
				'total_time': time.time() - total_start
			}
		defer.returnValue(result)

from twisted.spread import pb
from twisted.python import log
from twisted.internet import defer, threads
from twisted.internet.threads import deferToThread

from pbplugins import EasyReferenceable

import pymongo
import tst
import pprint

mongo_host='HOL-SRV-DB00'
class TernarySearchTest(EasyReferenceable):
	
	@defer.inlineCallbacks
	def clientConnectionMade(self, app):
		'''
		Called when the client instantiates this class ...
		Do whatever you want in here.
		It's ok to return deferreds from here.
		'''
		self.search = PhoneTST()
		yield deferToThread(self.search.build_tst)

	
	@defer.inlineCallbacks
	def get_completion(self, field, search):
		'''
		Get completion suggestions
		
		Returns: [list] 
		[
			(markup, value, key),
			...
		]
		'''
		result = yield deferToThread(self.search.get_matches_markup, search)
		defer.returnValue( result )

	def message( self ):
		'''
		Return a test string, letting the client know you're working
		'''
		return "TernarySearchTest class working!"
		
		
class PhoneTST():
	'''
	This is a working class that uses PyTST to suggest possible phone
	numbers.

	Rules:
	------------
	*There are two sets of rules one for international and one for national.
	*National rules are preferred unless a '+' is typed in.
	*The results use a "mix-in" approach to offer the best possibility of providing
	 a relevant result as the user types

	A search for "624" should yield:
		624-151-2187         < Prefix (National)
		574-624-5722         < Prefix (National Ignoring Area Code)
		212-162-4188         < Substring (National)
		+46 244 182 10 11    < Substring (Intl)
		
	If a + is typed first, logic assumes international number is being
	searched first.

	Note in the example above that a prefix match is preferred first. Then a 
	prefix match ignoring area code, and then a substring match.
	'''
	def build_tst(self):
		'''
		Build the Ternary Search Tree in memory
		'''
		print "\nBuilding Search Tree..."
		mongo = pymongo.Connection(mongo_host)
		db = mongo['orders']
		collection = db['mysql_web_orders']

		self.tree = tree = tst.TST()

		docs = collection.find({})
		print "Adding %s documents" % (docs.count())#, stringsfile)
		for idx, order in enumerate(docs):
			if(idx == 0):
				pprint.pprint(order)
			orderid = str(order['_id'])
			for key in ('daytime_phone', 'evening_phone'):
				n = order['customer'].get(key, None)
				if(n):
					#Cleanup the phone numbers
					n = n.replace("-", "")
					n = n.replace(" ", "")
					n = n.replace(".", "")
					n = n.replace("(", "")
					n = n.replace(")", "")
					n = n.strip()
					if n != "":
						if(n[0] != '+' and len(n) > 10 and (n[0] == '1' and len(n) == 11)):
							#If the number is American International Dialing rules, with a 1, get rid of it
							n = n[1:]
						elif(n[0] != '+' and len(n) < 10):
							#If the number is american dialing rules and less 10 digits ignore it
							continue
						elif(n[0] != '+' and len(n) > 10 ):
							#If the number is more than American dialing rules and doesn't begin with a +
							#n = "+"+n
							continue #IGNORE IT
					
						if(n[0] != '+'):
							#Conform ALL number formats to INTL
							n = '+01' + n
						# Append to the search tree
						tree[n] = orderid  #orderid should become customer_id 
		
	def get_matches_markup(self, search):
		'''
		Get matches with GTK markup applied to them
		'''
		matches = self.get_matches(search)
		print matches
		for idx,match in enumerate(matches):
			matches[idx] = (self.markup_match(search, match[0]), match[1])
			#match.insert(0, self.markup_match(search, match[0]))
		return matches
		
	def markup_match(self, search, value):
		'''
		"Marks up" the longest matching string in the value passed
		'''
		return value
		
	def get_matches(self, search):
		'''
		Get Type-Ahead / Autocomplete matches
		
		Returns List of Tuples
		[ (value, docid), ...]
		'''
		tree = self.tree
		
		maxmatches = 6
		usage = (3, 3, 3, 2, 2)
		match = []
		n = search
		if(not n):
			return []
		n = n.replace("-", "")
		n = n.replace(" ", "")
		n = n.replace(".", "")
		n = n.replace("(", "")
		n = n.replace(")", "")
		search = n.strip()
		
		if(n[0] != '+'):
			#National Search

			#Search on exact prefix (best/ideal match)
			match.append( tree.walk(None, tst.DictAction(), '+01'+search) ) # < Natl Prefix Search
			
			if(len(search) >= 9):
				#If the search string is greater than or equal to 9 digits
				#this means the user may have typed the number very close to correct
				#If they are just 1 character off do we still want to find the number?
				#YES - so you use close_match()
				maxdistance = 11 - len(search)  #This is the levenshtein distance Adding, Removing, and Moving characters all cost 1 point
				match.append( tree.close_match('+01'+search, maxdistance, None, tst.DictAction()) )
			else:
				match.append({})
			 
			match.append( tree.match('+01???' + search + '*', None, tst.DictAction()) )         # < Natl Prefix Search Area Code Excluded
			match.append( tree.match('+??' + search + '*', None, tst.DictAction()) )            # < Intl Prefix Match
			#Last and least... we want to do a generic substring search
			match.append( tree.match( '*'+search+'*', None, tst.DictAction()) )
			
		else:
			#International Search
			match.append( tree.match('???' + search + '*', None, tst.DictAction()) )            # < Intl Prefix Match
			match.append( tree.match('+??' + search[3:] + '*', None, tst.DictAction()) )        # < Intl Prefix, Country-Code wilcard
			match.append( tree.match( '*'+search[3:]+'*', None, tst.DictAction()) )             # < Substring
			
		match_vals = []
		numbers = set()
		for idxa, m in enumerate(match):
			if(len(match_vals) >= maxmatches):
				break
			keys = m.keys()
			keys.sort()
			if(not len(keys)):
				continue
			for idxb in range(0, min(usage[idxa], len(keys))):
				if(len(match_vals) >= maxmatches):
					break
				nbr = keys[idxb]
				if(nbr in numbers):
					continue #NO DUPLICATES!
				numbers.add(nbr)
				v = (nbr, m[nbr][1] ) # [1] Contains the mongo id
				match_vals.append(v)
	
		return match_vals
		

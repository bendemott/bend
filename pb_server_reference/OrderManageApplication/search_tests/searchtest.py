from twisted.spread import pb
from twisted.python import log
from twisted.internet import defer, threads
from twisted.internet.threads import deferToThread

from pbplugins import EasyReferenceable

import phonenumbers #For formatting phone number strings
import tsttest

#For the test search data
import pymongo
import random

import glib #To properly escape markup text

states = {
	"Alabama" : "AL",
	"Alaska" : "AK",
	"Arizona" : "AZ",
	"Arkansas" : "AR",
	"California" : "CA",
	"Colorado" : "CO",
	"Connecticut" : "CT",
	"Delaware" : "DE",
	"Florida" : "FL",
	"Georgia" : "GA",
	"Hawaii" : "HI",
	"Idaho" : "ID",
	"Illinois" : "IL",
	"Indiana" : "IN",
	"Iowa" : "IA",
	"Kansas" : "KS",
	"Kentucky" : "KY",
	"Louisiana" : "LA",
	"Maine" : "ME",
	"Maryland" : "MD",
	"Massachusetts" : "MA",
	"Michigan" : "MI",
	"Minnesota" : "MN",
	"Mississippi" : "MS",
	"Missouri" : "MO",
	"Montana" : "MT",
	"Nebraska" : "NE",
	"Nevada" : "NV",
	"New Hampshire" : "NH",
	"New Jersey" : "NJ",
	"New Mexico" : "NM",
	"New York" : "NY",
	"North Carolina" : "NC",
	"North Dakota" : "ND",
	"Ohio" : "OH",
	"Oklahoma" : "OK",
	"Oregon" : "OR",
	"Pennsylvania" : "PA",
	"Rhode Island" : "RI",
	"South Carolina" : "SC",
	"South Dakota" : "SD",
	"Tennessee" : "TN",
	"Texas" : "TX",
	"Utah" : "UT",
	"Vermont" : "VT",
	"Virginia" : "VA",
	"Washington" : "WA",
	"West Virginia" : "WV",
	"Wisconsin" : "WI",
	"Wyoming" : "WY",
}

#swap keys, vals
state_abbrev = dict(zip(states.values(), states.keys()))

RED = "#9D0000"

class SearchTests(EasyReferenceable):

	#@defer.inlineCallbacks
	def clientConnectionMade(self, app):
		'''
		Called when the client instantiates this class ...
		Do whatever you want in here.
		It's ok to return deferreds from here.
		'''
		#This is needed to get phone entry-completion working.
		#Currently commented out because it takes forever to load the client
		#Initialization of the TST should be made when server is initialized!
		#self.search = tsttest.PhoneTST()
		#yield deferToThread(self.search.build_tst)
		self.search = app.phone_tst


	@defer.inlineCallbacks
	def search(self, query={}):
		'''
		'''
		defer.returnValue( False )
		
	@defer.inlineCallbacks
	def search_advanced(self, query={}):
		'''
		'''
		defer.returnValue( False )

	def message( self ):
		'''
		Return a test string, letting the client know you're working
		'''
		return "SearchTest class working!"
	

	def get_entry_completion_data( self, mode, search ):
		'''
		This callback generates the data to apply to the gtk.EntryCompletion
		widget's listmodel, so that it will display choices based on the search
		string typed in so far
		'''
		formatted_results = None
		if mode == 'phone':
			search_results =  self.search.get_matches_markup(search)
			formatted_results = search_results
			formatted_results = self._format_phone_data(formatted_results)
			place_holder = formatted_results
			for idx,search_result in enumerate(place_holder):
				result = search_result[0]
				result = self._generate_markup( result, search )
				formatted_results[idx] = [result, search_results[idx][0]]
		return formatted_results

	def _format_phone_data( self, search ):
		'''
		Generate data to display for phone number searches.
		
		Args:
			search[list]: the search results
		'''
		"""
		search= [
			['+16163998074'],
			['+16164222624'],
			['+16169316644'],
			['+4407700954321']
		]
		"""
		for idx,result in enumerate(search):
			number = result[0]
			if number.startswith( "+01"):
				number = "+1" + number[3:]
			try:
				format = phonenumbers.parse( number )
				if format.country_code is 1:
					format_number = phonenumbers.format_number( format, phonenumbers.PhoneNumberFormat.NATIONAL )
				else:
					format_number = phonenumbers.format_number( format, phonenumbers.PhoneNumberFormat.INTERNATIONAL )
			except:
				format_number = number
			
			search[idx] = [format_number]
		return search

	def _generate_markup(self, number,search):
		'''
		Creates a pango markup string out of the given number by
		bolding the search substring within the properly formatted number
		'''
		new_search = ''
		for idx,char in enumerate(search):
			if char.isdigit():
				new_search += char
		search = new_search
				
		print "SEARCH:%s"%search
		start_idx = None #The start index of the substring within the string
		search_idx = 0#The index pointing to the current character of the search string you're looking for
		end_idx = None#The end index of the substring within the string
		for idx, char in enumerate(number):
			#We only care about the numbers, ignore the white space and formatting characters
			if char.isdigit():
				if search[search_idx] == char:
					if search_idx == 0:
						#Found first char, set start_idx
						start_idx = idx

					search_idx+=1
					if search_idx == len( search):
						#Found the substring, set the end index and exit loop
						end_idx = idx+1
						break
				else:
					search_idx = 0
					start_idx = None
	
		#If either start or end index is not set, then didn't find the substring
		#within the string, so just return the original
		if start_idx is None or end_idx is None:
			return number
	
		#Return the string, adding the <b> markup at the start and end indices
		return number[0:start_idx] + "<b>" + number[start_idx:end_idx] + "</b>" + number[end_idx:]


	def get_data_from_mongo(self):
		'''
		Connects to the mongo database `pyfullfill` to the collection `orders_review`
		in order to get sample data to populate the search_results treeview.
	
		This function returns the data created that will make up the liststore
		
		NOTE: this is the deprecated test version for the old ConfigTreeView
		implementation
		'''
		
		mongo = pymongo.Connection( "HOL-SRV-DB00" )
		db = mongo['orders']
		collection = db['mysql_web_orders']

		mongo_data = []
		for idx,item in enumerate(collection.find({}).limit(500)):
			row = [str(item['_id']), random.choice([0,1,2])]
			
			#Status----------------------------------------------------------------------------
			statuses = ['Backordered', 'Sourcing', 'Sourcing(2 Items)', 'Completed', '<span foreground="%s">Failed</span>'%RED, 'Completed', 'Completed', 'Completed', 'Completed']
			last_status = statuses[random.randint( 0, len( statuses)-1)]
			current_status = statuses[random.randint( 0, len( statuses)-1)]
			title_string = ''
			status_string = ''
			if last_status == current_status:
				title_string = 'Current Status: '
				status_string = current_status
			else:
				title_string = 'Last Status: \nCurrent Status: '
				status_string = last_status + '\n' + current_status
			row.append( title_string )
			row.append( status_string )
			#----------------------------------------------------------------------------------
			
			#Name------------------------------------------------------------------------------
			cust_name = glib.markup_escape_text(item.get('customer',{}).get('name_text', '?') )
			ship_name = glib.markup_escape_text(item.get('shipping',{}).get('first','?')) + ' ' + glib.markup_escape_text( item.get('shipping',{}).get('last','?'))
			billing = item.get('payments',[])[0].get('billing',{})
			billing_name = glib.markup_escape_text(billing.get('first','?')) + ' ' + glib.markup_escape_text(billing.get('last', '?'))
			
			name_string = cust_name
			ship_string = ''
			billing_string = ''
			
			if ship_name.strip().lower() != cust_name.strip().lower():
				ship_string = '\n<b>Ship To:</b> ' + ship_name
			if billing_name.strip().lower() != cust_name.strip().lower() and billing_name.strip().lower() != ship_name.strip().lower():
				billing_string = '\n<b>Billing:</b> ' + billing_name
			
			row.append( name_string + ship_string + billing_string )
			#----------------------------------------------------------------------------------
			
			#Address
			#This is going to show the last known customer address, and if different
			#than that address, billing and shipping addresses will be shown
			shipping_addr = self.format_address( item.get('shipping', {} ) )
			billing_addr = self.format_address( item.get('payments',[])[0].get('billing',{}) )

			address_string = shipping_addr		
			if shipping_addr.strip().lower() != billing_addr.strip().lower():
				address_string += '\n<b>Billing:</b> ' + billing_addr
			
			row.append( address_string )
			if name_string == 'Tomer Shohat':
				print item
			#----------------------------------------------------------------------------------

			#Determine contact display
			#Displays one of the options in contact_list, listed in order of importance
			contact_list = ['email', 'daytime_phone', 'evening_phone']
			contact_str = ""
			for option in contact_list:
				contact_str = item.get('customer',{}).get( option, '')
				if contact_str != '':
					if 'phone' in option:
						contact_str = self._format_phone_number( contact_str )
					break
			row.append( glib.markup_escape_text(contact_str) )
			#----------------------------------------------------------------------------------

			#Payment--Summary of payment method used and the status
			payment = item['payments'][0]
			payment_method = payment.get('method_text','')
			if payment_method == '' or payment_method == None:
				rands = ['Visa', 'GiftCard', 'MasterCard', 'AmericanExpress', 'PayPal']
				payment_method = rands[random.randint( 0, len(rands)-1)]
			payment_str = ' $' + str(payment.get('total', '?'))
			row.append( payment_method )
			row.append( payment_str )
			#---------------------------------------------------------------------------------
			
			#Shipping--Summary of shipped method/status (Since no data, make up random shit)
			shipping_methods = ['Fedex Ground', 'USPS', 'UPSGround', '<span foreground="%s">Not Shipped</span>'%RED]
			shipping_dates =  ['1/28/2012', '2/3/2012', '12/23/2011', '3/3/2012', '1/29/2012']

			shipping = shipping_methods[random.randint(0,len( shipping_methods)-1)]
			if shipping  != shipping_methods[3]:
				shipping += '\n' + shipping_dates[random.randint(0,len(shipping_dates)-1)]

			row.append( shipping )
			#--------------------------------------------------------------------------------
			
			#Comments--Again, just generating random comments
			people = ['Misty', 'TJ', 'Mike', 'Kara', 'Josh', 'Brad']
			comments = ['Left voicemail', 'Filed complaint', 'Fixed Shipping', 'Fixed Billing', 'Gave compliment']
			dates = ['Yesterday', 'An hour ago', 'Last week', 'A month ago', '1/23/2012']
			
			#Simulate the occurence of a comment in the 'Comments' column
			comment_choice = [None]*50
			comment_choice.append( 'Yes' )
			comment_str = ''
			if random.choice( comment_choice ) == 'Yes':
				comment_str = dates[random.randint(0,len(dates)-1)] + " " + people[random.randint(0,len(people)-1)] + ":" + comments[random.randint(0,len(comments)-1)]

			row.append( comment_str )
			#---------------------------------------------------------------------------------
			#Placed--The date of the order
			row.append( str( item['order']['date'] ))
			#---------------------------------------------------------------------------------
			
			mongo_data.append( row )

		return mongo_data

	def get_new_data(self ):
		'''
		Connects to the mongo database `pyfullfill` to the collection `orders_review`
		in order to get sample data to populate the search_results treeview.
	
		This function returns the data created that will make up the liststore
		NOTE: This function uses the new kind of 
		'''
		
		mongo = pymongo.Connection( "HOL-SRV-DB00" )
		db = mongo['orders']
		collection = db['mysql_web_orders']

		mongo_data = []
		for idx,item in enumerate(collection.find({}).limit(500)):
			row = {
				'id': str(item['_id']),
				'market': {
					'pixbuf': random.choice(['ebay','amazon','www']),
				},

			}
			
			#Status----------------------------------------------------------------------------
			statuses = ['Backordered', 'Sourcing', 'Sourcing(2 Items)', 'Completed', '<span foreground="%s">Failed</span>'%RED, 'Completed', 'Completed', 'Completed', 'Completed']
			last_status = statuses[random.randint( 0, len( statuses)-1)]
			current_status = statuses[random.randint( 0, len( statuses)-1)]
			title_string = ''
			status_string = ''
			if last_status == current_status:
				title_string = 'Current Status: '
				status_string = current_status
			else:
				title_string = 'Last Status: \nCurrent Status: '
				status_string = last_status + '\n' + current_status
			row['status'] = [{'markup': title_string}, {'markup': status_string}]
			#----------------------------------------------------------------------------------
			
			#Name------------------------------------------------------------------------------
			cust_name = glib.markup_escape_text(item.get('customer',{}).get('name_text', '?') )
			ship_name = glib.markup_escape_text(item.get('shipping',{}).get('first','?')) + ' ' + glib.markup_escape_text( item.get('shipping',{}).get('last','?'))
			billing = item.get('payments',[])[0].get('billing',{})
			billing_name = glib.markup_escape_text(billing.get('first','?')) + ' ' + glib.markup_escape_text(billing.get('last', '?'))
			
			name_string = cust_name
			ship_string = ''
			billing_string = ''
			
			if ship_name.strip().lower() != cust_name.strip().lower():
				ship_string = '\n<b>Ship To:</b> ' + ship_name
			if billing_name.strip().lower() != cust_name.strip().lower() and billing_name.strip().lower() != ship_name.strip().lower():
				billing_string = '\n<b>Billing:</b> ' + billing_name
			
			row['name'] = {'markup': name_string + ship_string + billing_string}
			#----------------------------------------------------------------------------------
			
			#Address
			#This is going to show the last known customer address, and if different
			#than that address, billing and shipping addresses will be shown
			shipping_addr = self.format_address( item.get('shipping', {} ) )
			billing_addr = self.format_address( item.get('payments',[])[0].get('billing',{}) )

			address_string = shipping_addr		
			if shipping_addr.strip().lower() != billing_addr.strip().lower():
				address_string += '\n<b>Billing:</b> ' + billing_addr
			
			row['address'] = {'markup': address_string}
			#----------------------------------------------------------------------------------

			#Determine contact display
			#Displays one of the options in contact_list, listed in order of importance
			contact_list = ['email', 'daytime_phone', 'evening_phone']
			contact_str = ""
			for option in contact_list:
				contact_str = item.get('customer',{}).get( option, '')
				if contact_str != '':
					if 'phone' in option:
						contact_str = self._format_phone_number( contact_str )
					break
			row['contact'] = {'markup': glib.markup_escape_text(contact_str)}
			#----------------------------------------------------------------------------------

			#Payment--Summary of payment method used and the status
			payment = item['payments'][0]
			payment_method = payment.get('method_text','')
			if payment_method == '' or payment_method == None:
				rands = ['Visa', 'GiftCard', 'MasterCard', 'AmericanExpress', 'PayPal']
				payment_method = rands[random.randint( 0, len(rands)-1)]
			payment_str = ' $' + str(payment.get('total', '?'))
			row['payment'] = [{'markup': payment_method},{'markup':payment_str}]
			#---------------------------------------------------------------------------------
			
			#Shipping--Summary of shipped method/status (Since no data, make up random shit)
			shipping_methods = ['Fedex Ground', 'USPS', 'UPSGround', '<span foreground="%s">Not Shipped</span>'%RED]
			shipping_dates =  ['1/28/2012', '2/3/2012', '12/23/2011', '3/3/2012', '1/29/2012']

			shipping = shipping_methods[random.randint(0,len( shipping_methods)-1)]
			if shipping  != shipping_methods[3]:
				shipping += '\n' + shipping_dates[random.randint(0,len(shipping_dates)-1)]

			row['shipping'] = {'markup': shipping}
			#--------------------------------------------------------------------------------
			
			#Comments--Again, just generating random comments
			people = ['Misty', 'TJ', 'Mike', 'Kara', 'Josh', 'Brad']
			comments = ['Left voicemail', 'Filed complaint', 'Fixed Shipping', 'Fixed Billing', 'Gave compliment']
			dates = ['Yesterday', 'An hour ago', 'Last week', 'A month ago', '1/23/2012']
			
			#Simulate the occurence of a comment in the 'Comments' column
			comment_choice = [None]*50
			comment_choice.append( 'Yes' )
			comment_str = ''
			if random.choice( comment_choice ) == 'Yes':
				comment_str = dates[random.randint(0,len(dates)-1)] + " " + people[random.randint(0,len(people)-1)] + ":" + comments[random.randint(0,len(comments)-1)]

			row['comments'] = {'markup': comment_str}
			#---------------------------------------------------------------------------------
			#Placed--The date of the order
			row['placed'] = {'markup':str( item['order']['date'] ) }
			#---------------------------------------------------------------------------------
			
			mongo_data.append( row )

		return mongo_data
		
	def format_address( self, address ):
		'''
		Format the address for display in the search results
		`address` should contain the fields: 'country_text', 'province_text', 'city_text'
		
		If the Country is 'US', then format the string to display the city name and the 2-digit state abbrev
		Else, return either the province( first) or a city(if no province) and the country( 3 char ISO code)
		'''
		country = address['country_text']
		if country.strip().lower() in ['us', 'usa', 'u.s.', 'u.s.a']:
			city = address.get('city_text','?').title()
			state = address.get('province_text', '??').upper() 
			state = state_abbrev.get( state, None )
			
			if not state:
				state = address['province_text'] 
				state.ljust(2) #ensure it's 2 chars in length
				found = False
				for name in states.keys():
					if name.lower() in state.lower():
						state = name
						found = True
						break;
				if not found and state_abbrev.get( state[0:2].upper(), None):
					state = state_abbrev[state[0:2].upper()]
				
			return "%s, <b>%s</b>" % (glib.markup_escape_text(city), glib.markup_escape_text(state))
			
		else:
			#Province, Country OR
			#City, Country( if province isn't found )
			province = address['province_text']
			if len(province) and not province[0].isupper():
				province = province.title()
			elif not province:
				province = address['city_text'].title() 
			country = address['country_text'].upper()
			
			return '%s, <b>%s</b>' % (glib.markup_escape_text(province), glib.markup_escape_text(country))
			
			
	def _format_phone_number( self, number ):
		'''
		Format a phone number string.
		If it's a US number, format it in US format, otherwise, make it international format
		'''
		if(number):
			#Cleanup the phone numbers
			number = number.replace("-", "")
			number = number.replace(" ", "")
			number = number.replace(".", "")
			number = number.replace("(", "")
			number = number.replace(")", "")
			
			if number.startswith( '0'):
				#Replace all leading zero's with a single +
				number = number.lstrip('0')
				number = "+" + number
			if(number[0] != '+' and len(number) > 10 and (number[0] == '1' and len(number) == 11)):
				#If the number is American International Dialing rules, with a 1, get rid of it
				number = number[1:]
			elif(number[0] != '+' and len(number) < 10):
				#If the number is american dialing rules and less 10 digits ignore it
				pass
			elif(number[0] != '+' and len(number) > 10 ):
				#If the number is more than American dialing rules and doesn't begin with a +
				#n = "+"+n
				pass
				
			if(number[0] != '+'):
				#Conform ALL number formats to INTL
				number = '+01' + number
		if number.startswith( '+01' ):
			number = '+1' + number[3:]
		try:
			format = phonenumbers.parse( number )
			if format.country_code is 1:
				format_number = phonenumbers.format_number( format, phonenumbers.PhoneNumberFormat.NATIONAL )
			else:
				format_number = phonenumbers.format_number( format, phonenumbers.PhoneNumberFormat.INTERNATIONAL )
		except:
			format_number = number
		return format_number
				


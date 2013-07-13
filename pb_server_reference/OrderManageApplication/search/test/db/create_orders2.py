# coding: utf-8
"""
This script converts the Collection "mysql_web_orders" to
"mysql_web_orders2" in the "orders" Mongo Database.
"""

import pprint
import sys
import traceback
import re

import pymongo
import titlecase

province_codes = {
	'usa': {
		'ak': 'ak',
		'alaska': 'ak',
		'al': 'al',
		'alabama': 'al',
		'ar': 'ar',
		'arkansas': 'ar',
		'az': 'az',
		'arizona': 'az',
		'ca': 'ca',
		'california': 'ca',
		'co': 'co',
		'colorado': 'co',
		'ct': 'ct',
		'connecticut': 'ct',
		'de': 'de',
		'delaware': 'de',
		'dc': 'dc',
		'fl': 'fl',
		'florida': 'fl',
		'ga': 'ga',
		'georgia': 'ga',
		'hi': 'hi',
		'hawaii': 'hi',
		'id': 'id',
		'idaho': 'id',
		'ia': 'ia',
		'iowa': 'ia',
		'il': 'il',
		'illinois': 'il',
		'in': 'in',
		'indiana': 'in',
		'ks': 'ks',
		'kansas': 'ks',
		'ky': 'ky',
		'kentucky': 'ky', 
		'la': 'la',
		'louisiana': 'la',
		'ma': 'ma',
		'massachusetts': 'ma',
		'md': 'md',
		'maryland': 'md',
		'me': 'me',
		'maine': 'me',
		'mi': 'mi',
		'michigan': 'mi',
		'mn': 'mn',
		'minnesota': 'mn',
		'mo': 'mo',
		'missouri': 'mo',
		'ms': 'ms',
		'mississippi': 'ms',
		'mt': 'mt',
		'montana': 'mt',
		'nc': 'nc',
		'north carolina': 'nc',
		'nd': 'nd',
		'north dakota': 'nd',
		'ne': 'ne',
		'nebraska': 'ne',
		'nm': 'nm',
		'new mexico': 'nm',
		'nh': 'nh',
		'new hampshire': 'nh',
		'nj': 'nj',
		'new jersey': 'nj',
		'nv': 'nv',
		'nevada': 'nv',
		'ny': 'ny',
		'ny': 'new york',
		'oh': 'oh',
		'ohio': 'oh',
		'ok': 'ok',
		'oklahoma': 'ok',
		'or': 'or',
		'oregon': 'or',
		'pa': 'pa',
		'pennsylvania': 'pa',
		'ri': 'ri',
		'rhode island': 'ri',
		'sc': 'sc',
		'south carolina': 'sc',
		'sd': 'sd',
		'south dakota': 'sd',
		'tn': 'tn',
		'tennessee': 'tn',
		'tx': 'tx',
		'texas': 'tx', 
		'ut': 'ut',
		'utah': 'ut',
		'va': 'va',
		'virginia': 'va',
		'vt': 'vt',
		'vermont': 'vt',
		'wa': 'wa',
		'washington': 'wa',
		'wi': 'wi',
		'wisconsin': 'wi',
		'wv': 'wv',
		'west virginia': 'wv',
		'wy': 'wy',
		'wyoming': 'wy',
		
		'aa': 'aa',
		'ae': 'ae',
		'ap': 'ap'
	}
}

province_names = {
	#'aus': {
	#	'act': "Australian Capital",
	#	'cx': "Christmas Island",
	#	'cc': "Cocos Islands",
	#	'hm': "Heard Islands",
	#	'jbt': "Jervis Bay",
	#	'nsw': "New South Wales",
	#	'nf': "Norfolk Island",
	#	'nt': "Northern Territory",
	#	'qld': "Queensland",
	#	'sa': "South Australia",
	#	'tas': "Tasmania",
	#	'vic': "Victoria",
	#	'wa': "Western Australia"
	#},
	#'can': {
	#	'ab': "Alberta",
	#	'bc': "British Columbia",
	#	'mb': "Manitoba",
	#	'nb': "New Brunswick",
	#	'nl': "Newfoundland",
	#	'ns': "Nova Scotia",
	#	'nt': "Northwest Territories",
	#	'nu': "Nunavut",
	#	'on': "Ontario",
	#	'pe': "Prince Edward Island",
	#	'qc': "Quebec",
	#	'sk': "Saskatchewan",
	#	'yt': "Yukon"
	#},
	'usa': {
		'al': "Alabama",
		'ak': "Alaska",
		'ar': "Arkansas",
		'az': "Arizona",
		'ca': "California",
		'co': "Colorado",
		'ct': "Connecticut",
		'de': "Delaware",
		'dc': "District of Columbia",
		'fl': "Florida",
		'ga': "Georgia",
		'hi': "Hawaii",
		'id': "Idaho",
		'ia': "Iowa",
		'il': "Illinois",
		'in': "Indiana",
		'ks': "Kansas",
		'ky': "Kentucky",
		'la': "Louisiana",
		'ma': "Massachusetts",
		'md': "Maryland",
		'me': "Maine",
		'mi': "Michigan",
		'mn': "Minnesota",
		'mo': "Missouri",
		'ms': "Mississippi",
		'mt': "Montana",
		'nc': "North Carolina",
		'nd': "North Dakota",
		'ne': "Nebraska",
		'nm': "New Mexico",
		'nh': "New Hampshire",
		'nj': "New Jersey",
		'nv': "Nevada",
		'ny': "New York",
		'oh': "Ohio",
		'ok': "Oklahoma",
		'or': "Oregon",
		'pa': "Pennsylvania",
		'ri': "Rhode Island",
		'sc': "South Carolina",
		'sd': "South Dakota",
		'tn': "Tennessee",
		'tx': "Texas", 
		'ut': "Utah",
		'va': "Virginia",
		'vt': "Vermont",
		'wa': "Washington",
		'wi': "Wisconsin",
		'wv': "West Virginia",
		'wy': "Wyoming",
	
		'as': "American Samoa",
		'fm': "Federated States of Micronesia",
		'gu': "Guam",
		'mh': "Marshall Islands",
		'mp': "Northern Mariana Islands",
		'pr': "Puerto Rico",
		'pw': "Palau",
		'vi': "Virgin Islands",
		
		'aa': "Armed Forces Americas",
		'ae': "Armed Forces Europe",
		'ap': "Armed Forces Pacific"
	},
}

country_codes = {
	'fxx': 'fra',
	'rom': 'rou',
	'tmp': 'tls'
}

country_names = {
	'abw': "Aruba",
	'afg': "Afghanistan",
	'ago': "Angola",
	'aia': "Anguilla",
	'ala': "Åland Islands",
	'alb': "Albania",
	'and': "Andorra",
	'are': "United Arab Emirates",
	'arg': "Argentina",
	'arm': "Armenia",
	'asm': "American Samoa",
	'ata': "Antarctica",
	'atf': "French Southern Territories",
	'atg': "Antigua and Barbuda",
	'aus': "Australia",
	'aut': "Austria",
	'aze': "Azerbaijan",
	'bdi': "Burundi",
	'bel': "Belgium",
	'ben': "Benin",
	'bes': "Caribbean Netherlands",
	'bfa': "Burkina Faso",
	'bgd': "Bangladesh",
	'bgr': "Bulgaria",
	'bhr': "Bahrain",
	'bhs': "Bahamas",
	'bih': "Bosnia and Herzegovina",
	'blm': "Saint Barthélemy",
	'blr': "Belarus",
	'blz': "Belize",
	'bmu': "Bermuda",
	'bol': "Bolivia",
	'bra': "Brazil",
	'brb': "Barbados",
	'brn': "Brunei Darussalam",
	'btn': "Bhutan",
	'bvt': "Bouvet Island",
	'bwa': "Botswana",
	'caf': "Central African Republic",
	'can': "Canada",
	'cck': "Cocos Islands",
	'che': "Switzerland",
	'chl': "Chile",
	'chn': "China",
	'civ': "Côte d'Ivoire",
	'cmr': "Cameroon",
	'cod': "D.R. Congo",
	'cog': "Congo",
	'cok': "Cook Islands",
	'col': "Colombia",
	'com': "Comoros",
	'cpv': "Cape Verde",
	'cri': "Costa Rica",
	'cub': "Cuba",
	'cuw': "Curaçao",
	'cxr': "Christmas Island",
	'cym': "Cayman Islands",
	'cyp': "Cyprus",
	'cze': "Czech Republic",
	'deu': "Germany",
	'dji': "Djibouti",
	'dma': "Dominica",
	'dnk': "Denmark",
	'dom': "Dominican Republic",
	'dza': "Algeria",
	'ecu': "Ecuador",
	'egy': "Egypt",
	'eri': "Eritrea",
	'esh': "Western Sahara",
	'esp': "Spain",
	'est': "Estonia",
	'eth': "Ethiopia",
	'fin': "Finland",
	'fji': "Fiji",
	'flk': "Falkland Islands",
	'fra': "France",
	'fro': "Faroe Islands",
	'fsm': "Micronesia",
	'gab': "Gabon",
	'gbr': "United Kingdom",
	'geo': "Georgia",
	'ggy': "Guernsey",
	'gha': "Ghana",
	'gib': "Gibraltar",
	'gin': "Guinea",
	'glp': "Guadeloupe",
	'gmb': "Gambia",
	'gnb': "Guinea-Bissau",
	'gnq': "Equatorial Guinea",
	'grc': "Greece",
	'grd': "Grenada",
	'grl': "Greenland",
	'gtm': "Guatemala",
	'guf': "French Guiana",
	'gum': "Guam",
	'guy': "Guyana",
	'hkg': "Hong Kong",
	'hmd': "Heard Island",
	'hnd': "Honduras",
	'hrv': "Croatia",
	'hti': "Haiti",
	'hun': "Hungary",
	'idn': "Indonesia",
	'imn': "Isle of Man",
	'ind': "India",
	'iot': "British Indian Ocean Territory",
	'irl': "Ireland",
	'irn': "Iran",
	'irq': "Iraq",
	'isl': "Iceland",
	'isr': "Israel",
	'ita': "Italy",
	'jam': "Jamaica",
	'jey': "Jersey",
	'jor': "Jordan",
	'jpn': "Japan",
	'kaz': "Kazakhstan",
	'ken': "Kenya",
	'kgz': "Kyrgyzstan",
	'khm': "Cambodia",
	'kir': "Kiribati",
	'kna': "Saint Kitts and Nevis",
	'kor': "South Korea",
	'kwt': "Kuwait",
	'lao': "Laos",
	'lbn': "Lebanon",
	'lbr': "Liberia",
	'lby': "Libya",
	'lca': "Saint Lucia",
	'lie': "Liechtenstein",
	'lka': "Sri Lanka",
	'lso': "Lesotho",
	'ltu': "Lithuania",
	'lux': "Luxembourg",
	'lva': "Latvia",
	'mac': "Macao",
	'maf': "Saint Martin",
	'mar': "Morocco",
	'mco': "Monaco",
	'mda': "Moldova",
	'mdg': "Madagascar",
	'mdv': "Maldives",
	'mex': "Mexico",
	'mhl': "Marshall Islands",
	'mkd': "Macedonia",
	'mli': "Mali",
	'mlt': "Malta",
	'mmr': "Myanmar",
	'mne': "Montenegro",
	'mng': "Mongolia",
	'mnp': "Northern Mariana Islands",
	'moz': "Mozambique",
	'mrt': "Mauritania",
	'msr': "Montserrat",
	'mtq': "Martinique",
	'mus': "Mauritius",
	'mwi': "Malawi",
	'mys': "Malaysia",
	'myt': "Mayotte",
	'nam': "Namibia",
	'ncl': "New Caledonia",
	'ner': "Niger",
	'nfk': "Norfolk Island",
	'nga': "Nigeria",
	'nic': "Nicaragua",
	'niu': "Niue",
	'nld': "Netherlands",
	'nor': "Norway",
	'npl': "Nepal",
	'nru': "Nauru",
	'nzl': "New Zealand",
	'omn': "Oman",
	'pak': "Pakistan",
	'pan': "Panama",
	'pcn': "Pitcairn",
	'per': "Peru",
	'phl': "Philippines",
	'plw': "Palau",
	'png': "Papua New Guinea",
	'pol': "Poland",
	'pri': "Puerto Rico",
	'prk': "North Korea",
	'prt': "Portugal",
	'pry': "Paraguay",
	'pse': "Palestinian Territory",
	'pyf': "French Polynesia",
	'qat': "Qatar",
	'reu': "Réunion",
	'rou': "Romania",
	'rus': "Russian Federation",
	'rwa': "Rwanda",
	'sau': "Saudi Arabia",
	'sdn': "Sudan",
	'sen': "Senegal",
	'sgp': "Singapore",
	'sgs': "South Georgia Islands",
	'shn': "Saint Helena",
	'sjm': "Svalbard and Jan Mayen",
	'slb': "Solomon Islands",
	'sle': "Sierra Leone",
	'slv': "El Salvador",
	'smr': "San Marino",
	'som': "Somalia",
	'spm': "Saint Pierre and Miquelon",
	'srb': "Serbia",
	'ssd': "South Sudan",
	'stp': "Sao Tome and Principe",
	'sur': "Suriname",
	'svk': "Slovakia",
	'svn': "Slovenia",
	'swe': "Sweden",
	'swz': "Swaziland",
	'sxm': "Sint Maarten",
	'syc': "Seychelles",
	'syr': "Syria",
	'tca': "Turks and Caicos Islands",
	'tcd': "Chad",
	'tgo': "Togo",
	'tha': "Thailand",
	'tjk': "Tajikistan",
	'tkl': "Tokelau",
	'tkm': "Turkmenistan",
	'tls': "Timor-Leste",
	'ton': "Tonga",
	'tto': "Trinidad and Tobago",
	'tun': "Tunisia",
	'tur': "Turkey",
	'tuv': "Tuvalu",
	'twn': "Taiwan",
	'tza': "Tanzania",
	'uga': "Uganda",
	'ukr': "Ukraine",
	'umi': "U.S. Minor Outlying Islands",
	'ury': "Uruguay",
	'usa': "United States",
	'uzb': "Uzbekistan",
	'vat': "Vatican City",
	'vct': "Saint Vincent",
	'ven': "Venezuela",
	'vgb': "British Virgin Islands",
	'vir': "U.S. Virgin Islands",
	'vnm': "Viet Nam",
	'vut': "Vanuatu",
	'wlf': "Wallis and Futuna",
	'wsm': "Samoa",
	'yem': "Yemen",
	'zaf': "South Africa",
	'zmb': "Zambia",
	'zwe': "Zimbabwe",
	
	# Transitional
	'yug': "Yugoslavia"
}

def main(argv):
	
	mongo_uri = 'hol-srv-db00'
	
	print "Connecting to %r..." % mongo_uri,; sys.stdout.flush()
	mongo = pymongo.Connection(mongo_uri)
	order_db = mongo['orders']
	src_tb = order_db['mysql_web_orders']
	dest_tb = order_db['mysql_web_orders2']
	print "done"
	
	print "Copying...",; sys.stdout.flush()
	dest_tb.drop()
	cursor = src_tb.find()
	count = cursor.count()
	for i, doc in enumerate(cursor, 1):
		if not i % 100:
			print "\rCopying %i/%i" % (i, count),; sys.stdout.flush()
		
		customer = doc['customer']
		name_first, name_last = customer['name_text'].split(' ', 1)
		email = customer['email']
		timezone = customer['timezone']
		daytime_phone = customer['daytime_phone']
		evening_phone = customer['evening_phone']
		
		phones = []
		if daytime_phone:
			phones.append({
				'name': "Daytime",
				'number': daytime_phone
			})
		if evening_phone:
			phones.append({
				'name': "Evening",
				'number': evening_phone
			})
			phones['evening'] = evening_phone
		
		order = doc['order']
		comments = order['notes']
		
		platform = doc['platform']
		if platform['market_name'] == 'ridersdiscount.com':
			market_code = 'www'
			market_name = 'RidersDiscount.com'
		else:
			print "UNKNOWN MARKET"
			pprint.pprint(doc)
			sys.exit(1)
			
		insert_payments = []
		for payment in doc['payments']:
			billing = payment['billing']
			
			details = {key: val for key, val in payment['details']}
			
			try:
				country_code = billing['country_text'].strip().lower().replace(' ', '_')
				if country_code in country_codes:
					country_code = country_codes[country_code]
				if country_code in country_names:
					country_text = country_names[country_code]
				else:
					country_text = titlecase.titlecase(billing['country_text'])
					
				province_code = billing['province_text'].strip().lower().replace(' ', '_')
				if country_code in province_codes and province_code in province_codes[country_code]:
					province_code = province_codes[country_code][province_code]
				if country_code in province_names and province_code in province_names[country_code]:
					province_text = province_names[country_code][province_code]
				else:
					province_text = titlecase.titlecase(billing['province_text'])
			except KeyError:
				traceback.print_exc()
				pprint.pprint(doc)
				sys.exit(1)
				
			insert_payment = {
				'method_code': 'creditcard',
				'method_text': "Credit Card",
				'status_code': 'pending',
				'status_text': "Pending",
				'amount': payment['total'],
				'billing': {
					'recipient': (billing['first'] + " " + billing['last']).strip(),
					'address': billing['address'],
					'city': billing['city_text'],
					'province_code': province_code,
					'province_text': province_text,
					'country_code': country_code,
					'country_text': country_text,
					'postal': billing['postal']
				},
				'details': {
					'name': details['Card Name'],
					'number': details['Card Number']
				},
				'fraud': payment['fraud'],
			}
			if billing['company']:
				insert_payment['billing']['company'] = billing['company']
			if details['Message'] and 'approved' in details['Message']:
				insert_payment['details']['status_code'] = 'approved'
				insert_payment['details']['status_text'] = "Approved"
		
			insert_payments.append(insert_payment)
			
		shipping = doc['shipping']
		
		try:
			country_code = shipping['country_text'].strip().lower().replace(' ', '_')
			if country_code in country_codes:
				country_code = country_codes[country_code]
			if country_code in country_names:
				country_text = country_names[country_code]
			else:
				country_text = titlecase.titlecase(shipping['country_text'])
				
			province_code = shipping['province_text'].strip().lower().replace(' ', '_')
			if country_code in province_codes and province_code in province_codes[country_code]:
				province_code = province_codes[country_code][province_code]
			if country_code in province_names and province_code in province_names[country_code]:
				province_text = province_names[country_code][province_code]
			else:
				province_text = titlecase.titlecase(shipping['province_text'])
		except KeyError:
			traceback.print_exc()
			pprint.pprint(doc)
			sys.exit(1)
		
		insert_shipping = {
			'address': {
				'recipient': (shipping['first'] + " " + shipping['last']).strip(),
				'address': shipping['address'],
				'city': shipping['city_text'],
				'province_code': province_code,
				'province_text': province_text,
				'country_code': country_code,
				'country_text': country_text,
				'postal': shipping['postal']
			},
			'status_code': '',
			'status_text': ""
		}
		if shipping['company']:
			insert_shipping['company'] = shipping['company']
		
		insert = {
			'customer': {
				'name_first': name_first,
				'name_last': name_last,
			},
			'geoip': doc['geoip'],
			'items': doc['items'],
			'order': {
				'date': order['date'],
				'item_qty': order['item_qty'],
				'subtotal': order['subtotal'],
				'shiptotal': order['shiptotal'],
				'taxtotal': order['tax'],
				'total': order['total'],
				'status_code': '',
				'status_text': ""
			},
			'payments': insert_payments,
			'platform': {
				'market_code': market_code,
				'market_name': market_name,
				'po_number': str(platform['order_id'])
			},
			'shipping': insert_shipping
		}
		if email:
			insert['customer']['email'] = email
		if timezone:
			insert['customer']['timezone'] = timezone
		if phones:
			insert['customer']['phones'] = phones
		if comments:
			insert['order']['comments'] = [comments] if isinstance(comments, basestring) else list(comments)
		
		dest_tb.insert(insert)
	
	print "\rCopying %i/%i" % (count, count)


if __name__ == '__main__':
	sys.exit(main(sys.argv))

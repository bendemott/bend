# encoding: utf-8
"""
This is version 3 of the Order structure.

Previous versions of this structure are:

- v1: it/Development/projects/python/web_orders/moformat.txt
- v2: it/Development/projects/python/response_orders/order_example.py
"""

__author__ = "Caleb"
__version__ = "0.3"
__status__ = "Prototype"

address = {
	# (optional) The attention line is the proxy to the recipient.
	'attention': str,
	
	# Recipient for the address.
	'recipient': str,
	
	# (optional) Company of recipient.
	'company': str,
	
	# Street address. This can consist of multiple lines.
	'address': [str],
	
	# City name.
	'city': str,
	
	# Province (or State) alpha 2 code (e.g., "mi") l 
	'province_code': str,
	
	# Province (or State) textual name (e.g., "Michigan").
	'province_text': str,
	
	# Country alpha 2 code (e.g., "us" or "ca").
	'country_code': str,
	
	# Country textual name (e.g., "USA" or "Canada").
	'country_text': str,
	
	# Postal code.
	'postal': str
}

order = {
	# Customer contains contact information for the customer.
	'customer': {
		# First name.
		'name_first': str,
		
		# Last name.
		'name_last': str,
		
		# (optional) Company name.
		'company': str,
		
		# (optional) Email address: aaa@bbb.ccc
		'email': str,
		
		# (optional) Phone numbers.
		'phones': [
			{
				# The name for the number (e.g., "Cell" or "Home").
				'name': str,
				
				# The number in international format::
				#
				#   phone ::= "+" cc number ("x" extension)?
				#   cc ::= digit+
				#   number ::= digit+
				#   extension ::= digit+
				#
				# where *cc* is the country calling code, *number* is the phone
				# number, and optionally with an *extension* prefixed by an "x".
				'number': str
			}
		],
		
		# (optional) The customer's timezone must formatted as an ISO 8601
		# Time Zone Designator and preferably using the following format::
		#
		#   timezone ::= direction hours ":" minutes
		#   direction ::= "+" | "-"
		#   hours ::= digit*2
		#   minutes ::= digit*2
		#
		# where *direction* is whether the timezone offset is behind ("-")
		# or ahead ("+") of UTC, *hours* is the number of hours offset, and
		# *minutes* is the number of minutes offset. 
		'timezone': str,
	},
	
	# GeoIP contains geolocation information about this order.
	#
	# .. TODO: This is from v1 and needs to be reviewed/revised.
	'geoip': {
		'address': '76.104.175.4',
		'anonymous': None,
		'country_id': None,
		'country_text': '',
		'distance_to_shipping': None,
		'latitude': 'None',
		'longitude': 'None',
		'postal': None,
		'province_id': '',
		'province_text': '',
		'proxy': None
	},
	
	# Items contains all relevant information about the ordered items.
	#
	# .. TODO: This is from v1 and v2, and needs to be revised.
	'items': {
	
		# This is the structure of an item from v1.
		'3405-0389': {
			'data_id': '',
			'image_urls': ['channel-images/13/131148/395x395-ENLARGED.jpg'],
			'item_title': 'ALPINESTARS FASTLANE SHOES BLACK YELLOW US 7',
			'listing_id': '',
			'order_quantity': 1,
			'product_id': 131148L,
			'product_title': 'FASTLANE SHOES',
			'revision_id': '',
			'sale_price': 119.95,
			'ship': None,
			'ship_tax': None,
			'stock': {'local': 0, 'supplier': 0},
			'tax': None,
			'thumb_url': 'channel-images/13/131148/72x72-THUMB.jpg',
			'url': 'street-gear/boots-men/136265.php'
		},
	
		# This is the structure of an item from v2 used by Response.
		"{sku}": {
			"product_sku": str, # The SKU
			'order_qty': int, # The number of items ordered
			'sale_price': float, # The price per item.
		}
	},
	
	# Order contains an overview of the order information.
	'order': {
		# (optional) Any comments pertaining to the order.
		'comments': [str],
		
		# The date the order was made.
		'date': datetime,
		
		# The total number of items. This is the sum of 'order_qty' for all
		# items.
		'item_qty': int,
		
		# The price for all items before taxes and shipping.
		'subtotal': float,
		
		# The total shipping cost.
		'shiptotal': float,
		
		# The total tax on the order.
		'taxtotal': float,
		
		# The total cost for the order. This is the sum of 'subtotal',
		# 'shiptotal', and 'taxtotal'.
		'total': float,
		
		# The order status code. 
		'status_code': str,
		
		# The order textual status.
		'status_text': str
	},
	
	# Payments contains all information pertaining to payments. This is an
	# array to allow a full payment to me comprized of multiple parts.
	# E.g., an order paid for partially with a gift-card, and the
	# remaining with a credit-card.
	'payments': [
		{
			# The method code:
			#
			# - "amazon": The payment is through Amazon.
			# - "authnet": The payment is though Authorize.Net.
			# - "cash": The payment is cash.
			# - "check": The payment is a personal check
			# - "creditcard": The payment is a credit-card.
			# - "giftcard": The payment is a gift-card.
			# - "paypal": The payment is though PayPal.
			'method_code': str,
			
			# The method textual name (e.g., "Credit Card").
			'method_text': str,
			
			# The payment status ID indicates the general status of the
			# payment without specific details:
			#
			# - "new": The payment is new and has not been initiated.
			# - "pending": The payment is pending.
			# - "success": The payment succeeded.
			# - "failed": The payment failed.
			# - "returned": The payment was returned or refunded.
			'status_code': str,
			
			# The payment textual status (e.g., "Pending").
			'status_text': str,
			
			# The amount of the payment.
			'amount': float,
			
			# The billing address.
			'billing': address,
			
			# (optional) Contains fraud information about the payment.
			#
			# .. NOTE: This is from v1 and needs to be reviewed/revised.
			'fraud': {
				'bank_bin': None,
				'bank_country': None,
				'bank_name': None,
				'bank_phone': None,
				'distance_to_bank': None,
				'distance_to_geoip': None
			},
			
			# (optional) Contains details specific to the payment method.
			'details': {},
			
			# TODO: Amazon details.
			
			# TODO: Authorize.Net details.
			
			# TODO: Check details.
			
			# Credit Card details.
			'details': {
				# (optional) The issuer ID (e.g., "visa").
				'issuer_code': str,
				
				# (optional) The issuer textual name (e.g., "MasterCard").
				'issuer_text': str,
				
				# (optional) The name of card holder (e.g., "Moises Bentiez").
				'name': str,
				
				# (optional) The card number (e.g., "xxxx xxxx xxxx xxxx").
				'number': str,
				
				# (optional) Expiration year (standard A.D.).
				'exp_year': int,
				
				# (optional) Expiration month: 1-12.
				'exp_month': int,
				
				# (optional) The card security code number (or CVV, CVC, etc.).
				'sec_code': str,
				
				# (optional) The detailed payment status code.
				'status_code': str,
				
				# (optional) The detailed payment textual status.
				'status_text': str
			},
			
			# TODO: Gift Card details.
			
			# TODO: PayPal details.
		}
	],
	
	# Platform contains information about where the order originated from
	# and how it can be identified.
	'platform': {
		# The market code:
		#
		# - "amazon": The order came from Amazon.
		# - "ebay": The order came from Ebay.
		# - "www": The order came from RidersDiscount.com.
		'market_code': str,
		
		# The market textual name.
		'market_text': str,
	
		# The PO number (Amazon Order ID, Ebay Order ID, Channel Advisor
		# Listing Number, etc.).
		'po_number': str
	},
	
	# Shipping contains all information pertaining to shipping.
	'shipping': {
		# The shipping address.
		'address': address,
		
		# The shipping status code. 
		'status_code': str,
		
		# The shipping textual status.
		'status_text': str
	}
}

from twisted.spread import pb
from twisted.python import log
from twisted.internet import defer, threads
from twisted.internet.threads import deferToThread

from pbplugins import EasyReferenceable

#import pycountry#This module is used to determine country code information, to choose the correct flag icon

class DetailsTest( EasyReferenceable ):

	@defer.inlineCallbacks
	def clientConnectionMade(self, app):
		'''
		Called when the client instantiates this class ...
		Do whatever you want in here.
		It's ok to return deferreds from here.
		'''
		return None
	

	def get_image_location(self, country):
		'''
		Determines the image location for the flag icons.
		'''
		base_file_name = 'images/flags/png/'
		image_location = None
		
		if len( country ) == 2:
			try:
				name = pycountry.countries.get( alpha2=country)
				image_location = name.alpha2
			except KeyError:
				image_location = None
		elif len( country ) == 3:
			if country.isalpha():
				try:
					name = pycountry.countries.get( alpha3=country)
					image_location = name.alpha2
				except KeyError:
					image_location = None

			elif country.isdigit():
				try:
					name = pycountry.countries.get( numeric=country )
					image_location = name.alpha2
				except KeyError:
					image_location = None
		else:	
			try:
				name = pycountry.countries.get( name=country )
				image_location = name.alpha2
			except KeyError:
				image_location = None
		
		if image_location:
			image_location = base_file_name + image_location.lower() + '.png'
		
		return image_location
		


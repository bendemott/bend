'''
Testing formatting of a phone number string
'''

import sys

def generate_markup(number,search):
	'''
	Creates a pango markup string out of the given number by
	bolding the search substring within the properly formatted number
	'''
	
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
	
	#print "START:%s" % start_idx
	#print "END:%s" % end_idx
	
	#If either start or end index is not set, then didn't find the substring
	#within the string, so just return the original
	if start_idx is None or end_idx is None:
		return number
	
	#Return the string, adding the <b> markup at the start and end indices
	return number[0:start_idx] + "<b>" + number[start_idx:end_idx] + "</b>" + number[end_idx:]
	
		

def main():

	example = "(616) 399-8074"
	#Tests
	print generate_markup( example, '399' )
	print generate_markup( example, '616' )
	print generate_markup( example, '1639' )
	print generate_markup( example, '6163998074')
	print generate_markup( example, '998' )
	print generate_markup( example, '62' )


if __name__=='__main__':
	sys.exit(main())

	

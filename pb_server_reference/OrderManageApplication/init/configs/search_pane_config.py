'''
The configuration structure to initialize the SearchPane
'''
search_config = {

	'basic_text': "Names, Addresses, Phone Numbers, etc...", 
	'advanced': [
		{
			'field': 'id',
			'label': 'Order#', 
			'type': 'entry', 
			'completion': False,			
		},
		{
			'field': 'name',
			'label': 'Name',
			'type': 'entry',
			'completion': False,
		},
		{
			'field': 'address',
			'label': 'Address',
			'type': 'entry',
			'completion': False,
		},
		{
			'field': 'phone',
			'label': 'Phone',
			'type': 'entry',
			'completion': True,
		},
		{
			'field': 'email',
			'label': 'Email',
			'type': 'entry',
			'completion': False,
		},
		{
			'field': 'creditcard',
			'label': 'Card#',
			'type': 'entry',
			'completion': False,
		},
		{
			'field': 'sep',
			'type': 'sep'
		},
		{	
			'field': 'date', 
			'type': 'combo', 
			'label_before': 'Since', 
			'label_after': 'days ago',
			'options':[ 
				['7', 'days_7'],
				['30', 'days_30'],
				['90', 'days_90'],
			]
		}
	]
	
}

'''
This config file gives the configuration for the orders treeview that you'll find
in the customer_details_pane of the customer_record window
This particular implementation is for the New ConfigTreeView API
'''

orders_config = {
	'treeview':{
		'properties': {
			'headers-visible': False,
			'height-request': 175,
		},
		'selection-mode': 'SELECTION_SINGLE',
		'kwargs':{'primary_key': '$index.primary_key'},
	},
	'index_names':{
		'primary_key': 'int',
		'order_id': {'markup': 'str'},
		'date': {'markup': 'str'},
		'status': {'markup': 'str'},
		'total': {'markup': 'str'},
	},
	'column_order':['order_id', 'date', 'status', 'total'],
	'macros':{
		'cell-font':{'font': 'Lucida Sans 8'},
	},
	'columns':{
		'order_id':{
			'renderers':{
				'indices':{'markup': True},
				'macros': ['cell-font'],
			},
		},
		'date': {
			'renderers':{
				'indices':{'markup': True},
				'macros':['cell-font'],
			},
		},
		'status':{
			'renderers':{
				'indices':{'markup':True},
				'macros': ['cell-font'],
			},
		},
		'total':{
			'renderers':{
				'indices':{'markup':True},
				'macros': ['cell-font']
			},
		}
	}
}

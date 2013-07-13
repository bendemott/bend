'''
This is a new configuration file for the cart treeview that will use the
new ConfigTreeView api.
'''

cart_config = {
	'treeview': {
		'selection-color': '#bfd3e7',
		'args': ['$index.product.0.pixbuf'],
	},
	'treemodel':{
		'module': 'chronicle.gui.tools.image_loader',
		'class': 'ImageStore',
		'args': ['$index.product.0.pixbuf'],
	},
	'index_names': {
		'product':[{'pixbuf':'gtk.gdk.Pixbuf'}, {'markup': 'str'}],
		'sku':{'markup': 'str'},
		'qty':{'markup': 'str'},
		'price':{'markup': 'str'},
	},
	'column_order':['product', 'sku', 'qty', 'price'],
	'macros':{
		'cell-font': {
			'font': 'Lucida Sans 8'
		}
	},
	'columns':{
		'product':{
			'header':{
				'title': 'Product',
			},
			'renderers':[
				{
					'pack': 'pack_start',
					'expand': False,
					'class': 'CellRendererPixbuf',
					'indices':{'pixbuf': True}
				},
				{
					'macros':['cell-font'],
					'indices':{'markup': True}
				}
			],
		},
		'sku':{
			'header':{
				'title': 'SKU',
			},
			'renderers':{
				'macros': ['cell-font'],
				'indices':{'markup': True}
			}
		},
		'qty':{
			'header':{
				'title': 'Qty',
			},
			'renderers':{
				'macros': ['cell-font'],
				'indices':{'markup': True}
			}
		},
		'price':{
			'header':{
				'title': 'Price',
			},
			'renderers':{
				'macros': ['cell-font'],
				'indices':{'markup': True}
			}
		}
	}
	
}

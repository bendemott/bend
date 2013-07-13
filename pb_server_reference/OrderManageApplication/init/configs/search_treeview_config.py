search_treeview_config = {
	'treeview': {
		'properties': {
			'rules-hint': True,
			'headers-clickable': True,
		},
		'selection-mode': 'SELECTION_SINGLE',
		'args': ['$index.cell-bg-index', '$index.id', '$index.market.pixbuf'],
	},
	'treemodel': {
		'module': 'chronicle.gui.tools.image_loader',
		'class': 'ImageStore',
		'args': ['$index.market.pixbuf'],
		'kwargs': {'ebay':'markets/ebay-logo.jpg', 'amazon': 'markets/amazon-logo.gif', 'www':'markets/riders_discount.gif'},
	},
	'index_names':{
		'cell-bg-index': 'bool',
		'market':{'pixbuf': "gtk.gdk.Pixbuf"},
		'status':[{'markup':'str'},{'markup':'str'}],
		'name':{'markup':'str'},
		'address':{'markup':'str'},
		'contact':{'markup':'str'},
		'payment':[{'markup':'str'}, {'markup':'str'}],
		'shipping':{'markup':'str'},
		'comments':{'markup':'str'},
		'placed':{'markup':'str'},
		'id': 'str',
	},
	'column_order':['market', 'status', 'name', 'address', 'contact', 'payment', 'shipping', 'comments', 'placed'],
	'macros':{
		'col-default': {
			'expand': True,
			'resizable': True,
			'clickable': True,
			'reorderable': True,
		},
		'cell-text': {
			'font': 'Lucida Sans 8'
		},
		'cell-bg': {
			'cell-background': "#7CB3C0"
		},
	},
	'columns':{
		'market':{
			'properties':{
				'expand': False,
				'resizable': True,
				'clickable': True,
			},
			'renderers':{
				'class': 'CellRendererPixbuf',
				'indices': {
					'pixbuf': True,
					'cell-background-set': 'cell-bg-index'
				},
				'macros':['cell-bg']
			},
		},
		'status':{
			'macros': ['col-default'],
			'header': {
				'title': 'Status',
			},
			'renderers':[
				{
					'properties':{
						'font': 'Lucida Sans 8',
						'foreground': '#656565',
					},
					'indices':{
						'markup': True,
						'cell-background-set': 'cell-bg-index',
					},
					'macros': ['cell-bg'],
				},
				{
					'macros': ['cell-text', 'cell-bg'],
					'indices':{
						'markup': True,
						'cell-background-set': 'cell-bg-index',
					},
				},
			],
		},
		'name':{
            "macros": ["col-default"],
            "header":{
                "title": "Name"
            },
            "properties":{
            	#"fixed_width": 150,
            	#"sizing": 2
            	
            },
            "renderers":{
                "macros": ["cell-text","cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index'
                },
            }			
		},
		'address':{
            "macros": ["col-default"],
            "header":{
                "title": "Address"
            },
            "renderers":{
                "macros": ["cell-text", "cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index'
                }
            }
		},
		'contact':{
            "macros": ["col-default"],
            "header":{
                "title": "Contact"
            },
            "renderers":{
                "macros": ["cell-text", "cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index'
                }
            }
		},
		'payment':{
            "macros": ["col-default"],
            "header":{
                "title": "Payment"
            },
            "renderers":[
                {
                    "macros": ["cell-text", "cell-bg"],
                    "indices":{
                        "markup":True,
                        "cell-background-set": 'cell-bg-index'
                    }
                },
                {
                    "macros": ["cell-text", "cell-bg"],
                    "indices":{
                        "markup": True,
                        "cell-background-set": 'cell-bg-index'
                    }
                }
			],
		},
		'shipping':{
            "macros": ["col-default"],
            "header":{
                "title": "Shipping"
            },
            "renderers":{
                "macros": ["cell-text", "cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index',
            	}
            }
		},
		'comments':{
            "macros": ["col-default"],
            "header":{
                "title": "Comments"
            },
            "renderers":{
                "macros": ["cell-text","cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index',
                }
            }
		},
		'placed':{
            "macros": ["col-default"],
            "header":{
                "title": "Placed"
            },
            "renderers":{
                "macros": ["cell-text", "cell-bg"],
                "indices":{
                    "markup": True,
                    "cell-background-set": 'cell-bg-index'
                }
            }
		}
	},
}

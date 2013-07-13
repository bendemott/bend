"""
This is the configuration structure for the Preview CartTreeView.
This TreeView displays 'quick' information about the items in an order
You'll see this ConfigTreeView displayed in the CustomerPreview pane
of the MainWindow
This includes:
	* A column that displays a mini image of the item
	* A column that displays brand and title of the item
	* A column that displays quantity and style of the item
	* A column that displays price of the item.
"""
preview_cart_config = {
	"treeview": {
		"properties":{
			"headers-visible": False,
			"height-request": 128
		},
		"kwargs":{"pixbuf_index": "$index.image.pixbuf"}
	},
	"treemodel":{
		"module": "chronicle.gui.tools.image_loader",
		"class": "ImageStore",
		"args": [("$index.image.pixbuf", 20, 20)],
	},

	"index_names":{
		"image":{"pixbuf": "gtk.gdk.Pixbuf"},
		"title":{"markup": "str"},
		"qty":{"markup": "str"},
		"price":{"markup": "str"}
	},
	"column_order":["image", "title", "qty", "price"],
	"macros":{
		"text-cell":{"font": "Lucida Sans 8"}
	},
	"columns":{
		"image":{
			 "renderers":{
			 	"indices":{"pixbuf":True},
			 	"class": "CellRendererPixbuf",
			 	"properties": {
			 		"height": 20,
			 		"width": 20,
			 	}
			 }
		},
		"title":{
			"renderers":{
				"indices":{"markup":True},
				"macros": ["text-cell"],
				"properties": {
					"wrap-mode": 2,
					"wrap-width": 100,
					#"background": "blue"
				}
			}
		},
		"qty":{
			"renderers":{
				"indices":{"markup":True},
				"macros": ["text-cell"],
			}
		},
		"price":{
			"renderers":{
				"indices":{"markup":True},
				"macros": ["text-cell"],
			}
		}
	}
}

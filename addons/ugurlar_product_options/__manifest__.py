{
    'name': 'Uğurlar Ürün Seçenekleri',
    'version': '19.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Ürün listesi için gelişmiş filtreleme araçları',
    'description': """
        Ürün Varyantları listesine barkod/iç referans bazlı
        toplu filtreleme özelliği ekler.
    """,
    'author': 'Uğurlar',
    'website': 'https://ugurlar.com',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'stock',
    ],
    'data': [
        'views/product_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ugurlar_product_options/static/src/css/barcode_filter.css',
            'ugurlar_product_options/static/src/js/barcode_filter.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

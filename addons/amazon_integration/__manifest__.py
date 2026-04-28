{
    'name': 'Amazon SP-API Integration',
    'version': '19.0.1.0.0',
    'category': 'Sales/Integration',
    'summary': 'Amazon Selling Partner API (SP-API) entegrasyonu',
    'author': 'Odoo Ugurlar',
    'depends': ['base', 'sale_management', 'stock', 'delivery'],
    'data': [
        'security/ir.model.access.csv',
        'views/amazon_config_views.xml',
        'views/amazon_store_views.xml',
        'views/amazon_sync_log_views.xml',
        'views/amazon_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

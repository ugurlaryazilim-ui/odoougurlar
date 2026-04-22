# -*- coding: utf-8 -*-
{
    'name': 'Pttavm Entegrasyonu',
    'version': '19.0.1.0.0',
    'summary': 'Pttavm Sipariş Entegrasyonu',
    'description': 'Pttavm Pazaryeri API üzerinden siparişlerin çekilmesi, Odoo\'da oluşturulması ve Nebim entegrasyonuna hazır hale getirilmesi.',
    'author': 'Uğurlar',
    'category': 'Sales',
    'depends': ['sale_management', 'sale_stock', 'stock', 'delivery', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/pttavm_config_views.xml',
        'views/pttavm_store_views.xml',
        'views/pttavm_order_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

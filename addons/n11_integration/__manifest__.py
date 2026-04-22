# -*- coding: utf-8 -*-
{
    'name': 'N11 Entegrasyonu',
    'version': '19.0.1.0.0',
    'summary': 'N11 Sipariş Entegrasyonu',
    'description': 'N11 Pazaryeri API üzerinden siparişlerin çekilmesi, Odoo\'da oluşturulması ve Nebim entegrasyonuna hazır hale getirilmesi.',
    'author': 'Uğurlar',
    'category': 'Sales',
    'depends': ['sale_management', 'sale_stock', 'stock', 'delivery', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/n11_config_views.xml',
        'views/n11_store_views.xml',
        'views/n11_order_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'icon': '/n11_integration/static/description/n11.png',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

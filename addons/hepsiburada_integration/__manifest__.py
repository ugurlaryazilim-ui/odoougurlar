# -*- coding: utf-8 -*-
{
    'name': 'Hepsiburada.com Entegrasyonu',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Hepsiburada API Entegrasyonu (Sipariş Yönetimi)',
    'description': """
        Hepsiburada pazaryeri entegrasyonu.
        - Ödemesi tamamlanmış sipariş aktarımı
        - Stok ve Fiyat eşleştirmeleri
        - Nebim V3 ve Barkod (Depo) sistemleriyle entegre
    """,
    'author': 'Ugurlar',
    'website': 'https://www.ugurlar.com',
    'depends': ['base', 'sale', 'stock', 'odoougurlar'],
    'data': [
        'security/ir.model.access.csv',
        'views/hepsiburada_store_views.xml',
        'views/hepsiburada_config_views.xml',
        'views/hepsiburada_order_views.xml',
        'views/hepsiburada_sync_log_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'icon': '/hepsiburada_integration/static/description/hepsiburada.png',
    'auto_install': False,
    'license': 'LGPL-3',
}

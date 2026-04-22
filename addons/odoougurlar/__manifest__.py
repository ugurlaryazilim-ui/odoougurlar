{
    'name': 'Odoo Uğurlar - Nebim Entegrasyonu',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': 'Nebim V3 ERP entegrasyonu - Ürün, Stok, Fiyat ve Fatura senkronizasyonu',
    'description': """
        Uğurlar mağazaları için Nebim V3 Integrator Service entegrasyonu.
        
        Özellikler:
        - Nebim'den ürün senkronizasyonu (varyant, barkod, fiyat)
        - Stok ve fiyat güncelleme (periyodik)
        - Satış faturası aktarımı (Odoo → Nebim)
        - MCP (Model-Connector-Processor) mimarisi
        - Zamanlanmış görevler (ir.cron)
        - Detaylı hata yönetimi ve loglama
    """,
    'author': 'Uğurlar',
    'website': 'https://ugurlar.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'stock',
        'account',
        'sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'data/ugo_sequence.xml',
        'views/wizard_view.xml',
        'views/settings_view.xml',
        'views/marketplace_mapping_views.xml',
        'views/tax_mapping_views.xml',
        'views/sale_order_views.xml',
        'views/invoice_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

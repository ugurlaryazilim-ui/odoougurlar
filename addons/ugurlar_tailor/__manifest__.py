{
    'name': 'Terzi Takip',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'summary': 'Mağaza terzi takip ve yönetim sistemi — Nebim ERP entegrasyonlu',
    'description': """
        Terzi Takip Sistemi
        ====================
        * Nebim MSSQL üzerinden fatura sorgulama
        * Barkod ile ürün doğrulama
        * Terzi tanımlama ve hizmet fiyat yönetimi
        * Terziye özel fiyat matrisi
        * Sipariş oluşturma ve durum takibi
        * Termal yazıcı fiş çıktısı (QWeb)
        * Mobil uyumlu OWL frontend
        * Raporlama ve istatistik
    """,
    'author': 'Uğurlar',
    'depends': ['base', 'mail'],
    'data': [
        'security/ugurlar_tailor_security.xml',
        'security/ir.model.access.csv',
        'data/tailor_service_data.xml',
        'views/tailor_service_views.xml',
        'views/tailor_order_views.xml',
        'views/tailor_views.xml',
        'views/tailor_menu.xml',
        'views/tailor_settings_views.xml',
        'report/tailor_receipt_report.xml',
        'report/tailor_receipt_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ugurlar_tailor/static/src/css/tailor.css',
            'ugurlar_tailor/static/src/xml/tailor_templates.xml',
            'ugurlar_tailor/static/src/js/tailor_action.js',
            'ugurlar_tailor/static/src/js/screens/tailor_main_menu.js',
            'ugurlar_tailor/static/src/js/screens/tailor_new_order.js',
            'ugurlar_tailor/static/src/js/screens/tailor_order_list.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/ugurlar_tailor/static/description/icon.png',
}

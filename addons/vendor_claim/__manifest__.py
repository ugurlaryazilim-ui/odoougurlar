{
    'name': 'Tedarikçi İnceleme Takibi',
    'version': '19.0.1.2.0',
    'category': 'Inventory',
    'summary': 'Müşteriden gelen ayıplı ürünün tedarikçiye inceleme gönderimi ve dönüş takibi',
    'description': """
        Tedarikçi İnceleme Takibi
        =========================
        * Nebim fatura numarasından müşteri ve ürün bilgisi
        * Ürünün Tedarikçi özelliğinden tedarikçi kartı eşleme
        * Teslim alındı → Tedarikçide → İncelemeden geldi → Teslim edildi durum takibi
        * Gidiş / dönüş kargo takibi, fotoğraf ve tedarikçi yanıt belgesi
        * Durum değişiminde müşteriye otomatik SMS (sms_system / Turatel)
        * Tedarikçide geciken kayıtlar için uyarı
        * İnceleme talep formu ve müşteri teslim fişi çıktısı
        * Mobil ekran: fatura arama, kamera ile okutma, fotoğraf, toplu durum
    """,
    'author': 'Uğurlar',
    'depends': ['mail', 'product', 'account', 'sms_system', 'ugurlar_barcode', 'ugurlar_tailor'],
    'data': [
        'security/vendor_claim_security.xml',
        'security/ir.model.access.csv',
        'data/vendor_claim_data.xml',
        'data/vendor_claim_sms_data.xml',
        'views/vendor_claim_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/vendor_claim_menu.xml',
        'report/vendor_claim_reports.xml',
        'report/vendor_claim_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'vendor_claim/static/src/css/vendor_claim.css',
            'vendor_claim/static/src/xml/vendor_claim_templates.xml',
            'vendor_claim/static/src/js/sms_notice.js',
            'vendor_claim/static/src/js/screens/main_menu.js',
            'vendor_claim/static/src/js/screens/claim_list.js',
            'vendor_claim/static/src/js/screens/new_claim.js',
            'vendor_claim/static/src/js/screens/bulk.js',
            'vendor_claim/static/src/js/vendor_claim_action.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/vendor_claim/static/description/icon.png',
}

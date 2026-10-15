{
    'name': 'Tedarikçi İnceleme Takibi',
    'version': '19.0.1.0.0',
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
    """,
    'author': 'Uğurlar',
    'depends': ['mail', 'product', 'account', 'sms_system', 'ugurlar_tailor'],
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
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/vendor_claim/static/description/icon.png',
}

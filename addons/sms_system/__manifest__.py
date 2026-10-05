{
    'name': 'SMS Sistemi (Turatel)',
    'version': '19.0.1.3.0',
    'category': 'Marketing',
    'summary': 'Turatel üzerinden SMS gönderimi — şablonlar, gönderim kaydı, diğer modüller için ortak servis',
    'description': """
        Genel amaçlı SMS servisi:
        * Turatel XML API ile gönderim, kalan kredi sorgusu, iletim raporu
        * Şablonlar ({musteri}, {siparis} gibi yer tutucular)
        * Her gönderimin kaydı (numara, metin, durum, sağlayıcı cevabı, kaynak kayıt)
        * Test modu, başarısız gönderimleri yeniden deneme
        * Rehber ve listeler (Excel/CSV, Odoo kişileri/kullanıcılar), kara liste
        * Toplu SMS: önizleme, planlı gönderim, paketli kuyruk, günlük sınır
        * Diğer modüller: env['sms.system.message'].send_sms(numara, metin, record=kayıt)
    """,
    'author': 'Uğurlar',
    'depends': ['base', 'mail'],
    'data': [
        'security/sms_security.xml',
        'security/ir.model.access.csv',
        'data/sms_cron.xml',
        'views/sms_views.xml',
        'views/sms_bulk_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/sms_system/static/description/sms_logo.png',
}

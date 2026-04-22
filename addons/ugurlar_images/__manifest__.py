{
    'name': 'Uğurlar Resim Yönetimi',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Products',
    'summary': 'Toplu ürün görseli yükleme ve otomatik barkod eşleştirme',
    'description': """
        Uğurlar Resim Yönetimi Modülü
        ==============================
        
        Bu modül iki farklı yöntemle toplu ürün görseli yüklemeyi sağlar:
        
        1. **ZIP ile Toplu Yükleme**: Odoo arayüzünden ZIP dosyası yükleyerek
           barkod bazlı otomatik görsel eşleştirme.
        
        2. **Windows Sync Agent**: Yerel bilgisayardaki bir klasörü izleyerek
           yeni görselleri otomatik Odoo'ya yükleyen arka plan uygulaması.
        
        Görsel isimlendirme formatı: BARKOD_SIRA.uzantı
        Örnek: 8691234560001_1.jpg, 8691234560001_2.jpg
    """,
    'author': 'Uğurlar Yazılım',
    'website': 'https://ugurlar.com',
    'depends': ['product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/image_settings_views.xml',
        'views/bulk_image_wizard_views.xml',
        'views/image_sync_log_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

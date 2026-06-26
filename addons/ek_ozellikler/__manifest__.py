{
    'name': 'Uğurlar Ek Özellikler',
    'version': '19.0.1.3.0',
    'category': 'Sales/Sales',
    'summary': 'E-ticaret yayınlama, kategori eşleme, SKU/barkod gösterimi ve ek araçlar',
    'description': """
        Uğurlar Ek Özellikler Modülü
        =============================

        Ürün yönetimi için ek araçlar:

        1. **e-Ticarete Toplu Bağlama**: Ürün listesinden seçili ürünleri
           tek tıkla e-ticarete yayınlar.

        2. **Otomatik Kategori Eşleme**: Dahili ürün kategorilerini
           e-ticaret kategorilerine otomatik eşler.

        3. **SKU & Barkod Gösterimi**: Ürün detay sayfasında SKU ve barkod
           bilgisini dinamik olarak gösterir (renk/beden değişince güncellenir).

        4. İleride eklenecek diğer ek özellikler.
    """,
    'author': 'Uğurlar Yazılım',
    'website': 'https://ugurlar.com',
    'depends': ['product', 'website_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/server_actions.xml',
        'views/settings_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ek_ozellikler/static/src/js/product_sku_barcode.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

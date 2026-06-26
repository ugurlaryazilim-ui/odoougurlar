{
    'name': 'Uğurlar Ek Özellikler',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'E-ticaret yayınlama, kategori eşleme ve ek araçlar',
    'description': """
        Uğurlar Ek Özellikler Modülü
        =============================

        Ürün yönetimi için ek araçlar:

        1. **e-Ticarete Toplu Bağlama**: Ürün listesinden seçili ürünleri
           tek tıkla e-ticarete yayınlar.

        2. **Otomatik Kategori Eşleme**: Dahili ürün kategorilerini
           e-ticaret kategorilerine otomatik eşler.

        3. İleride eklenecek diğer ek özellikler.
    """,
    'author': 'Uğurlar Yazılım',
    'website': 'https://ugurlar.com',
    'depends': ['product', 'website_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/server_actions.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

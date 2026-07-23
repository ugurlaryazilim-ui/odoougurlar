# -*- coding: utf-8 -*-
{
    'name': 'Uğurlar Nebim - Toptan Alış Fatura Arşivleyici (ZIP)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Nebim Toptan Alış Faturalarını Marka ve Ürün Grubu bazında tarayıp PDF olarak ZIP indirir.',
    'description': """
        Toptan Alış Fatura Arşiv Sihirbazı
        ===================================
        - Marka ve Ürün Grubu seçimi.
        - Nebim Toptan Alış belgelerinin otomatik taranıp tekleştirilmesi.
        - Doğan E-Dönüşüm / Nebim servislerinden PDF indirilmesi.
        - Tüm PDF'lerin marka-ürüngrubu-tarih-saat.zip olarak indirilmesi.
    """,
    'author': 'Uğurlar Grup',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'product',
        'account',
        'odoougurlar',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/dogan_config.xml',
        'views/invoice_collector_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

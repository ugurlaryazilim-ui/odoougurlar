# -*- coding: utf-8 -*-
{
    'name': 'Kargo (Çekirdek)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Sağlayıcıdan bağımsız kargo gönderisi çekirdeği (firma ayarları, gruplar, yönetilen firma kancaları)',
    'description': """
Kargo çekirdeği
===============

* Kargo firması/hesabı = ``delivery.carrier`` (sağlayıcı eklentisi ``delivery_type`` ekler)
* Sağlayıcı arayüzü: ``<delivery_type>_cargo_send|cancel|find|track|cod_code``
* Varsayılan firma, ağırlık, kapıda ödeme üst sınırı ve etiket sayfası ayarları
* Gruplar: Kargo / Kullanıcı, Kargo / Yönetici
""",
    'author': 'Uğurlar',
    'license': 'LGPL-3',
    # NEDEN: stock_delivery -> delivery + sale_stock; picking'deki carrier_id/carrier_tracking_ref
    # ve "Send to Shipper" akışı oradadır (bkz. KARARLAR K-20).
    'depends': ['mail', 'stock_delivery'],
    # Sıra: veri -> security xml -> csv -> görünümler -> menüler.
    'data': [
        'data/ir_sequence.xml',
        'security/cargo_security.xml',
        'security/ir.model.access.csv',
        'wizard/cargo_shipment_missing_views.xml',
        'views/delivery_carrier_views.xml',
        'views/res_config_settings_views.xml',
        'views/cargo_area_views.xml',
        'views/cargo_shipment_views.xml',
        'views/stock_picking_views.xml',
        'views/cargo_menus.xml',
    ],
    'application': True,
    'installable': True,
}

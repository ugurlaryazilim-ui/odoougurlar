# -*- coding: utf-8 -*-
{
    'name': 'Kargo - UPS Türkiye',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'UPS Türkiye kargo sağlayıcısı (hesap alanları, il/ilçe kodları) - kargo çekirdeği eklentisi',
    'description': """
Kargo - UPS Türkiye
===================

* ``delivery.carrier`` için ``ups_tr`` sağlayıcı tipi (hesap bilgileri yalnız Kargo / Yönetici)
* UPS il/ilçe kodları (``cargo.area``, 1014 ilçe, KKTC hariç) ve kesin ad değişikliği takma adları
* Hazır UPS Türkiye firma kaydı: test ucunda (``prod_environment`` kapalı), kapıda ödeme açık (yalnız nakit)
""",
    'author': 'Uğurlar',
    'license': 'LGPL-3',
    # NEDEN: yeni bağımlılık yok; il/ilçe modeli, gruplar ve firma kancaları çekirdekte (K-20, K-22).
    'depends': ['cargo'],
    # Sıra: ilçe kodları -> takma adlar (aynı kayıtlara xmlid ile bağlanır) -> firma kaydı -> görünüm.
    'data': [
        'data/cargo.area.csv',
        'data/cargo_area_alias_data.xml',
        'data/delivery_carrier_data.xml',
        'views/delivery_carrier_views.xml',
    ],
    'installable': True,
}

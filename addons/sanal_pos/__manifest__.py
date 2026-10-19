# -*- coding: utf-8 -*-
{
    'name': 'Sanal POS (Ödeme Linki)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment',
    'summary': 'Nebim faturasına bağlı Paratika ödeme linki oluşturma, takip, iptal ve iade',
    'description': """
Sanal POS / Ödeme Linki
=======================

* Nebim fatura numarasından ödeme linki oluşturma (Paratika)
* Durum takibi (webhook tetiği + sorgu ile doğrulama, cron uzlaştırma)
* Ödeme iptali (VOID) ve iade (REFUND)
* Sağlayıcı katmanı (yeni sağlayıcı = yeni ``sanal.pos.provider.<kod>`` modeli)
""",
    'author': 'Uğurlar',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'external_dependencies': {'python': ['requests']},
    # Sıra: security xml -> csv -> data -> sihirbaz görünümleri -> görünümler -> menüler.
    # data/sql/*.sql dosyaları BELGEDİR; manifest'e eklenmez, Odoo çalıştırmaz.
    'data': [
        'security/sanal_pos_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron.xml',
        'wizard/payment_create_wizard_views.xml',
        'wizard/review_close_wizard_views.xml',
        'wizard/payment_resend_wizard_views.xml',
        'wizard/payment_refund_wizard_views.xml',
        'views/sanal_pos_payment_views.xml',
        'views/sanal_pos_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'application': True,
    'installable': True,
}

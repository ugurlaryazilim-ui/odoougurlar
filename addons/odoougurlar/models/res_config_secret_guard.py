# -*- coding: utf-8 -*-
"""Ayar ekranı sır koruması (A5 K1): tüm kurulu modüllerin res.config.settings sırları.

Çekirdek ``res.config.settings.default_get`` (base/models/res_config.py) config_parameter
değerlerini ``ir.config_parameter.sudo()`` ile okur, alan ``groups=`` kısıtını uygulamaz ve
sonuna ``get_values()`` ekler. ``default_get``/``get_values`` ``@api.model`` herkese açık
metotlardır: RPC dağıtıcısı model ACL'sine bakmaz, yani her iç kullanıcı tek istekle tüm
ayar sırlarını okuyabilir (DERSLER 19.10).

res.config.settings tek birleşik model olduğundan buradaki override tüm modüllerin
alanlarını kapsar. odoougurlar canlıda her zaman kuruludur (Nebim entegrasyonu).

read/onchange için ayrı kod yok: res.config.settings ACL'i yalnız base.group_system'de
(çekirdek), onchange(yeni kayıt) create denetiminde AccessError verir; ACL veren başka bir
modül olsa da kayıt bu filtreli varsayılanlarla oluşur.
"""
from odoo import api, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    @api.model
    def _ugurlar_secret_fields(self):
        """Sistem yöneticisi olmayana dönmemesi gereken alan adları."""
        names = set()
        for name, field in self._fields.items():
            if field.groups and not self._has_field_access(field, 'read'):
                names.add(name)
                continue
            # NEDEN: ad kalıbı kara listesi sızdırıyordu (nebim_url/MSSQL sunucu, twilio sid gibi kalıba
            # uymayan ama hassas değerler). Ayar ekranı yalnız group_system'e açık; yönetici olmayanın
            # hiçbir config_parameter değerine ihtiyacı yok -> hepsi düşer (kara liste yerine toptan).
            if getattr(field, 'config_parameter', None):
                names.add(name)
        return names

    @api.model
    def _ugurlar_drop_secrets(self, res):
        # DIKKAT: superuser/sudo (cron, set_values içindeki default_get) ve sistem yöneticisi tam görür.
        if self.env.su or self.env.user.has_group('base.group_system'):
            return res
        for name in self._ugurlar_secret_fields():
            res.pop(name, None)
        return res

    @api.model
    def default_get(self, fields):
        return self._ugurlar_drop_secrets(super().default_get(fields))

    @api.model
    def get_values(self):
        return self._ugurlar_drop_secrets(super().get_values())

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
import re

from odoo import api, models

# NEDEN: adı/parametresi bu kalıba uyan metin alanı sır sayılır (groups= unutulmuş çekirdek ve
# modül alanları: google_gmail_client_secret, twilio_account_token, *_api_key ...). Fazla eşleşme
# zararsız: sistem yöneticisi olmayan ayarları zaten kaydedemez (çekirdek execute is_admin).
_SECRET_NAME_RE = re.compile(r'key|secret|password|passwd|token|sifre', re.IGNORECASE)


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
            icp = getattr(field, 'config_parameter', None)
            if icp and field.type in ('char', 'text') and _SECRET_NAME_RE.search(name + ' ' + icp):
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

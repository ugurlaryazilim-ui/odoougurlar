# -*- coding: utf-8 -*-
"""Sanal POS ayarları (tasarım §12). Ayarlar yalnız base.group_system'dedir.

Sır alanları (Paratika şifresi, secretKey, MSSQL kullanıcı/şifre)
``groups='base.group_system'`` taşır. Değerleri kod tarafında yalnız
``ir.config_parameter.sudo().get_param`` ile okunur; loglara girmez.

Boolean ayar tuzağı: Odoo boolean ``config_parameter`` alanı kapatılınca
parametre satırını SİLER ve okurken yokluğu alan varsayılanına çevirir.
Varsayılanı True olan ``require_contact`` bu yüzden ekrandan kapatılamazdı;
bu sınıf onu açıkça ``'True'/'False'`` olarak saklar. Kod tarafında okurken
``get_bool_param`` kullanılır (diğer boolean ayarlar: yok = False).
"""
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# Varsayılanı True olan boolean ayarlar: alan adı -> parametre anahtarı
_TRUE_DEFAULT_BOOLS = {'sanal_pos_require_contact': 'sanal_pos.require_contact'}
_FALSE_VALUES = ('', 'false', '0', 'no', 'none')
# Yalnız sistem yöneticisinin görebileceği sır alanları (default_get sızıntısı için)
_SECRET_FIELDS = (
    'sanal_pos_paratika_merchant_password',
    'sanal_pos_paratika_secret_key',
    'sanal_pos_mssql_user',
    'sanal_pos_mssql_password',
)
_VIEW_NAME_RE = re.compile(r'^[\w.\[\]]+$')

# (ugurlar_tailor.<ad> parametresi, sanal_pos ayar alanı); hedef parametre sanal_pos.<ad>
# Modül bağımlılığı YOK: yalnız ir.config_parameter okunur.
_TAILOR_MSSQL_MAP = (
    ('mssql_server', 'sanal_pos_mssql_server'),
    ('mssql_port', 'sanal_pos_mssql_port'),
    ('mssql_database', 'sanal_pos_mssql_database'),
    ('mssql_user', 'sanal_pos_mssql_user'),
    ('mssql_password', 'sanal_pos_mssql_password'),
    ('mssql_view_name', 'sanal_pos_mssql_view_name'),
)


def get_bool_param(env, key, default=False):
    """Boolean ayarı güvenle okur (yok -> ``default``; 'False'/'0' -> False)."""
    value = env['ir.config_parameter'].sudo().get_param(key)
    if value is False or value is None:
        return default
    return str(value).strip().lower() not in _FALSE_VALUES


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ---------------------------------------------------------------- genel
    sanal_pos_provider = fields.Selection(
        [('paratika', 'Paratika')], string='Sanal POS sağlayıcısı',
        config_parameter='sanal_pos.provider', default='paratika')
    sanal_pos_environment = fields.Selection(
        [('test', 'Test'), ('live', 'Canlı')], string='Ortam',
        config_parameter='sanal_pos.environment', default='test')
    sanal_pos_default_expiry_hours = fields.Integer(
        string='Varsayılan link geçerlilik süresi (saat)',
        config_parameter='sanal_pos.default_expiry_hours', default=168,
        help='1 ile 168 saat (7 gün) arası.')
    sanal_pos_ascii_mode = fields.Boolean(
        string="Türkçe karakterleri ASCII'ye çevir",
        config_parameter='sanal_pos.ascii_mode', default=False,
        help='Paratika Türkçe karakterleri kabul etmezse açın (Ç->C, ş->s ...).')
    sanal_pos_require_contact = fields.Boolean(
        string='E-posta ve telefon zorunlu',
        config_parameter='sanal_pos.require_contact', default=True,
        help='Açıkken link oluşturmak için geçerli e-posta ve telefon gerekir.')

    # ---------------------------------------------------------------- Paratika
    sanal_pos_paratika_merchant = fields.Char(
        string='Üye iş yeri kodu (MERCHANT)', config_parameter='sanal_pos.paratika_merchant')
    sanal_pos_paratika_merchant_user = fields.Char(
        string='API kullanıcı adı (MERCHANTUSER)', config_parameter='sanal_pos.paratika_merchant_user')
    sanal_pos_paratika_merchant_password = fields.Char(
        string='API şifresi (MERCHANTPASSWORD)', groups='base.group_system',
        config_parameter='sanal_pos.paratika_merchant_password')
    sanal_pos_paratika_secret_key = fields.Char(
        string='Gizli anahtar (secretKey)', groups='base.group_system',
        config_parameter='sanal_pos.paratika_secret_key')
    sanal_pos_paratika_test_url = fields.Char(
        string='Test API adresi', config_parameter='sanal_pos.paratika_test_url',
        default='https://test.paratika.com.tr/paratika/api/v2')
    sanal_pos_paratika_live_url = fields.Char(
        string='Canlı API adresi', config_parameter='sanal_pos.paratika_live_url',
        default='https://vpos.paratika.com.tr/paratika/api/v2',
        help='Paratika ile teyit edilmelidir.')
    sanal_pos_paratika_phone_format = fields.Selection(
        [('10', '5321112233'), ('0', '05321112233'),
         ('90', '905321112233'), ('+90', '+905321112233')],
        string='Telefon biçimi', config_parameter='sanal_pos.paratika_phone_format', default='10')
    sanal_pos_paratika_show_link_url = fields.Boolean(
        string='Link adresini göster', config_parameter='sanal_pos.paratika_show_link_url',
        default=False, help='Paratika link adresi biçimi teyit edilene kadar kapalı kalmalıdır.')

    # ---------------------------------------------------------------- Nebim MSSQL
    sanal_pos_mssql_server = fields.Char(
        string='SQL Server adresi', config_parameter='sanal_pos.mssql_server')
    sanal_pos_mssql_port = fields.Integer(
        string='SQL port', config_parameter='sanal_pos.mssql_port', default=1433)
    sanal_pos_mssql_database = fields.Char(
        string='SQL veritabanı', config_parameter='sanal_pos.mssql_database')
    sanal_pos_mssql_view_name = fields.Char(
        string='Fatura görünümü adı', config_parameter='sanal_pos.mssql_view_name',
        default='dbo.vw_TerziFaturalar')
    sanal_pos_mssql_user = fields.Char(
        string='SQL kullanıcı adı', groups='base.group_system',
        config_parameter='sanal_pos.mssql_user')
    sanal_pos_mssql_password = fields.Char(
        string='SQL şifre', groups='base.group_system',
        config_parameter='sanal_pos.mssql_password')

    sanal_pos_has_tailor_mssql = fields.Boolean(
        string='Terzi MSSQL ayarı var', compute='_compute_sanal_pos_has_tailor_mssql')

    # ---------------------------------------------------------------- bilgi (salt okunur)
    sanal_pos_notify_url = fields.Char(
        string='Bildirim adresi', compute='_compute_sanal_pos_urls',
        help="Paratika panelinde bildirim URL'si olarak tanımlanır.")
    sanal_pos_return_url = fields.Char(
        string='Dönüş adresi', compute='_compute_sanal_pos_urls')

    def _compute_sanal_pos_urls(self):
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        for rec in self:
            rec.sanal_pos_notify_url = '%s/sanal_pos/paratika/notify' % base
            rec.sanal_pos_return_url = '%s/sanal_pos/paratika/return' % base

    def _compute_sanal_pos_has_tailor_mssql(self):
        has = bool(self.env['ir.config_parameter'].sudo().get_param('ugurlar_tailor.mssql_server'))
        for rec in self:
            rec.sanal_pos_has_tailor_mssql = has

    def action_copy_tailor_mssql(self):
        """Terzi modülünün MSSQL ayarlarını Sanal POS ayarlarına kopyalar (yalnız sistem yöneticisi).

        ``ugurlar_tailor`` modülüne bağımlılık yoktur; yalnız ``ir.config_parameter``
        okunur. Terzi tarafında boş olan değer mevcut Sanal POS ayarını boşaltmaz.
        """
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('Bu işlemi yalnız sistem yöneticisi yapabilir.')
        ICP = self.env['ir.config_parameter'].sudo()
        if not ICP.get_param('ugurlar_tailor.mssql_server'):
            raise UserError('Terzi ayarlarında MSSQL bilgisi bulunamadı; kopyalanacak bir şey yok.')
        values = {}
        for tailor_name, fname in _TAILOR_MSSQL_MAP:
            raw = ICP.get_param('ugurlar_tailor.%s' % tailor_name)
            if not raw:
                continue
            if tailor_name == 'mssql_view_name' and not _VIEW_NAME_RE.match(raw):
                continue
            if tailor_name == 'mssql_port':
                try:
                    raw = int(raw)
                except ValueError:
                    continue
            values[fname] = raw
        for fname, raw in values.items():
            ICP.set_param('sanal_pos.%s' % fname[len('sanal_pos_'):], str(raw))
        if values:
            self.write(values)  # açık ayar ekranındaki eski değer ile geri ezilmesin
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ---------------------------------------------------------------- doğrulama
    @api.constrains('sanal_pos_default_expiry_hours')
    def _check_sanal_pos_expiry(self):
        for rec in self:
            if not 1 <= rec.sanal_pos_default_expiry_hours <= 168:
                raise ValidationError(
                    'Link geçerlilik süresi 1 ile 168 saat arasında olmalıdır.')

    @api.constrains('sanal_pos_mssql_view_name')
    def _check_sanal_pos_view_name(self):
        for rec in self:
            name = rec.sanal_pos_mssql_view_name
            if name and not _VIEW_NAME_RE.match(name):
                raise ValidationError(
                    'Görünüm adı yalnız harf, rakam, alt çizgi, nokta ve köşeli parantez içerebilir.')

    # ---------------------------------------------------------------- boolean tuzağı
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if not self.env.user.has_group('base.group_system'):
            # Odoo config_parameter değerlerini sudo ile okur; alan 'groups' kısıtı
            # default_get yolunda uygulanmaz. Sır değerleri RPC ile sızmasın.
            for fname in _SECRET_FIELDS:
                res.pop(fname, None)
        for fname, key in _TRUE_DEFAULT_BOOLS.items():
            if not fields_list or fname in fields_list:
                res[fname] = get_bool_param(self.env, key, default=True)
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        for fname, key in _TRUE_DEFAULT_BOOLS.items():
            ICP.set_param(key, 'True' if self[fname] else 'False')

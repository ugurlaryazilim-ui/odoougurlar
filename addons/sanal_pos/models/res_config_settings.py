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
from urllib.parse import urlsplit

from markupsafe import Markup

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
# Kaydederken baş/son boşluğu temizlenen alanlar
_STRIP_FIELDS = (
    'sanal_pos_paratika_merchant',
    'sanal_pos_paratika_merchant_user',
    'sanal_pos_paratika_merchant_password',
    'sanal_pos_paratika_secret_key',
    'sanal_pos_paratika_test_url',
    'sanal_pos_paratika_live_url',
)
# Bağlantı testinde kimlik alanları: (alan, Paratika parametresi, ekrandaki ad)
_CREDENTIAL_FIELDS = (
    ('sanal_pos_paratika_merchant', 'MERCHANT', 'Üye iş yeri kodu'),
    ('sanal_pos_paratika_merchant_user', 'MERCHANTUSER', 'API kullanıcı adı'),
    ('sanal_pos_paratika_merchant_password', 'MERCHANTPASSWORD', 'API şifresi'),
)
_ENV_NAMES = {'test': 'Test', 'live': 'Canlı'}

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

    # ---------------------------------------------------------------- bağlantı testi
    def action_sanal_pos_test_connection(self):
        """Ekrandaki Paratika bilgileriyle bağlantıyı dener.

        Arayüzde ayar formu kirliyse Odoo önce kaydetmeyi sorar; bu yüzden pratikte kayıtlı
        değerler denenir. RPC ile kaydedilmemiş değerler de denenebilir.

        Önce yerel kontroller (eksik alan, boşluk, adres, ortam-adres uyumu, sistem adresi),
        sonra salt-okuma bir sorgu gönderilir. Link oluşmaz, para hareketi olmaz.
        Sonuç ``sanal.pos.connection.test.wizard`` penceresinde gösterilir.
        """
        # provider_paratika bu modülü içe aktarır; döngü olmasın diye burada alınır
        from .provider_paratika import DEFAULT_LIVE_URL, DEFAULT_TEST_URL

        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('Bu işlemi yalnız sistem yöneticisi yapabilir.')
        environment = self.sanal_pos_environment or 'test'
        env_name = _ENV_NAMES.get(environment, environment)
        other_name = _ENV_NAMES['live' if environment == 'test' else 'test']
        errors, warnings, notes = [], [], []

        # 1) Kimlik alanları: boş mu, baş/son boşluk var mı
        credentials, missing, padded = {}, [], []
        for fname, param, label in _CREDENTIAL_FIELDS:
            raw = self[fname] or ''
            value = raw.strip()
            if not value:
                missing.append(label)
            elif value != raw:
                padded.append(label)
            credentials[param] = value
        if missing:
            errors.append('Eksik alan: %s.' % ', '.join(missing))
        if padded:
            warnings.append(
                '%s başında/sonunda boşluk vardı. Test boşluksuz değerle yapıldı; '
                '"Kaydet"e basınca boşluk temizlenir.' % ', '.join(padded))

        # 2) API adresi
        if environment == 'live':
            api_url = (self.sanal_pos_paratika_live_url or '').strip() or DEFAULT_LIVE_URL
        else:
            api_url = (self.sanal_pos_paratika_test_url or '').strip() or DEFAULT_TEST_URL
        api_url = api_url.rstrip('/')
        parts = urlsplit(api_url)
        host = (parts.hostname or '').lower()
        if parts.scheme not in ('http', 'https') or not host:
            errors.append('%s API adresi geçersiz: %s' % (env_name, api_url))
        else:
            if parts.scheme != 'https':
                warnings.append('%s API adresi https değil: %s' % (env_name, api_url))
            if environment == 'live' and 'test' in host:
                warnings.append(
                    'Ortam "Canlı" seçili ama canlı API adresi test sunucusunu gösteriyor (%s).'
                    % host)
            elif environment == 'test' and 'test' not in host:
                warnings.append(
                    'Ortam "Test" seçili ama test API adresi test sunucusu gibi görünmüyor (%s).'
                    % host)
        notes.append('Ortam: %s — adres: %s' % (env_name, api_url))
        if credentials.get('MERCHANT'):
            notes.append('Üye iş yeri: %s — kullanıcı: %s'
                         % (credentials['MERCHANT'], credentials.get('MERCHANTUSER') or '-'))

        # 3) Sistem adresi (dönüş/bildirim adresi buradan üretilir)
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').strip()
        if not base:
            warnings.append('Sistem adresi (web.base.url) boş; ödeme dönüş adresi üretilemez.')
        elif not base.isascii():
            warnings.append('Sistem adresi (web.base.url) Türkçe/ASCII dışı karakter içeriyor; '
                            'link oluşturulamaz.')
        elif not base.lower().startswith('https://'):
            warnings.append(
                'Sistem adresi (web.base.url) https değil: %s. Dönüş ve bildirim adresleri '
                'http gider; Paratika canlıda https isteyebilir. Sistem parametrelerinde '
                'web.base.url\'i https yapıp web.base.url.freeze = True ekleyin.' % base)

        # 4) Paratika'ya salt-okuma sorgu (yerel hata yoksa)
        if errors:
            level = 'danger'
            summary = 'Test yapılmadı: önce aşağıdaki hataları düzeltin.'
        else:
            provider_name = 'sanal.pos.provider.%s' % (self.sanal_pos_provider or 'paratika')
            if provider_name not in self.env:
                raise UserError('Bilinmeyen ödeme sağlayıcısı: %s' % self.sanal_pos_provider)
            res = self.env[provider_name].test_connection(environment, credentials, api_url)
            level, summary = self._sanal_pos_connection_verdict(
                res, env_name, other_name, errors, notes)
            if level == 'success' and warnings:
                level = 'warning'
                summary += ' Ancak aşağıdaki uyarılara bakın.'

        wizard = self.env['sanal.pos.connection.test.wizard'].create({
            'level': level,
            'summary': summary,
            'details': self._sanal_pos_connection_html(errors, warnings, notes),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Paratika Bağlantı Testi',
            'res_model': 'sanal.pos.connection.test.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @staticmethod
    def _sanal_pos_connection_verdict(res, env_name, other_name, errors, notes):
        """Sağlayıcı sonucunu (seviye, özet) çiftine çevirir; açıklamaları listelere ekler."""
        code = res.get('error_code') or ''
        message = res.get('error_message') or ''
        problem = res.get('problem')
        if problem is None:
            if code:
                notes.append('Deneme sorgusunun yanıtı: %s (kimlik doğrulandıktan sonra '
                              'verilen olağan bir yanıt).' % code)
            return 'success', 'Bağlantı başarılı: Paratika kullanıcıyı doğruladı (%s ortamı).' % env_name
        if problem == 'auth':
            errors.append(
                'Paratika kullanıcı adı/şifreyi reddetti (%s). Olası nedenler: '
                '(1) bilgiler %s ortamına ait — "Ortam"ı %s yapıp kaydedin ve tekrar deneyin; '
                '(2) şifre yanlış, süresi dolmuş ya da ilk girişte değiştirilmesi gerekiyor; '
                '(3) kullanıcı Paratika\'da API kullanıcısı olarak tanımlı değil.'
                % (code, other_name, other_name))
            return 'danger', 'Kimlik doğrulanamadı (%s ortamı).' % env_name
        if problem == 'permission':
            errors.append(
                'Kullanıcı tanındı ama API yetkisi eksik (%s: %s). Paratika\'dan API ve '
                '"link ile ödeme" yetkisini açmasını isteyin.' % (code, message))
            return 'danger', 'API yetkisi eksik (%s ortamı).' % env_name
        if problem == 'network':
            errors.append(
                'Paratika\'ya ulaşılamadı (ağ hatası ya da zaman aşımı). Sunucunun internet '
                'erişimini ve API adresini kontrol edin; Paratika IP kısıtı uyguluyorsa '
                'sunucu IP\'sini bildirin.')
            return 'danger', 'Paratika\'ya ulaşılamadı.'
        if problem == 'address':
            errors.append('Adres Paratika API yanıtı vermedi (%s: %s). API adresini kontrol edin.'
                          % (code, message))
            return 'danger', 'API adresi hatalı görünüyor.'
        errors.append(message or 'Paratika ayarları eksik.')
        return 'danger', 'Test yapılamadı.'

    @staticmethod
    def _sanal_pos_connection_html(errors, warnings, notes):
        sections = []
        for title, items in (('Hatalar', errors), ('Uyarılar', warnings), ('Bilgi', notes)):
            if items:
                sections.append(Markup('<p><strong>%s</strong></p><ul>%s</ul>') % (
                    title, Markup('').join(Markup('<li>%s</li>') % item for item in items)))
        return Markup('').join(sections)

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
        # G-2: çekirdek set_values yönetici denetimi yapmaz (denetim yalnız execute'ta) ve
        # RPC'ye açıktır; boş kayıt kümesiyle çağrı tüm config parametrelerini/grupları boş
        # değerle ezmeye başlar. Denetim HER yazmadan önce yapılmalı.
        if not self.env.is_superuser() and not self.env.user.has_group('base.group_system'):
            raise AccessError('Ayarları yalnız sistem yöneticisi değiştirebilir.')
        # Kopyala-yapıştırla gelen baş/son boşluk kaydedilmesin (Paratika ERR10020 verir)
        for rec in self:
            for fname in _STRIP_FIELDS:
                value = rec[fname]
                if value and value != value.strip():
                    rec[fname] = value.strip()
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        for fname, key in _TRUE_DEFAULT_BOOLS.items():
            ICP.set_param(key, 'True' if self[fname] else 'False')

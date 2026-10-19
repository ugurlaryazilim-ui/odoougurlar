from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services.smartadm import SmartAdmError
from ..services.turatel import ERROR_HINTS, TuratelError
from ..services.turatel_json import TuratelJsonClient, mask_digits
from .sms_message import (API_MODES, DEFAULT_ACCOUNT_COMMERCIAL, DEFAULT_ACCOUNT_INFO, DEFAULT_BULK_URL,
                          DEFAULT_JSON_USER_ID, DEFAULT_SINGLE_URL, DEFAULT_VALIDITY_MINUTES, parse_user_daily_limit,
                          parse_validity_minutes, resolve_api_mode, test_mode_enabled)

# JSON API (C1): ekran alanı -> ir.config_parameter anahtarı. Hepsi get_values/set_values'ta AÇIKÇA okunup yazılır
# (config_parameter kullanılmaz): boş değer parametreyi siler, okuma varsayılanı bu tabloya göre döner.
_JSON_TEXT_PARAMS = {
    'sms_json_info_user_id': 'sms_system.turatel_json_info_user_id',
    'sms_json_info_username': 'sms_system.turatel_json_info_username',
    'sms_json_info_password': 'sms_system.turatel_json_info_password',
    'sms_account_info': 'sms_system.turatel_account_info',
    'sms_json_com_user_id': 'sms_system.turatel_json_com_user_id',
    'sms_json_com_username': 'sms_system.turatel_json_com_username',
    'sms_json_com_password': 'sms_system.turatel_json_com_password',
    'sms_account_commercial': 'sms_system.turatel_account_commercial',
    'sms_single_url': 'sms_system.turatel_single_url',
    'sms_bulk_url': 'sms_system.turatel_bulk_url',
}
_JSON_DEFAULTS = {
    'sms_json_info_user_id': DEFAULT_JSON_USER_ID, 'sms_json_com_user_id': DEFAULT_JSON_USER_ID,
    'sms_account_info': DEFAULT_ACCOUNT_INFO, 'sms_account_commercial': DEFAULT_ACCOUNT_COMMERCIAL,
    'sms_single_url': DEFAULT_SINGLE_URL, 'sms_bulk_url': DEFAULT_BULK_URL,
}
_JSON_PASSWORDS = ('sms_json_info_password', 'sms_json_com_password')
_JSON_SETS = (('info', 'Bilgi'), ('commercial', 'Reklam'))   # düğmelerde her kimlik seti ayrı satır (C6)
_KIND_RANK = {'success': 0, 'warning': 1, 'danger': 2}
_JSON_DIGIT_FIELDS = ('sms_json_info_user_id', 'sms_account_info', 'sms_json_com_user_id', 'sms_account_commercial')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sms_turatel_url = fields.Char(string='Turatel API Adresi', config_parameter='sms_system.turatel_url',
                                  help='Boşsa https://processor.smsorigin.com/xml/process.aspx kullanılır')
    sms_turatel_channel_code = fields.Char(string='Kanal Kodu', config_parameter='sms_system.turatel_channel_code',
                                           groups='base.group_system')
    sms_turatel_username = fields.Char(string='Kullanıcı Adı', config_parameter='sms_system.turatel_username',
                                       groups='base.group_system')
    sms_turatel_password = fields.Char(string='Şifre', config_parameter='sms_system.turatel_password',
                                       groups='base.group_system')
    sms_turatel_originator = fields.Char(string='Mesaj Başlığı', config_parameter='sms_system.turatel_originator',
                                         help='Turatel hesabında onaylı gönderici adı (en fazla 11 karakter)')
    sms_ascii_mode = fields.Boolean(string='Türkçe karakterleri dönüştür', config_parameter='sms_system.ascii_mode',
                                    help='ı ş ğ İ Ş Ğ harflerini i s g I S G yapar; mesaj daha az parçaya bölünür')
    # config_parameter KULLANILMAZ: çekirdek set_values False/0 değerinde parametreyi siliyor, get_values ise
    # 'False' metnini True okuyor. get_values/set_values aşağıda açık yazılır (test modu: K2).
    sms_test_mode = fields.Boolean(string='Test modu',
                                   help='Açıkken SMS gönderilmez, yalnız kayıt oluşur')

    sms_daily_limit = fields.Integer(string='Günlük toplu SMS sınırı', config_parameter='sms_system.daily_limit',
                                     help='Son 24 saatte toplu SMS ile gönderilebilecek en fazla numara (0 = sınırsız)')
    sms_user_daily_limit = fields.Integer(string='Kullanıcı başı günlük elle SMS',
                                          help='"Yeni SMS" ile bir çalışanın 24 saatte gönderebileceği en fazla SMS '
                                               '(SMS yöneticileri ve otomatik bildirimler hariç; 0 = sınırsız)')
    sms_optout_text = fields.Char(string='Ret metni', config_parameter='sms_system.optout_text',
                                  help='Ticari SMS sonuna eklenir; ör. "SMS almamak için RET yazıp 4609 a gönderin"')

    # ── Turatel JSON API (C1) ── config_parameter YOK: get_values/set_values açık yazar (bkz. _JSON_TEXT_PARAMS)
    sms_api_mode = fields.Selection([('legacy_xml', 'Eski XML API'), ('json', 'JSON API')], string='API Modu',
                                    default='legacy_xml',
                                    help='Eski XML API varsayılandır. JSON API için bilgi kimlik seti zorunludur.')
    sms_json_info_user_id = fields.Char(string='Bilgi: Kullanıcı No (userId)', groups='base.group_system',
                                        help='Boşsa %s' % DEFAULT_JSON_USER_ID)
    sms_json_info_username = fields.Char(string='Bilgi: Kullanıcı Adı', groups='base.group_system')
    sms_json_info_password = fields.Char(string='Bilgi: Şifre', groups='base.group_system')
    sms_account_info = fields.Char(string='Bilgi Hesabı (accountId)', groups='base.group_system',
                                   help='Tekli SMS ile bilgilendirme/personel kampanyası hesabı; varsayılan %s'
                                        % DEFAULT_ACCOUNT_INFO)
    sms_json_com_user_id = fields.Char(string='Reklam: Kullanıcı No (userId)', groups='base.group_system',
                                       help='Varsayılan %s; bilgi setinden bağımsızdır' % DEFAULT_JSON_USER_ID)
    sms_json_com_username = fields.Char(string='Reklam: Kullanıcı Adı', groups='base.group_system')
    sms_json_com_password = fields.Char(string='Reklam: Şifre', groups='base.group_system')
    sms_account_commercial = fields.Char(string='Reklam Hesabı (accountId)', groups='base.group_system',
                                         help='Ticari kampanya hesabı; varsayılan %s' % DEFAULT_ACCOUNT_COMMERCIAL)
    sms_single_url = fields.Char(string='JSON Tekli SMS Adresi (singlesms)', groups='base.group_system',
                                 help='Boşsa %s' % DEFAULT_SINGLE_URL)
    sms_bulk_url = fields.Char(string='JSON Toplu SMS Adresi (bulksms)', groups='base.group_system',
                               help='Boşsa %s' % DEFAULT_BULK_URL)
    sms_validity_minutes = fields.Integer(string='Geçerlilik Süresi (dk)',
                                          help='SMS operatörde bu süre içinde iletilemezse düşer; boş/0 = %d dk'
                                               % DEFAULT_VALIDITY_MINUTES)

    sms_iys_enabled = fields.Boolean(string='İYS kontrolü etkin', config_parameter='sms_system.iys_enabled',
                                     help='Açıkken ticari SMS yalnız İYS onaylı numaralara gider ve rehber otomatik senkronlanır')
    sms_iys_customer_code = fields.Char(string='SmartADM Müşteri Kodu', config_parameter='sms_system.iys_customer_code',
                                        groups='base.group_system')
    sms_iys_username = fields.Char(string='SmartADM Kullanıcı Adı', config_parameter='sms_system.iys_username',
                                   groups='base.group_system')
    sms_iys_password = fields.Char(string='SmartADM Şifre', config_parameter='sms_system.iys_password',
                                   groups='base.group_system')
    sms_iys_store = fields.Char(string='Mağaza Adı (RemoteStoreId)', config_parameter='sms_system.iys_store',
                                help='İsteğe bağlı; SmartADM kayıtlarında işlemin hangi mağazadan yapıldığı görünür')
    sms_iys_url = fields.Char(string='SmartADM API Adresi', config_parameter='sms_system.iys_url',
                              help='Boşsa https://adm.smartadm.net/webservice/api')

    @api.model
    def _drop_restricted_sms_values(self, res):
        """Sistem yöneticisi olmayandan groups'lu sms_* alanlarını düşür (DERSLER 19.10).

        default_get ve get_values RPC'ye açıktır ve config_parameter sırlarını sudo ile okuyabilir.
        """
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            for name, field in self._fields.items():
                if name.startswith('sms_') and field.groups:
                    res.pop(name, None)
        return res

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        res['sms_test_mode'] = test_mode_enabled(icp.get_param('sms_system.test_mode'))
        res['sms_user_daily_limit'] = parse_user_daily_limit(icp.get_param('sms_system.user_daily_limit'))
        res['sms_api_mode'] = resolve_api_mode(icp.get_param('sms_system.api_mode'))
        for name, key in _JSON_TEXT_PARAMS.items():
            res[name] = icp.get_param(key) or _JSON_DEFAULTS.get(name, '')
        res['sms_validity_minutes'] = parse_validity_minutes(icp.get_param('sms_system.turatel_validity_minutes'))
        return self._drop_restricted_sms_values(res)

    def set_values(self):
        # Çekirdek set_values RPC'ye açıktır (yönetici denetimi yalnız execute'ta): super()'den ÖNCE denetle.
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Yalnız sistem yöneticileri ayarları değiştirebilir.'))
        # Negatif sınır '0' (sınırsız) olarak kaydedilmemeli: hiçbir parametre yazılmadan reddedilir (D-7)
        if any((rec.sms_user_daily_limit or 0) < 0 for rec in self):
            raise UserError(_('Kullanıcı başı günlük SMS sınırı negatif olamaz (0 = sınırsız).'))
        json_values = [rec._json_values_checked() for rec in self]   # super()'den önce: hata -> hiçbir şey yazılmaz
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()
        for values in json_values:
            for name, key in _JSON_TEXT_PARAMS.items():
                icp.set_param(key, values[name] or False)   # boş = parametreyi sil (okuma varsayılana düşer)
            icp.set_param('sms_system.api_mode', values['sms_api_mode'])
            icp.set_param('sms_system.turatel_validity_minutes', str(values['sms_validity_minutes']))
        # 'False' ve '0' açıkça yazılır; set_param(False) parametreyi silerdi
        icp.set_param('sms_system.test_mode', 'True' if self.sms_test_mode else 'False')
        icp.set_param('sms_system.user_daily_limit', str(self.sms_user_daily_limit or 0))

    def _json_values_checked(self):
        """JSON ayarlarını normalleştirip doğrular (KK-C2, KK-C29); hata UserError, hiçbir parametre yazılmaz.

        Mesajlara şifre/kullanıcı adı değeri yazılmaz.
        """
        self.ensure_one()
        values = {}
        for name in _JSON_TEXT_PARAMS:
            raw = self[name] or ''
            if name in _JSON_PASSWORDS:
                values[name] = raw if raw.strip() else ''     # şifrenin kenar boşlukları korunur
            else:
                values[name] = raw.strip()
        for name in _JSON_DIGIT_FIELDS:
            if values[name] and not values[name].isdigit():
                raise UserError(_('"%s" yalnız rakamlardan oluşmalıdır.') % self._fields[name].string)
        mode = self.sms_api_mode if self.sms_api_mode in API_MODES else 'legacy_xml'
        values['sms_api_mode'] = mode
        values['sms_validity_minutes'] = parse_validity_minutes(self.sms_validity_minutes)

        if mode == 'json':
            missing = [self._fields[n].string for n in (
                'sms_json_info_user_id', 'sms_json_info_username', 'sms_json_info_password', 'sms_account_info')
                if not values[n]]
            if missing:
                raise UserError(_('JSON API için bilgi kimlik seti eksik: %s') % ', '.join(missing))
        # Reklam seti ya tam ya boş: yarım set ticari gönderimde yanlış hesaba/kullanıcıya yol açardı
        com_user, com_pw = values['sms_json_com_username'], values['sms_json_com_password']
        if bool(com_user) != bool(com_pw):
            raise UserError(_('Reklam kimlik seti yarım: kullanıcı adı ve şifre birlikte girilmeli '
                              '(set kullanılmayacaksa ikisini de boş bırakın).'))
        if com_user and not (values['sms_json_com_user_id'] and values['sms_account_commercial']):
            raise UserError(_('Reklam kimlik seti yarım: kullanıcı adı girildiğinde reklam kullanıcı numarası '
                              've reklam hesabı da dolu olmalıdır.'))
        return values

    @api.model
    def default_get(self, fields_list):
        return self._drop_restricted_sms_values(super().default_get(fields_list))

    def action_iys_test(self):
        self.ensure_one()
        self.execute()
        try:
            self.env['sms.system.iys'].test_connection()
        except SmartAdmError as e:
            raise UserError(str(e)) from e
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('SmartADM'), 'type': 'success',
                           'message': _('Bağlantı başarılı, oturum açıldı.')}}

    def action_iys_sync_now(self):
        self.ensure_one()
        self.execute()
        Iys = self.env['sms.system.iys']
        if not Iys._enabled():
            raise UserError(_('Önce "İYS kontrolü etkin" seçeneğini açıp kaydedin.'))
        Iys._icp().set_param('sms_system.iys_paused_until', False)
        self.env.ref('sms_system.cron_sms_iys').sudo()._trigger()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('İYS'), 'type': 'info',
                           'message': _('Senkron arka planda başladı; rehberdeki İYS durumları birkaç dakika içinde güncellenir.')}}

    def action_sms_check_credit(self):
        self.ensure_one()
        self.execute()  # ekrandaki değerler kaydedilsin
        try:
            answer = self.env['sms.system.message'].check_credit()
        except TuratelError as e:
            raise UserError(str(e))
        hint = ERROR_HINTS.get(answer.strip())
        message = _('Turatel cevabı: %s') % answer
        if hint:
            message += _(' — bu bir hata kodu olabilir: %s') % hint
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Turatel Bağlantısı'), 'message': message,
                       'type': 'warning' if hint else 'success', 'sticky': True},
        }

    # ── Turatel JSON okuma düğmeleri (C6): iki kimlik seti ayrı satır, test modunda da çalışır, SendSms çağırmaz ──

    def _turatel_json_notify(self, title, probe, single_token=False):
        """Her kimlik setine `probe(client, account, cfg) -> (metin, tür)` uygular; sonuçları tek bildirimde verir.

        Kaydedilmiş ayarlar kullanılır (web arayüzü kaydedilmemiş değişiklik için önce kaydetmeyi sorar). Set boşsa
        istek yapılmaz. Hata metinleri istemciden maskeli gelir; ayrıca rakam dizileri yeniden maskelenir.
        """
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Yalnız sistem yöneticileri Turatel hesap sorgusu yapabilir.'))
        cfg = self.env['sms.system.message']._settings()
        lines, worst = [], 'success'
        for key, label in _JSON_SETS:
            creds = cfg['json_creds'].get(key)
            if not creds:
                lines.append(_('%s kimliği tanımlı değil.') % label)
                text, kind = None, 'warning'
            else:
                user_id, username, password, account = creds
                try:
                    text, kind = probe(TuratelJsonClient(cfg['bulk_url'], user_id, username, password), account, cfg)
                except TuratelError as e:
                    text, kind = self._turatel_json_error_text(str(e), label), 'danger'
                lines.append('%s (%s): %s' % (label, account, text))
                if single_token and key == 'info':
                    # Tekli gönderim yalnız singlesms kullanır; C0 yalnız bulksms'i doğruladı
                    single = TuratelJsonClient(cfg['single_url'], user_id, username, password)
                    try:
                        single.get_token()
                        lines.append(_('%s: singlesms jetonu alındı.') % label)
                    except TuratelError as e:
                        lines.append(_('%s: singlesms jetonu alınamadı: %s') % (
                            label, self._turatel_json_error_text(str(e), label)))
                        kind = 'danger'
            if _KIND_RANK[kind] > _KIND_RANK[worst]:
                worst = kind
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': title, 'message': '\n'.join(lines), 'type': worst, 'sticky': True}}

    @api.model
    def _turatel_json_error_text(self, text, label):
        text = mask_digits(text or '')
        if '(-1000)' in text:
            text += _('; %s hesabı için %s kullanıcı adı/şifresi gerekir') % (label.lower(), label.lower())
        return text

    def _turatel_probe_accounts(self, client, account, _cfg):
        accounts = client.get_user_accounts()
        names = ', '.join('%s (%s)' % (a['accountId'], a['accountName'] or '-') for a in accounts) or _('hiç hesap yok')
        if str(account) not in {a['accountId'] for a in accounts}:
            return _('kullanıcı %s hesabını görmüyor; görünen hesaplar: %s') % (account, names), 'warning'
        return _('hesaplar: %s') % names, 'success'

    def _turatel_probe_originators(self, client, account, cfg):
        names = client.get_originators(account)
        listed = ', '.join(names) or _('hiç başlık yok')
        originator = (cfg['originator'] or '').strip()
        if not originator:
            return _('başlıklar: %s; ayarlarda mesaj başlığı tanımlı değil') % listed, 'warning'
        if originator not in names:
            return _('başlıklar: %s; ayarlı başlık "%s" listede yok') % (listed, originator), 'warning'
        return _('başlıklar: %s; ayarlı başlık "%s" tanımlı') % (listed, originator), 'success'

    def _turatel_probe_credit(self, client, account, _cfg):
        amount = '{:,}'.format(client.get_credit(account)).replace(',', '.')
        return _('kalan kredi: %s adet') % amount, 'success'

    def action_turatel_accounts(self):
        return self._turatel_json_notify(_('Turatel Hesapları'), self._turatel_probe_accounts, single_token=True)

    def action_turatel_originators(self):
        return self._turatel_json_notify(_('Turatel Başlıkları'), self._turatel_probe_originators)

    def action_turatel_credit(self):
        return self._turatel_json_notify(_('Turatel Kredisi'), self._turatel_probe_credit)

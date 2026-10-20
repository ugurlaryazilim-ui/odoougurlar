import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, time as dtime, timedelta, timezone

from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services.turatel import (MAX_SEGMENTS, TuratelClient, TuratelError, normalize_number, prepare_text,
                                segment_count)
from ..services.turatel_json import TZ, MAX_TEXT_LENGTH, TuratelJsonClient, json_segment_count
from ..services.turatel_json import delivery_state as map_delivery_code

_logger = logging.getLogger(__name__)

MAX_RETRY = 3
DEFAULT_USER_DAILY_LIMIT = 50
QUEUE_BATCH = 50
# Tekli kayıt bu kadar dakikadır 'gönderiliyor'daysa belirsiz sayılır (kampanyadaki eşikle aynı)
SINGLE_STUCK_MINUTES = 15
# Cron süresinin sonuna bu kadar saniye kala dur; kalanlar sonraki çalışmada
SINGLE_MIN_TIME_LEFT = 20

# Turatel JSON API ayarları (C1; tasarım §5.1)
API_MODES = ('legacy_xml', 'json')
DEFAULT_JSON_USER_ID = '20219'
DEFAULT_ACCOUNT_INFO = '9254'
DEFAULT_ACCOUNT_COMMERCIAL = '65672'
DEFAULT_SINGLE_URL = 'https://platform.turatel.com/singlesms'
DEFAULT_BULK_URL = 'https://platform.turatel.com/bulksms'
DEFAULT_VALIDITY_MINUTES = 1260
# KK-C29: ticari gönderim asla bilgi setine düşmez; set boşsa istek yapılmadan kalıcı hata
NO_COMMERCIAL_CREDS = 'Reklam hesabı kimlik bilgileri (kullanıcı adı/şifre) tanımlı değil'
NO_INFO_CREDS = 'Bilgi hesabı kimlik bilgileri (kullanıcı adı/şifre) tanımlı değil'
# KK-C26: ticari SMS ret metni (çıkış talimatı + Mersis no) olmadan gitmez; iki modda da geçerli
NO_OPTOUT_TEXT = 'Ticari SMS için ret metni (çıkış talimatı ve Mersis no) zorunludur'
# KK-C22: {1}, {2}... Turatel parametre yer tutucularıdır; kullanıcı yazarsa kişiselleştirme bozulur
NUMERIC_PLACEHOLDER = re.compile(r'\{\d+\}')
# KK-C23: Turatel tek SMS metni sınırı (JSON modu); alıcı başına son metin için hata iletisi
TEXT_TOO_LONG = 'metin %d karakteri aşıyor' % MAX_TEXT_LENGTH

# İletim durumu takibi (C5, tasarım §5.5)
JSON_SERVICES = ('single', 'bulk')
STATUS_WINDOW_HOURS = 48          # bu süreyi aşan 'bekliyor' kayıt 'bilinmeyen' olur, sorgulanmaz
STATUS_TRACKED = ('pending', 'unknown')   # unknown: tanınmayan (belgesiz) kod, 48 saat boyunca yeniden sorulur
STATUS_UNCERTAIN_LOOKBACK = 30    # dk; belirsiz kaydın gönderimi write_date'ten en çok bu kadar önce olabilir
STATUS_TIME_BUDGET = 120          # sn; durum cron'u çalışma başına en çok bu kadar sorgu yapar
STATUS_MIN_TIME_LEFT = 20         # sn; cron süresinin sonuna bu kadar kala dur


def test_mode_enabled(value):
    """Test modu tek kaynağı (K2): yalnız tam 'False' kapatır.

    Parametrenin yokluğu, boş değer, 'True', '0', 'false' ya da başka her değer test modunu AÇIK sayar:
    bozuk/silinmiş bir ayar canlı gönderime yol açmamalı.
    """
    return value != 'False'


# Test numarası ayracı: virgül, noktalı virgül, satır sonu. BOŞLUK ayraç DEĞİLDİR: '0532 111 22 33' tek numaradır (C-T2)
TEST_NUMBER_SEPARATORS = re.compile(r'[,;\r\n]+')


def parse_test_numbers(value):
    """Kayıtlı virgüllü test numaraları -> normalize numara listesi (geçersiz parça atlanır)."""
    out = []
    for part in TEST_NUMBER_SEPARATORS.split(value or ''):
        num = normalize_number(part) if part else None
        if num and num not in out:
            out.append(num)
    return out


def parse_user_daily_limit(value):
    """Kullanıcı başı günlük elle SMS sınırı: parametre yok/boş/bozuk/negatifse 50; '0' korunur (sınırsız)."""
    if not value:   # get_param yokluğu/boşu False döndürür; int(False) == 0 yanlışlıkla "sınırsız" olurdu
        return DEFAULT_USER_DAILY_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_USER_DAILY_LIMIT
    return limit if limit >= 0 else DEFAULT_USER_DAILY_LIMIT


def resolve_api_mode(value):
    """API modu: yalnız tam 'json' JSON'dur; yok/boş/bilinmeyen her değer eski XML (legacy_xml) sayılır."""
    return 'json' if value == 'json' else 'legacy_xml'


def count_segments(api_mode, text, sms_type='1'):
    """Parça tahmini (KK-C24): JSON modunda GSM-7/UCS-2 kuralı, eski modda eski hesap değişmeden."""
    return json_segment_count(text) if api_mode == 'json' else segment_count(text, sms_type)


def parse_validity_minutes(value):
    """Geçerlilik süresi (dk): yok/boş/0/negatif/bozuk -> 1260."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_VALIDITY_MINUTES
    return minutes if minutes > 0 else DEFAULT_VALIDITY_MINUTES


# G-2c: kullanıcı yazımıyla değişmeyen gönderim alanları; campaign_id her durumda, diğerleri bu durumlarda
SEND_CONTENT_FIELDS = ('campaign_id', 'body', 'number', 'originator', 'sms_type', 'contact_id')
LOCKED_CONTENT_STATES = ('queued', 'sending', 'sent', 'uncertain')

class SmsSystemMessage(models.Model):
    """Gönderilen her SMS'in kaydı (numara başına bir kayıt)."""
    _name = 'sms.system.message'
    _description = 'SMS Gönderim Kaydı'
    _order = 'id desc'
    _rec_name = 'number'

    number = fields.Char(string='Numara', required=True, index=True)
    body = fields.Text(string='Metin', required=True)
    originator = fields.Char(string='Başlık')
    sms_type = fields.Selection([('1', 'Normal'), ('2', 'Türkçe karakterli')], string='Tür', default='1')
    segments = fields.Integer(string='Parça (tahmini)')
    state = fields.Selection([
        ('queued', 'Kuyrukta'),
        ('sending', 'Gönderiliyor'),
        ('sent', 'Gönderildi'),
        ('test', 'Test (gönderilmedi)'),
        ('error', 'Hata'),
        ('uncertain', 'Belirsiz'),
    ], string='Durum', default='queued', required=True, index=True)
    provider_msg_id = fields.Char(string='Turatel Mesaj No', index=True)
    provider_answer = fields.Char(string='Sağlayıcı Cevabı')
    error = fields.Text(string='Hata')
    retry_count = fields.Integer(string='Deneme', default=0)
    delivery_report = fields.Text(string='İletim Raporu')
    sent_at = fields.Datetime(string='Gönderim Zamanı')
    res_model = fields.Char(string='Kaynak Model', index=True)
    res_id = fields.Integer(string='Kaynak Kayıt', index=True)
    template_id = fields.Many2one('sms.system.template', string='Şablon', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Gönderen', default=lambda self: self.env.user, index=True)
    campaign_id = fields.Many2one('sms.system.campaign', string='Toplu SMS', index=True, ondelete='cascade')
    manual = fields.Boolean(string='Elle Gönderildi', help='"Yeni SMS" penceresinden serbest metinle gönderildi')
    contact_id = fields.Many2one('sms.system.contact', string='Rehber Kişisi', index='btree_not_null',
                                 ondelete='set null')
    # Turatel JSON API (C3, tasarım §5.4); legacy ve eski kayıtlarda boş kalır (iletim takibi yok)
    provider_packet_id = fields.Char(string='Turatel Paket No', index='btree_not_null')
    delivery_state = fields.Selection([
        ('pending', 'Onay Bekliyor'),
        ('delivered', 'İletildi'),
        ('undelivered', 'İletilemedi'),
        ('unknown', 'Bilinmiyor'),
    ], string='İletim Durumu', index=True)
    delivery_code = fields.Char(string='İletim Kodu')
    provider_service = fields.Selection([
        ('legacy', 'Eski XML'),
        ('single', 'singlesms'),
        ('bulk', 'bulksms'),
    ], string='Turatel Servisi')
    provider_account_id = fields.Char(string='Turatel Hesap No')
    # KK-C7: iletim kodunun Türkçe açıklaması (kolon yok)
    delivery_label = fields.Char(string='İletim Açıklaması', compute='_compute_delivery_label')

    @api.depends('delivery_code')
    def _compute_delivery_label(self):
        for msg in self:
            msg.delivery_label = map_delivery_code(msg.delivery_code)[1] if msg.delivery_code else False

    # ── Ayarlar ──

    @api.model
    def _json_creds(self, icp, which, default_account):
        """Bir kimlik seti: (user_id, kullanıcı adı, şifre, hesap_id) ya da set eksikse None.

        which 'info' (bilgi) | 'com' (reklam). Setler arasında geri düşme YOKTUR: reklam seti boşsa
        bilgi kimlikleri kullanılmaz. userId ve hesap boşsa tasarım varsayılanları geçerlidir.
        """
        prefix = 'sms_system.turatel_json_%s_' % which
        username = (icp.get_param(prefix + 'username') or '').strip()
        password = icp.get_param(prefix + 'password') or ''
        if not username or not password.strip():
            return None
        user_id = (icp.get_param(prefix + 'user_id') or '').strip() or DEFAULT_JSON_USER_ID
        account = (icp.get_param('sms_system.turatel_account_%s' % (
            'info' if which == 'info' else 'commercial')) or '').strip() or default_account
        return (user_id, username, password, account)

    @api.model
    def _settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'api_mode': resolve_api_mode(icp.get_param('sms_system.api_mode')),
            # Şifreler yalnız bu sözlükte taşınır; loglanmaz, chatter'a/hata metnine yazılmaz (tasarım §2.4)
            'json_creds': {
                'info': self._json_creds(icp, 'info', DEFAULT_ACCOUNT_INFO),
                'commercial': self._json_creds(icp, 'com', DEFAULT_ACCOUNT_COMMERCIAL),
            },
            'single_url': (icp.get_param('sms_system.turatel_single_url') or '').strip() or DEFAULT_SINGLE_URL,
            'bulk_url': (icp.get_param('sms_system.turatel_bulk_url') or '').strip() or DEFAULT_BULK_URL,
            'validity_minutes': parse_validity_minutes(icp.get_param('sms_system.turatel_validity_minutes')),
            'url': icp.get_param('sms_system.turatel_url') or None,
            'channel_code': icp.get_param('sms_system.turatel_channel_code', ''),
            'username': icp.get_param('sms_system.turatel_username', ''),
            'password': icp.get_param('sms_system.turatel_password', ''),
            'originator': icp.get_param('sms_system.turatel_originator', ''),
            'ascii_mode': icp.get_param('sms_system.ascii_mode') == 'True',
            'test_mode': test_mode_enabled(icp.get_param('sms_system.test_mode')),
            'test_numbers': parse_test_numbers(icp.get_param('sms_system.test_numbers')),
        }

    @api.model
    def _client(self, cfg=None, service='single', purpose='info'):
        """Gönderim istemcisinin tek seçim noktası (tasarım §5.3, K-10).

        Legacy modda `service`/`purpose` yok sayılır ve eski XML istemcisi döner. JSON modunda
        (TuratelJsonClient, accountId) döner: purpose 'commercial' → reklam seti, diğerleri → bilgi seti;
        service 'single' → singlesms, 'bulk' → bulksms. Set boşsa istek yapmadan kalıcı TuratelError
        (reklam seti asla bilgi setine düşmez, KK-C29). İstemci kurmak ağa çıkmaz.
        """
        cfg = cfg or self._settings()
        if cfg['api_mode'] != 'json':
            return self._legacy_client(cfg)
        creds = cfg['json_creds'].get('commercial' if purpose == 'commercial' else 'info')
        if not creds:
            raise TuratelError(NO_COMMERCIAL_CREDS if purpose == 'commercial' else NO_INFO_CREDS)
        user_id, username, password, account = creds
        url = cfg['bulk_url'] if service == 'bulk' else cfg['single_url']
        return TuratelJsonClient(url, user_id, username, password), account

    def write(self, vals):
        if not self.env.su and any(name in vals for name in SEND_CONTENT_FIELDS):
            self._check_send_content_locked(vals)
        return super().write(vals)

    def _check_send_content_locked(self, vals):
        """G-2c (PoC P2i): kullanıcı yazımıyla kaydın kampanyası ve gönderim içeriği değişmez.

        Gönderim anında amaç (bilgi/ticari), ret metni ve şablon kampanyadan okunur; kuyruktaki ticari kaydı başka
        kampanyaya taşımak onay kapılarını atlatırdı. Kampanya bağı her durumda, metin/numara/başlık ise kayıt
        gönderim sürecindeyken (kuyruk, gönderiliyor, gönderildi, belirsiz) kilitlidir. Aynı değerin yeniden yazımı
        serbesttir. Sistem yazımları (kuyruk, cron, uzlaştırma, kampanya akışları) su/sudo ile yapılır.
        """
        for msg in self:
            for name in SEND_CONTENT_FIELDS:
                if name not in vals:
                    continue
                if name != 'campaign_id' and msg.state not in LOCKED_CONTENT_STATES:
                    continue
                new, old = vals[name], msg[name]
                new = getattr(new, 'id', new) or False
                old = getattr(old, 'id', old) or False
                if new != old:
                    raise UserError(_('SMS kaydının kampanyası ve gönderim içeriği elle değiştirilemez (%s).')
                                    % self._fields[name].string)

    @api.model
    def _json_target(self, cfg, service, purpose='info'):
        """JSON modunda kaydın gideceği servis ve hesap (C5 uzlaştırma bağlamı); legacy ya da set yoksa {}."""
        if cfg['api_mode'] != 'json':
            return {}
        creds = cfg['json_creds'].get('commercial' if purpose == 'commercial' else 'info')
        return {'provider_service': service, 'provider_account_id': creds[3]} if creds else {}

    def _mark_sending(self, cfg, service, purpose='info'):
        """'sending' yazımı; JSON modunda servis ve hesap da aynı yazımda (KK-C16, Ö1).

        Çağıran hemen ardından commit eder ve sağlayıcıyı çağırır: işçi SendSms sırasında ölürse takılı kayıt
        süpürmesi kaydı belirsiz yapar ve C5 durum cron'u / "Durumu Sorgula" onu bu bağlamla bulur. Test modunda
        gönderilmeyecek (engellenen) kayıtlar bağlam almaz.
        """
        target = self._json_target(cfg, service, purpose)
        blocked = self.filtered(lambda m: self._blocked_by_test_mode(cfg, normalize_number(m.number)))
        (self - blocked).write(dict(target, state='sending'))
        blocked.write({'state': 'sending'})

    def _pack_purpose(self):
        """Paketin kimlik seti: ticari kampanya → reklam, diğerleri → bilgi (tek karar noktası)."""
        return 'commercial' if self[:1].campaign_id.message_type == 'commercial' else 'info'

    @api.model
    def _legacy_client(self, cfg=None):
        cfg = cfg or self._settings()
        return TuratelClient(cfg['channel_code'], cfg['username'], cfg['password'], url=cfg['url'])

    @api.model
    def _db8(self):
        return (self.env['ir.config_parameter'].sudo().get_param('database.uuid') or '')[:8]

    def _client_ref(self, db8):
        """Alıcı clientId'si (KK-C12): id'den yeniden üretilebilir, ayrı kolon gerekmez."""
        return '%s-m%d' % (db8, self.id)

    # ── Gönderim API'si (diğer modüller bunu kullanır) ──

    @api.model
    @api.private
    def send_sms(self, numbers, body=None, record=None, template=None, values=None, originator=None,
                 queue=False):
        """SMS gönder ve kayıtlarını döndür.

        numbers: tek numara ya da liste. body verilmezse template + values ile üretilir.
        record: kaynak kayıt (iz için); chatter'ı varsa gönderim notu düşülür.
        queue: True ise sağlayıcı çağrılmaz; kayıt 'queued' kalır ve tekli kuyruk cron'u tetiklenir
        (başlık yoksa 'error', test modunda 'test'). İstek süresini sağlayıcıya bağlamamak için (KK-B11).
        Geçersiz numara UserError verir. Sağlayıcı hatası kaydı 'error' bırakır (istisna fırlatmaz).
        RPC'ye kapalıdır (@api.private): yalnız Python'dan çağrılır. Kayıtlar sudo ile oluşturulur
        (normal kullanıcının mesaj ACL'i yalnız okuma) ve gönderen çağıran kullanıcıdır; dönen recordset
        çağıranın env'indedir (kendi kaydını rule_sms_message_own ile okur).
        """
        if isinstance(numbers, str):
            numbers = [numbers]
        if template and not body:
            body = template.render(values or {})
        if not (body or '').strip():
            raise UserError(_('SMS metni boş olamaz.'))
        normalized = []
        for raw in numbers:
            num = normalize_number(raw)
            if not num:
                raise UserError(_('Geçersiz cep telefonu: %s') % raw)
            if num not in normalized:
                normalized.append(num)

        cfg = self._settings()
        text, sms_type = prepare_text(body, ascii_mode=cfg['ascii_mode'])
        segments = count_segments(cfg['api_mode'], text, sms_type)
        if cfg['api_mode'] == 'json':
            if len(text) > MAX_TEXT_LENGTH:   # KK-C23: tam 402 serbest; kayıt oluşmaz
                raise UserError(_('SMS metni çok uzun (%(n)s karakter). En fazla %(max)s karakter gönderilebilir; '
                                  'metni kısaltın.', n=len(text), max=MAX_TEXT_LENGTH))
        elif segments > MAX_SEGMENTS:
            raise UserError(_('SMS metni çok uzun (%(n)s parça). En fazla %(max)s parça gönderilebilir; metni kısaltın.',
                              n=segments, max=MAX_SEGMENTS))
        if record:
            # Sağlayıcıdan ÖNCE: yetkisiz kayıtta SMS hiç gitmez (sonra gelen AccessError kaydı geri alırdı, G-1)
            self._check_record_access(record)
        manual = bool(self.env.context.get('sms_manual'))
        if manual:
            self._check_manual_limit(len(normalized))
        sender = originator or cfg['originator']
        messages = self.sudo().create([{
            'user_id': self.env.uid,
            'number': num,
            'body': text,
            'originator': sender,
            'sms_type': sms_type,
            'segments': segments,
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
            'template_id': template.id if template else False,
            'manual': manual,
        } for num in normalized])
        if queue:
            if messages._settle_without_provider(cfg):
                self._trigger_send_queue()
        else:
            messages._deliver(cfg)
        if record and hasattr(record, 'message_post'):
            self._post_sms_note(record, messages)
        return messages.with_env(self.env)

    @api.model
    def _check_record_access(self, record):
        """Kaynak kayda gönderim notu düşülebilir mi: chatter'lı kayıtta not yazma yetkisi (_mail_post_access,
        varsayılan write), diğerlerinde okuma. Yetkisizse AccessError; sağlayıcı çağrılmadan önce çalışır."""
        if hasattr(record, 'message_post'):
            operations = set(record._mail_get_operation_for_mail_message_operation('create').values())
        else:
            operations = {'read'}
        for operation in operations:
            record.check_access(operation)

    @api.model
    def _post_sms_note(self, record, messages):
        """Kaynak kayda gönderim notu. Sağlayıcı çağrısından sonra çalışır: hiçbir hata SMS kaydını (iz ve günlük
        sınır sayacı) geri aldırmamalı. Not savepoint içinde yazılır, hata yalnız loglanır."""
        states = dict(self._fields['state'].selection)
        try:
            with self.env.cr.savepoint():
                for msg in messages:
                    record.message_post(body=_('SMS → %(num)s [%(state)s]: %(text)s') % {
                        'num': msg.number, 'state': states[msg.state], 'text': msg.body})
        except Exception:  # noqa: BLE001 — SMS gitti/kuyrukta; not yazılamaması kaydı geri aldırmamalı
            _logger.warning('SMS gönderim notu kaynak kayda yazılamadı (%s,%s); SMS kayıtları korundu (%s)',
                            record._name, record.id, messages.ids, exc_info=True)

    @api.model
    def _check_manual_limit(self, count):
        """'Yeni SMS' ile serbest metin gönderiminde kullanıcı başı 24 saatlik sınır (yönetici muaf)."""
        if self.env.user.has_group('sms_system.group_sms_manager'):
            return
        limit = parse_user_daily_limit(self.env['ir.config_parameter'].sudo().get_param('sms_system.user_daily_limit'))
        if not limit:
            return
        since = fields.Datetime.now() - timedelta(days=1)
        used = self.sudo().search_count([('user_id', '=', self.env.uid), ('manual', '=', True),
                                         ('create_date', '>=', since)])
        if used + count > limit:
            raise UserError(_('Günlük elle SMS sınırınız doldu (%(limit)s). Yöneticinize başvurun.', limit=limit))

    def _settle_without_provider(self, cfg):
        """Sağlayıcıya gitmeden sonuçlanan kayıtları kapat, gönderilmesi gerekenleri döndür (sudo).

        Başlık yoksa kalıcı hata; test modunda 'test' (KK-A27). Senkron gönderim, kuyruk ve yeniden
        deneme aynı kapıdan geçer: test modu tek yerde uygulanır.
        """
        pending = self
        if not cfg['originator']:
            missing = pending.filtered(lambda m: not m.originator)
            # Kalıcı hata: başlık sonradan girilse de otomatik gönderilmez (retry_count=MAX)
            missing.write({'state': 'error', 'retry_count': MAX_RETRY,
                           'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
            pending -= missing
        return pending._settle_test_blocked(cfg)

    def _settle_test_blocked(self, cfg):
        """Test modunda test listesi dışındaki kayıtları 'test' yap; gönderilmesi gerekenleri döndür."""
        if not cfg['test_mode']:
            return self
        blocked = self.filtered(lambda m: self._blocked_by_test_mode(cfg, normalize_number(m.number)))
        blocked.write({'state': 'test', 'sent_at': fields.Datetime.now(), 'provider_answer': 'TEST'})
        return self - blocked

    @api.model
    def _blocked_by_test_mode(self, cfg, number):
        """Test modunda gerçek gönderim yalnız 'Test numaraları' listesindekilere yapılır (C7, KK-C27).

        Liste boşsa test modunda hiçbir numara gönderilmez (KK-A27); test modu kapalıysa liste etkisizdir.
        """
        return bool(cfg['test_mode'] and number not in cfg['test_numbers'])

    def _deliver(self, cfg=None):
        """Kayıtları Turatel'e gönder (sudo ile çağrılır)."""
        cfg = cfg or self._settings()
        pending = self._settle_without_provider(cfg)
        if not pending:
            return
        if cfg['api_mode'] == 'json':
            pending._deliver_json(cfg)
            return
        client = self._client(cfg)
        for msg in pending:
            try:
                msg_id, answer = client.send([msg.number], msg.body, msg.originator, msg.sms_type)
                msg.write({'state': 'sent', 'provider_msg_id': msg_id, 'provider_answer': answer,
                           'sent_at': fields.Datetime.now(), 'error': False, 'provider_service': 'legacy'})
            except TuratelError as e:
                msg._write_send_error(e)

    def _write_send_error(self, e, extra=None):
        """Tekli gönderim hatasını kayda yaz (iki modda aynı eşleme)."""
        _logger.warning('SMS gönderilemedi (%s): %s', self.id, e)
        if e.uncertain:
            # Gidip gitmediği belirsiz: asla otomatik yeniden gönderilmez (mükerrer SMS riski)
            self.write(dict(extra or {}, state='uncertain', error=str(e), retry_count=MAX_RETRY))
        else:
            # Kalıcı hatalar (hesap/başlık/kredi/numara) otomatik yeniden denenmez
            self.write({'state': 'error', 'error': str(e),
                        'retry_count': self.retry_count + 1 if e.retryable else MAX_RETRY})

    def _json_success_vals(self, result, ref, service, account):
        return {'state': 'sent', 'provider_msg_id': result.message_ids.get(ref) or False,
                'provider_packet_id': result.packet_id or False, 'provider_service': service,
                'provider_account_id': account, 'delivery_state': 'pending', 'delivery_code': False,
                'provider_answer': result.raw, 'sent_at': fields.Datetime.now(), 'error': False}

    def _deliver_json(self, cfg):
        """JSON tekli yol: kayıt başına bir SendSms; referenceId = alıcının clientId'si (KK-C12)."""
        try:
            client, account = self._client(cfg, service='single', purpose='info')
        except TuratelError as e:
            for msg in self:
                msg._write_send_error(e)
            return
        db8 = self._db8()
        for msg in self:
            ref = msg._client_ref(db8)
            try:
                result = client.send_sms(account, msg.originator, msg.body, [msg.number], client_ids=[ref],
                                         reference_id=ref, check_blacklist=False,
                                         validity_minutes=cfg['validity_minutes'])
                msg.write(msg._json_success_vals(result, ref, 'single', account))
            except TuratelError as e:
                # Belirsiz kayıt C5 durum cron'unda bu hesabın setiyle uzlaştırılır
                msg._write_send_error(e, extra={'provider_service': 'single', 'provider_account_id': account})

    def _deliver_pack(self, cfg, client):
        """Aynı metni taşıyan kayıtları tek Turatel isteğiyle gönder (toplu SMS kuyruğu, sudo)."""
        if not self:
            return
        first = self[0]
        if not first.originator:
            self.write({'state': 'error', 'retry_count': MAX_RETRY,
                        'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
            return
        self = self._settle_test_blocked(cfg)
        if not self:
            return
        if cfg['api_mode'] == 'json':
            self._deliver_pack_json(cfg)
            return
        try:
            msg_id, answer = client.send(self.mapped('number'), first.body, first.originator, first.sms_type)
            self.write({'state': 'sent', 'provider_msg_id': msg_id, 'provider_answer': answer,
                        'sent_at': fields.Datetime.now(), 'error': False, 'provider_service': 'legacy'})
        except TuratelError as e:
            _logger.warning('Toplu SMS paketi gönderilemedi (%s numara): %s', len(self), e)
            if e.uncertain:
                # Paket Turatel'e ulaşmış olabilir: kayıtlar belirsiz kalır, "Hatalıları Yeniden Gönder" almaz
                self.write({'state': 'uncertain', 'error': str(e), 'retry_count': MAX_RETRY})
            else:
                self.write({'state': 'error', 'error': str(e)})

    def _json_pack_content(self, cfg):
        """Paketin gönderilecek içeriği: (gönderilebilir kayıtlar, messageText, parametreler ya da None).

        Kişiselleştirilmiş kampanyada (JSON, {ad}) messageText `{1}` içeren şablondur; her alıcının parameter'ı
        `[güncel ad]`dır ve kaydın `body`'si o kişiye giden son metne yazılır (gönderilen = görünen, KK-C21).
        Son metni 402 karakteri aşan alıcı (uzun ad) gönderilmeden kalıcı hataya alınır, diğerleri gider (KK-C23).
        """
        campaign = self[0].campaign_id
        template, personalized = campaign._json_template(cfg['ascii_mode']) if campaign else (None, False)
        if personalized:
            names = {msg.id: prepare_text(msg.contact_id.name or '', ascii_mode=cfg['ascii_mode'])[0] for msg in self}
            finals = {msg.id: template.replace('{1}', names[msg.id]) for msg in self}
            too_long = self.filtered(lambda m: len(finals[m.id]) > MAX_TEXT_LENGTH)
            sendable = self - too_long
            for msg in sendable:
                if msg.body != finals[msg.id]:
                    msg.body = finals[msg.id]
            message_text, parameters = template, [[names[msg.id]] for msg in sendable]
        else:
            message_text, parameters = self[0].body, None
            too_long = self if len(message_text) > MAX_TEXT_LENGTH else self.browse()
            sendable = self - too_long
        if too_long:
            too_long.write({'state': 'error', 'retry_count': MAX_RETRY, 'error': TEXT_TOO_LONG})
        return sendable, message_text, parameters

    def _deliver_pack_json(self, cfg):
        """JSON paket yolu: bulksms; ticari kampanya → reklam seti + isCheckBlackList, diğerleri → bilgi seti.

        Her kayıt kendi clientId'siyle gider; yanıttaki mesaj kimliği clientId ile eşlenir (paket içinde
        kimlikler karışmaz). referenceId = {db8}-p{ilk kayıt id}. Kişiselleştirilmiş kampanya tek istekte
        `{1}` şablonu + alıcı başına parameter ile gider (_json_pack_content).
        """
        first = self[0]
        purpose = self._pack_purpose()
        try:
            client, account = self._client(cfg, service='bulk', purpose=purpose)
        except TuratelError as e:
            # Kimlik seti yok (KK-C29): istek yapılmadı, kalıcı hata
            self.write({'state': 'error', 'error': str(e), 'retry_count': MAX_RETRY})
            return
        pack, message_text, parameters = self._json_pack_content(cfg)
        if not pack:
            return
        db8 = self._db8()
        refs = [msg._client_ref(db8) for msg in pack]
        try:
            result = client.send_sms(account, first.originator, message_text, pack.mapped('number'),
                                     client_ids=refs, reference_id='%s-p%d' % (db8, pack[0].id),
                                     parameters=parameters, check_blacklist=purpose == 'commercial',
                                     validity_minutes=cfg['validity_minutes'])
        except TuratelError as e:
            _logger.warning('Toplu SMS paketi gönderilemedi (%s numara): %s', len(pack), e)
            if e.uncertain:
                # Paket Turatel'e ulaşmış olabilir: C5 durum cron'u bu hesabın setiyle uzlaştırır
                pack.write({'state': 'uncertain', 'error': str(e), 'retry_count': MAX_RETRY,
                            'provider_service': 'bulk', 'provider_account_id': account})
            elif e.retryable:
                pack.write({'state': 'error', 'error': str(e)})
            else:
                pack.write({'state': 'error', 'error': str(e), 'retry_count': MAX_RETRY})
            return
        for msg, ref in zip(pack, refs):
            msg.write(msg._json_success_vals(result, ref, 'bulk', account))

    # ── Butonlar / cron ──

    def action_retry(self):
        """'Yeniden Gönder': kampanyasız 'error' kayıtları kuyruğa alır; senkron göndermez, commit etmez.

        Belirsiz, gönderiliyor ya da başka bir işlemde kilitli kayıtlar atlanır (KK-A16, A17).
        retry_count değişmez; gönderim kuyruk cron'unun tetiklenmesiyle saniyeler içinde yapılır.
        Yalnız SMS yöneticisi: düğmedeki groups yalnız görünürlüktür, RPC yolunu sunucu tarafı denetim kapatır (G-3).
        """
        if not (self.env.su or self.env.user.has_group('sms_system.group_sms_manager')):
            raise AccessError(_('Yalnız SMS yöneticileri SMS yeniden gönderebilir.'))
        candidates = self.filtered(lambda m: m.state == 'error' and not m.campaign_id)
        queued = self.sudo()._lock_for_send(candidates.ids, ('error',))
        if queued:
            queued.write({'state': 'queued'})
            self._trigger_send_queue()
            message = _('%s kayıt kuyruğa alındı; birkaç saniye içinde gönderilir.') % len(queued)
        else:
            message = _('Kuyruğa alınacak kayıt yok.')
        skipped = len(self) - len(queued)
        if skipped:
            message += ' ' + _('%s kayıt atlandı (yalnız hatalı kayıtlar yeniden gönderilir; belirsiz, '
                               'gönderiliyor ya da başka bir işlemde olanlar atlanır).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'success' if queued else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_fetch_report(self):
        """'Durumu Sorgula': JSON kaydı kendi servis ve hesap setiyle sorgulanır, eski XML kaydı eski rapor ucuyla.

        Yön kayda göre seçilir (gönderildiği servis), API moduna göre değil. Yalnız SMS yöneticisi: düğmedeki
        groups yalnız görünürlüktür, RPC yolunu sunucu tarafı denetim kapatır (ağdan önce).
        """
        if not (self.env.su or self.env.user.has_group('sms_system.group_sms_manager')):
            raise AccessError(_('Yalnız SMS yöneticileri iletim durumunu sorgulayabilir.'))
        # Y1: yalnız gönderilmiş/belirsiz kayıt sorgulanır; hata kaydı servis/hesap taşısa da (Ö1) Turatel'de yoktur
        queryable = self.filtered(lambda m: m.state in ('sent', 'uncertain'))
        if not queryable:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'message': _("Yalnız gönderilmiş ya da belirsiz SMS'lerin iletim durumu sorgulanır."),
                               'type': 'warning', 'sticky': False}}
        json_msgs = queryable.filtered(lambda m: m.provider_service in JSON_SERVICES)
        legacy = (queryable - json_msgs).filtered('provider_msg_id')
        if legacy:
            client = self._legacy_client()
            for msg in legacy:
                try:
                    msg.sudo().delivery_report = client.report(msg.provider_msg_id)[:2000]
                except TuratelError as e:
                    msg.sudo().delivery_report = str(e)
        if not json_msgs:
            return None
        cfg = dict(self._settings(), api_mode='json')
        results = [msg._fetch_json_status(cfg) for msg in json_msgs.sudo()]
        levels = {level for _text, level in results}
        level = next(lvl for lvl in ('danger', 'warning', 'success') if lvl in levels)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': '\n'.join(text for text, _level in results),
                'type': level,
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _fetch_json_status(self, cfg):
        """Tek JSON kaydının durumunu sorgula ve uygula. Döner: (bildirim metni, düzey)."""
        self.ensure_one()
        account = (self.provider_account_id or '').strip()
        client = self._status_client(cfg, self.provider_service, account)
        if client is None:
            return _('Bu kaydın Turatel hesabı (%s) için kimlik seti tanımlı değil.') % (account or '-'), 'warning'
        try:
            if self.provider_packet_id:
                rows = client.get_status(account, self.provider_packet_id,
                                         [self.provider_msg_id] if self.provider_msg_id else None)
            else:
                rows = []
                for day in self._status_days():
                    rows += client.get_status_between(account, *self._day_bounds(day))
        except TuratelError as e:
            return _('Turatel durum sorgusu başarısız: %s') % e, 'danger'
        if not rows:   # -6 dahil (istemci boş liste döner)
            return _("Turatel'de henüz kayıt yok."), 'warning'
        matched, _changed, _reconciled = self._apply_status_rows(rows)
        row = matched.get(self.id)
        if not row:
            return _('Turatel yanıtında bu kayıt bulunamadı (%s satır).') % len(rows), 'warning'
        # Ham satır (maskeli, ≤500 karakter): belgesiz alan adları geçişte buradan doğrulanır (R1)
        self.delivery_report = row.raw
        return _('İletim durumu: %s') % map_delivery_code(row.code)[1], 'success'

    # ── İletim durumu takibi (C5, tasarım §5.5) ──

    @api.model
    def _day_bounds(self, day):
        """İstanbul takvim günü → (00:00:00, 23:59:59) UTC naive (format_date naive'i UTC kabul eder)."""
        start = TZ.localize(datetime.combine(day, dtime.min))
        end = TZ.localize(datetime.combine(day, dtime(23, 59, 59)))
        return tuple(dt.astimezone(timezone.utc).replace(tzinfo=None) for dt in (start, end))

    @staticmethod
    def _local_day(dt):
        return dt.replace(tzinfo=timezone.utc).astimezone(TZ).date()

    def _status_days(self):
        """Kaydın Turatel raporunda arandığı İstanbul günleri.

        Gönderildi: sent_at günü. Belirsiz: gönderim zamanı yazılmaz; isteğin gittiği an write_date'ten
        en çok STATUS_UNCERTAIN_LOOKBACK dk öncedir (takılı 'gönderiliyor' eşiği + cron aralığı).
        """
        self.ensure_one()
        if self.state != 'uncertain' and self.sent_at:
            return [self._local_day(self.sent_at)]
        end = self.write_date or fields.Datetime.now()
        day, last = self._local_day(end - timedelta(minutes=STATUS_UNCERTAIN_LOOKBACK)), self._local_day(end)
        days = [day]
        while days[-1] < last:
            days.append(days[-1] + timedelta(days=1))
        return days

    @api.model
    def _status_client(self, cfg, service, account):
        """Gönderimde kullanılan hesabın kimlik setiyle istemci (accountId'si bu hesaba eşit olan set).

        Setler arasında geri düşme yok; eşleşen set yoksa None. İstemci seçimi yine _client'tan geçer.
        """
        account = (account or '').strip()
        if not account:
            return None
        for purpose in ('info', 'commercial'):
            creds = cfg['json_creds'].get(purpose)
            if creds and str(creds[3]).strip() == account:
                client, _account = self._client(dict(cfg, api_mode='json'), service=service, purpose=purpose)
                return client
        return None

    def _apply_status_rows(self, rows):
        """Turatel durum satırlarını bu aday kayıtlara uygula (cron ve 'Durumu Sorgula' ortak eşleyici).

        Eşleme: messageId → provider_msg_id; yoksa clientId → {db8}-m{id} (başka veritabanının clientId'si
        eşleşmez). Gönderim durumu değişmez (iletim kodu asla yeniden gönderim tetiklemez); belirsiz kayıt
        raporda bulunursa 'sent' olur (KK-C16). Döner: ({kayıt id: satır}, değişen kayıt, uzlaşan belirsiz).
        """
        by_mid = {m.provider_msg_id: m for m in self if m.provider_msg_id}
        db8 = self._db8()
        by_ref = {m._client_ref(db8): m for m in self}
        matched = {}
        for row in rows:
            msg = (row.message_id and by_mid.get(row.message_id)) or (row.client_id and by_ref.get(row.client_id))
            if msg and msg.id not in matched:
                matched[msg.id] = row
        groups = defaultdict(list)
        reconciled = 0
        for msg in self:
            row = matched.get(msg.id)
            if not row:
                continue
            state, _label = map_delivery_code(row.code)
            vals = {}
            if state != 'pending':
                vals.update(delivery_state=state, delivery_code=row.code)
            if msg.state == 'uncertain':
                reconciled += 1
                vals.update(state='sent', error=False, sent_at=msg.sent_at or msg.write_date)
                vals.setdefault('delivery_state', 'pending')
            if row.message_id and not msg.provider_msg_id:
                vals['provider_msg_id'] = row.message_id
            if any(msg[name] != value for name, value in vals.items()):
                groups[tuple(sorted(vals.items()))].append(msg.id)
        for key, ids in groups.items():
            self.browse(ids).write(dict(key))
        return matched, sum(len(ids) for ids in groups.values()), reconciled

    @api.model
    def _cron_fetch_delivery_status(self):
        """'SMS: İletim durumu' (15 dk; KK-C16, C18).

        1. 48 saati aşan 'bekliyor' kayıtlar 'bilinmeyen' olur (sorgulanmaz).
        2. JSON modunda adaylar (son 48 saatte gönderildi + bekliyor/bilinmeyen; belirsiz) (servis, hesap,
           İstanbul günü) parçalarıyla o hesabın kimlik setiyle GetStatusByTwoDates'e sorulur; parça başına
           commit, süre bütçesi bitince kalanlar sonraki çalışmaya.
        Turatel hatası cron'u çökertmez; çalışma başına en çok bir uyarı satırı. -6 boş sonuçtur (uyarı yok).
        Test modunda da çalışır: aday yalnız gerçekten gönderilmiş kayıttır (C7 test numaraları).
        """
        Message = self.sudo()
        IrCron = self.env['ir.cron']
        started = time.monotonic()
        since = fields.Datetime.now() - timedelta(hours=STATUS_WINDOW_HOURS)
        expired = Message.search([('state', '=', 'sent'), ('delivery_state', '=', 'pending'),
                                  ('sent_at', '<', since)])
        if expired:
            expired.write({'delivery_state': 'unknown'})
        IrCron._commit_progress()
        cfg = Message._settings()
        if cfg['api_mode'] != 'json':
            return   # legacy modda JSON isteği yok (KK-C14)
        candidates = Message.search([
            ('provider_service', 'in', JSON_SERVICES), '|',
            '&', '&', ('state', '=', 'sent'), ('delivery_state', 'in', STATUS_TRACKED), ('sent_at', '>=', since),
            '&', ('state', '=', 'uncertain'), ('write_date', '>=', since),
        ], order='id')
        chunks = defaultdict(list)
        for msg in candidates:
            for day in msg._status_days():
                chunks[(day, msg.provider_service, (msg.provider_account_id or '').strip())].append(msg.id)
        clients, missing, problems, resolved = {}, set(), [], set()
        stats = Counter()
        for day, service, account in sorted(chunks):
            if time.monotonic() - started > STATUS_TIME_BUDGET:
                stats['ertelendi'] += 1
                continue
            if (service, account) not in clients:
                clients[(service, account)] = Message._status_client(cfg, service, account)
            client = clients[(service, account)]
            if client is None:
                missing.add((service, account or '-'))
                continue
            todo = Message.browse([i for i in chunks[(day, service, account)] if i not in resolved])
            if not todo:
                continue
            try:
                rows = client.get_status_between(account, *Message._day_bounds(day))
            except TuratelError as e:
                problems.append('%s/%s %s: %s' % (service, account, day.isoformat(), e))
                continue
            stats['sorgu'] += 1
            if not rows:
                stats['boş'] += 1
            matched, changed, reconciled = todo._apply_status_rows(rows)
            resolved.update(matched)
            stats['güncellendi'] += changed
            stats['uzlaşan belirsiz'] += reconciled
            if IrCron._commit_progress(len(todo)) < STATUS_MIN_TIME_LEFT:
                stats['ertelendi'] += 1
                break
        if missing or problems:
            parts = []
            if missing:
                parts.append('kimlik seti tanımlı olmayan hesap atlandı (%s)' % ', '.join(
                    '%s/%s' % key for key in sorted(missing)))
            if problems:
                parts.append('%d sorgu başarısız, ilki %s' % (len(problems), problems[0]))
            _logger.warning('SMS iletim durumu: %s', '; '.join(parts))
        if stats:
            _logger.info('SMS iletim durumu: %s (boş = Turatel\'de kayıt yok/-6); süresi dolan bekleyen: %s',
                         ', '.join('%s %s' % (v, k) for k, v in sorted(stats.items())), len(expired))

    # ── Tekli kuyruk (KK-A16, A17, B11) ──

    @api.model
    def _trigger_send_queue(self):
        """Tekli kuyruk cron'unu hemen çalıştır. Cron kaydı yoksa (redeploy ile -u arası) atla:
        kuyruktaki kayıtları _cron_retry_failed en geç 15 dk içinde gönderir."""
        cron = self.env.ref('sms_system.cron_sms_send_queued', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _lock_for_send(self, ids, states):
        """Kayıtları kilitle ve durumu kilit altında yeniden doğrula; başka işlemin tuttuklarını atla.

        Döner: kilitlenen ve hâlâ `states` içindeki kayıtlar. Kilit, işlem commit edilene kadar sürer.
        REPEATABLE READ'de kayıt bu işlemin anlık görüntüsünden sonra başkasınca değiştirilmişse
        PostgreSQL SerializationFailure verir: kayıt şu an başka bir işlemde demektir, atlanır.
        """
        ids, states = tuple(ids), tuple(states)
        if not ids or not states:
            return self.browse()
        self.flush_model(['state'])
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    'SELECT id FROM sms_system_message WHERE id IN %s AND state IN %s '
                    'ORDER BY id FOR UPDATE SKIP LOCKED', (ids, states))
                locked_ids = [row[0] for row in self.env.cr.fetchall()]
        except pg_errors.SerializationFailure:
            _logger.info('SMS kaydı başka bir işlemde güncellendi, bu çalışmada atlandı (%s kayıt)', len(ids))
            return self.browse()
        locked = self.browse(locked_ids)
        locked.invalidate_recordset(['state'])
        return locked

    @api.model
    def _send_one_by_one(self, candidates, states):
        """Adayları kayıt kayıt gönder: kilit → 'sending' + commit (sağlayıcı çağrısından ÖNCE) → gönder
        → commit. Kayıt başına yapılır: toplu 'sending' süresi takılı kayıt eşiğini aşabilir ve hiç
        gönderilmemiş kayıtlar belirsize düşerdi. Döner: cron süresi bitti mi (True: dur)."""
        IrCron = self.env['ir.cron']
        cfg = self._settings()
        for msg_id in candidates.ids:
            msg = self._lock_for_send([msg_id], states)
            if not msg:
                continue
            msg._mark_sending(cfg, 'single')
            IrCron._commit_progress()
            msg._deliver(cfg)
            if IrCron._commit_progress(1) < SINGLE_MIN_TIME_LEFT:
                return True
        return False

    @api.model
    def _cron_send_queued(self):
        """Tekli gönderim kuyruğu: kampanyasız 'queued' kayıtları gönderir.

        Önce 15 dk'dan uzun 'sending'de kalan tekli kayıtları belirsiz yapar (gidip gitmediği bilinmez,
        asla yeniden gönderilmez). Döner: cron süresi bitti mi.
        """
        Message = self.sudo()
        IrCron = self.env['ir.cron']
        stuck_before = fields.Datetime.now() - timedelta(minutes=SINGLE_STUCK_MINUTES)
        stuck = Message.search([('campaign_id', '=', False), ('state', '=', 'sending'),
                                ('write_date', '<', stuck_before)])
        stuck = Message._lock_for_send(stuck.ids, ('sending',))
        if stuck:
            _logger.warning('%s tekli SMS kaydı gönderiliyor durumunda takıldı, belirsiz yapıldı', len(stuck))
            stuck.write({'state': 'uncertain', 'retry_count': MAX_RETRY,
                         'error': _('Gönderim yarıda kesildi; iletilip iletilmediği belirsiz. '
                                    'Tekrar gönderilmedi (mükerrer olmasın diye).')})
        IrCron._commit_progress()
        last_id = 0
        while True:
            queued = Message.search([('campaign_id', '=', False), ('state', '=', 'queued'), ('id', '>', last_id)],
                                    order='id', limit=QUEUE_BATCH)
            if not queued:
                return False
            last_id = queued[-1].id
            if Message._send_one_by_one(queued, ('queued',)):
                return True

    @api.model
    def _cron_retry_failed(self):
        """Ağ hatası vb. geçici hatalı gönderimleri sınırlı sayıda yeniden dene (son 1 gün).

        Önce tekli kuyruğu boşaltır (kuyruk cron'u yokken de kuyruk 15 dk içinde gider). Yalnız 'error';
        belirsiz ve gönderiliyor kayıtlar asla yeniden gönderilmez.
        """
        if self._cron_send_queued():
            return
        since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        Message = self.sudo()
        failed = Message.search([('state', '=', 'error'), ('retry_count', '<', MAX_RETRY),
                                 ('campaign_id', '=', False), ('create_date', '>=', since)],
                                order='id', limit=QUEUE_BATCH)
        Message._send_one_by_one(failed, ('error',))

    @api.model
    @api.private
    def check_credit(self):
        """Ayarlar ekranındaki 'Bağlantı / Kredi' butonu."""
        return self._legacy_client().credit()

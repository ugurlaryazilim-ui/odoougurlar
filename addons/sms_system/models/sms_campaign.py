import logging
import time
from collections import OrderedDict
from datetime import timedelta

import pytz

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import html2plaintext, html_escape
from odoo.exceptions import UserError

from ..services.turatel import MAX_SEGMENTS, TuratelError, prepare_text
from ..services.turatel_json import MAX_TEXT_LENGTH, TuratelJsonClient, mask_digits
from .sms_iys import FRESH
from .sms_message import (MAX_RETRY, NO_COMMERCIAL_CREDS, NO_OPTOUT_TEXT, NUMERIC_PLACEHOLDER, count_segments,
                          resolve_api_mode)
from .sms_template import PLACEHOLDER

_logger = logging.getLogger(__name__)

PACK_SIZE = 500          # Turatel'e tek istekte giden en fazla numara
MIN_TIME_LEFT = 20       # cron süresinin sonuna bu kadar saniye kala dur, kalan sonraki çalışmada
STUCK_MINUTES = 15       # 'gönderiliyor'da bu kadar dakika kalan kayıt belirsiz sayılır (tekrar gönderilmez)
CREATE_CHUNK = 5000      # büyük kampanyada gönderim kayıtları parça parça oluşturulur
CREDIT_TIMEOUT = (3, 6)  # onay penceresinde kredi okuması: yavaş Turatel pencereyi uzun bekletmesin
IYS_REFRESH_SECONDS = 120  # gönderim anı İYS tazelemesine ayrılan süre; yetmezse paket bekler, sonraki çalışma sürdürür
CONTENT_FIELDS = ('body', 'message_type', 'list_ids', 'template_id')   # yalnız taslakta değişir (G-C2)


class SmsSystemCampaign(models.Model):
    """Toplu SMS: listelerdeki kişilere tek metin. Gönderimi cron kuyruğu paketler halinde yapar."""
    _name = 'sms.system.campaign'
    _description = 'Toplu SMS'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Başlık', required=True, tracking=True)
    message_type = fields.Selection([
        ('info', 'Bilgilendirme'),
        ('commercial', 'Ticari (kampanya / indirim)'),
        ('staff', 'Personel duyurusu'),
    ], string='İleti Türü', default='info', required=True, tracking=True,
        help='Ticari iletiler yalnız İYS onaylı numaralara gider ve sonuna ret bilgisi eklenir.')
    list_ids = fields.Many2many('sms.system.list', string='Alıcı Listeleri', required=True)
    template_id = fields.Many2one('sms.system.template', string='Şablon')
    body = fields.Text(string='Metin', required=True,
                       help='{ad} yazılırsa her kişiye kendi adı yazılır (bu durumda numara başı ayrı gönderilir).')
    scheduled_at = fields.Datetime(string='Planlanan Gönderim', help='Boşsa "Gönder" ile hemen başlar')
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('scheduled', 'Planlandı'),
        ('sending', 'Gönderiliyor'),
        ('done', 'Tamamlandı'),
        ('cancel', 'İptal'),
    ], string='Durum', default='draft', required=True, index=True, tracking=True)
    user_id = fields.Many2one('res.users', string='Oluşturan', default=lambda self: self.env.user, readonly=True)
    started_at = fields.Datetime(string='Başlama', readonly=True)
    finished_at = fields.Datetime(string='Bitiş', readonly=True)
    message_ids_sms = fields.One2many('sms.system.message', 'campaign_id', string='Gönderimler')

    # Önizleme (taslakta canlı hesap)
    final_body = fields.Text(string='Gönderilecek Metin', compute='_compute_preview')
    preview_count = fields.Integer(string='Alıcı (tahmini)', compute='_compute_preview')
    preview_skipped = fields.Integer(string='Atlanacak', compute='_compute_preview',
                                     help='Kara listede ya da (ticari ise) İYS onayı olmayan numaralar')
    preview_segments = fields.Integer(string='Parça / SMS', compute='_compute_preview')
    preview_credit = fields.Integer(string='Tahmini Kredi', compute='_compute_preview')
    preview_iys_pending = fields.Integer(string='İYS kontrolü bekleyen', compute='_compute_preview',
                                         help='Gönderimden hemen önce İYS\'den sorgulanacak numaralar (izin 24 saatten eski)')
    personalized = fields.Boolean(string='Kişiye Özel', compute='_compute_preview')
    iys_enabled = fields.Boolean(compute='_compute_iys_enabled')

    # Sonuç
    skipped_count = fields.Integer(string='Atlanan', readonly=True)
    total_count = fields.Integer(string='Alıcı', compute='_compute_stats')
    sent_count = fields.Integer(string='Gönderilen', compute='_compute_stats')
    error_count = fields.Integer(string='Hatalı', compute='_compute_stats')
    uncertain_count = fields.Integer(string='Belirsiz', compute='_compute_stats',
                                     help='Sağlayıcıya gidip gitmediği bilinmeyen kayıtlar; mükerrer olmasın diye yeniden gönderilmez')
    pending_count = fields.Integer(string='Bekleyen', compute='_compute_stats')
    progress = fields.Float(string='İlerleme', compute='_compute_stats', help='Gönderilen + hatalı + belirsiz / toplam (%)')
    delivered_count = fields.Integer(string='İletildi', compute='_compute_delivery_counts',
                                     help='Turatel iletim raporuna göre alıcıya ulaşan (yalnız JSON API)')
    undelivered_count = fields.Integer(string='İletilemedi', compute='_compute_delivery_counts',
                                       help='Turatel iletim raporuna göre alıcıya ulaşmayan (yalnız JSON API)')
    phone_preview = fields.Html(string='Telefonda Görünüm', compute='_compute_phone_preview', sanitize=True)

    # ── Hesaplar ──

    def _icp(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def _build_body(self):
        self.ensure_one()
        body = (self.body or '').strip()
        if self.message_type == 'commercial':
            optout = (self._icp('sms_system.optout_text') or '').strip()
            if optout and optout not in body:
                body = '%s %s' % (body, optout)
        return body

    def _optout_text(self):
        return (self._icp('sms_system.optout_text') or '').strip()

    def _recipient_domain(self):
        self.ensure_one()
        domain = [('list_ids', 'in', self.list_ids.ids), ('opt_out', '=', False)]
        if self.message_type == 'commercial':
            domain.append(('iys_status', '=', 'approved'))
        return domain

    def _iys_stale_domain(self):
        """Gönderimden önce İYS'den (yeniden) sorgulanacak kişiler: hiç sorgulanmamışlar ile izni 24 saatten eski
        ONAYLILAR. Daha önce sorgulanmış 'unknown'/'rejected' kişiler sorgulanmaz: zaten gönderilmezler ve
        "kayıtsız" cevapları SmartADM hata oranını şişirip hesabı 24 saat bloklatabilir (S-6)."""
        limit_dt = fields.Datetime.now() - FRESH
        return ['&', ('opt_out', '=', False),
                '|', ('iys_checked_at', '=', False),
                '&', ('iys_status', '=', 'approved'), ('iys_checked_at', '<', limit_dt)]

    def _iys_stale(self):
        """Ticari gönderim adayları içinde İYS sorgusu gereken kişiler (bkz. _iys_stale_domain)."""
        self.ensure_one()
        return self.env['sms.system.contact'].sudo().search(
            [('list_ids', 'in', self.list_ids.ids)] + self._iys_stale_domain(), order='id')

    def _recipients(self):
        """(gönderilecek kişiler, atlanan sayısı) — numara bazında tekil."""
        self.ensure_one()
        Contact = self.env['sms.system.contact'].sudo()
        if not self.list_ids:
            return Contact, 0
        all_count = Contact.search_count([('list_ids', 'in', self.list_ids.ids)])
        contacts = Contact.search(self._recipient_domain(), order='id')
        return contacts, all_count - len(contacts)

    @api.depends('body', 'message_type', 'list_ids')
    def _compute_preview(self):
        ascii_mode = self._icp('sms_system.ascii_mode') == 'True'
        api_mode = resolve_api_mode(self._icp('sms_system.api_mode'))
        sample_name = _('Ayşe Yılmaz')
        for camp in self:
            body = camp._build_body()
            camp.personalized = bool(PLACEHOLDER.search(body))
            sample = PLACEHOLDER.sub(lambda m: sample_name if m.group(1) == 'ad' else '', body)
            text, sms_type = prepare_text(sample, ascii_mode=ascii_mode)
            camp.final_body = text
            camp.preview_segments = count_segments(api_mode, text, sms_type) if text else 0
            if camp.state in ('draft', 'scheduled'):
                contacts, skipped = camp._recipients()
                camp.preview_count = len(contacts)
                camp.preview_skipped = skipped
            else:
                camp.preview_count = camp.total_count
                camp.preview_skipped = camp.skipped_count
            camp.preview_iys_pending = (len(camp._iys_stale()) if camp.message_type == 'commercial'
                                        and camp.state in ('draft', 'scheduled') and camp.list_ids else 0)
            camp.preview_credit = camp.preview_count * camp.preview_segments

    def _compute_iys_enabled(self):
        enabled = self._icp('sms_system.iys_enabled') == 'True'
        for camp in self:
            camp.iys_enabled = enabled

    def _compute_stats(self):
        Message = self.env['sms.system.message'].sudo()
        data = {}
        for camp, state, count in Message._read_group([('campaign_id', 'in', self.ids)],
                                                      ['campaign_id', 'state'], ['__count']):
            data.setdefault(camp.id, {})[state] = count
        for camp in self:
            d = data.get(camp.id, {})
            camp.total_count = sum(d.values())
            camp.sent_count = d.get('sent', 0) + d.get('test', 0)
            camp.error_count = d.get('error', 0)
            camp.uncertain_count = d.get('uncertain', 0)
            camp.pending_count = d.get('queued', 0) + d.get('sending', 0)
            done = camp.sent_count + camp.error_count + camp.uncertain_count
            camp.progress = (100.0 * done / camp.total_count) if camp.total_count else 0.0

    def _compute_delivery_counts(self):
        Message = self.env['sms.system.message'].sudo()
        data = {}
        for camp, state, count in Message._read_group(
                [('campaign_id', 'in', self.ids), ('delivery_state', 'in', ('delivered', 'undelivered'))],
                ['campaign_id', 'delivery_state'], ['__count']):
            data.setdefault(camp.id, {})[state] = count
        for camp in self:
            d = data.get(camp.id, {})
            camp.delivered_count = d.get('delivered', 0)
            camp.undelivered_count = d.get('undelivered', 0)

    @api.depends('final_body', 'preview_segments')
    def _compute_phone_preview(self):
        originator = self._icp('sms_system.turatel_originator') or 'SMS'
        for camp in self:
            text = html_escape(camp.final_body or _('Metin yazın...')).replace('\n', Markup('<br/>'))
            camp.phone_preview = Markup(
                '<div style="max-width:300px;border:8px solid #222;border-radius:28px;padding:14px 12px 22px;'
                'background:#f5f5f7;font-family:-apple-system,Segoe UI,sans-serif">'
                '<div style="text-align:center;font-size:12px;color:#666;margin-bottom:10px"><b>%s</b></div>'
                '<div style="background:#e5e5ea;color:#000;border-radius:16px;padding:9px 12px;font-size:14px;'
                'line-height:1.35;white-space:normal;word-wrap:break-word">%s</div>'
                '<div style="font-size:11px;color:#888;margin-top:8px;text-align:right">%s karakter · %s SMS</div>'
                '</div>') % (html_escape(originator), text, len(camp.final_body or ''), camp.preview_segments)

    def action_send_test_to_me(self):
        """Metni kullanıcının kendi cep telefonuna tek SMS olarak gönder ({ad} = kullanıcının adı)."""
        self.ensure_one()
        number = self.env.user.partner_id.phone
        if not number:
            raise UserError(_('Profilinizde telefon yok. Sağ üstte adınız > Profilim > Telefon alanını doldurun.'))
        body = PLACEHOLDER.sub(lambda m: self.env.user.name if m.group(1) == 'ad' else '', self._build_body())
        msg = self.env['sms.system.message'].send_sms(number, body, record=self)
        ok = msg.state in ('sent', 'test')
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Deneme SMS'), 'type': 'success' if ok else 'danger',
                           'message': (_('%s numarasına gönderildi.') % msg.number) + (
                               _(' (Test modu açık: gerçekte gönderilmedi.)') if msg.state == 'test' else '')
                           if ok else (msg.error or _('Gönderilemedi.'))}}

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.body = self.template_id.body

    def write(self, vals):
        if vals.get('state') in ('draft', 'scheduled', 'cancel', 'sending') or any(name in vals for name in CONTENT_FIELDS):
            self._check_content_locked(vals)
        return super().write(vals)

    def _check_content_locked(self, vals):
        """G-C2: onaylanmış kampanyanın metni, türü, listeleri ve şablonu değişmez.

        Ekrandaki readonly yalnız arayüzdür; RPC ile değişiklik ticari kapıyı (tür) ya da onaylanan içeriği
        atlatırdı. Aynı değerin yeniden yazılması serbesttir. Kilit yalnız o anki duruma bakmaz: kampanyaya ait SMS
        kaydı varsa (G-C2b) durum ne olursa olsun içerik kilitlidir; böyle bir kampanya kullanıcı yazımıyla
        taslağa/planlıya/iptale de geri alınamaz (sending -> scheduled/cancel -> draft -> içerik -> sending zinciri).
        Sistem yazımları (cron, _start/_finish) sudo ile yapılır ve geri alma denetiminden muaftır; bağlam bayrağı
        kullanılmaz çünkü RPC çağıranı bağlamı kendisi belirler. Meşru akışlar etkilenmez: "Taslağa Al" ve iptal,
        kayıtsız kampanyada çalışır; kayıtlı kampanyada iptal zaten 'done' yapar.
        """
        for camp in self:
            if vals.get('state') == 'sending' and camp.state != 'sending' and not self.env.su:
                # G-2c: gönderimi yalnız onay/gönderim akışları (sudo) başlatır; RPC ile taslak/planlı -> sending
                # onay kapılarını (İYS, ret metni, günlük sınır) atlatırdı
                raise UserError(_('Toplu SMS gönderimi elle başlatılamaz; "Gönder" akışını kullanın: %s') % camp.name)
            has_messages = bool(camp.sudo().message_ids_sms)
            if (vals.get('state') in ('draft', 'scheduled', 'cancel') and vals['state'] != camp.state
                    and has_messages and not self.env.su):
                raise UserError(_('Gönderimi başlamış toplu SMS taslağa, plana ya da iptale geri alınamaz: %s')
                                % camp.name)
            if vals.get('state') == 'draft' and camp.state in ('sending', 'done'):
                raise UserError(_('Gönderimi başlamış toplu SMS taslağa alınamaz: %s') % camp.name)
            if camp.state == 'draft' and not has_messages:
                continue
            changed = [name for name in CONTENT_FIELDS if name in vals and not camp._same_content(name, vals[name])]
            if changed:
                raise UserError(_("Onaylanmış toplu SMS'in içeriği değiştirilemez (%(fields)s). Değiştirmek için "
                                  'önce taslağa alın: %(name)s',
                                  fields=', '.join(self._fields[n].string for n in changed), name=camp.name))

    def _same_content(self, name, value):
        if name == 'list_ids':
            # Yalnız aynı kümeyi yeniden kuran komut değişiklik sayılmaz; diğer her komut değişikliktir
            commands = list(value or [])
            return (len(commands) == 1 and isinstance(commands[0], (list, tuple)) and commands[0][0] == 6
                    and set(commands[0][2] or []) == set(self.list_ids.ids))
        if name == 'template_id':
            return (getattr(value, 'id', value) or False) == (self.template_id.id or False)
        return (value or False) == (self[name] or False)

    # ── Kontroller ──

    def _check_can_send(self, count):
        self.ensure_one()
        if not self.list_ids:
            raise UserError(_('En az bir alıcı listesi seçin.'))
        if not (self.body or '').strip():
            raise UserError(_('SMS metni boş olamaz.'))
        if self.message_type == 'commercial' and self._icp('sms_system.iys_enabled') != 'True':
            raise UserError(_(
                'Ticari (kampanya/indirim) SMS için İYS izin kontrolü zorunludur. '
                'İYS (SmartADM) entegrasyonu henüz etkin değil; bilgilendirme ya da personel türünü kullanın.'))
        if self.message_type == 'commercial' and self._json_creds_missing():
            raise UserError(_(
                'Reklam hesabı kimlik bilgileri (kullanıcı adı/şifre) tanımlı değil. Ayarlar > SMS > Turatel JSON API '
                'bölümünde reklam kimlik setini doldurun; ticari kampanya bilgi hesabıyla gönderilmez.'))
        if self.message_type == 'commercial' and not self._optout_text():
            raise UserError(self._no_optout_message())
        if resolve_api_mode(self._icp('sms_system.api_mode')) == 'json':
            self._check_json_text()
        if self.preview_segments > MAX_SEGMENTS:
            raise UserError(_('Metin çok uzun (%(n)s parça). En fazla %(max)s parça gönderilebilir.',
                              n=self.preview_segments, max=MAX_SEGMENTS))
        if self.message_type == 'commercial' and not count:
            count = len(self._iys_stale())
        if not count:
            raise UserError(_('Gönderilecek alıcı yok (listeler boş, kara listede ya da İYS onaylı değil).'))
        self._check_daily_limit(count)

    def _no_optout_message(self):
        return _('%s. Ayarlar > SMS bölümünde "Ret metni" alanını doldurun.') % NO_OPTOUT_TEXT

    def _check_json_text(self):
        """JSON modu metin kuralları: kullanıcı {<sayı>} yazamaz (KK-C22); örnek adla hesaplanan metin 402
        karakteri aşamaz (KK-C23). Aşan tek tek alıcılar gönderimde hataya düşer (_json_pack_content)."""
        self.ensure_one()
        if NUMERIC_PLACEHOLDER.search(self._build_body()):
            raise UserError(_('Metinde {1}, {2} gibi sayılı yer tutucu kullanılamaz (kişiselleştirme için '
                              'ayrılmıştır). Kişinin adı için {ad} yazın.'))
        length = len(self.final_body or '')
        if length > MAX_TEXT_LENGTH:
            raise UserError(_('Metin çok uzun (örnek adla %(n)s karakter). En fazla %(max)s karakter gönderilebilir; '
                              'metni kısaltın.', n=length, max=MAX_TEXT_LENGTH))

    def _json_creds_missing(self):
        """JSON modunda ticari kampanyanın reklam kimlik seti boş mu (KK-C29). Bilgi setine düşülmez."""
        cfg = self.env['sms.system.message']._settings()
        return cfg['api_mode'] == 'json' and not cfg['json_creds'].get('commercial')

    def _json_credit(self):
        """json modunda kampanyanın hesabı için kalan kredi: (adet, None) ya da (None, maskeli hata). Legacy: (None, None).

        Hesaba ait kimlik setiyle sorgulanır (ticari = reklam, diğerleri = bilgi). Okuma isteğidir; test modunda da yapılır.
        """
        self.ensure_one()
        cfg = self.env['sms.system.message']._settings()
        if cfg['api_mode'] != 'json':
            return None, None
        creds = cfg['json_creds'].get('commercial' if self.message_type == 'commercial' else 'info')
        if not creds:
            return None, _('kimlik seti tanımlı değil')
        user_id, username, password, account = creds
        try:
            client = TuratelJsonClient(cfg['bulk_url'], user_id, username, password, timeout=CREDIT_TIMEOUT)
            return client.get_credit(account), None
        except TuratelError as e:
            return None, mask_digits(str(e))

    def _check_daily_limit(self, count):
        """Günlük toplu SMS sınırı: `count` yeni kayıt eklenirse son 24 saatteki toplam sınırı aşıyor mu."""
        limit = int(self._icp('sms_system.daily_limit', '0') or 0)
        if limit:
            today = fields.Datetime.now() - timedelta(days=1)
            used = self.env['sms.system.message'].sudo().search_count([
                ('campaign_id', '!=', False), ('state', 'in', ('sent', 'test', 'queued', 'sending')),
                ('create_date', '>=', today)])
            if used + count > limit:
                raise UserError(_('Günlük toplu SMS sınırı aşılıyor: son 24 saatte %(used)s, bu gönderim %(count)s, '
                                  'sınır %(limit)s. Sınır Ayarlar > SMS ekranından değiştirilebilir.',
                                  used=used, count=count, limit=limit))

    def _commercial_hour_warning(self, when=None):
        if self.message_type != 'commercial':
            return ''
        tz = pytz.timezone(self.env.user.tz or 'Europe/Istanbul')
        local = pytz.utc.localize(when or fields.Datetime.now()).astimezone(tz)
        if not (9 <= local.hour < 21):
            return _(' Not: ticari SMS gece saatinde (%s) gönderiliyor.') % local.strftime('%H:%M')
        return ''

    def unlink(self):
        if self.filtered(lambda c: c.state in ('scheduled', 'sending', 'done')):
            raise UserError(_('Gönderilmiş ya da devam eden toplu SMS silinemez; iptal edebilirsiniz.'))
        return super().unlink()

    # ── Butonlar ──

    def action_confirm_send(self):
        """Gönder butonu: alıcı ve kredi sayısını gösteren onay penceresi."""
        self.ensure_one()
        contacts, _skipped = self._recipients()
        self._check_can_send(len(contacts))
        wiz = self.env['sms.system.campaign.confirm'].create({'campaign_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': wiz._name, 'res_id': wiz.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Toplu SMS Onayı')}

    def action_send(self):
        """Gönder (planlı tarih varsa planla)."""
        for camp in self:
            if camp.state != 'draft':
                raise UserError(_('Yalnız taslak toplu SMS gönderilebilir.'))
            contacts, _skipped = camp._recipients()
            camp._check_can_send(len(contacts))
            if camp.message_type == 'commercial':
                camp.write({'state': 'scheduled', 'scheduled_at': camp.scheduled_at or fields.Datetime.now()})
                camp.message_post(body=_('Ticari SMS: gönderimden önce alıcıların İYS izinleri kontrol edilecek, '
                                         'ardından gönderim başlayacak.'))
                self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger(camp.scheduled_at)
            elif camp.scheduled_at and camp.scheduled_at > fields.Datetime.now():
                camp.state = 'scheduled'
                camp.message_post(body=_('%(n)s alıcıya planlandı.%(warn)s', n=len(contacts),
                                         warn=camp._commercial_hour_warning(camp.scheduled_at)))
                self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger(camp.scheduled_at)
            else:
                camp._start()
        self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger()
        return True

    def action_cancel(self):
        for camp in self:
            queued = camp.sudo().message_ids_sms.filtered(lambda m: m.state == 'queued')
            queued.unlink()
            camp.state = 'cancel' if not camp.sudo().message_ids_sms else 'done'
            camp.message_post(body=_('İptal edildi; %s bekleyen gönderim kaldırıldı.') % len(queued))

    def action_draft(self):
        self.filtered(lambda c: c.state in ('scheduled', 'cancel')).write({'state': 'draft'})

    def action_retry_errors(self):
        """Hatalı kayıtları yeniden kuyruğa al (belirsizler asla; mükerrer SMS olmasın).

        Sıra: ticari + İYS kapalı → UserError; kara listede / İYS onayı olmayan kayıtlar gerekçeli hata olarak
        kalır, kuyruğa girmez; günlük sınır kuyruğa girecek sayıyla denetlenir, aşılırsa hiçbir kayıt değişmez.
        İYS tazeliği (24 saat) gönderim anında _commercial_gate ile denetlenir.
        """
        self.ensure_one()
        if self.message_type == 'commercial' and self._icp('sms_system.iys_enabled') != 'True':
            raise UserError(_('Ticari (kampanya/indirim) SMS için İYS izin kontrolü zorunludur. İYS (SmartADM) '
                              'entegrasyonu etkin olmadığı için hatalı kayıtlar yeniden gönderilemez.'))
        if self.message_type == 'commercial' and self._json_creds_missing():
            # KK-C29: kuyruğa alınsa da kalıcı hataya düşerdi; ticari kampanya bilgi hesabıyla gönderilmez
            raise UserError(_('%s. Ayarlar > SMS > Turatel JSON API bölümünde reklam kimlik setini doldurun.')
                            % NO_COMMERCIAL_CREDS)
        if self.message_type == 'commercial' and not self._optout_text():
            raise UserError(self._no_optout_message())
        messages = self.sudo().message_ids_sms
        errors = messages.filtered(lambda m: m.state == 'error')
        uncertain = len(messages.filtered(lambda m: m.state == 'uncertain'))
        uncertain_text = _('%s belirsiz kayıt mükerrer olmaması için yeniden gönderilmez.') % uncertain
        if not errors:
            if uncertain:
                raise UserError(uncertain_text)
            return self._notify(_('Yeniden gönderilecek hatalı kayıt yok.'), 'warning')
        sendable, rejected = self._gate_split(errors)
        self._check_daily_limit(len(sendable))   # aşılırsa hiçbir kayıt değişmez
        self._reject_messages(rejected)
        parts = []
        if sendable:
            sendable.write({'state': 'queued', 'error': False})
            self.sudo().write({'state': 'sending', 'finished_at': False})
            self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger()
            parts.append(_('%s kayıt kuyruğa alındı.') % len(sendable))
        else:
            parts.append(_('Kuyruğa alınacak kayıt yok.'))
        blocked = sum(len(ids) for ids in rejected.values())
        if blocked:
            parts.append(_('%s kayıt kara listede ya da İYS onayı olmadığı için gönderilmedi.') % blocked)
        if uncertain:
            parts.append(uncertain_text)
        return self._notify(' '.join(parts), 'success' if sendable else 'warning')

    def _notify(self, message, kind='success'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': message, 'type': kind, 'sticky': False,
                           'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}

    def action_view_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'sms.system.message',
            'view_mode': 'list,form', 'domain': [('campaign_id', '=', self.id)],
            'context': {'search_default_group_state': 1},
        }

    # ── Gönderim anı kapısı ──

    def _gate_reason(self, contact):
        """Kişiye gönderimi engelleyen gerekçe ('' = engel yok). İYS tazeliği burada denetlenmez."""
        if not contact or contact.opt_out:
            return _('Kara listede (ya da rehberde yok): gönderilmedi.')
        if self.message_type == 'commercial' and contact.iys_status != 'approved':
            return _('İYS onayı yok: gönderilmedi.')
        return ''

    def _gate_split(self, messages, still_stale=frozenset()):
        """Kayıtları ayır: (gönderilebilir kayıtlar, {gerekçe: [kayıt id]}). still_stale: tazelenemeyen kişi
        id'leri; bunların kayıtları ne gönderilebilir ne reddedilir (bekletilir)."""
        sendable_ids, rejected = [], {}
        for msg in messages:
            contact = msg.contact_id
            reason = self._gate_reason(contact)
            if reason:
                rejected.setdefault(reason, []).append(msg.id)
            elif contact.id not in still_stale:
                sendable_ids.append(msg.id)
        return messages.browse(sendable_ids), rejected

    def _reject_messages(self, rejected):
        Message = self.env['sms.system.message'].sudo()
        for reason, ids in rejected.items():
            Message.browse(ids).write({'state': 'error', 'error': reason})

    def _note_once(self, text):
        """Kampanya notu: son (içeriği olan) not aynı metinse tekrar yazma. Yeni kolon gerekmez; aynı hata her
        cron çalışmasında chatter'ı doldurmasın (S-7)."""
        self.ensure_one()
        last = self.env['mail.message'].sudo().search(
            [('model', '=', self._name), ('res_id', '=', self.id)], order='id desc', limit=10)
        for note in last:
            plain = html2plaintext(note.body or '').strip()
            if plain:
                if plain == text.strip():
                    return False
                break
        self.message_post(body=text)
        return True

    def _refresh_iys(self, contacts):
        """Kişileri İYS'den korumalı (hata oranı korumalı) sorgula. Döner: (tamam, hata metni, geçici mi).
        tamam=False: sorgu yapılamadı/durdu; çağıran gönderimi bekletir. geçici=False: kalıcı hata (yanlış şifre
        vb.), beklemek çözmez. Beklenmeyen istisna yutulmaz: loga yazılır, geçici sayılır ve hata metniyle
        çağırana döner (çağıran kullanıcıya not düşer)."""
        Iys = self.env['sms.system.iys']
        paused = Iys._paused_until()
        if paused:
            return False, _('İYS sorgusu hata oranı koruması nedeniyle %s tarihine kadar durduruldu '
                            '(SmartADM hesabı bloklanmasın diye).') % fields.Datetime.to_string(paused), True
        try:
            stats = Iys.refresh_contacts(contacts, deadline=time.monotonic() + IYS_REFRESH_SECONDS)
        except Exception as e:  # noqa: BLE001 — beklenmeyen hata: loga yaz, çağıran not düşer
            _logger.exception('İYS tazelemesi beklenmeyen hatayla durdu (kampanya %s)', self.id)
            return False, _('Beklenmeyen hata: %s') % e, True
        self.env['ir.cron']._commit_progress()
        if stats.get('stopped') == 'error' and stats.get('invalid') and not stats.get('errors'):
            # Yalnız numaraya özgü geçersiz numara hataları: kişiler 'bilinmiyor' işaretlendi, kapı onları gerekçeyle
            # reddeder; tek geçersiz numara ticari kampanyayı süresiz bekletmemeli (D-8)
            return True, '', True
        if stats.get('stopped') == 'error':
            return False, stats.get('error') or _('bilinmeyen hata'), bool(stats.get('retryable'))
        if stats.get('stopped') == 'guard':
            return False, _('İYS sorgusu hata oranı koruması nedeniyle durduruldu: numaraların çoğu İYS kaydında '
                            'yok.'), True
        return True, '', True

    def _commercial_gate(self, messages):
        """Paketi göndermeden önce denetle; gönderilebilir kayıtları döndür.

        Rehber kaydı yok / kara liste / (ticari) İYS onayı yok → gerekçeli 'error'. Ticari kampanyada izni 24
        saatten eski onaylı ya da hiç sorgulanmamış kişiler göndermeden önce İYS'den (korumalı) sorgulanır.
        Sorgu yapılamazsa paket gönderilmez, 'queued' kalır (not düşülür). Bilgilendirme/personel: yalnız kara
        liste süzülür, SmartADM çağrısı yoktur.
        """
        self.ensure_one()
        messages = messages.sudo()
        commercial = self.message_type == 'commercial'
        if commercial and not self.env['sms.system.iys']._enabled():
            self._note_once(_('İYS kontrolü kapalı olduğu için ticari SMS gönderimi bekletiliyor.'))
            return messages.browse()
        sendable, rejected = self._gate_split(messages)
        self._reject_messages(rejected)
        if commercial and sendable:
            Contact = self.env['sms.system.contact'].sudo().with_context(active_test=False)
            stale_domain = self._iys_stale_domain()
            stale = Contact.search([('id', 'in', sendable.contact_id.ids)] + stale_domain, order='id')
            if stale:
                ok, error, _transient = self._refresh_iys(stale)
                if not ok:
                    self._note_once(_('İYS kontrolü yapılamadı, ticari gönderim bekletiliyor: %s') % error)
                    return messages.browse()
                still_stale = set(Contact.search([('id', 'in', stale.ids)] + stale_domain).ids)
                sendable, rejected = self._gate_split(sendable, still_stale)
                self._reject_messages(rejected)
        return sendable

    # ── Kuyruk ──

    def _start(self):
        """Alıcıları dondur: her numara için kuyrukta bir gönderim kaydı oluştur."""
        self.ensure_one()
        contacts, skipped = self._recipients()
        self._check_can_send(len(contacts))
        cfg = self.env['sms.system.message']._settings()
        body = self._build_body()
        vals_list = []
        for contact in contacts:
            text = PLACEHOLDER.sub(lambda m: (contact.name or '') if m.group(1) == 'ad' else '', body)
            text, sms_type = prepare_text(text, ascii_mode=cfg['ascii_mode'])
            vals_list.append({
                'number': contact.mobile, 'body': text, 'originator': cfg['originator'],
                'sms_type': sms_type, 'segments': count_segments(cfg['api_mode'], text, sms_type),
                'campaign_id': self.id, 'contact_id': contact.id, 'state': 'queued',
                'res_model': self._name, 'res_id': self.id, 'template_id': self.template_id.id or False,
                'user_id': self.env.user.id,
            })
        Message = self.env['sms.system.message'].sudo()
        for i in range(0, len(vals_list), CREATE_CHUNK):
            Message.create(vals_list[i:i + CREATE_CHUNK])
        self.sudo().write({'state': 'sending', 'started_at': fields.Datetime.now(), 'skipped_count': skipped})
        self.message_post(body=_('%(n)s alıcıya gönderim başladı (%(s)s numara atlandı).%(warn)s',
                                 n=len(vals_list), s=skipped, warn=self._commercial_hour_warning()))

    @api.model
    def _cron_process_queue(self):
        """Planlananları başlat, kuyruktaki gönderimleri paketler halinde Turatel'e ilet."""
        IrCron = self.env['ir.cron']
        now = fields.Datetime.now()
        Iys = self.env['sms.system.iys']
        for camp in self.search([('state', '=', 'scheduled'), ('scheduled_at', '<=', now)]):
            if camp.message_type == 'commercial':
                if not camp._optout_text():
                    # KK-C26: ret metni silinmişse İYS sorgusuna da başlanmaz; ayar girilip yeniden planlanır
                    camp.sudo().write({'state': 'draft'})
                    camp.message_post(body=_('Planlı gönderim başlatılamadı: %s') % camp._no_optout_message())
                    IrCron._commit_progress()
                    continue
                if not Iys._enabled():
                    camp.sudo().write({'state': 'draft'})
                    camp.message_post(body=_('İYS kontrolü kapalı olduğu için ticari SMS gönderilmedi.'))
                    continue
                stale = camp._iys_stale()
                if stale:
                    ok, error, transient = camp._refresh_iys(stale)
                    if not ok and transient:
                        camp._note_once(_('İYS kontrolü yapılamadı, tekrar denenecek: %s') % error)
                        continue   # geçici hata: planlı kalır, sonraki çalışmada yeniden denenir
                    if not ok:
                        # kalıcı hata: beklemek çözmez; ayar düzeltilip yeniden planlanmalı
                        camp.sudo().write({'state': 'draft'})
                        camp._note_once(_('İYS kontrolü kalıcı bir hatayla başarısız oldu, planlı gönderim iptal '
                                          'edilip taslağa alındı. Ayarları düzeltip yeniden planlayın: %s') % error)
                        IrCron._commit_progress()
                        continue
                    if camp._iys_stale():
                        continue  # süre yetmedi; kalanlar sonraki çalışmada
            try:
                camp._start()
            except UserError as e:
                camp.sudo().write({'state': 'draft'})
                camp.message_post(body=_('Planlı gönderim başlatılamadı: %s') % e)
            IrCron._commit_progress()

        Message = self.env['sms.system.message'].sudo()
        # Kesilen bir çalışmadan 'gönderiliyor'da kalanlar: gidip gitmediği bilinmez, tekrar gönderilmez
        stuck = Message.search([('campaign_id', '!=', False), ('state', '=', 'sending'),
                                ('write_date', '<', now - timedelta(minutes=STUCK_MINUTES))])
        if stuck:
            stuck.write({'state': 'uncertain', 'retry_count': MAX_RETRY,
                         'error': _('Gönderim yarıda kesildi; iletilip iletilmediği belirsiz. '
                                    'Tekrar gönderilmedi (mükerrer olmasın diye).')})

        cfg = Message._settings()
        # JSON modunda istemci paket başına kampanya türüne göre seçilir (_deliver_pack_json); burada kurulmaz
        client = Message._client(cfg) if cfg['api_mode'] != 'json' else None
        campaigns = self.search([('state', '=', 'sending')], order='id')
        remaining = Message.search_count([('campaign_id', 'in', campaigns.ids), ('state', '=', 'queued')])
        IrCron._commit_progress(remaining=remaining)
        for camp in campaigns:
            creds_missing = camp.message_type == 'commercial' and camp._json_creds_missing()
            if creds_missing:
                # Kuyruktakiler kalıcı hata; o an kilitli olan kalırsa sonraki çalışmada. Gönderim döngüsüne
                # girilmez (N5): girilseydi kapı İYS'yi sorgular, paket de reklam seti olmadan denenirdi
                camp._fail_without_commercial_creds()
            elif (camp.message_type == 'commercial' and not camp._optout_text()
                    and Message.search_count([('campaign_id', '=', camp.id), ('state', '=', 'queued')])):
                # KK-C26: ret metni sonradan silindiyse ticari kayıtlar kuyrukta bekler (ayar girilince sürer)
                camp._note_once(camp._no_optout_message())
                continue
            held = creds_missing   # True: kampanyanın kalanı sonraki çalışmaya (İYS doğrulanamadı, kilitli, set yok)
            while not held:
                queued = Message.search([('campaign_id', '=', camp.id), ('state', '=', 'queued')],
                                        order='id', limit=PACK_SIZE * 4)
                if not queued:
                    break
                for pack in self._make_packs(queued):
                    gated = camp._commercial_gate(pack)
                    IrCron._commit_progress()
                    # Kilit altında yeniden doğrula: başka işlemin tuttuğu/değiştirdiği kayıt bu pakete girmez (KK-C17)
                    sendable = Message._lock_for_send(gated.ids, ('queued',))
                    # Kapının beklettiği ya da kilitli olduğu için kuyrukta kalan kayıt varsa kampanyanın kalanı
                    # sonraki çalışmaya kalır (aynı kayıtları yeniden çekip dönmesin)
                    held = bool(pack.filtered(lambda m: m.state == 'queued') - sendable)
                    if sendable:
                        sendable._mark_sending(cfg, sendable._pack_service(), sendable._pack_purpose())
                        IrCron._commit_progress()
                        sendable._deliver_pack(cfg, client)
                        left = IrCron._commit_progress(len(sendable))
                        # ConfirmSms paket başına, gönderim commit'inden SONRA; süre azsa durum cron'u onaylar
                        if left >= MIN_TIME_LEFT and sendable._confirm_sent_packets(cfg):
                            left = IrCron._commit_progress()
                        if left < MIN_TIME_LEFT:
                            return
                    if held:
                        break
            if not Message.search_count([('campaign_id', '=', camp.id), ('state', 'in', ('queued', 'sending'))]):
                camp._finish()
                IrCron._commit_progress()

    def _fail_without_commercial_creds(self):
        """JSON modunda reklam seti boşken kuyruktaki ticari kayıtlar: kalıcı hata, hiçbir istek yok (KK-C29).

        İYS kapısından önce çalışır (SmartADM de çağrılmaz); bilgi setine asla düşülmez. Metin değişmez.
        """
        self.ensure_one()
        Message = self.env['sms.system.message'].sudo()
        queued = Message.search([('campaign_id', '=', self.id), ('state', '=', 'queued')], order='id')
        locked = Message._lock_for_send(queued.ids, ('queued',))
        if locked:
            locked.write({'state': 'error', 'retry_count': MAX_RETRY, 'error': NO_COMMERCIAL_CREDS})
            self._note_once(_('%s; ticari kampanyanın bekleyen kayıtları gönderilmedi (bilgi hesabıyla gönderilmez).')
                            % NO_COMMERCIAL_CREDS)
            self.env['ir.cron']._commit_progress()

    @api.model
    def _make_packs(self, messages):
        """Aynı son metin/başlık/türdeki numaraları en fazla PACK_SIZE'lık paketlere ayır.

        Kişiselleştirme (`{ad}`) paket düzeyinde değil, kaydın `body`'sindedir (_start): aynı adı taşıyanlar aynı
        pakette gider. Turatel `parameter`'ı uygulamıyor (canlıda kanıtlandı); şablon/parametre yolu yoktur."""
        groups = OrderedDict()
        for msg in messages:
            key = (msg.body, msg.originator, msg.sms_type)
            groups.setdefault(key, []).append(msg.id)
        Message = self.env['sms.system.message'].sudo()
        for ids in groups.values():
            for i in range(0, len(ids), PACK_SIZE):
                yield Message.browse(ids[i:i + PACK_SIZE])

    def _finish(self):
        self.ensure_one()
        self.write({'state': 'done', 'finished_at': fields.Datetime.now()})
        self.message_post(body=_('Tamamlandı: %(sent)s gönderildi, %(err)s hatalı, %(unc)s belirsiz, %(skip)s atlandı.',
                                 sent=self.sent_count, err=self.error_count, unc=self.uncertain_count,
                                 skip=self.skipped_count))


class SmsSystemCampaignConfirm(models.TransientModel):
    _name = 'sms.system.campaign.confirm'
    _description = 'Toplu SMS Onayı'

    campaign_id = fields.Many2one('sms.system.campaign', required=True, ondelete='cascade')
    summary = fields.Html(compute='_compute_summary', sanitize=True)

    @api.depends('campaign_id')
    def _compute_summary(self):
        now = fields.Datetime.now()
        for wiz in self:
            camp = wiz.campaign_id
            if camp.scheduled_at and camp.scheduled_at > now:
                local = fields.Datetime.context_timestamp(camp, camp.scheduled_at)
                when = _('%s tarihinde') % local.strftime('%d.%m.%Y %H:%M')
            else:
                when = _('hemen')
            types = dict(camp._fields['message_type'].selection)
            wiz.summary = _(
                '<p><b>%(n)s</b> kişiye %(when)s gönderilecek (%(s)s numara atlanacak).</p>'
                '<p>Tahmini kredi: <b>%(c)s</b> (%(seg)s parça/SMS). Tür: %(t)s.</p>',
                n=camp.preview_count, when=when, s=camp.preview_skipped, c=camp.preview_credit,
                seg=camp.preview_segments, t=types[camp.message_type]) + wiz._credit_html(camp) + _(
                '<p class="text-muted">Gönderim başladıktan sonra yalnız henüz gitmemiş mesajlar durdurulabilir.</p>')

    def _credit_html(self, camp):
        """json modunda kalan kredi satırı (KK-C20); uyarılar onayı engellemez. Legacy modda boş."""
        remaining, error = camp._json_credit()
        if remaining is None and error is None:
            return ''
        if remaining is None:
            return _('<p class="text-warning">Kalan kredi alınamadı (%s). Onay engellenmez.</p>') % html_escape(error)
        text = _('<p>Kalan kredi: <b>%s</b> adet.</p>') % remaining
        if camp.preview_credit > remaining:
            text += _('<p class="text-danger">Kredi yetersiz: gerekli %(need)s, kalan %(left)s. '
                      'Gönderim engellenmez; yetersiz krediyle gönderim eksik kalabilir.</p>',
                      need=camp.preview_credit, left=remaining)
        return text

    def action_confirm(self):
        self.ensure_one()
        self.campaign_id.action_send()
        return {'type': 'ir.actions.act_window_close'}

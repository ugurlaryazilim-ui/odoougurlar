# -*- coding: utf-8 -*-
"""Sanal POS ödeme talebi (tasarım §3.1, §4). Çekirdek model ve durum makinesi tabanı.

Kullanıcı grupları bu modele YALNIZ OKUMA ACL'i ile erişir (ir.model.access.csv).
Hiçbir alan kullanıcı tarafından write/create ile değiştirilemez; tüm değişiklikler
ilerleyen görevlerde eklenecek kontrollü model metotlarıyla (``sudo()`` en dar
kapsamda) yapılır. Chatter'a not yazabilmek için ``_mail_post_access = 'read'``.

Dış çağrı kuralı: çağrıdan ÖNCE "işlemde" durumu yazılıp ``_sp_commit()`` edilir;
``_sp_commit`` asla bir ``cr.savepoint()`` bloğunun içinden çağrılmaz.
"""
import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from psycopg2 import errors as pg_errors

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .res_config_settings import get_bool_param

_logger = logging.getLogger(__name__)

# Durum kümeleri: tüm kontroller bunları kullanır (tek yerde sabit).
OPEN_STATES = ('sending', 'sent', 'unknown')
PAID_STATES = ('paid', 'partial_refund', 'review')
REUSABLE_STATES = ('expired', 'link_cancelled', 'error', 'voided', 'refunded')
REFUNDED_STATES = ('voided', 'refunded')

PAYMENT_STATES = [
    ('sending', 'Gönderiliyor'),
    ('sent', 'Gönderildi'),
    ('unknown', 'Belirsiz'),
    ('error', 'Hata'),
    ('expired', 'Süresi doldu'),
    ('link_cancelled', 'Link iptal edildi'),
    ('paid', 'Ödendi'),
    ('review', 'İnceleme gerekli'),
    ('partial_refund', 'Kısmen iade edildi'),
    ('refunded', 'İade edildi'),
    ('voided', 'Ödeme iptal edildi'),
]

# Paratika uzunluk sınırları (KK-10): alan -> en çok karakter
FIELD_MAX_LENGTH = {
    'customer_name': 128,
    'customer_email': 64,
    'customer_address': 255,
    'customer_city': 32,
    'customer_zip': 16,
}

# Kullanıcı mesajları (01-gereksinimler; metinler testlerle sabit)
OPEN_LINK_MSG = 'Bu faturaya ait açık bir link var%s. Yeniden gönderin veya iptal edin.'   # KK-18
PAID_MSG = 'Bu fatura için ödeme alınmış/incelemede; yeni link oluşturulamaz.'             # KK-19
PRIOR_REFUND_MSG = ('Bu faturanın önceki ödemesi iade/iptal edilmiş. Yeni link için '      # KK-20
                    '"Önceki iadeyi/iptali biliyorum" kutusunu işaretleyin.')
UNKNOWN_MSG = 'Paratika yanıt vermedi; link oluşmuş olabilir. Durum otomatik kontrol edilecek.'  # KK-16
BUSY_MSG = 'Bu kayıt üzerinde başka bir işlem sürüyor; birazdan tekrar deneyin.'

SYNC_CRON_XMLID = 'sanal_pos.cron_sanal_pos_sync'   # G8
UNKNOWN_SYNC_DELAY = timedelta(minutes=2)

_ISTANBUL = ZoneInfo('Europe/Istanbul')
_UTC = ZoneInfo('UTC')
_DEFAULT_TEST_URL = 'https://test.paratika.com.tr/paratika/api/v2'
_DEFAULT_LIVE_URL = 'https://vpos.paratika.com.tr/paratika/api/v2'


class SanalPosPayment(models.Model):
    _name = 'sanal.pos.payment'
    _description = 'Sanal POS Ödeme Talebi'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _mail_post_access = 'read'

    # ---------------------------------------------------------------- kısıtlar
    _merchant_payment_id_uniq = models.Constraint(
        'UNIQUE(merchant_payment_id)', 'Bu ödeme numarası zaten kullanılmış.')
    # Açık link tekilliği (KK-21): aynı faturada tek açık kayıt, veritabanı düzeyinde.
    _invoice_open_uniq = models.UniqueIndex(
        "(invoice_no) WHERE state IN ('sending','sent','unknown')",
        'Bu faturaya ait açık bir link zaten var.')
    _expiry_hours_check = models.Constraint(
        'CHECK(expiry_hours BETWEEN 1 AND 168)',
        'Link geçerlilik süresi 1 ile 168 saat arasında olmalıdır.')
    _amount_positive_check = models.Constraint(
        'CHECK(amount > 0)', 'Tutar sıfırdan büyük olmalıdır.')

    # ---------------------------------------------------------------- kimlik
    name = fields.Char(string='Talep No', readonly=True, copy=False, index=True, default='/')
    provider = fields.Selection(
        [('paratika', 'Paratika')], string='Sağlayıcı', required=True, default='paratika')
    environment = fields.Selection(
        [('test', 'Test'), ('live', 'Canlı')], string='Ortam', required=True,
        default=lambda self: self._default_environment(),
        help='Oluşturma anındaki ayarın anlık görüntüsü; sonraki tüm çağrılar bu ortama gider.')
    is_test = fields.Boolean(string='Test ortamı', compute='_compute_is_test')
    company_id = fields.Many2one(
        'res.company', string='Şirket', default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='Oluşturan', default=lambda self: self.env.user, index=True)

    # ---------------------------------------------------------------- fatura
    invoice_source = fields.Selection(
        [('nebim', 'Nebim')], string='Fatura kaynağı', default='nebim')
    invoice_no = fields.Char(string='Fatura No', required=True, index=True)
    invoice_ref = fields.Char(string='Fatura Kimliği')
    invoice_date = fields.Datetime(string='Fatura Tarihi')
    customer_code = fields.Char(string='Müşteri Kodu')

    # Faturadan gelen ham değerler (KK-5 iz)
    source_name = fields.Char(string='Faturadaki Ad')
    source_phone = fields.Char(string='Faturadaki Telefon')
    source_email = fields.Char(string='Faturadaki E-posta')

    # Sağlayıcıya gönderilen değerler
    customer_name = fields.Char(string='Müşteri Adı')
    customer_phone = fields.Char(string='Telefon')
    customer_email = fields.Char(string='Müşteri e-postası')
    customer_address = fields.Char(string='Adres')
    customer_city = fields.Char(string='İl')
    customer_zip = fields.Char(string='Posta Kodu')

    # ---------------------------------------------------------------- tutar
    currency_id = fields.Many2one(
        'res.currency', string='Para Birimi', required=True,
        default=lambda self: self.env.ref('base.TRY', raise_if_not_found=False))
    amount = fields.Monetary(string='Tutar', currency_field='currency_id', required=True,
                             readonly=True)

    # ---------------------------------------------------------------- link
    channel_sms = fields.Boolean(string='SMS ile gönder')
    channel_email = fields.Boolean(string='E-posta ile gönder')
    channels_display = fields.Char(string='Kanal', compute='_compute_channels_display')
    expiry_hours = fields.Integer(string='Geçerlilik (saat)', default=168)
    state = fields.Selection(
        PAYMENT_STATES, string='Durum', required=True, default='sending',
        index=True, tracking=True, copy=False)
    attempt_no = fields.Integer(string='Deneme No', default=1, copy=False)
    merchant_payment_id = fields.Char(
        string='Ödeme Numarası (MERCHANTPAYMENTID)', required=True, copy=False, index=True)
    provider_token = fields.Char(string='Sağlayıcı Token', copy=False)
    link_url = fields.Char(string='Link Adresi', compute='_compute_link_url')
    sent_at = fields.Datetime(string='Gönderim Zamanı', copy=False)
    expires_at = fields.Datetime(string='Son Geçerlilik', copy=False)

    # ---------------------------------------------------------------- ödeme
    provider_tran_ref = fields.Char(string='İşlem No (pgTranId)', copy=False)
    paid_at = fields.Datetime(string='Ödeme Zamanı', copy=False)
    paid_amount = fields.Monetary(string='Ödenen Tutar', currency_field='currency_id', copy=False)
    installment_count = fields.Integer(string='Taksit', copy=False)
    card_last4 = fields.Char(string='Kart Son 4', copy=False)
    failed_attempt_count = fields.Integer(string='Başarısız Deneme', copy=False)
    last_error_code = fields.Char(string='Son Hata Kodu', copy=False)
    last_error_message = fields.Char(string='Son Hata', copy=False)

    # ---------------------------------------------------------------- senkron
    last_checked_at = fields.Datetime(string='Son Sorgu', copy=False)
    sync_requested = fields.Boolean(string='Senkron İstendi', index=True, copy=False)
    last_refund_sync_at = fields.Datetime(string='Son İade Senkronu', copy=False)

    # ---------------------------------------------------------------- iade
    refund_ids = fields.One2many('sanal.pos.refund', 'payment_id', string='İade Geçmişi')
    refunded_amount = fields.Monetary(
        string='İade Edilen', currency_field='currency_id', compute='_compute_refunded_amount',
        store=True)
    refundable_amount = fields.Monetary(
        string='İade Edilebilir', currency_field='currency_id',
        compute='_compute_refundable_amount')
    can_void = fields.Boolean(string='İptal edilebilir', compute='_compute_can_void')
    can_refund = fields.Boolean(string='İade edilebilir', compute='_compute_can_refund')

    # ---------------------------------------------------------------- varsayılanlar
    @api.model
    def _default_environment(self):
        value = self.env['ir.config_parameter'].sudo().get_param('sanal_pos.environment')
        return value if value in ('test', 'live') else 'test'

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = sequence.next_by_code('sanal.pos.payment') or '/'
        # Oluşturanı takipçi yapma, "kayıt oluşturuldu" notu düşme: bildirim yalnız açık message_post ile
        return super(SanalPosPayment, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True)).create(vals_list)

    # ---------------------------------------------------------------- compute
    @api.depends('environment')
    def _compute_is_test(self):
        for rec in self:
            rec.is_test = rec.environment == 'test'

    @api.depends('channel_sms', 'channel_email')
    def _compute_channels_display(self):
        for rec in self:
            parts = []
            if rec.channel_sms:
                parts.append('SMS')
            if rec.channel_email:
                parts.append('E-posta')
            rec.channels_display = '+'.join(parts)

    @api.depends('provider_token', 'environment', 'provider')
    def _compute_link_url(self):
        """Ödeme sayfası adresi; yalnız ``sanal_pos.paratika_show_link_url`` açıksa dolu (KK-17)."""
        # Boolean ayar kapatılınca parametre satırı silinir: yok = kapalı
        show = get_bool_param(self.env, 'sanal_pos.paratika_show_link_url', default=False)
        ICP = self.env['ir.config_parameter'].sudo()
        for rec in self:
            rec.link_url = False
            if not show or not rec.provider_token or rec.provider != 'paratika':
                continue
            if rec.environment == 'live':
                api_url = ICP.get_param('sanal_pos.paratika_live_url') or _DEFAULT_LIVE_URL
            else:
                api_url = ICP.get_param('sanal_pos.paratika_test_url') or _DEFAULT_TEST_URL
            parts = urlsplit(api_url)
            if parts.scheme and parts.netloc:
                rec.link_url = '%s://%s/merchant/payment/%s' % (
                    parts.scheme, parts.netloc, rec.provider_token)

    @api.depends('refund_ids.state', 'refund_ids.amount')
    def _compute_refunded_amount(self):
        for rec in self:
            rec.refunded_amount = sum(
                line.amount for line in rec.refund_ids if line.state == 'done')

    @api.depends('paid_amount', 'refunded_amount')
    def _compute_refundable_amount(self):
        for rec in self:
            rec.refundable_amount = (rec.paid_amount or 0.0) - (rec.refunded_amount or 0.0)

    @api.depends('state', 'paid_at', 'refund_ids.state')
    def _compute_can_void(self):
        """KK-41: aynı gün (Europe/Istanbul) ve hiç iade/iptal işlemi yokken."""
        today = datetime.now(_ISTANBUL).date()
        for rec in self:
            rec.can_void = bool(
                rec.state == 'paid' and rec.paid_at
                and rec.paid_at.replace(tzinfo=_UTC).astimezone(_ISTANBUL).date() == today
                and not rec._has_blocking_refund_line(include_done=True))

    @api.depends('state', 'paid_amount', 'refunded_amount', 'refund_ids.state')
    def _compute_can_refund(self):
        """KK-45: ödenmiş/kısmen iade, kalan tutar var, devam eden işlem yok."""
        for rec in self:
            rounding = rec.currency_id.rounding or 0.01
            rec.can_refund = bool(
                rec.state in ('paid', 'partial_refund')
                and float_compare(rec.refundable_amount, 0.0, precision_rounding=rounding) > 0
                and not rec._has_blocking_refund_line(include_done=False))

    def _has_blocking_refund_line(self, include_done):
        """Devam eden (processing/unknown) ya da istenirse tamamlanmış iade/iptal satırı var mı."""
        self.ensure_one()
        blocking = {'processing', 'unknown'}
        if include_done:
            blocking.add('done')
        return any(line.state in blocking for line in self.refund_ids)

    # ---------------------------------------------------------------- doğrulama
    @api.constrains(*FIELD_MAX_LENGTH)
    def _check_field_lengths(self):
        """KK-10 savunma: sınır aşan değer sessizce kırpılmaz, reddedilir."""
        for rec in self:
            for name, limit in FIELD_MAX_LENGTH.items():
                if len(rec[name] or '') > limit:
                    raise ValidationError(
                        '%s en çok %d karakter olabilir.' % (rec._fields[name].string, limit))

    # ---------------------------------------------------------------- yardımcılar
    def _sp_commit(self):
        """Dış çağrıdan önce/sonra durumu kalıcılaştırır.

        Testlerde yamalanır (TransactionCase'te ``cr.commit()`` yasaktır). ASLA bir
        ``cr.savepoint()`` bloğunun içinden çağrılmaz: commit savepoint'i düşürür.
        """
        self.env.flush_all()
        self.env.cr.commit()

    # ---------------------------------------------------------------- yeni link (G7, tasarım §6.1/§6.2)
    # Sihirbaz (wizard/payment_create_wizard.py) adım 1-6'yı yürütür; burada ortak kurallar ve
    # dış çağrı sonrası adımlar (7-9) bulunur. ``sending`` kaydının başlangıç zamanı create_date'tir:
    # G8 cron'u ``sending`` kaydı yalnız yaş eşiği + FOR UPDATE SKIP LOCKED ile almalıdır.
    @api.model
    def _check_sanal_pos_user(self):
        if not (self.env.su or self.env.user.has_group('sanal_pos.group_sanal_pos_user')):
            raise AccessError('Bu işlem için Sanal POS kullanıcı yetkisi gerekir.')

    @api.model
    def _format_local(self, value):
        """UTC naive -> 'gg.aa.yyyy SS:DD' (Europe/Istanbul)."""
        if not value:
            return ''
        return value.replace(tzinfo=_UTC).astimezone(_ISTANBUL).strftime('%d.%m.%Y %H:%M')

    @api.model
    def _open_link_message(self, creator_name=None, created_at=None):
        """KK-18 metni; oluşturan/tarih bilinmiyorsa parantezsiz."""
        detail = ''
        if creator_name or created_at:
            detail = ' (%s, %s)' % (creator_name or '-', self._format_local(created_at) or '-')
        return OPEN_LINK_MSG % detail

    @api.model
    def _new_link_blocker(self, invoice_no, confirm_prior_refund=False, refresh=False):
        """Yeni link engeli mesajı (boş = engel yok). KK-19 > KK-18 > KK-20.

        ORM ile ön kontrol (kullanıcıya erken ve ayrıntılı mesaj); asıl kilit DB'deki kısmi
        UNIQUE indekstir (``_invoice_open_uniq``). ``refresh`` yalnız oluşturma anında: süresi
        geçmiş 'Gönderildi' kayıtları için ``_refresh_before_new_link`` kancası çağrılır.
        """
        if not invoice_no:
            return ''
        Payment = self.sudo()
        domain = [('invoice_no', '=', invoice_no)]
        if refresh:
            stale = Payment.search(
                domain + [('state', '=', 'sent'), ('expires_at', '<', fields.Datetime.now())])
            if stale:
                stale._refresh_before_new_link()
        records = Payment.search(
            domain + [('state', 'in', PAID_STATES + OPEN_STATES + REFUNDED_STATES)], order='id desc')
        if any(rec.state in PAID_STATES for rec in records):
            return PAID_MSG
        open_rec = records.filtered(lambda rec: rec.state in OPEN_STATES)[:1]
        if open_rec:
            creator = open_rec.user_id or open_rec.create_uid
            return self._open_link_message(creator.name, open_rec.create_date)
        if not confirm_prior_refund and any(rec.state in REFUNDED_STATES for rec in records):
            return PRIOR_REFUND_MSG
        return ''

    def _refresh_before_new_link(self):
        """Süresi geçmiş 'Gönderildi' kayıtlarını yeni link öncesi tazeler.

        G7: işlem yok (kayıt açık kalır, KK-18 ile engellenir: güvenli taraf).
        G8: NOWAIT kilit + ``_sync_status`` (expired/paid) ile doldurulur.
        """
        return True

    @api.model
    def _open_link_message_sql(self, invoice_no):
        """DB tekillik ihlalinde KK-18 metni; ORM aramasına bağlı değildir (KK-21)."""
        self.env.cr.execute("""
            SELECT partner.name, p.create_date
              FROM sanal_pos_payment p
              LEFT JOIN res_users u ON u.id = COALESCE(p.user_id, p.create_uid)
              LEFT JOIN res_partner partner ON partner.id = u.partner_id
             WHERE p.invoice_no = %s AND p.state IN %s
             ORDER BY p.id DESC
             LIMIT 1
        """, [invoice_no, OPEN_STATES])
        row = self.env.cr.fetchone()
        # Eşzamanlı istekte (REPEATABLE READ) diğer işlemin satırı görünmeyebilir: parantezsiz
        return self._open_link_message(*(row or (None, None)))

    @api.model
    def _next_attempt_no(self, invoice_no):
        """Faturanın TÜM denemelerinin en büyük numarası + 1 (KK-20; ORM'den bağımsız)."""
        self.flush_model(['invoice_no', 'attempt_no'])
        self.env.cr.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM sanal_pos_payment WHERE invoice_no = %s",
            [invoice_no])
        return self.env.cr.fetchone()[0]

    @api.model
    def _insert_sending(self, vals):
        """'Gönderiliyor' kaydını savepoint içinde açar; tekillik ihlali -> KK-18 UserError.

        Savepoint geri alındığı için işlem (transaction) zehirlenmez; diğer IntegrityError'lar
        (CHECK vb.) olduğu gibi yükselir.
        """
        try:
            with self.env.cr.savepoint():
                return self.sudo().create(vals)
        except pg_errors.UniqueViolation:
            raise UserError(self._open_link_message_sql(vals['invoice_no'])) from None

    def _post_note(self, body):
        self.ensure_one()
        self.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')

    def _lock_for_provider_call(self):
        """Dış çağrı süresince satırı kilitler (NOWAIT). Kilit alınamazsa False.

        LockNotAvailable Odoo'nun yeniden deneme listesindedir; savepoint içinde yakalanmazsa
        tüm istek tekrar çalışır (ikinci dış çağrı riski).
        """
        self.ensure_one()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    'SELECT id FROM sanal_pos_payment WHERE id = %s FOR UPDATE NOWAIT', [self.id])
        except pg_errors.LockNotAvailable:
            return False
        return True

    def _call_create_link(self):
        """Sağlayıcı ``create_link``; beklenmeyen istisna belirsiz sonuca çevrilir (raise yok)."""
        self.ensure_one()
        payment_id = self.id
        try:
            with self.env.cr.savepoint():
                return self._provider().create_link(self)
        except Exception as exc:  # noqa: BLE001 - dış çağrıdan sonra raise yok (§6.1)
            # Metin sır içerebilir (KK-37): yalnız sınıf adı loglanır
            _logger.error('sanal_pos: link oluşturmada beklenmeyen hata (%s), ödeme id=%s',
                          type(exc).__name__, payment_id)
            return {'ok': False, 'timeout': True, 'error_code': 'EXCEPTION',
                    'error_message': UNKNOWN_MSG}

    def _apply_create_result(self, result):
        """Sağlayıcı sonucunu kayda yazar: sent / unknown / error (+ chatter)."""
        self.ensure_one()
        if result.get('ok') and result.get('token'):
            now = fields.Datetime.now()
            self.write({
                'state': 'sent', 'provider_token': result['token'], 'sent_at': now,
                'expires_at': now + timedelta(hours=self.expiry_hours),
                'last_error_code': False, 'last_error_message': False,
            })
            self._post_note('Link oluşturuldu, %s ile gönderildi' % self.channels_display)
        elif result.get('ok') or result.get('timeout'):
            # Token'sız başarı da belirsizdir: link oluşmuş olabilir, 'Gönderildi' yazılmaz
            self.write({
                'state': 'unknown', 'last_error_code': result.get('error_code') or 'TIMEOUT',
                'last_error_message': UNKNOWN_MSG,
            })
            self._post_note(UNKNOWN_MSG)
        else:
            message = result.get('error_message') or 'Paratika isteği reddetti.'
            self.write({
                'state': 'error', 'last_error_code': result.get('error_code') or False,
                'last_error_message': message,
            })
            self._post_note('Link oluşturulamadı: %s' % message)

    def _trigger_sync_cron(self):
        """Belirsiz sonuçta uzlaştırma cron'unu öne çeker (cron G8'de; yoksa sessiz)."""
        cron = self.env.ref(SYNC_CRON_XMLID, raise_if_not_found=False)
        if not cron:
            return
        try:
            with self.env.cr.savepoint():
                cron.sudo()._trigger(fields.Datetime.now() + UNKNOWN_SYNC_DELAY)
        except Exception as exc:  # noqa: BLE001 - tetik kurulamazsa periyodik cron toplar
            _logger.warning('sanal_pos: senkron tetiği kurulamadı (%s)', type(exc).__name__)

    def _run_create_link(self):
        """Tasarım §6.1 adım 7-9. Kayıt 'sending' olarak COMMIT EDİLMİŞ olmalıdır; raise etmez."""
        self.ensure_one()
        if not self._lock_for_provider_call():
            # Başka işlem (ör. G8 cron) kaydı tutuyor: ikinci dış çağrı yapılmaz, cron uzlaştırır
            return self._notification_action(BUSY_MSG, 'warning')
        result = self._call_create_link()
        self._apply_create_result(result)
        if self.state == 'unknown':
            self._trigger_sync_cron()
        self._sp_commit()
        if self.state == 'sent':
            return self._form_action()
        kind = 'warning' if self.state == 'unknown' else 'danger'
        return self._notification_action(self.last_error_message or UNKNOWN_MSG, kind)

    def _form_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'sanal.pos.payment',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def _notification_action(self, message, kind):
        """Kalıcı bildirim + ardından ödeme formu (hata/belirsiz sonuçlar raise edilmez)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Ödeme linki: %s' % self.name,
                'message': message,
                'type': kind,
                'sticky': True,
                'next': self._form_action(),
            },
        }

    def action_new_link(self):
        """'Yeni Link Oluştur' (REUSABLE_STATES): sihirbazı faturayı yeniden getirip bu kaydın
        müşteri/kanal değerleriyle açar. Engel kuralları sihirbazda yine uygulanır."""
        self.ensure_one()
        self._check_sanal_pos_user()
        if self.state not in REUSABLE_STATES:
            raise UserError('Yeni link yalnız süresi dolmuş, iptal edilmiş, hatalı veya '
                            'iade/iptal edilmiş taleplerden oluşturulabilir.')
        wizard = self.env['sanal.pos.payment.create.wizard'].create({'invoice_no': self.invoice_no})
        wizard.action_fetch_invoice()
        wizard.write({
            'customer_name': self.customer_name or wizard.customer_name,
            'customer_phone': self.customer_phone or wizard.customer_phone,
            'customer_email': self.customer_email or wizard.customer_email,
            'customer_address': self.customer_address or wizard.customer_address,
            'customer_city': self.customer_city or wizard.customer_city,
            'customer_zip': self.customer_zip or wizard.customer_zip,
            'channel_sms': self.channel_sms,
            'channel_email': self.channel_email,
            'expiry_hours': self.expiry_hours or wizard.expiry_hours,
        })
        return wizard._reopen_action()

    def _recompute_refund_state(self):
        """İade satırlarından durumu yeniden hesaplar (yalnız paid/partial_refund kayıtlara).

        done void satırı -> voided; iade toplamı ödenene ulaştıysa refunded;
        >0 ise partial_refund; yoksa paid.
        """
        for rec in self:
            if rec.state not in ('paid', 'partial_refund'):
                continue
            rounding = rec.currency_id.rounding or 0.01
            refunded = rec.refunded_amount
            if any(line.kind == 'void' and line.state == 'done' for line in rec.refund_ids):
                new_state = 'voided'
            elif rec.paid_amount and float_compare(
                    refunded, rec.paid_amount, precision_rounding=rounding) >= 0:
                new_state = 'refunded'
            elif float_compare(refunded, 0.0, precision_rounding=rounding) > 0:
                new_state = 'partial_refund'
            else:
                new_state = 'paid'
            if new_state != rec.state:
                rec.sudo().write({'state': new_state})

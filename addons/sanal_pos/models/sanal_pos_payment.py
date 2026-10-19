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
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from psycopg2 import errors as pg_errors

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from ..tools import format_try
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

# G8: durum senkronu (tasarım §6.2, §6.3; 08-sozlesme-G8.md)
IRREVERSIBLE_STATES = ('paid', 'partial_refund', 'refunded', 'voided')
LATE_PAYMENT_STATES = ('expired', 'link_cancelled', 'error')
STALE_SENDING_AGE = timedelta(minutes=5)
CHECK_STATUS_MAX_AGE = timedelta(days=30)
REFUND_SYNC_WINDOW = timedelta(days=30)
# Risk 1 (yönetici kararı): zaman aşımı sonrası "bulunamadı" yanıtı tek başına yeterli değildir
LINK_NOT_FOUND_MIN_CHECKS = 2
LINK_NOT_FOUND_MIN_AGE = timedelta(minutes=15)
CRON_SYNC_LIMIT = 200
# G-1: webhook kaynaklı sorgu çoğaltmasına karşı
SYNC_REQUEST_MIN_INTERVAL = timedelta(minutes=1)   # ödeme başına iki sorgu arası en az
SENT_RECHECK_AGE = timedelta(minutes=9)            # bayraksız 'sent' periyodik yeniden sorgu yaşı
CRON_TIME_BUDGET = 8 * 60  # saniye; aşılırsa cron kendini hemen yeniden planlar
QUERY_FAILED_MSG = 'Paratika durum sorgusu yanıt vermedi; durum değiştirilmedi.'
LINK_NOT_FOUND_MSG = "Link Paratika'da bulunamadı; yeni link oluşturabilirsiniz."
LINK_NOT_FOUND_PENDING_MSG = "Link Paratika'da henüz bulunamadı; durum tekrar kontrol edilecek."
AMBIGUOUS_MSG = ("Paratika'da birden fazla aday link bulundu; yönetici Paratika panelinden "
                 'kontrol etmelidir.')
STALE_SENDING_MSG = "Link oluşturma işlemi yarıda kaldı; durum Paratika'dan uzlaştırılacak."
# G10: yeniden gönder / link iptali (KK-31, KK-32)
CHANNEL_MSG = 'En az bir gönderim kanalı seçin.'                                         # KK-9
RESEND_CHANNELS = ('sms', 'email')
RESEND_LABELS = {'sms': 'SMS', 'email': 'E-posta'}
RESEND_FAILED_MSG = 'Yeniden gönderim başarısız oldu; mesaj gönderilmedi.'
RESEND_TIMEOUT_MSG = ('Paratika yanıt vermedi; mesaj gönderilmiş olabilir. '
                      'Müşteriye ulaşıp ulaşmadığını kontrol edin.')
CANCEL_FAILED_MSG = 'Link iptali başarısız oldu; link hâlâ açık olabilir.'
CANCEL_TIMEOUT_MSG = ('Paratika yanıt vermedi; link iptal edilmiş sayılmadı. '
                      'Durumu sorgulayıp gerekirse tekrar deneyin.')
CANCEL_PENDING_MSG = ("Paratika'da devam eden bir ödeme işlemi var; link iptal edilmedi. "
                      'Birazdan durumu sorgulayın.')
CANCEL_ALREADY_MSG = "Link Paratika'da zaten iptal edilmiş; kayıt iptal olarak işaretlendi."

# İptal / iade (G11, 11-sozlesme-G11)
REFUND_WIZARD = 'sanal.pos.payment.refund.wizard'
REFUND_BUSY_MSG = 'Bu ödeme için devam eden bir iade/iptal işlemi var.'                   # KK-45
NOTHING_LEFT_MSG = 'İade edilebilir tutar kalmadı.'                                     # KK-45
REFUND_REASON_MSG = 'İptal/iade nedeni zorunludur (en az 5 karakter).'                   # KK-40
REFUND_RANGE_MSG = 'İade tutarı 0,01 ile %s arasında olmalı.'                            # KK-44
REFUND_NOT_PAID_MSG = 'İptal/iade yalnız ödenmiş taleplerde yapılabilir.'
VOID_NOT_ALLOWED_MSG = ('Ödeme yalnız ödendiği gün içinde ve iade yapılmamışsa iptal edilebilir; '
                        'iade yapın.')                                                   # KK-41
REFUND_SYNC_FAILED_MSG = "Paratika'ya ulaşılamadı; iade/iptal yapılmadı."                # KK-44
REFUND_UNKNOWN_MSG = ('Paratika yanıt vermedi; iade gerçekleşmiş olabilir. '
                      'Durum otomatik kontrol edilecek, tekrar denemeyin.')              # KK-47
REFUND_NOT_SENT_MSG = 'İstek Paratika\'ya gönderilmedi; birazdan tekrar deneyin.'
REFUND_NOT_FOUND_MSG = "Paratika'da iade/iptal işlemi bulunamadı; işlem yapılmamış sayıldı."
REFUND_STALE_MSG = "İade/iptal isteği yarıda kaldı; durum Paratika'dan uzlaştırılacak."
REFUND_STALE_AGE = timedelta(minutes=5)          # 'İşleniyor' bu yaştan sonra yarıda kalmış sayılır
# Yönetici şartı 1 (G8 Risk 1 ile aynı): belirsiz satır ancak en az 2 ayrı sorguda bulunamaz,
# bekleyen (IP) işlem yoktur ve ilk belirsizlikten 15 dk geçmişse 'Başarısız' olur.
REFUND_NOT_FOUND_MIN_CHECKS = 2
REFUND_NOT_FOUND_MIN_AGE = timedelta(minutes=15)
REFUND_SECOND_CHECK_DELAY = timedelta(minutes=16)
REFUND_MATCH_TOLERANCE = timedelta(minutes=5)    # işlem zamanı satırdan bu kadar önce olabilir
REFUND_KIND_LABELS = {'void': 'Ödeme iptali', 'refund': 'İade'}

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
    # Belirsiz link uzlaştırması (KK-16, Risk 1): "bulunamadı" yanıtı sayacı ve başlangıç zamanı
    unknown_since = fields.Datetime(string='Belirsizlik Başlangıcı', copy=False)
    link_not_found_count = fields.Integer(string='"Bulunamadı" Yanıt Sayısı', copy=False)

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
    can_resend = fields.Boolean(string='Yeniden gönderilebilir', compute='_compute_can_resend')

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

    @api.depends('state', 'expires_at')
    def _compute_can_resend(self):
        """KK-31: yalnız Gönderildi ve süresi dolmamış linkler yeniden gönderilebilir."""
        now = fields.Datetime.now()
        for rec in self:
            rec.can_resend = bool(
                rec.state == 'sent' and (not rec.expires_at or rec.expires_at > now))

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
        """Süresi geçmiş 'Gönderildi' kayıtlarını yeni link öncesi sorgular (expired/paid/review).

        Kayıt başına NOWAIT kilit; meşgul kayıt atlanır (açık kalır, KK-18 engeller: güvenli
        taraf). Sonuç ``_sp_commit`` ile kalıcılaşır, böylece ardından gelen KK-19 UserError'ı
        sorgu sonucunu (ör. paid) geri almaz. Bir savepoint içinden çağrılmamalıdır.
        """
        refreshed = False
        for rec in self.sudo():
            if not rec._lock_for_provider_call():
                continue
            rec.invalidate_recordset()
            if rec.state != 'sent':
                continue
            rec._sync_status()
            refreshed = True
        if refreshed:
            self._sp_commit()
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
                'unknown_since': fields.Datetime.now(), 'link_not_found_count': 0,
            })
            self._post_note(UNKNOWN_MSG)
        else:
            message = result.get('error_message') or 'Paratika isteği reddetti.'
            self.write({
                'state': 'error', 'last_error_code': result.get('error_code') or False,
                'last_error_message': message,
            })
            self._post_note('Link oluşturulamadı: %s' % message)

    @api.model
    def _trigger_sync_cron(self, at=None):
        """Senkron cron'unu öne çeker: varsayılan ``now+2dk`` (G7 belirsiz), G9 ``at=now``."""
        cron = self.env.ref(SYNC_CRON_XMLID, raise_if_not_found=False)
        if not cron:
            return
        when = at or (fields.Datetime.now() + UNKNOWN_SYNC_DELAY)
        try:
            with self.env.cr.savepoint():
                cron.sudo()._trigger(when)
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

    def _notification_action(self, message, kind, sticky=True):
        """Bildirim + ardından ödeme formu (hata/belirsiz sonuçlar raise edilmez)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Ödeme linki: %s' % self.name,
                'message': message,
                'type': kind,
                'sticky': sticky,
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

    # ---------------------------------------------------------------- durum senkronu (G8, tasarım §6.2/§6.3)
    # Kilit kuralı: ``_sync_status`` / ``_reconcile_unknown_link`` kilit ALMAZ ve commit ETMEZ;
    # çağıran (cron: SKIP LOCKED, buton: NOWAIT) satırı kilitler ve ``_sp_commit`` eder.
    def _call_provider_safely(self, method, label, *args, message=QUERY_FAILED_MSG):
        """Sağlayıcı çağrısı; beklenmeyen istisna belirsiz sonuca çevrilir (raise yok)."""
        self.ensure_one()
        payment_id = self.id
        try:
            with self.env.cr.savepoint():
                return getattr(self._provider(), method)(self, *args)
        except Exception as exc:  # noqa: BLE001 - dış çağrıdan sonra raise yok
            # Metin sır içerebilir (KK-37): yalnız sınıf adı loglanır
            _logger.error('sanal_pos: %s beklenmeyen hata (%s), ödeme id=%s',
                          label, type(exc).__name__, payment_id)
            return {'ok': False, 'timeout': True, 'error_code': 'EXCEPTION',
                    'error_message': message, 'transactions': []}

    def _sync_status(self):
        """QUERYTRANSACTION ile durumu günceller (kararın tek kaynağı). Son sonucu döndürür."""
        result = {}
        for rec in self.sudo():
            result = rec._call_provider_safely('query_status', 'durum sorgusunda')
            rec._apply_status(result)
        return result

    def _sync_refunds(self, transactions):
        """Sorgudaki iade/iptal işlemlerini satırlara yansıtır (KK-27, KK-47; sözleşme §6).

        Çağıran kilidi tutar ve commit eder; yalnız başarılı sorgu sonucuyla çağrılır.
        Sıra: yarıda kalmış istek -> belirsiz satır eşleşmesi -> ref benimseme (R-3) ->
        uçuştaki istek -> tek iptal -> panel satırı; ardından eşleşmeyen belirsiz satırlar.
        """
        self.ensure_one()
        rec = self.sudo()
        now = fields.Datetime.now()
        for line in rec.refund_ids.filtered(
                lambda l: l.state == 'processing' and l.create_date
                and l.create_date < now - REFUND_STALE_AGE):
            line.write({'state': 'unknown', 'unknown_since': now, 'not_found_count': 0,
                        'error_code': 'STALE', 'error_message': REFUND_UNKNOWN_MSG})
            rec._post_note('%s (%s): %s' % (REFUND_KIND_LABELS[line.kind],
                                            format_try(line.amount), REFUND_STALE_MSG))
        financial = [t for t in transactions if t.get('kind') in ('refund', 'void')]
        approved = [t for t in financial if t.get('status') == 'approved'
                    and rec._to_cents(t.get('amount')) is not None]
        pending = [t for t in financial if t.get('status') == 'pending']
        listed = {t.get('ref') for t in approved if t.get('ref')}
        for tran in approved:
            rec._sync_refund_transaction(tran, listed, now)
        if not pending:
            rec._count_refund_not_found(now)
        rec._recompute_refund_state()
        return True

    def _sync_refund_transaction(self, tran, listed, now):
        """Onaylı tek iade/iptal işlemi (sözleşme §6 a-f)."""
        ref = tran.get('ref') or False
        if ref and ref in set(self.refund_ids.mapped('provider_ref')):
            return 'known'
        kind, cents = tran['kind'], self._to_cents(tran.get('amount'))
        label = REFUND_KIND_LABELS[kind]

        def same(line):
            return line.kind == kind and self._to_cents(line.amount) == cents

        when = tran.get('time')
        line = self.refund_ids.filtered(
            lambda l: l.state == 'unknown' and l.source == 'odoo' and same(l)
            and (not when or not l.create_date or when >= l.create_date - REFUND_MATCH_TOLERANCE))[:1]
        if line:
            line.write({'state': 'done', 'provider_ref': ref, 'done_at': when or now,
                        'error_code': False, 'error_message': False})
            self._post_note('%s (%s) Paratika sorgusunda bulundu; başarılı olarak işaretlendi.' % (
                label, format_try(line.amount)))
            return 'matched'
        if not ref:
            # İşlem numarasız kayıt tekilleştirilemez; panel satırı açılmaz (her sorguda kopya olurdu)
            _logger.warning('sanal_pos: işlem numarasız %s işlemi atlandı, ödeme id=%s', kind, self.id)
            return 'skipped'
        line = self.refund_ids.filtered(
            lambda l: l.state == 'done' and l.source == 'odoo' and same(l)
            and (not l.provider_ref or l.provider_ref not in listed))[:1]
        if line:
            # R-3: yanıttaki işlem no sorgudakinden farklı/boş; aynı işlem iki kez sayılmaz
            line.write({'provider_ref': ref})
            self._post_note('%s (%s) işlem no Paratika sorgusuyla eşleştirildi: %s' % (
                label, format_try(line.amount), ref))
            return 'adopted'
        if self.refund_ids.filtered(lambda l: l.state == 'processing' and same(l)):
            return 'in_flight'
        if kind == 'void' and self.refund_ids.filtered(
                lambda l: l.kind == 'void' and l.state == 'done'):
            return 'void_known'
        return self._create_panel_line(tran, kind, cents, ref, now)

    def _create_panel_line(self, tran, kind, cents, ref, now):
        """Paratika panelinden yapılmış işlem: 'Başarılı' + kaynak panel; bildirim gitmez."""
        try:
            with self.env.cr.savepoint():
                line = self.env['sanal.pos.refund'].sudo().create({
                    'payment_id': self.id, 'kind': kind, 'amount': float(cents),
                    'state': 'done', 'source': 'panel', 'reason': 'Paratika panelinden',
                    'user_id': False, 'provider_ref': ref, 'done_at': tran.get('time') or now,
                })
                line.flush_recordset()
        except pg_errors.UniqueViolation:
            self.invalidate_recordset(['refund_ids'])
            return 'known'
        self._post_note('Paratika panelinden %s: %s (işlem no %s)' % (
            REFUND_KIND_LABELS[kind].lower(), format_try(cents), ref))
        return 'panel'

    def _count_refund_not_found(self, now):
        """Eşleşmeyen belirsiz satırlar: yalnız ≥2 ayrı sorgu + ≥15 dk sonra 'Başarısız'."""
        for line in self.refund_ids.filtered(lambda l: l.state == 'unknown'):
            count = line.not_found_count + 1
            since = line.unknown_since or line.create_date or now
            if count >= REFUND_NOT_FOUND_MIN_CHECKS and now >= since + REFUND_NOT_FOUND_MIN_AGE:
                line.write({'state': 'failed', 'not_found_count': count,
                            'error_code': 'NOT_FOUND', 'error_message': REFUND_NOT_FOUND_MSG})
                self._post_note('%s (%s): %s' % (REFUND_KIND_LABELS[line.kind],
                                                 format_try(line.amount), REFUND_NOT_FOUND_MSG))
            else:
                line.write({'not_found_count': count})

    @api.model
    def _to_cents(self, value):
        try:
            return Decimal(str(value)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def _creator_partner(self):
        self.ensure_one()
        return (self.user_id or self.create_uid).partner_id

    def _notify_creator(self, body):
        """Chatter notu + linki oluşturana Odoo bildirimi (KK-30). Müşteriye mesaj gitmez."""
        self.ensure_one()
        partner = self._creator_partner()
        self.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note',
                          partner_ids=partner.ids)

    def _payment_values(self, tran):
        values = {'provider_tran_ref': tran.get('ref') or False,
                  'paid_at': tran.get('time') or fields.Datetime.now(),
                  'installment_count': tran.get('installment_count') or 1,
                  'card_last4': tran.get('card_last4') or False}
        cents = self._to_cents(tran.get('amount'))
        if cents is not None:
            values['paid_amount'] = float(cents)
        return values

    def _apply_status(self, result):
        """Sorgu sonucunu uygular (08-sozlesme-G8 §2). Bildirim yalnız geçiş anında yazılır."""
        self.ensure_one()
        rec = self.sudo()
        now = fields.Datetime.now()
        if not result.get('ok'):
            values = {'last_checked_at': now}
            if rec.state in ('sent', 'review') + LATE_PAYMENT_STATES:
                values.update(last_error_code=result.get('error_code') or 'TIMEOUT',
                              last_error_message=result.get('error_message') or QUERY_FAILED_MSG)
            rec.write(values)
            return False
        transactions = result.get('transactions') or []
        rec.write({'last_checked_at': now})
        if rec.state in IRREVERSIBLE_STATES:
            rec._sync_refunds(transactions)
            return True
        if rec.state in ('sent', 'unknown'):
            rec._apply_open_status(transactions, now)
        elif rec.state in LATE_PAYMENT_STATES:
            rec._apply_late_status(transactions)
        # review: yalnız yönetici eylemiyle çıkar; sending: G7/cron'un işidir
        return True

    @api.model
    def _classify(self, transactions):
        sales = [t for t in transactions if t.get('kind') == 'sale']
        approved = [t for t in sales if t.get('status') == 'approved']
        in_review = [t for t in sales if t.get('status') == 'review']
        pending = [t for t in sales if t.get('status') == 'pending']
        failed = {t.get('ref') or '#%d' % i for i, t in enumerate(sales)
                  if t.get('status') in ('failed', 'cancelled')}
        others = [t for t in transactions
                  if t.get('kind') != 'sale' and t.get('status') == 'approved']
        return approved, in_review, pending, failed, others

    def _review_reason(self, approved, in_review, others):
        """İnceleme nedeni (boş = ödendi sayılabilir)."""
        expected = self._to_cents(self.amount)
        currency = self.currency_id.name or 'TRY'
        if len(approved) > 1:
            amounts = ', '.join(format_try(t.get('amount') or 0) for t in approved)
            return 'REVIEW_MULTIPLE', ('Birden fazla onaylı satış (%d adet: %s); çift tahsilat '
                                       'olabilir. Talep tutarı %s.' % (
                                           len(approved), amounts, format_try(self.amount)))
        if approved:
            tran = approved[0]
            got = self._to_cents(tran.get('amount'))
            if got is None or got != expected:
                return 'REVIEW_AMOUNT', ('Tutar uyuşmazlığı: Paratika\'da tahsil edilen %s, '
                                         'talep tutarı %s.' % (
                                             format_try(tran.get('amount') or 0),
                                             format_try(self.amount)))
            if (tran.get('currency') or '') != currency:
                return 'REVIEW_CURRENCY', ('Para birimi uyuşmazlığı: Paratika %s, talep %s '
                                           '(tutar %s).' % (tran.get('currency') or '-', currency,
                                                            format_try(tran.get('amount') or 0)))
            return '', ''
        if in_review:
            return 'REVIEW_MR', ('Paratika işlemi manuel incelemede (MR): %s, talep tutarı %s.' % (
                format_try(in_review[0].get('amount') or 0), format_try(self.amount)))
        if others:
            return 'REVIEW_OTHER', ('Onaylı satış olmadan onaylı iptal/iade işlemi var: %s, '
                                    'talep tutarı %s.' % (format_try(others[0].get('amount') or 0),
                                                         format_try(self.amount)))
        return None, None

    def _set_review(self, code, reason, tran):
        values = {'state': 'review', 'last_error_code': code, 'last_error_message': reason[:250]}
        if tran:
            values.update(self._payment_values(tran))
        self.write(values)
        self._notify_creator('%s – İnceleme gerekli. %s' % (self.invoice_no, reason))

    def _apply_open_status(self, transactions, now):
        approved, in_review, pending, failed, others = self._classify(transactions)
        values = {'failed_attempt_count': len(failed)}
        code, reason = self._review_reason(approved, in_review, others)
        if code == '':
            tran = approved[0]
            values.update(self._payment_values(tran))
            values.update(state='paid', last_error_code=False, last_error_message=False)
            self.write(values)
            detail = ['%d taksit' % (values.get('installment_count') or 1)]
            if values.get('card_last4'):
                detail.append('kart son 4: %s' % values['card_last4'])
            self._notify_creator('%s – %s ödendi (%s)' % (
                self.invoice_no, format_try(tran.get('amount')), ', '.join(detail)))
            self._sync_refunds(transactions)
            return
        if code:
            self.write(values)
            self._set_review(code, reason, (approved or in_review or [None])[0])
            return
        if failed:
            values.update(last_error_code='CARD_FAILED',
                          last_error_message='Kart denemesi başarısız (%d)' % len(failed))
        elif self.state == 'sent':
            values.update(last_error_code=False, last_error_message=False)
        self.write(values)
        if self.state == 'sent' and self.expires_at and now > self.expires_at and not pending:
            self.write({'state': 'expired'})
            self._post_note('Link süresi doldu; Paratika\'da onaylı ödeme yok.')

    def _apply_late_status(self, transactions):
        """Süresi dolmuş / iptal / hatalı kayda gelen ödeme: tutar eşit olsa bile review."""
        approved, in_review, _pending, _failed, _others = self._classify(transactions)
        tran = (approved or in_review or [None])[0]
        if not tran:
            return
        code, reason = self._review_reason(approved, in_review, [])
        prefix = 'Kapalı linke (%s) geç ödeme geldi: Paratika %s, talep tutarı %s.' % (
            dict(PAYMENT_STATES).get(self.state, self.state),
            format_try(tran.get('amount') or 0), format_try(self.amount))
        self._set_review('REVIEW_LATE', ('%s %s' % (prefix, reason or '')).strip(), tran)

    # ---------------------------------------------------------------- belirsiz uzlaştırma (KK-16)
    def _mark_stale_sending(self):
        """5 dakikadan eski 'Gönderiliyor' (yarıda kalmış istek) -> 'Belirsiz'."""
        self.ensure_one()
        self.sudo().write({'state': 'unknown', 'unknown_since': fields.Datetime.now(),
                           'link_not_found_count': 0, 'last_error_code': 'STALE_SENDING',
                           'last_error_message': UNKNOWN_MSG})
        self._post_note(STALE_SENDING_MSG)

    def _reconcile_unknown_link(self):
        """'Belirsiz' kaydı uzlaştırır: önce ödeme sorgusu, onay yoksa ``find_link``.

        Risk 1 (yönetici kararı): "bulunamadı" yanıtı kaydı ancak en az
        ``LINK_NOT_FOUND_MIN_CHECKS`` ayrı sorguda ve ilk belirsizlikten
        ``LINK_NOT_FOUND_MIN_AGE`` geçtikten sonra 'Hata' yapar (Paratika gecikmesiyle
        eski link açıkken yeni link açılıp çift tahsilat olmasın).
        """
        self.ensure_one()
        rec = self.sudo()
        result = rec._sync_status()
        if rec.state != 'unknown' or not result.get('ok'):
            return result
        found = rec._call_provider_safely('find_link', 'link uzlaştırmasında')
        now = fields.Datetime.now()
        if found.get('ok') and found.get('found') and found.get('token'):
            sent_at = rec.create_date or now
            rec.write({
                'state': 'sent', 'provider_token': found['token'], 'sent_at': sent_at,
                'expires_at': sent_at + timedelta(hours=rec.expiry_hours or 168),
                'link_not_found_count': 0, 'last_error_code': False, 'last_error_message': False,
            })
            rec._post_note('Link Paratika\'da bulundu; durum Gönderildi olarak düzeltildi.')
            # Süre geçmişse aynı turda expired (sorgu sonucu zaten elde)
            rec._apply_status(result)
            return found
        answered = bool(found.get('ok') or found.get('ambiguous'))
        if found.get('ambiguous'):
            if rec.last_error_code != 'AMBIGUOUS':
                rec._post_note(AMBIGUOUS_MSG)
            rec.write({'last_error_code': 'AMBIGUOUS', 'last_error_message': AMBIGUOUS_MSG})
        elif found.get('ok'):
            count = rec.link_not_found_count + 1
            since = rec.unknown_since or rec.create_date or now
            if count >= LINK_NOT_FOUND_MIN_CHECKS and now >= since + LINK_NOT_FOUND_MIN_AGE:
                rec.write({'state': 'error', 'link_not_found_count': count,
                           'last_error_code': 'LINK_NOT_FOUND',
                           'last_error_message': LINK_NOT_FOUND_MSG})
                rec._post_note(LINK_NOT_FOUND_MSG)
                return found
            rec.write({'link_not_found_count': count, 'last_error_code': 'LINK_NOT_FOUND_PENDING',
                       'last_error_message': LINK_NOT_FOUND_PENDING_MSG})
        # Fark 2 (onaylı): link süresi dolmuş, sorgu ve arama onaylı işlem göstermiyor -> expired
        window_end = (rec.create_date or now) + timedelta(hours=rec.expiry_hours or 168)
        if answered and rec.state == 'unknown' and now > window_end:
            rec.write({'state': 'expired'})
            rec._post_note('Link süresi doldu; Paratika\'da onaylı ödeme bulunmadı.')
        return found

    # ---------------------------------------------------------------- kilit yardımcıları
    def _try_lock_skip_locked(self):
        """Cron: satırı kilitler; başkası tutuyorsa False (beklemez)."""
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM sanal_pos_payment WHERE id = %s FOR UPDATE SKIP LOCKED', [self.id])
        return bool(self.env.cr.fetchone())

    def _try_lock_nowait(self):
        """Webhook bayrağı: kilit beklenmez; kilitli veya eşzamanlı değişmişse False."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    'SELECT id FROM sanal_pos_payment WHERE id = %s FOR UPDATE NOWAIT', [self.id])
        except (pg_errors.LockNotAvailable, pg_errors.SerializationFailure):
            return False
        return True

    # ---------------------------------------------------------------- G9 arayüzü
    @api.model
    @api.private
    def _mark_sync_requested(self, merchant_payment_id):
        """Webhook/dönüş tetiği: yalnız bayrak + cron tetiği. Dış çağrı ve commit yok.

        Gövde asla karar için okunmaz. Satır kilitliyse bayrak atlanır; sent/unknown kayıtlar
        periyodik cron'da zaten sorgulanır (Risk 2). Dönüş: kayıt veya boş recordset.

        G-1: cron tetiği yalnız bayrak False->True geçişinde kurulur (aynı ödemeye tekrarlanan
        bildirimler tetik çoğaltmaz) ve son sorgudan ``SYNC_REQUEST_MIN_INTERVAL`` sonrasına
        ertelenir. Kilit alınamazsa tetik de kurulmaz.
        """
        Payment = self.sudo()
        if not merchant_payment_id:
            return Payment.browse()
        rec = Payment.search([('merchant_payment_id', '=', merchant_payment_id)], limit=1)
        if not rec or not rec._try_lock_nowait():
            return rec
        rec.invalidate_recordset(['sync_requested', 'last_checked_at'])
        if rec.sync_requested:
            return rec  # tetik zaten kurulu; bayrak cron'da temizlenene kadar yeni tetik yok
        rec.write({'sync_requested': True})
        when = fields.Datetime.now()
        if rec.last_checked_at and rec.last_checked_at + SYNC_REQUEST_MIN_INTERVAL > when:
            when = rec.last_checked_at + SYNC_REQUEST_MIN_INTERVAL
        self._trigger_sync_cron(at=when)
        return rec

    # ---------------------------------------------------------------- kullanıcı: Durumu Sorgula (KK-28)
    def action_check_status(self):
        self.ensure_one()
        self._check_sanal_pos_user()
        rec = self.sudo()
        now = fields.Datetime.now()
        if rec.state not in OPEN_STATES + ('review',) and rec.create_date < now - CHECK_STATUS_MAX_AGE:
            raise UserError('30 günden eski kapanmış kayıt sorgulanamaz.')
        if rec.state == 'sending' and rec.create_date >= now - STALE_SENDING_AGE:
            raise UserError(BUSY_MSG)
        if not rec._lock_for_provider_call():
            raise UserError(BUSY_MSG)
        rec.invalidate_recordset()
        # Kilitten sonra raise yok: dış çağrı sonucu commit edilir, bildirimle gösterilir
        if rec.state == 'sending':
            rec._mark_stale_sending()
        if rec.state == 'unknown':
            result = rec._reconcile_unknown_link()
        else:
            result = rec._sync_status()
        rec.write({'sync_requested': False})
        self._sp_commit()
        label = dict(PAYMENT_STATES).get(rec.state, rec.state)
        message = 'Durum: %s' % label
        if rec.last_error_message:
            message = '%s – %s' % (message, rec.last_error_message)
        kind = 'success' if result.get('ok') else 'warning'
        return self._notification_action(message, kind)

    # ---------------------------------------------------------------- kullanıcı: link yönetimi (G10)
    # Desen (G7/G8 ile aynı): NOWAIT kilit -> kilitten sonra durum yeniden doğrulanır -> dış çağrı ->
    # sonuç yazılır -> ``_sp_commit`` -> bildirim. Dış çağrıdan sonra ASLA raise edilmez (sonuç
    # Paratika'da gerçekleşmiş olabilir); hatalar kayda ve bildirime yazılır. Kilit, çağrı boyunca
    # tutulur (commit çağrıdan sonradır): önce commit kilidi bırakırdı.
    def _check_link_open(self, require_unexpired):
        """Yalnız 'Gönderildi' linkler (yeniden gönderim için ayrıca süresi dolmamış)."""
        self.ensure_one()
        if self.state != 'sent':
            raise UserError('Bu işlem yalnız "Gönderildi" durumundaki linklerde yapılabilir.')
        if require_unexpired and self.expires_at and self.expires_at <= fields.Datetime.now():
            raise UserError('Linkin süresi dolmuş; yeniden gönderilemez. Yeni link oluşturun.')

    def action_resend(self, channels=None):
        """KK-31: linki seçilen kanallardan yeniden gönderir.

        ``channels`` verilmezse (form düğmesi) kanal seçim sihirbazı açılır; sihirbaz
        ``['sms', 'email']`` alt kümesiyle bu metodu yeniden çağırır.
        """
        self.ensure_one()
        self._check_sanal_pos_user()
        rec = self.sudo()
        rec._check_link_open(require_unexpired=True)
        if channels is None:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Linki Yeniden Gönder',
                'res_model': 'sanal.pos.payment.resend.wizard',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'new',
                'context': {'default_payment_id': self.id},
            }
        channels = list(channels)
        if not channels:
            raise UserError(CHANNEL_MSG)
        if any(c not in RESEND_CHANNELS for c in channels):
            raise UserError('Geçersiz gönderim kanalı.')
        channels = [c for c in RESEND_CHANNELS if c in channels]
        if not rec._lock_for_provider_call():
            raise UserError(BUSY_MSG)
        rec.invalidate_recordset()
        rec._check_link_open(require_unexpired=True)
        # Kilitten sonra raise yok: sonuç kayda ve bildirime yazılır
        result = rec._call_provider_safely(
            'resend', 'yeniden gönderimde', channels, message=RESEND_FAILED_MSG)
        if result.get('ok'):
            label = '+'.join(RESEND_LABELS[c] for c in channels)
            if rec.last_error_code and rec.last_error_code != 'CARD_FAILED':
                rec.write({'last_error_code': False, 'last_error_message': False})
            rec._post_note('Yeniden gönderildi (%s)' % label)
            message, kind = 'Yeniden gönderildi (%s)' % label, 'success'
        else:
            if result.get('timeout'):
                code, message, kind = 'TIMEOUT', RESEND_TIMEOUT_MSG, 'warning'
            else:
                code = result.get('error_code') or False
                message = result.get('error_message') or RESEND_FAILED_MSG
                kind = 'danger'
            rec.write({'last_error_code': code, 'last_error_message': message})
        self._sp_commit()
        return self._notification_action(message, kind, sticky=kind != 'success')

    def action_cancel_link(self):
        """KK-32: açık linki Paratika'da iptal eder.

        ERR10143 (zaten ödenmiş/iptal): gerçek durum QUERYTRANSACTION ile belirlenir (tek sorgu);
        yanıt alınamayan (zaman aşımı) iptal, iptal sayılmaz.
        """
        self.ensure_one()
        self._check_sanal_pos_user()
        rec = self.sudo()
        rec._check_link_open(require_unexpired=False)
        if not rec._lock_for_provider_call():
            raise UserError(BUSY_MSG)
        rec.invalidate_recordset()
        rec._check_link_open(require_unexpired=False)
        # Kilitten sonra raise yok
        result = rec._call_provider_safely(
            'cancel_link', 'link iptalinde', message=CANCEL_FAILED_MSG)
        if result.get('ok'):
            message, kind = rec._set_link_cancelled('Link iptal edildi.')
        elif result.get('already_closed'):
            message, kind = rec._resolve_already_closed()
        elif result.get('timeout'):
            rec.write({'last_error_code': 'TIMEOUT', 'last_error_message': CANCEL_TIMEOUT_MSG})
            message, kind = CANCEL_TIMEOUT_MSG, 'warning'
        else:
            message = result.get('error_message') or CANCEL_FAILED_MSG
            rec.write({'last_error_code': result.get('error_code') or False,
                       'last_error_message': message})
            kind = 'danger'
        self._sp_commit()
        return self._notification_action(message, kind, sticky=kind != 'success')

    def _set_link_cancelled(self, note):
        self.ensure_one()
        self.write({'state': 'link_cancelled', 'last_error_code': False,
                    'last_error_message': False})
        self._post_note(note)
        return note, 'success'

    def _resolve_already_closed(self):
        """ERR10143: link zaten ödenmiş ya da iptal edilmiş; gerçek durum tek sorguyla yazılır."""
        self.ensure_one()
        result = self._sync_status()
        if self.state == 'sent':
            # Sorgu onaylı/inceleme işlemi göstermedi: bekleyen işlem yoksa link zaten iptaldir
            _approved, _in_review, pending, _failed, _others = self._classify(
                result.get('transactions') or [])
            if result.get('ok') and not pending:
                return self._set_link_cancelled(CANCEL_ALREADY_MSG)
            message = CANCEL_PENDING_MSG if result.get('ok') else QUERY_FAILED_MSG
            self.write({'last_error_code': 'CANCEL_UNRESOLVED', 'last_error_message': message})
            return message, 'warning'
        label = dict(PAYMENT_STATES).get(self.state, self.state)
        if self.state == 'paid':
            return 'Ödeme alınmış; link iptal edilemedi. Durum: %s' % label, 'warning'
        return 'Link iptal edilemedi; gerçek durum: %s' % label, 'warning'

    # ---------------------------------------------------------------- yönetici: inceleme (KK-24)
    def _check_review_action(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('sanal_pos.group_sanal_pos_manager')):
            raise AccessError('Bu işlem için Sanal POS yönetici yetkisi gerekir.')
        if self.state != 'review':
            raise UserError('Bu işlem yalnız "İnceleme gerekli" durumundaki taleplerde yapılabilir.')

    def action_review_accept(self):
        """İnceleme -> Ödendi (yönetici). KK-30 bildirimi oluşturana gider."""
        self._check_review_action()
        rec = self.sudo()
        if not rec._lock_for_provider_call():
            raise UserError(BUSY_MSG)
        rec.invalidate_recordset()
        rec._check_review_action()
        amount = rec.paid_amount or rec.amount
        rec.write({'state': 'paid', 'paid_amount': amount,
                   'paid_at': rec.paid_at or fields.Datetime.now(),
                   'last_error_code': False, 'last_error_message': False})
        rec._notify_creator('%s – %s ödendi (inceleme sonucu kabul eden yönetici: %s)' % (
            rec.invoice_no, format_try(amount), self.env.user.name))
        return self._form_action()

    def action_review_close(self):
        """İnceleme -> Hata (yönetici). Kapatma notu zorunludur (Risk 3): sihirbaz açılır."""
        self._check_review_action()
        return {
            'type': 'ir.actions.act_window',
            'name': 'İncelemeyi Kapat',
            'res_model': 'sanal.pos.payment.review.close.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_payment_id': self.id},
        }

    def _review_close(self, reason):
        """Sihirbazdan: notu chatter'a yazar ve kaydı 'Hata' yapar (fatura yeni linke açılır)."""
        self._check_review_action()
        reason = (reason or '').strip()
        if len(reason) < 5:
            raise UserError('Kapatma notu zorunludur (en az 5 karakter).')
        rec = self.sudo()
        if not rec._lock_for_provider_call():
            raise UserError(BUSY_MSG)
        rec.invalidate_recordset()
        rec._check_review_action()
        rec.write({'state': 'error', 'last_error_code': 'REVIEW_CLOSED',
                   'last_error_message': ('İnceleme kapatıldı: %s' % reason)[:250]})
        rec._post_note('İnceleme kapatıldı (yönetici: %s). Not: %s' % (self.env.user.name, reason))
        return self._form_action()

    # ---------------------------------------------------------------- yönetici: iptal / iade (G11)
    # Değişmez (sözleşme §0): Paratika'ya VOID/REFUND gitmeden önce COMMIT EDİLMİŞ bir 'İşleniyor'
    # satırı vardır; kısmi benzersiz indeks ikinci satırı engeller. Satır 'İşleniyor/Belirsiz'
    # durumundan yalnız kanıtla çıkar (yanıt ya da uzlaştırma). Dış çağrıdan sonra raise yok.
    @api.model
    def _check_refund_manager(self):
        """KK-49/U-3: yalnız Sanal POS Yöneticisi; sudo/sistem yöneticisi muafiyeti yok."""
        if not self.env.user.has_group('sanal_pos.group_sanal_pos_manager'):
            raise AccessError('İptal/iade için Sanal POS yönetici yetkisi gerekir.')

    @api.model
    def _parse_refund_cents(self, amount):
        """Tutar -> kuruş (int). 2'den fazla ondalık, NaN/sonsuz, bool -> None (yuvarlama yok)."""
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str, Decimal)):
            return None
        try:
            value = Decimal(str(amount).strip())
        except (InvalidOperation, ValueError):
            return None
        if not value.is_finite():
            return None
        cents = value * 100
        if cents != cents.to_integral_value():
            return None
        return int(cents)

    def _refundable_cents(self):
        """Ödenen − başarılı − devam eden (kuruş)."""
        self.ensure_one()
        used = sum(int(self._to_cents(l.amount) * 100) for l in self.refund_ids
                   if l.state in ('done', 'processing', 'unknown'))
        return int((self._to_cents(self.paid_amount or 0) or 0) * 100) - used

    def _refund_validate(self, kind, cents):
        """Durum, devam eden satır ve tutar/iptal kuralları (kilitten önce ve sonra)."""
        self.ensure_one()
        if self.state in REFUNDED_STATES:
            raise UserError(NOTHING_LEFT_MSG)
        if self.state not in ('paid', 'partial_refund'):
            raise UserError(REFUND_NOT_PAID_MSG)
        if self._has_blocking_refund_line(include_done=False):
            raise UserError(REFUND_BUSY_MSG)
        if kind == 'void':
            if not self.can_void:
                raise UserError(VOID_NOT_ALLOWED_MSG)
            return
        left = self._refundable_cents()
        if left <= 0:
            raise UserError(NOTHING_LEFT_MSG)
        if cents is None or cents < 1 or cents > left:
            raise UserError(REFUND_RANGE_MSG % format_try(Decimal(left) / 100))

    def action_void(self, reason):
        """KK-40: ödeme iptali (VOID) — aynı gün, iadesiz kayıtta tam tutar."""
        self.ensure_one()
        return self._run_refund_flow('void', None, reason)

    def action_refund(self, amount, reason):
        """KK-42/43: tam veya kısmi iade (REFUND)."""
        self.ensure_one()
        return self._run_refund_flow('refund', amount, reason)

    def action_open_refund_wizard(self):
        return self._open_refund_wizard('refund')

    def action_open_void_wizard(self):
        return self._open_refund_wizard('void')

    def _open_refund_wizard(self, kind):
        self.ensure_one()
        self._check_refund_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ödemeyi İptal Et' if kind == 'void' else 'İade Et',
            'res_model': REFUND_WIZARD,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_payment_id': self.id, 'default_kind': kind},
        }

    def _run_refund_flow(self, kind, amount, reason):
        """Sözleşme §4: ön kontrol -> kilit -> senkron -> yeniden doğrula -> satır -> commit #1 ->
        kilit -> dış çağrı -> sonuç -> commit #2 -> bildirim."""
        self.ensure_one()
        self._check_refund_manager()
        reason = (reason or '').strip()
        if len(reason) < 5:
            raise UserError(REFUND_REASON_MSG)
        cents = self._parse_refund_cents(amount) if kind == 'refund' else None
        rec = self.sudo()
        rec._refund_validate(kind, cents)
        if not rec._try_lock_nowait():
            raise UserError(REFUND_BUSY_MSG)
        rec.invalidate_recordset()
        result = rec._sync_status()                      # KK-44: karar güncel durumla verilir
        if not result.get('ok'):
            self._sp_commit()
            raise UserError(REFUND_SYNC_FAILED_MSG)
        try:
            rec._refund_validate(kind, cents)
            line = rec._create_processing_line(kind, cents, reason)
        except UserError:
            self._sp_commit()                            # senkron sonucu (ör. paid->voided) korunur
            raise
        self._sp_commit()                                # commit #1: satır kalıcı, kilit bırakıldı
        # Bu noktadan sonra raise yok
        if not rec._try_lock_nowait():
            line.write({'state': 'failed', 'error_code': 'NOT_SENT',
                        'error_message': REFUND_NOT_SENT_MSG})
            rec._post_note('%s (%s): %s' % (REFUND_KIND_LABELS[kind], format_try(line.amount),
                                            REFUND_NOT_SENT_MSG))
            self._sp_commit()
            return rec._notification_action(REFUND_BUSY_MSG, 'warning')
        result = rec._call_provider_safely(
            kind, 'iptal/iade isteğinde', line, message=REFUND_UNKNOWN_MSG)
        try:
            with self.env.cr.savepoint():
                message, notify_type = rec._apply_refund_result(line, result, reason)
        except Exception as exc:  # noqa: BLE001 - dış çağrıdan sonra raise yok
            _logger.error('sanal_pos: iade sonucu yazılamadı (%s), ödeme id=%s',
                          type(exc).__name__, rec.id)
            rec._mark_refund_line_unknown(line, 'APPLY_ERROR')
            message, notify_type = REFUND_UNKNOWN_MSG, 'warning'
        if line.state == 'unknown':
            rec._trigger_sync_cron()
            rec._trigger_sync_cron(at=fields.Datetime.now() + REFUND_SECOND_CHECK_DELAY)
        self._sp_commit()                                # commit #2
        return rec._notification_action(message, notify_type, sticky=notify_type != 'success')

    def _create_processing_line(self, kind, cents, reason):
        """'İşleniyor' satırı; kısmi benzersiz indeks ihlali = devam eden işlem (KK-45)."""
        amount = self.paid_amount if kind == 'void' else float(Decimal(cents) / 100)
        try:
            with self.env.cr.savepoint():
                line = self.env['sanal.pos.refund'].sudo().create({
                    'payment_id': self.id, 'kind': kind, 'amount': amount,
                    'state': 'processing', 'source': 'odoo', 'reason': reason,
                    'user_id': self.env.user.id,
                })
                line.flush_recordset()
        except pg_errors.UniqueViolation:
            self.invalidate_recordset(['refund_ids'])
            raise UserError(REFUND_BUSY_MSG) from None
        return line

    def _mark_refund_line_unknown(self, line, code):
        """Yedek yol: sonuç yazılamadıysa satır 'Belirsiz' (uzlaştırma karar verir)."""
        line.invalidate_recordset()
        try:
            with self.env.cr.savepoint():
                line.sudo().write({'state': 'unknown', 'unknown_since': fields.Datetime.now(),
                                   'not_found_count': 0, 'error_code': code,
                                   'error_message': REFUND_UNKNOWN_MSG})
        except Exception as exc:  # noqa: BLE001 - satır 'İşleniyor' kalır; cron 5 dk sonra alır
            _logger.error('sanal_pos: iade satırı belirsiz yapılamadı (%s), ödeme id=%s',
                          type(exc).__name__, self.id)

    def _safe_refund_ref(self, line, ref):
        """R-3: satışın işlem nosu ya da başka satırda kullanılan no saklanmaz (UNIQUE çakışmasın)."""
        if not ref:
            return False
        if line.kind == 'refund' and ref == self.provider_tran_ref:
            return False
        if any(l.provider_ref == ref for l in self.refund_ids if l != line):
            return False
        return ref

    def _apply_refund_result(self, line, result, reason):
        """Dış çağrı sonucu (sözleşme §5). Dönüş: (mesaj, bildirim türü)."""
        now = fields.Datetime.now()
        label = REFUND_KIND_LABELS[line.kind]
        amount_text = format_try(line.amount)
        if result.get('ok'):
            ref = self._safe_refund_ref(line, result.get('ref'))
            line.write({'state': 'done', 'provider_ref': ref, 'done_at': now,
                        'error_code': False, 'error_message': False})
            self._recompute_refund_state()
            done = 'ödeme iptal edildi' if line.kind == 'void' else 'iade edildi'
            body = '%s – %s %s (yönetici: %s). Neden: %s' % (
                self.invoice_no, amount_text, done, self.env.user.name, reason)
            if not ref:
                body += ' İşlem no Paratika sorgusuyla eşleştirilecek.'
            self._notify_creator(body)                   # KK-51
            return body, 'success'
        if result.get('timeout'):
            line.write({'state': 'unknown', 'unknown_since': now, 'not_found_count': 0,
                        'error_code': result.get('error_code') or 'TIMEOUT',
                        'error_message': REFUND_UNKNOWN_MSG})
            self._post_note('%s (%s): %s' % (label, amount_text, REFUND_UNKNOWN_MSG))
            return REFUND_UNKNOWN_MSG, 'warning'
        code = result.get('error_code') or 'ERROR'
        message = result.get('error_message') or 'Paratika isteği reddetti.'
        line.write({'state': 'failed', 'error_code': code, 'error_message': message[:250]})
        self._post_note('%s yapılamadı (%s): %s' % (label, amount_text, message))
        if code == 'ERR10032':
            self._sync_status()                          # KK-45: gerçek iade durumu yazılır
        return '%s yapılamadı: %s' % (label, message), 'danger'

    # ---------------------------------------------------------------- cron'lar (KK-25, KK-27, KK-39)
    @api.model
    def _sync_candidate_ids(self, limit):
        """Kilitsiz aday listesi: bayraklı > bayat sending > uzlaştırılacak iade satırı (G11) >
        unknown/sent (en eski sorgu önce)."""
        self.flush_model()
        self.env['sanal.pos.refund'].flush_model()
        cr = self.env.cr
        now = fields.Datetime.now()
        stale_before = now - STALE_SENDING_AGE
        ids = []
        for query, params in (
            ('SELECT id FROM sanal_pos_payment WHERE sync_requested ORDER BY id LIMIT %s', []),
            ("SELECT id FROM sanal_pos_payment WHERE state = 'sending' AND create_date < %s "
             'ORDER BY id LIMIT %s', [stale_before]),
            ("SELECT DISTINCT payment_id FROM sanal_pos_refund WHERE state = 'unknown' "
             "OR (state = 'processing' AND create_date < %s) ORDER BY payment_id LIMIT %s",
             [now - REFUND_STALE_AGE]),
            # G-1: bayraksız 'sent' son SENT_RECHECK_AGE içinde sorgulandıysa bu tur atlanır
            ("SELECT id FROM sanal_pos_payment WHERE state = 'unknown' OR (state = 'sent' "
             'AND (last_checked_at IS NULL OR last_checked_at < %s)) '
             'ORDER BY last_checked_at ASC NULLS FIRST, id LIMIT %s', [now - SENT_RECHECK_AGE]),
        ):
            cr.execute(query, params + [limit])
            for (pid,) in cr.fetchall():
                if pid not in ids:
                    ids.append(pid)
        return ids[:limit]

    def _cron_sync_one(self):
        """Kilitli kayıt üzerinde tek senkron adımı. False: kayıt bu tur uygun değil."""
        self.ensure_one()
        if not self._try_lock_skip_locked():
            return False
        self.invalidate_recordset()
        now = fields.Datetime.now()
        recent = self.last_checked_at and self.last_checked_at > now - SYNC_REQUEST_MIN_INTERVAL
        if self.sync_requested and recent:
            return False  # G-1 hız sınırı: bayrak korunur, ertelenmiş tetik/periyodik cron alır
        if (self.state == 'sent' and not self.sync_requested and self.last_checked_at
                and self.last_checked_at >= now - SENT_RECHECK_AGE
                and not self._has_refund_to_reconcile(now)):
            return False  # G-1: yakın zamanda sorgulandı (tetiklenmiş ek tur)
        if self.state == 'sending':
            if not self.create_date or self.create_date >= now - STALE_SENDING_AGE:
                return False  # G7 isteği sürüyor olabilir; bayrak korunur
            self._mark_stale_sending()
        if self.state == 'unknown':
            self._reconcile_unknown_link()
        elif self.state == 'sent' or self.sync_requested or self._has_refund_to_reconcile(now):
            self._sync_status()
        else:
            return False
        self.write({'sync_requested': False, 'last_checked_at': fields.Datetime.now()})
        return True

    def _has_refund_to_reconcile(self, now):
        """KK-47: belirsiz ya da yarıda kalmış ('İşleniyor', 5 dk+) iade/iptal satırı var mı."""
        self.ensure_one()
        return any(l.state == 'unknown' or (
            l.state == 'processing' and l.create_date and l.create_date < now - REFUND_STALE_AGE)
            for l in self.refund_ids)

    @api.model
    def _cron_sync(self, limit=CRON_SYNC_LIMIT):
        """10 dakikalık senkron: kayıt başına savepoint + SKIP LOCKED + commit; hata izolasyonu."""
        Payment = self.sudo()
        started = time.monotonic()
        for pid in Payment._sync_candidate_ids(limit):
            if time.monotonic() - started > CRON_TIME_BUDGET:
                Payment._trigger_sync_cron(at=fields.Datetime.now())
                break
            rec = Payment.browse(pid)
            try:
                with self.env.cr.savepoint():
                    rec._cron_sync_one()
            except Exception as exc:  # noqa: BLE001 - tek kayıt cron'u durdurmaz (KK-25)
                _logger.warning('sanal_pos: senkron hatası (%s), ödeme id=%s',
                                type(exc).__name__, pid)
                try:
                    with self.env.cr.savepoint():
                        rec.write({'last_checked_at': fields.Datetime.now()})
                except Exception as exc2:  # noqa: BLE001
                    _logger.warning('sanal_pos: son sorgu zamanı yazılamadı (%s), ödeme id=%s',
                                    type(exc2).__name__, pid)
            Payment._sp_commit()
        return True

    @api.model
    def _cron_daily(self):
        """Günlük: log temizliği (KK-39) + son 30 günde ödenenlerin iade senkronu (KK-27)."""
        self.env['sanal.pos.log'].sudo()._purge_old()
        self._sp_commit()
        Payment = self.sudo()
        now = fields.Datetime.now()
        local_now = now.replace(tzinfo=_UTC).astimezone(_ISTANBUL)
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) \
            .astimezone(_UTC).replace(tzinfo=None)
        candidates = Payment.search([
            ('state', 'in', ('paid', 'partial_refund')),
            ('paid_at', '>=', now - REFUND_SYNC_WINDOW),
            '|', ('last_refund_sync_at', '=', False), ('last_refund_sync_at', '<', day_start),
        ], order='id', limit=1000)
        started = time.monotonic()
        for pid in candidates.ids:
            if time.monotonic() - started > CRON_TIME_BUDGET:
                break  # kalanlar ertesi gün (gün içinde ikinci kez sorgulanmaz)
            rec = Payment.browse(pid)
            try:
                with self.env.cr.savepoint():
                    if rec._try_lock_skip_locked():
                        rec.invalidate_recordset()
                        rec._sync_status()
                        rec.write({'last_refund_sync_at': fields.Datetime.now()})
            except Exception as exc:  # noqa: BLE001
                _logger.warning('sanal_pos: günlük iade senkronu hatası (%s), ödeme id=%s',
                                type(exc).__name__, pid)
            Payment._sp_commit()
        return True

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

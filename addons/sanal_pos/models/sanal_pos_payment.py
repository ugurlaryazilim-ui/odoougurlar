# -*- coding: utf-8 -*-
"""Sanal POS ödeme talebi (tasarım §3.1, §4). Çekirdek model ve durum makinesi tabanı.

Kullanıcı grupları bu modele YALNIZ OKUMA ACL'i ile erişir (ir.model.access.csv).
Hiçbir alan kullanıcı tarafından write/create ile değiştirilemez; tüm değişiklikler
ilerleyen görevlerde eklenecek kontrollü model metotlarıyla (``sudo()`` en dar
kapsamda) yapılır. Chatter'a not yazabilmek için ``_mail_post_access = 'read'``.

Dış çağrı kuralı: çağrıdan ÖNCE "işlemde" durumu yazılıp ``_sp_commit()`` edilir;
``_sp_commit`` asla bir ``cr.savepoint()`` bloğunun içinden çağrılmaz.
"""
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .res_config_settings import get_bool_param

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
    customer_email = fields.Char(string='E-posta')
    customer_address = fields.Char(string='Adres')
    customer_city = fields.Char(string='İl')
    customer_zip = fields.Char(string='Posta Kodu')

    # ---------------------------------------------------------------- tutar
    currency_id = fields.Many2one(
        'res.currency', string='Para Birimi', required=True,
        default=lambda self: self.env.ref('base.TRY', raise_if_not_found=False))
    amount = fields.Monetary(string='Tutar', currency_field='currency_id', required=True)

    # ---------------------------------------------------------------- link
    channel_sms = fields.Boolean(string='SMS')
    channel_email = fields.Boolean(string='E-posta')
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

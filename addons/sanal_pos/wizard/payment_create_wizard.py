# -*- coding: utf-8 -*-
"""Yeni ödeme linki sihirbazı (tasarım §3.4, §6.1, §6.2; sözleşme 07-sozlesme-G7.md).

Akış (``action_create_link``):
  1. yetki + "fatura getirildi mi" denetimi
  2. fatura YENİDEN okunur; tutar getirilenle aynı olmalı (tutar kilidi, KK-5)
  3. alan doğrulaması (tek UserError'da toplanır; commit yok)
  4. ön kontrol: KK-19 / KK-18 / KK-20
  5. 'Gönderiliyor' kaydı savepoint içinde (tekillik ihlali -> KK-18, transaction temiz)
  6. KK-5 değişiklik notları + COMMIT  (bundan sonra raise yok)
  7-9. ödeme modelinde: kilit, dış çağrı, sonuç yazımı + COMMIT, belirsizse cron tetiği

Tutar sihirbazdan ALINMAZ: ``amount`` yalnız gösterimdir; ödeme kaydına her zaman
oluşturma anında yeniden okunan fatura tutarı yazılır.
"""
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from ..models.res_config_settings import get_bool_param
from ..models.sanal_pos_payment import FIELD_MAX_LENGTH
from ..tools import clean_text, format_try, normalize_phone, validate_email

# Yalnız "Faturayı Getir" (sunucu) yazabilir; create/write ile doğru değer gelirse reddedilir.
_PROTECTED_FIELDS = ('fetched', 'fetched_invoice_no', 'fetched_amount')

SMS_PHONE_MSG = 'SMS için geçerli bir cep telefonu girin (5XX XXX XX XX).'      # KK-7
PHONE_MSG = 'Geçerli bir cep telefonu girin (5XX XXX XX XX).'
CHANNEL_MSG = 'En az bir gönderim kanalı seçin.'                               # KK-9

# KK-5 değişiklik notu alanları: (sihirbaz kaynak alanı, girilen alan, etiket)
_CHANGE_FIELDS = (
    ('source_name', 'customer_name', 'Müşteri adı'),
    ('source_phone', 'customer_phone', 'Cep telefonu'),
    ('source_email', 'customer_email', 'E-posta'),
    ('source_address', 'customer_address', 'Adres'),
    ('source_city', 'customer_city', 'İl'),
)


class SanalPosPaymentCreateWizard(models.TransientModel):
    _name = 'sanal.pos.payment.create.wizard'
    _description = 'Sanal POS: Yeni Ödeme Linki'

    # ---------------------------------------------------------------- fatura
    invoice_no = fields.Char(string='Fatura No', required=True)
    fetched = fields.Boolean(string='Fatura getirildi', readonly=True)
    fetched_invoice_no = fields.Char(string='Getirilen fatura', readonly=True)
    fetched_amount = fields.Monetary(
        string='Getirilen tutar', currency_field='currency_id', readonly=True)
    invoice_ref = fields.Char(string='Fatura Kimliği', readonly=True)
    invoice_date = fields.Datetime(string='Fatura Tarihi', readonly=True)
    customer_code = fields.Char(string='Müşteri Kodu', readonly=True)

    # Faturadaki ham değerler (KK-5 karşılaştırması)
    source_name = fields.Char(string='Faturadaki ad', readonly=True)
    source_phone = fields.Char(string='Faturadaki telefon', readonly=True)
    source_email = fields.Char(string='Faturadaki e-posta', readonly=True)
    source_address = fields.Char(string='Faturadaki adres', readonly=True)
    source_city = fields.Char(string='Faturadaki il', readonly=True)

    # ---------------------------------------------------------------- müşteri (düzenlenebilir)
    customer_name = fields.Char(string='Müşteri adı')
    customer_phone = fields.Char(string='Müşteri cep telefonu')
    customer_email = fields.Char(string='Müşteri e-postası')
    customer_address = fields.Char(string='Fatura adresi')
    customer_city = fields.Char(string='İl')
    customer_zip = fields.Char(string='Posta kodu')

    # ---------------------------------------------------------------- tutar (yalnız gösterim)
    currency_id = fields.Many2one(
        'res.currency', string='Para Birimi', readonly=True,
        default=lambda self: self.env.ref('base.TRY', raise_if_not_found=False))
    amount = fields.Monetary(
        string='Tutar', currency_field='currency_id', readonly=True,
        help='Fatura genel toplamı; değiştirilemez. Link oluşturulurken fatura yeniden okunur.')

    # ---------------------------------------------------------------- link
    channel_sms = fields.Boolean(string='SMS ile gönder', default=True)
    channel_email = fields.Boolean(string='E-posta ile gönder')
    expiry_hours = fields.Integer(
        string='Geçerlilik (saat)', default=lambda self: self._default_expiry_hours(),
        help='1 ile 168 saat (7 gün) arası.')
    is_test = fields.Boolean(string='Test ortamı', compute='_compute_is_test')
    prior_refunded = fields.Boolean(
        string='Önceki ödeme iade/iptal edilmiş', compute='_compute_prior_refunded')
    confirm_prior_refund = fields.Boolean(string='Önceki iadeyi/iptali biliyorum')
    blocking_message = fields.Char(string='Uyarı', compute='_compute_blocking_message')

    # ---------------------------------------------------------------- varsayılan / compute
    @api.model
    def _default_expiry_hours(self):
        value = self.env['ir.config_parameter'].sudo().get_param('sanal_pos.default_expiry_hours')
        try:
            hours = int(value or 168)
        except (TypeError, ValueError):
            hours = 168
        return hours if 1 <= hours <= 168 else 168

    def _compute_is_test(self):
        environment = self.env['sanal.pos.payment']._default_environment()
        for wiz in self:
            wiz.is_test = environment == 'test'

    def _invoice_key(self):
        return (self.fetched_invoice_no or self.invoice_no or '').strip()

    @api.depends('invoice_no', 'fetched_invoice_no')
    def _compute_prior_refunded(self):
        Payment = self.env['sanal.pos.payment'].sudo()
        for wiz in self:
            key = wiz._invoice_key()
            wiz.prior_refunded = bool(key) and bool(Payment.search_count(
                [('invoice_no', '=', key), ('state', 'in', ('voided', 'refunded'))]))

    @api.depends('invoice_no', 'fetched', 'fetched_invoice_no')
    def _compute_blocking_message(self):
        """KK-18/19/20 ön bilgisi: yalnız DB'ye bakar, dış çağrı yapmaz."""
        Payment = self.env['sanal.pos.payment']
        for wiz in self:
            key = wiz._invoice_key() if wiz.fetched else ''
            wiz.blocking_message = Payment._new_link_blocker(
                key, confirm_prior_refund=True) or False

    @api.onchange('customer_phone')
    def _onchange_customer_phone(self):
        phone = normalize_phone(self.customer_phone)
        if phone:
            self.customer_phone = phone

    # ---------------------------------------------------------------- korumalı alanlar
    @api.model
    def _check_protected_vals(self, vals):
        if any(vals.get(name) for name in _PROTECTED_FIELDS):
            raise UserError('Fatura bilgisi yalnız "Faturayı Getir" ile alınabilir.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_protected_vals(vals)
        # G-3: ``default_fetched*`` context anahtarları korumalı alanları vals dışından
        # doldurabilirdi; süzülür ve sonuç ayrıca doğrulanır.
        blocked = {'default_%s' % name for name in _PROTECTED_FIELDS}
        if blocked & set(self.env.context):
            self = self.with_context({k: v for k, v in self.env.context.items() if k not in blocked})
        records = super().create(vals_list)
        if any(rec.fetched or rec.fetched_invoice_no or rec.fetched_amount for rec in records):
            raise UserError('Fatura bilgisi yalnız "Faturayı Getir" ile alınabilir.')
        return records

    def write(self, vals):
        self._check_protected_vals(vals)
        return super().write(vals)

    def _write_fetched(self, vals):
        """Yalnız sunucu kodu: korumalı alanları ``write`` denetimini atlayarak yazar."""
        return super(SanalPosPaymentCreateWizard, self).write(vals)

    # ---------------------------------------------------------------- fatura getir
    def _read_invoice(self, invoice_no):
        # find_invoice @api.private + grup denetimi: yalnız sunucu tarafında çağrılır
        return self.env['sanal.pos.invoice.source.nebim'].find_invoice(invoice_no)

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yeni Ödeme Linki',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_fetch_invoice(self):
        """Faturayı getirir, alanları kaynaktan doldurur ve aynı sihirbazı yeniden açar."""
        self.ensure_one()
        self.env['sanal.pos.payment']._check_sanal_pos_user()
        info = self._read_invoice(self.invoice_no)
        amount = float(info['amount'])
        self._write_fetched({
            'invoice_no': info['invoice_no'],
            'fetched': True,
            'fetched_invoice_no': info['invoice_no'],
            'fetched_amount': amount,
            'amount': amount,
            'currency_id': self.env.ref('base.TRY').id,
            'invoice_ref': info['invoice_ref'] or False,
            'invoice_date': info['invoice_date'] or False,
            'customer_code': info['customer_code'] or False,
            'source_name': info['name'] or False,
            'source_phone': info['phone'] or False,
            'source_email': info['email'] or False,
            'source_address': info['address'] or False,
            'source_city': info['city'] or False,
            'customer_name': info['name'] or False,
            'customer_phone': info['phone'] or False,
            'customer_email': info['email'] or False,
            'customer_address': info['address'] or False,
            'customer_city': info['city'] or False,
            'customer_zip': False,
            'confirm_prior_refund': False,
        })
        return self._reopen_action()

    # ---------------------------------------------------------------- doğrulama
    def _validated_values(self):
        """Girişleri doğrular ve temizlenmiş değerleri döndürür; hatalar tek UserError'da."""
        self.ensure_one()
        require_contact = get_bool_param(self.env, 'sanal_pos.require_contact', default=True)
        errors = []
        values = {
            'customer_name': clean_text(self.customer_name),
            'customer_address': clean_text(self.customer_address),
            'customer_city': clean_text(self.customer_city),
            'customer_zip': clean_text(self.customer_zip),
        }
        if not values['customer_name']:
            errors.append('Müşteri adı zorunludur.')
        for name in ('customer_name', 'customer_address', 'customer_city', 'customer_zip'):
            limit = FIELD_MAX_LENGTH[name]
            if len(values[name]) > limit:
                errors.append('%s en çok %d karakter olabilir.' % (self._fields[name].string, limit))

        # Telefon (KK-6/7, U-4)
        phone_raw = (self.customer_phone or '').strip()
        phone = normalize_phone(phone_raw) or ''
        if self.channel_sms and not phone:
            errors.append(SMS_PHONE_MSG)
        elif phone_raw and not phone:
            errors.append(PHONE_MSG)
        elif require_contact and not phone:
            errors.append('Müşteri cep telefonu zorunludur (Ayarlar: e-posta ve telefon zorunlu).')

        # E-posta (KK-8, KK-10, U-4): uzunluk biçimden önce
        email = (self.customer_email or '').strip()
        limit = FIELD_MAX_LENGTH['customer_email']
        if email:
            if len(email) > limit:
                errors.append('Müşteri e-postası en çok %d karakter olabilir.' % limit)
            elif not validate_email(email):
                errors.append('Geçerli bir e-posta adresi girin.')
        elif self.channel_email:
            errors.append('E-posta ile gönderim için müşteri e-postası girin.')
        elif require_contact:
            errors.append('Müşteri e-postası zorunludur (Ayarlar: e-posta ve telefon zorunlu).')

        if not self.channel_sms and not self.channel_email:
            errors.append(CHANNEL_MSG)
        if not 1 <= (self.expiry_hours or 0) <= 168:
            errors.append('Link geçerlilik süresi 1 ile 168 saat arasında olmalıdır.')
        if errors:
            raise UserError('\n'.join(errors))

        values.update({
            'customer_phone': phone or False,
            'customer_email': email or False,
            'channel_sms': bool(self.channel_sms),
            'channel_email': bool(self.channel_email),
            'expiry_hours': self.expiry_hours,
        })
        for key in ('customer_address', 'customer_city', 'customer_zip'):
            values[key] = values[key] or False
        return values

    def _change_notes(self, info, values):
        """KK-5: faturadan farklı girilen değerler için 'faturadan gelen → girilen' satırları."""
        source = {
            'source_name': info['name'], 'source_phone': info['phone'],
            'source_email': info['email'], 'source_address': info['address'],
            'source_city': info['city'],
        }
        lines = []
        for source_field, field, label in _CHANGE_FIELDS:
            old = clean_text(source[source_field])
            new = clean_text(values.get(field) or '')
            if old != new:
                lines.append(Markup('%s: faturadan gelen değer: %s → girilen: %s') % (
                    label, old or '(boş)', new or '(boş)'))
        if not lines:
            return False
        return Markup('Faturadan farklı girilen müşteri bilgileri:<br/>') + Markup('<br/>').join(lines)

    # ---------------------------------------------------------------- link oluştur
    def action_create_link(self):
        """Tasarım §6.1: kontroller -> 'Gönderiliyor' + commit -> dış çağrı -> sonuç + commit."""
        self.ensure_one()
        Payment = self.env['sanal.pos.payment']
        # 1. yetki ve getirme
        Payment._check_sanal_pos_user()
        if not self.fetched or not self.fetched_invoice_no:
            raise UserError('Önce "Faturayı Getir" ile faturayı getirin.')
        invoice_no = self.fetched_invoice_no
        if (self.invoice_no or '').strip() != invoice_no:
            raise UserError('Fatura numarası değişti; faturayı yeniden getirin.')
        # 2. fatura yeniden okunur, tutar kilidi
        info = self._read_invoice(invoice_no)
        # G-3: indeks, açık link kontrolü ve MPID kaynağın kanonik numarasını kullanır
        # (MSSQL harmanlaması harfe duyarsız; DB tekillik indeksi duyarlı).
        if info['invoice_no'] != invoice_no:
            raise UserError('Fatura numarası değişti; faturayı yeniden getirin.')
        invoice_no = info['invoice_no']
        amount = float(info['amount'])
        if float_compare(amount, self.fetched_amount, precision_digits=2) != 0:
            raise UserError('Fatura tutarı değişti (getirilen: %s, şimdiki: %s); faturayı yeniden getirin.'
                            % (format_try(self.fetched_amount), format_try(info['amount'])))
        # 3. doğrulama
        values = self._validated_values()
        # 4. ön kontrol (UX); asıl engel adım 5'teki DB indeksi
        blocker = Payment._new_link_blocker(
            invoice_no, confirm_prior_refund=self.confirm_prior_refund, refresh=True)
        if blocker:
            raise UserError(blocker)
        # 5. 'Gönderiliyor' kaydı (savepoint; tekillik ihlali -> KK-18)
        attempt_no = Payment._next_attempt_no(invoice_no)
        values.update({
            'invoice_source': 'nebim',
            'invoice_no': invoice_no,
            'invoice_ref': info['invoice_ref'] or False,
            'invoice_date': info['invoice_date'] or False,
            'customer_code': info['customer_code'] or False,
            'source_name': info['name'] or False,
            'source_phone': info['phone'] or False,
            'source_email': info['email'] or False,
            'amount': amount,
            'currency_id': self.env.ref('base.TRY').id,
            'state': 'sending',
            'attempt_no': attempt_no,
            'merchant_payment_id': '%s-%d' % (invoice_no, attempt_no),
            'user_id': self.env.uid,
        })
        payment = Payment._insert_sending(values)
        # 6. KK-5 notları + commit (dış çağrıdan önce kayıt kalıcı)
        notes = self._change_notes(info, values)
        if notes:
            payment._post_note(notes)
        payment._sp_commit()
        # 7-9. kilit, dış çağrı, sonuç (raise yok)
        return payment._run_create_link()

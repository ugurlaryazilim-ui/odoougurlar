# -*- coding: utf-8 -*-
"""Kargo gönderisi (02-tasarim 4.5, KARARLAR K-20/K-21/K-26).

Bu dosyada: alanlar, varsayılanlar, ilçe (``area_id``) hesaplama, gönderim öncesi doğrulama
(``_cargo_check_ready``) ve kilitler. Gönder / uzlaştır / iptal akışı sonraki görevdedir; o akış
sistem alanlarını ``sudo()`` ile yazar.

Kilit modeli (DERSLER: kilit write override'ıyla değil kayıt kuralıyla kurulur):
* Kullanıcı alanları yalnız ``draft``/``failed`` durumunda yazılabilir: ``security/cargo_security.xml``
  kayıt kuralları (write/create/unlink).
* Sistem alanları (``_CARGO_SYSTEM_FIELDS``) yalnız ``env.su`` ile yazılır; RPC/form yazımı AccessError verir.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .res_company import _cargo_carrier_domain

# NEDEN: alan sınırları ilk sağlayıcının (UPS) sınırlarıdır.
# EKIP-BORC: farklı sınırlı ikinci sağlayıcı gelirse bu sabitler ``<tip>_cargo_limits`` kancasına taşınmalı.
NAME_MAX = 40
NAME_MIN = 3
STREET_MIN, STREET_MAX = 3, 255
PHONE_MIN, PHONE_MAX = 10, 16
EMAIL_MAX = 64
PACKAGE_MAX = 99
WEIGHT_MAX = 70.0
ORIGIN_REF_MAX = 40
INVOICE_MAX = 20
DESCRIPTION_MAX = 120

# Yalnız env.su ile yazılır (gönderi akışı sudo() kullanır). RPC/form yazımı AccessError verir.
# DIKKAT: bir sistem alanı ekler/çıkarırsan test_shipment_model'deki kilit testlerini de güncelle.
_CARGO_SYSTEM_FIELDS = frozenset((
    'name', 'state', 'picking_id', 'source_model', 'source_id', 'test_mode', 'tracking_ref',
    'label_pdf_id', 'label_missing', 'error_code', 'error_message', 'sent_at', 'cancelled_at'))
_EDITABLE_STATES = ('draft', 'failed')


class CargoShipment(models.Model):
    _name = 'cargo.shipment'
    _description = 'Kargo gönderisi'
    _inherit = ['mail.thread']
    _order = 'id desc'
    # NEDEN: kargo kullanıcısı kilitli (created vb.) gönderiye de not düşebilmeli; yazma kilidi kayıt
    # kuralındadır, chatter yazımı ise 'read' erişimine bağlanır (sanal_pos ile aynı).
    _mail_post_access = 'read'

    # NEDEN: bir iş referansıyla yalnız tek AKTİF gönderi olur (KK-API-2, picking'den ikinci gönderi yok);
    # iptal/hatalı olanın ardından yenisi açılabilir (K-21).
    _origin_ref_active_uniq = models.UniqueIndex(
        "(origin_ref) WHERE origin_ref IS NOT NULL AND state NOT IN ('cancelled', 'failed')",
        message='Bu iş referansıyla açık bir kargo gönderisi zaten var.')

    # ------------------------------------------------------------------ sistem alanları
    # copy=False: kopya her zaman temiz taslak olur.
    name = fields.Char(string='Gönderi no', default='Yeni', readonly=True, copy=False, index=True)
    state = fields.Selection([
        ('draft', 'Taslak'), ('sending', 'Gönderiliyor'), ('uncertain', 'Belirsiz'),
        ('created', 'Oluşturuldu'), ('in_transit', 'Yolda'), ('out_for_delivery', 'Dağıtımda'),
        ('delivered', 'Teslim edildi'), ('returned', 'İade'), ('exception', 'Sorunlu'),
        ('cancelled', 'İptal'), ('failed', 'Hatalı')],
        string='Durum', default='draft', required=True, readonly=True, copy=False, index=True)
    picking_id = fields.Many2one('stock.picking', string='Transfer', copy=False, index=True, ondelete='set null')
    source_model = fields.Char(string='Kaynak model', copy=False)
    source_id = fields.Integer(string='Kaynak kayıt', copy=False)
    # NEDEN: test_mode gönderim anında not carrier.prod_environment ile yazılır (K-26); taslakta da
    # firmaya göre gösterilir. Hesaplamalı değildir: gönderilmiş kaydın değeri firma bayrağı sonradan
    # değişince oynamamalı.
    test_mode = fields.Boolean(string='Test', copy=False)
    tracking_ref = fields.Char(string='Takip no', copy=False, index=True)
    label_pdf_id = fields.Many2one('ir.attachment', string='Etiket (PDF)', copy=False, ondelete='set null')
    label_missing = fields.Boolean(string='Etiket yok', copy=False)
    error_code = fields.Char(string='Hata kodu', copy=False)
    error_message = fields.Text(string='Hata mesajı', copy=False)
    sent_at = fields.Datetime(string='Gönderim zamanı', copy=False)
    cancelled_at = fields.Datetime(string='İptal zamanı', copy=False)

    # ------------------------------------------------------------------ kilitli (draft/failed) alanlar
    carrier_id = fields.Many2one(
        'delivery.carrier', string='Kargo firması', required=True, index=True, ondelete='restrict',
        domain=_cargo_carrier_domain, default=lambda self: self._default_carrier_id())
    # Form alan filtresi (area_id domain'i) için; sağlayıcı kodu = delivery_type.
    carrier_type = fields.Selection(related='carrier_id.delivery_type', string='Firma tipi')
    company_id = fields.Many2one('res.company', string='Şirket', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Para birimi')
    origin_ref = fields.Char(string='İş referansı', copy=False, help='Transfer adı ya da çağıranın verdiği referans.')
    invoice_no = fields.Char(string='Fatura no', copy=False)
    partner_id = fields.Many2one('res.partner', string='Müşteri', ondelete='set null')
    recipient_name = fields.Char(string='Alıcı adı')
    recipient_phone = fields.Char(string='Alıcı telefonu')
    recipient_email = fields.Char(string='Alıcı e-postası')
    recipient_street = fields.Char(string='Alıcı adresi')
    recipient_state_id = fields.Many2one(
        'res.country.state', string='İl', domain="[('country_id.code', '=', 'TR')]")
    recipient_district = fields.Char(string='İlçe')
    area_id = fields.Many2one(
        'cargo.area', string='Kargo ilçesi', compute='_compute_area_id', store=True, readonly=False,
        domain="[('provider', '=', carrier_type), ('state_id', '=', recipient_state_id)]",
        help='İlçe metninden otomatik bulunur; eşleşmezse listeden seçin.')
    area_match_note = fields.Char(string='İlçe eşleme notu', compute='_compute_area_match_note')
    package_count = fields.Integer(string='Paket sayısı', default=1)
    package_weight = fields.Float(
        string='Paket ağırlığı (kg)', default=lambda self: self.env.company.cargo_default_weight or 1.0,
        help='Paket başına.')
    description = fields.Char(string='Açıklama')
    # EKIP-BORC: tutar şirket para biriminde (TRY varsayımı) tutulur ve sağlayıcıya TL gider; şirket birimi
    # TRY değilse ODP kontrolü yoktur. Çok para birimi istenirse _cargo_check_ready'ye TRY denetimi eklenmeli.
    cod_amount = fields.Monetary(string='Kapıda ödeme tutarı', currency_field='currency_id', default=0.0)
    cod_method = fields.Selection(
        [('cash', 'Nakit'), ('card', 'Kredi kartı'), ('check', 'Çek')], string='Tahsil şekli')

    # ------------------------------------------------------------------ varsayılanlar
    @api.model
    def _default_carrier_id(self):
        return self.env.company.cargo_default_carrier_id.id

    # ------------------------------------------------------------------ ilçe eşleme (KK-8/8b/8c)
    @api.depends('carrier_id.delivery_type', 'recipient_state_id', 'recipient_district')
    def _compute_area_id(self):
        for shipment in self:
            # NEDEN: yalnız cargo.area._match (tam anahtar); geri düşüş yok (K-25). Belirsiz/eşleşmeyen
            # girdi boş kalır ve operatör listeden seçer.
            shipment.area_id = self.env['cargo.area']._match(
                shipment.carrier_id.delivery_type, shipment.recipient_state_id, shipment.recipient_district)

    @api.depends('area_id', 'carrier_id.delivery_type', 'recipient_state_id', 'recipient_district')
    def _compute_area_match_note(self):
        Area = self.env['cargo.area']
        for shipment in self:
            note = False
            if not shipment.area_id:
                state, text = shipment.recipient_state_id, shipment.recipient_district or ''
                where = '%s/%s' % (state.name or '?', text.strip() or '?')
                if not state or state.country_id.code != 'TR':
                    note = _('İl seçilmedi (Türkiye ili gerekli): ilçe eşlenemez.')
                elif not Area._input_key_tiers(state, text):
                    # boş metin, il adı ya da büyükşehirde 'Merkez': hiçbir zaman otomatik eşlenmez (K-25)
                    note = _('İlçe belirsiz: %s → hangi ilçe olduğu belirsiz. Listeden ilçe seçin.', where)
                else:
                    candidates = Area._match_candidates(shipment.carrier_id.delivery_type, state, text)
                    if len(candidates) > 1:
                        note = _('İlçe belirsiz: %(where)s → %(names)s. Listeden ilçe seçin.',
                                 where=where, names=', '.join(candidates.mapped('name')))
                    else:
                        note = _('İlçe eşleşmedi: %s. Listeden ilçe seçin.', where)
            shipment.area_match_note = note

    @api.constrains('area_id', 'carrier_id', 'recipient_state_id')
    def _check_area_scope(self):
        # NEDEN: elle seçim başka ilin/sağlayıcının kodunu seçerek yanlış ilçeye gönderi açmasın (KK-8b).
        for shipment in self.filtered('area_id'):
            area = shipment.area_id
            if area.provider != shipment.carrier_id.delivery_type or area.state_id != shipment.recipient_state_id:
                raise ValidationError(_(
                    '"%(area)s" ilçesi bu gönderinin ili ya da kargo firmasıyla uyuşmuyor.', area=area.display_name))

    def _cargo_area_manual_note(self):
        """Elle seçilen (hesaplanandan farklı) ilçe için chatter metni; fark yoksa ''.

        Metin burada tanımlıdır; yazımı gönder akışındadır (hesaplanandan farklı seçim gönderilirken izlenir).
        """
        self.ensure_one()
        if not self.area_id:
            return ''
        computed = self.env['cargo.area']._match(
            self.carrier_id.delivery_type, self.recipient_state_id, self.recipient_district)
        if computed == self.area_id:
            return ''
        return _('İlçe elle seçildi: "%(text)s" → %(area)s',
                 text=self.recipient_district or '', area=self.area_id.name)

    # ------------------------------------------------------------------ create / write kilitleri
    @api.model_create_multi
    def create(self, vals_list):
        su = self.env.su
        sequence = self.env['ir.sequence'].sudo()
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not su:
                denied = _CARGO_SYSTEM_FIELDS & set(vals)
                if denied:
                    raise AccessError(_('Bu alanlar yalnız sistem tarafından yazılır: %s', ', '.join(sorted(denied))))
            # '' boş değerdir: kısmi benzersiz indeks yalnız NULL'ı dışlar.
            if 'origin_ref' in vals:
                vals['origin_ref'] = (vals['origin_ref'] or '').strip() or False
            carrier = self.env['delivery.carrier'].browse(vals.get('carrier_id') or self._default_carrier_id())
            if not carrier:
                raise UserError(_(
                    'Varsayılan kargo firması ayarlı değil. Gönderide firma seçin ya da Ayarlar › Kargo '
                    'bölümünden varsayılan firmayı belirleyin.'))
            vals['carrier_id'] = carrier.id    # carrier_id=False verilse de varsayılan firma kullanılır (KK-4)
            vals.setdefault('test_mode', not carrier.sudo().prod_environment)
            if not vals.get('name') or vals['name'] == 'Yeni':
                vals['name'] = sequence.next_by_code('cargo.shipment') or 'Yeni'
        # NEDEN: kısmi benzersiz indeksi DB'de değerlendirilir; aynı işlemde bekleyen state yazımı (iptal/hata)
        # flush edilmeden aynı referansla yeni gönderi eklenirse yanlış ihlal alınır.
        self.flush_model(['state', 'origin_ref'])
        context = dict(self.env.context, mail_create_nosubscribe=True, mail_create_nolog=True)
        if not su:
            # DIKKAT: RPC'de with_context(default_state=...) vals süzmesinden SONRA super().create içinde
            # uygulanır (DERSLER, 3. tekrar); sistem alanlarının default_ bağlamları burada atılır. Test:
            # test_shipment_model::test_default_baglami_sistem_alanini_degistiremez.
            context = {key: value for key, value in context.items()
                       if not (key.startswith('default_') and key[len('default_'):] in _CARGO_SYSTEM_FIELDS)}
        return super(CargoShipment, self.with_context(context)).create(vals_list)

    def write(self, vals):
        if not self.env.su:
            denied = _CARGO_SYSTEM_FIELDS & set(vals)
            if denied:
                raise AccessError(_('Bu alanlar yalnız sistem tarafından yazılır: %s', ', '.join(sorted(denied))))
        vals = dict(vals)
        if 'origin_ref' in vals:
            vals['origin_ref'] = (vals['origin_ref'] or '').strip() or False
        if vals.get('carrier_id') and 'test_mode' not in vals and set(self.mapped('state')) <= set(_EDITABLE_STATES):
            vals['test_mode'] = not self.env['delivery.carrier'].browse(vals['carrier_id']).sudo().prod_environment
        return super().write(vals)

    # ------------------------------------------------------------------ gönderim öncesi doğrulama
    def _cargo_check_ready(self):
        """Gönderime hazır mı? Tüm hataları TEK UserError'da listeler (KK-7).

        Başarılıysa gönderi verisini sağlayıcı sınırına getirir: 40'ı aşan ad kelime sınırında kısaltılıp
        chatter'a not düşülür, telefon rakamlara indirgenir. Dış çağrıdan ÖNCE çağrılır (hata varsa
        sağlayıcıya hiç gidilmez).
        """
        self.ensure_one()
        sudo = self.sudo()
        label = lambda name: self._fields[name].string  # noqa: E731
        errors = []

        carrier = sudo.carrier_id
        if not carrier or not carrier._cargo_is_managed():
            errors.append(_('%s: kargo gönderisi için ayarlı bir firma seçin.', label('carrier_id')))

        name = ' '.join((self.recipient_name or '').split())
        if len(name) < NAME_MIN:
            errors.append(_('%(field)s en az %(min)d karakter olmalı.', field=label('recipient_name'), min=NAME_MIN))
        phone = re.sub(r'\D', '', self.recipient_phone or '')
        if not PHONE_MIN <= len(phone) <= PHONE_MAX:
            errors.append(_('%(field)s %(min)d-%(max)d rakam olmalı.',
                            field=label('recipient_phone'), min=PHONE_MIN, max=PHONE_MAX))
        if len(self.recipient_email or '') > EMAIL_MAX:
            errors.append(_('%(field)s en çok %(max)d karakter olabilir.', field=label('recipient_email'), max=EMAIL_MAX))
        if not STREET_MIN <= len((self.recipient_street or '').strip()) <= STREET_MAX:
            errors.append(_('%(field)s %(min)d-%(max)d karakter olmalı.',
                            field=label('recipient_street'), min=STREET_MIN, max=STREET_MAX))
        if not self.recipient_state_id or self.recipient_state_id.country_id.code != 'TR':
            errors.append(_('%s: Türkiye ili seçin.', label('recipient_state_id')))
        if not (self.recipient_district or '').strip():
            errors.append(_('%s boş olamaz.', label('recipient_district')))
        if not self.area_id and self.area_match_note:
            errors.append(self.area_match_note)
        if not 1 <= self.package_count <= PACKAGE_MAX:
            errors.append(_('%(field)s 1-%(max)d arası olmalı.', field=label('package_count'), max=PACKAGE_MAX))
        if not 0 < self.package_weight <= WEIGHT_MAX:
            errors.append(_('%(field)s 0 ile %(max)s kg arasında olmalı.', field=label('package_weight'), max=WEIGHT_MAX))
        for field, limit in (('origin_ref', ORIGIN_REF_MAX), ('invoice_no', INVOICE_MAX), ('description', DESCRIPTION_MAX)):
            if len(self[field] or '') > limit:
                errors.append(_('%(field)s en çok %(max)d karakter olabilir.', field=label(field), max=limit))

        errors += self._cargo_check_cod(carrier)

        # Gönderici (şirket adresi) aynı kuralla eşlenir; eşleşmezse çağrı yapılmaz (V-3).
        if carrier and not self.env['cargo.area']._match(carrier.delivery_type, self.company_id.state_id, self.company_id.city):
            errors.append(_(
                'Şirket adresinin ilçesi eşleşmedi: %(state)s/%(city)s. Şirket adresini düzeltin ya da '
                'yönetici ilçe için diğer ad eklesin.',
                state=self.company_id.state_id.name or '?', city=self.company_id.city or '?'))

        if errors:
            raise UserError(_('Gönderi gönderilemez:\n- %s', '\n- '.join(errors)))

        updates = {}
        if phone != self.recipient_phone:
            updates['recipient_phone'] = phone
        if len(name) > NAME_MAX:
            short = self._cargo_shorten_name(name)
            updates['recipient_name'] = short
            self.message_post(
                body=_('Alıcı adı %(max)d karakteri aştığı için kısaltıldı: "%(old)s" → "%(new)s"',
                       max=NAME_MAX, old=name, new=short), subtype_xmlid='mail.mt_note')
        if updates:
            sudo.write(updates)

    def _cargo_check_cod(self, carrier):
        """Kapıda ödeme (ODP) hataları: KK-18, KK-19, KK-19b, KK-19c."""
        label = lambda name: self._fields[name].string  # noqa: E731
        errors = []
        if self.cod_amount < 0:
            return [_('%s negatif olamaz.', label('cod_amount'))]
        if not self.cod_amount:
            return errors
        if not self.cod_method:
            errors.append(_('%s seçilmeli.', label('cod_method')))
        # ODP bayrakları yönetici grubundadır; gönderi akışı sudo() ile okur.
        flags = carrier.sudo()
        if not flags.cargo_cod_enabled:
            errors.append(_('Kapıda ödeme etkin değil: "%s" firmasında ODP kapalı.', carrier.display_name))
        elif self.cod_method and not flags['cargo_cod_allow_%s' % self.cod_method]:
            errors.append(_('%(field)s bu firmada kapalı: %(method)s',
                            field=label('cod_method'),
                            method=dict(self._fields['cod_method'].selection)[self.cod_method]))
        maximum = self.company_id.cargo_cod_max_amount
        if maximum and self.cod_amount > maximum:
            errors.append(_('%(field)s üst sınırı (%(max)s) aşıyor.', field=label('cod_amount'), max=maximum))
        return errors

    @staticmethod
    def _cargo_shorten_name(name):
        """``NAME_MAX``'ı aşan adı kelime sınırında keser; sınırda boşluk yoksa ya da sonuç çok kısaysa sert keser."""
        head = name[:NAME_MAX + 1]
        cut = head.rfind(' ')
        short = name[:cut].rstrip() if cut >= NAME_MIN else name[:NAME_MAX]
        return short

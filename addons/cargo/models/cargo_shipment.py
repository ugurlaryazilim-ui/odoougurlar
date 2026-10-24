# -*- coding: utf-8 -*-
"""Kargo gönderisi (02-tasarim 4.5, KARARLAR K-20/K-21/K-26).

Bu dosyada: alanlar, varsayılanlar, ilçe (``area_id``) hesaplama, gönderim öncesi doğrulama
(``_cargo_check_ready``), kilitler ve gönder / uzlaştır / iptal akışı (K-21; sistem alanları ``sudo()`` ile).

Kilit modeli (DERSLER: kilit write override'ıyla değil kayıt kuralıyla kurulur):
* Kullanıcı alanları yalnız ``draft``/``failed`` durumunda yazılabilir: ``security/cargo_security.xml``
  kayıt kuralları (write/create/unlink).
* Sistem alanları (``_CARGO_SYSTEM_FIELDS``) yalnız ``env.su`` ile yazılır; RPC/form yazımı AccessError verir.
"""
import logging
import math
import re
from datetime import timedelta

from psycopg2 import errors as pg_errors

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .cargo_label import build_label_pdf
from .res_company import _cargo_carrier_domain

_logger = logging.getLogger(__name__)

# NEDEN: alan sınırları ilk sağlayıcının sınırlarıdır (çekirdekte sağlayıcı adı geçmez, KK-30).
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
    'label_pdf_id', 'label_png_ids', 'label_missing', 'error_code', 'error_message', 'sent_at', 'cancelled_at'))
_EDITABLE_STATES = ('draft', 'failed')
_SHIPPED_STATES = ('in_transit', 'out_for_delivery', 'delivered', 'returned')
# NEDEN: iptal edilmiş gönderinin etiketi geçersizdir (barkod firmada iptal); basılırsa yanlışlıkla pakete yapışır.
_PRINTABLE_STATES = ('created',) + _SHIPPED_STATES + ('exception',)
# NEDEN: sağlayıcıda kaydın sorguda görünme gecikmesi bilinmiyor (CD-6); daha genç "bulunamadı" kesin değildir,
# yanlış "yok" kararı mükerrer gönderi açar (K-21). Yaş son sending geçişinden (sent_at) ölçülür.
RECONCILE_MIN_AGE = timedelta(minutes=15)
# NEDEN: sağlayıcı hata metnini sırlardan temizler (sağlayıcı ``_scrub``); çekirdek yalnız uzunluğu sınırlar.
ERROR_MESSAGE_MAX = 500
_PROVIDER_STATUSES = {
    'send': ('ok', 'error', 'uncertain'),
    'cancel': ('ok', 'error', 'uncertain'),
    'find': ('found', 'not_found', 'error'),
}
_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


class CargoShipment(models.Model):
    _name = 'cargo.shipment'
    _description = 'Kargo gönderisi'
    _inherit = ['mail.thread']
    _order = 'id desc'
    # NEDEN: kargo kullanıcısı kilitli (created vb.) gönderiye de not düşebilmeli; yazma kilidi kayıt
    # kuralındadır, chatter yazımı ise 'read' erişimine bağlanır (sanal_pos ile aynı).
    _mail_post_access = 'read'
    # NEDEN: çok şirketli veritabanında başka şirketin kargo hesabı/transferi/müşterisi seçilmesin
    # (güvenlik taraması 2026-10-24); okuma ayrımı security'deki global şirket kuralındadır.
    _check_company_auto = True

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
    picking_id = fields.Many2one(
        'stock.picking', string='Transfer', copy=False, index=True, ondelete='set null', check_company=True)
    source_model = fields.Char(string='Kaynak model', copy=False)
    source_id = fields.Integer(string='Kaynak kayıt', copy=False)
    # NEDEN: test_mode gönderim anında not carrier.prod_environment ile yazılır (K-26); taslakta da
    # firmaya göre gösterilir. Hesaplamalı değildir: gönderilmiş kaydın değeri firma bayrağı sonradan
    # değişince oynamamalı.
    test_mode = fields.Boolean(string='Test', copy=False)
    tracking_ref = fields.Char(string='Takip no', copy=False, index=True)
    label_pdf_id = fields.Many2one('ir.attachment', string='Etiket (PDF)', copy=False, ondelete='set null')
    # NEDEN: PDF yalnız sağlayıcıdan gelen PNG'lerden üretilir. Ek aramasını res_model/res_id/ad ile yapmak,
    # gönderiye chatter'dan ek yükleyen birinin etikete yabancı bir barkod sokmasına izin verirdi (güvenlik taraması).
    # Sistem alanıdır: yalnız ``_cargo_store_labels`` (sudo) yazar.
    label_png_ids = fields.Many2many(
        'ir.attachment', 'cargo_shipment_label_png_rel', 'shipment_id', 'attachment_id',
        string='Etiket görüntüleri', copy=False)
    label_missing = fields.Boolean(string='Etiket yok', copy=False)
    error_code = fields.Char(string='Hata kodu', copy=False)
    error_message = fields.Text(string='Hata mesajı', copy=False)
    sent_at = fields.Datetime(string='Gönderim zamanı', copy=False)
    cancelled_at = fields.Datetime(string='İptal zamanı', copy=False)

    # ------------------------------------------------------------------ kilitli (draft/failed) alanlar
    carrier_id = fields.Many2one(
        'delivery.carrier', string='Kargo firması', required=True, index=True, ondelete='restrict',
        domain=_cargo_carrier_domain, default=lambda self: self._default_carrier_id(), check_company=True,
        tracking=True)
    # Form alan filtresi (area_id domain'i) için; sağlayıcı kodu = delivery_type.
    carrier_type = fields.Selection(related='carrier_id.delivery_type', string='Firma tipi')
    company_id = fields.Many2one('res.company', string='Şirket', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Para birimi')
    origin_ref = fields.Char(string='İş referansı', copy=False, help='Transfer adı ya da çağıranın verdiği referans.')
    invoice_no = fields.Char(string='Fatura no', copy=False)
    partner_id = fields.Many2one('res.partner', string='Müşteri', ondelete='set null', check_company=True)
    # NEDEN: tracking=True (alıcı, ODP, firma): taslakta tutarı/adresi değiştiren yalnız write_uid olarak
    # görünmesin, eski değer chatter'da kalsın (05-guvenlik D-3).
    recipient_name = fields.Char(string='Alıcı adı', tracking=True)
    recipient_phone = fields.Char(string='Alıcı telefonu', tracking=True)
    recipient_email = fields.Char(string='Alıcı e-postası', tracking=True)
    recipient_street = fields.Char(string='Alıcı adresi', tracking=True)
    recipient_state_id = fields.Many2one(
        'res.country.state', string='İl', domain="[('country_id.code', '=', 'TR')]", tracking=True)
    recipient_district = fields.Char(string='İlçe', tracking=True)
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
    cod_amount = fields.Monetary(string='Kapıda ödeme tutarı', currency_field='currency_id', default=0.0, tracking=True)
    cod_method = fields.Selection(
        [('cash', 'Nakit'), ('card', 'Kredi kartı'), ('check', 'Çek')], string='Tahsil şekli', tracking=True)

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
    @api.model
    def default_get(self, fields):
        # NEDEN: create'teki sistem alanı denetimi yalnız çağıranın verdiği vals'a bakar; eksik alanlar sonra
        # default_get ile (default_ bağlamı + kullanıcının kendine yazdığı kişisel ir.default) doldurulur.
        # Sudo create yollarında (transfer düğmesi, create_and_send) da uid aynıdır: kişisel ir.default ile
        # label_pdf_id yabancı eke (sudo ile ezilir), picking_id başka transfere (sudo takip yazılır) işaret
        # ederdi (05-inceleme K1, DERSLER 21). Sistem alanı yalnız alanın kendi varsayılanını alır.
        # DIKKAT: kaldırılırsa test_system_defaults kırmızı olur; ikinci savunma create'teki sıfırlamadır.
        system = _CARGO_SYSTEM_FIELDS.intersection(fields)
        defaults = super().default_get([name for name in fields if name not in system])
        for name in system:
            field = self._fields[name]
            if field.default:
                defaults[name] = field.default(self)
        return defaults

    def _cargo_reset_unrequested_system_fields(self, vals_list):
        """İkinci savunma: vals'ta verilmemiş sistem alanı varsayılanından farklı oluşmuşsa varsayılana döner."""
        for shipment, vals in zip(self.sudo(), vals_list):
            reset = {}
            for name in _CARGO_SYSTEM_FIELDS.difference(vals):
                field = self._fields[name]
                if field.relational:
                    if shipment[name]:
                        reset[name] = [Command.clear()] if field.type == 'many2many' else False
                    continue
                default = (field.default(shipment) if field.default else False) or False
                if (shipment[name] or False) != default:
                    reset[name] = default
            if reset:
                _logger.warning('cargo.shipment %s: istenmeyen sistem alanı varsayılanı sıfırlandı: %s',
                                shipment.id, ', '.join(sorted(reset)))
                shipment.write(reset)

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
        # DIKKAT: default_ bağlamı ve ir.default vals süzmesinden SONRA super().create içinde uygulanır
        # (DERSLER 21); sistem alanları default_get override'ında atılır. Testler:
        # test_shipment_model::test_default_baglami_sistem_alanini_degistiremez, test_system_defaults.
        shipments = super(CargoShipment, self.with_context(context)).create(vals_list)
        shipments._cargo_reset_unrequested_system_fields(vals_list)
        return shipments

    def write(self, vals):
        if not self.env.su:
            denied = _CARGO_SYSTEM_FIELDS & set(vals)
            if denied:
                raise AccessError(_('Bu alanlar yalnız sistem tarafından yazılır: %s', ', '.join(sorted(denied))))
            # NEDEN: şirket kuralı yazımdan ÖNCE denetlenir, sonra yeniden denetlenmez; gönderi kullanıcının
            # erişemediği şirkete taşınıp alıcı verisi o şirkete açılmasın (05-guvenlik D-1).
            if vals.get('company_id') and vals['company_id'] not in self.env.companies.ids:
                raise AccessError(_('Gönderi yalnız erişebildiğiniz bir şirkete taşınabilir.'))
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
        if carrier and not self._cargo_sender_area():
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
        return name[:cut].rstrip() if cut >= NAME_MIN else name[:NAME_MAX]

    def _cargo_sender_area(self):
        """Gönderici (şirket adresi) ilçesi; alıcıyla aynı tam anahtar kuralı (V-3, K-25)."""
        self.ensure_one()
        company = self.company_id
        return self.env['cargo.area']._match(self.sudo().carrier_id.delivery_type, company.state_id, company.city)

    # ------------------------------------------------------------------ gönder / uzlaştır / iptal (K-21)
    def action_send(self):
        self.ensure_one()
        return self._cargo_notification(self._cargo_send())

    def action_reconcile(self):
        self.ensure_one()
        return self._cargo_notification(self._cargo_reconcile())

    def action_cancel(self):
        self.ensure_one()
        return self._cargo_notification(self._cargo_cancel())

    def action_print_label(self):
        """Etiket PDF'ini saklanan PNG'lerden yeniden üretir ve indirme eylemi döner (KK-21).

        NEDEN: PDF önbellekten verilmez; yönetici etiket sayfası ayarını değiştirmiş olabilir. Sağlayıcı çağrılmaz:
        etiket gönderi anında bir kez alınır, yeniden alma yolu belgesiz (§1.3).
        """
        self.ensure_one()
        self._cargo_check_user()
        if self.state not in _PRINTABLE_STATES:
            raise UserError(_('Etiket yalnız oluşturulmuş (iptal edilmemiş) gönderi için basılır.'))
        if self.label_missing:
            raise UserError(_('Etiket kargo firmasından alınamadı: kargo firmasının panelinden basın ya da '
                              'gönderiyi iptal edip yeniden oluşturun.'))
        try:
            pdf = self._cargo_build_label_pdf()
        except Exception as error:      # noqa: BLE001 - bozuk PNG; ayrıntı kullanıcıya gitmez
            _logger.warning('cargo.shipment %s: etiket PDF üretilemedi (%s)', self.id, type(error).__name__)
            pdf = False
        if not pdf:
            raise UserError(_('Etiket PDF üretilemedi: gönderiye bağlı geçerli etiket görüntüsü yok.'))
        self._cargo_side_job('chatter', self._cargo_post, _('Etiket basıldı.'))
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%d?download=false' % pdf.id, 'target': 'new'}

    @api.model
    @api.private
    def create_and_send(self, *, recipient_name, phone, street, state, district, package_count=1, weight=None,
                        reference=None, invoice_no=None, cod_amount=0.0, cod_method=None, carrier=None, source=None,
                        email=None, partner=None):
        """Gönderi açar ve kargo firmasına gönderir (KK-API, K-24); tek ``cargo.shipment`` kaydı döner.

        ``state``: res.country.state, ``carrier``: delivery.carrier (yoksa şirket varsayılanı), ``source``: gönderiyi
        açan herhangi bir kayıt. Sonuç kayıttan okunur (``state``, ``tracking_ref``, ``error_message``,
        ``label_pdf_id``): sağlayıcı hatası istisna olmaz, kayıt ``failed``/``uncertain`` döner (KK-API-1).
        Doğrulama hatası UserError'dur ve kayıt bırakmaz; yetkisiz çağrı AccessError'dur (sudo ile bile, KK-API-3).
        ``reference`` aynı olan ``cancelled``/``failed`` dışındaki kayıt varsa YENİ GÖNDERİ AÇILMAZ, o kayıt
        döner (KK-API-2; durumuna bakılır: ``sending``/``uncertain`` olabilir, yeniden gönderilmez). Dönüş yalnız
        kayıt aynı ``source`` ile açılmışsa ve taslak değilse yapılır; değilse UserError (referans başkasına ait).

        DIKKAT: çağrı ortasında ``cr.commit()`` yapar (``_cargo_send`` ara noktaları): çağıranın o ana kadarki
        açık işlemi de kalıcılaşır ve çağrı savepoint içinden yapılamaz. Çağıran, kendi kaydını bu çağrıdan ÖNCE
        tutarlı bırakmalı.
        """
        if not self.env.user.has_group('cargo.group_cargo_user'):
            raise AccessError(_('Kargo gönderisi işlemleri için "Kargo / Kullanıcı" yetkisi gerekir.'))
        # NEDEN: '' boş referanstır (create da aynısını yapar); boş referansla "aynı kayıt" aranmaz.
        reference = (reference or '').strip() or False
        if reference:
            existing = self.search([('origin_ref', '=', reference), ('state', 'not in', ('cancelled', 'failed'))], limit=1)
            if existing:
                # NEDEN: referansı önceden alan başka bir kayıt (elle açılmış taslak, başka kaynak) çağırana
                # yabancı adres/ODP ile dönmesin (05-guvenlik D-2). Yalnız aynı kaynağın gönderilmiş kaydı döner.
                same_source = (existing.source_model, existing.source_id) == (
                    (source._name, source.id) if source else (False, 0))
                if not same_source or existing.state == 'draft':
                    raise UserError(_(
                        '"%(ref)s" iş referansı başka bir kargo gönderisine ait: %(name)s.',
                        ref=reference, name=existing.name))
                return existing
        vals = {
            'recipient_name': recipient_name, 'recipient_phone': phone, 'recipient_email': email,
            'recipient_street': street, 'recipient_state_id': state.id, 'recipient_district': district,
            'package_count': package_count, 'origin_ref': reference, 'invoice_no': invoice_no,
            'cod_amount': cod_amount, 'cod_method': cod_method, 'partner_id': partner.id if partner else False,
        }
        if weight is not None:
            vals['package_weight'] = weight
        if carrier:
            vals['carrier_id'] = carrier.id
        if source:
            vals['source_model'], vals['source_id'] = source._name, source.id
        try:
            # NEDEN: doğrulama hatasında yalnız UserError değil kayıt da geri alınmalı (çağıran hatayı yakalayıp
            # devam edebilir); commit'ler bu savepoint kapandıktan sonra, ``_cargo_send`` içinde yapılır.
            with self.env.cr.savepoint():
                # NEDEN: source_*/picking_id sistem alanıdır (yalnız sudo yazar); yetki yukarıda denetlendi.
                shipment = self.sudo().create(vals)
                shipment._cargo_check_ready()
        except pg_errors.UniqueViolation:
            # NEDEN: eşzamanlı ikinci çağrı aynı referansla birinciyi görmeden eklemeyi denedi; DB indeksi
            # mükerrerliği engeller. Birinci işlem commit'li değilse bu işlemin anlık görüntüsü onu göremez.
            raise UserError(_('Bu iş referansıyla açık bir kargo gönderisi zaten var. Birkaç saniye sonra '
                              'yeniden deneyin.')) from None
        shipment = shipment.with_env(self.env)
        shipment._cargo_send()
        return shipment

    def _cargo_send(self):
        """Gönder. ``{'status': 'ok'|'error'|'uncertain', 'message': str}`` döner (G7 ``create_and_send`` çağırır).

        DIKKAT: sıra değiştirilemez (K-21, KK-11): doğrulama → sending + commit → sağlayıcı → sonuç + commit →
        yan işler + commit. Sağlayıcı çağrısından sonra raise yoktur: gönderi kargo firmasında açılmış olabilir.
        DIKKAT: ara commit'ler çağıranın (G6 transfer, G7 API) o ana kadarki işlemini de kalıcı yapar.
        """
        self.ensure_one()
        self._cargo_check_user()
        state = self._cargo_lock()
        if state not in _EDITABLE_STATES:
            raise UserError(self._cargo_state_error(state))
        self._cargo_check_ready()
        note = self._cargo_area_manual_note()
        if note:
            self.message_post(body=note, subtype_xmlid='mail.mt_note')
        sudo = self.sudo()
        # NEDEN: test_mode gönderim anındaki firma bayrağıdır (K-26); sağlayıcı ucu buna göre seçer (G9 §2).
        sudo.write({
            'state': 'sending', 'sent_at': fields.Datetime.now(), 'test_mode': not sudo.carrier_id.prod_environment,
            'tracking_ref': False, 'error_code': False, 'error_message': False, 'label_missing': False})
        self._cargo_commit()

        result = self._cargo_provider_call('send')
        status, code, message = result['status'], result['error_code'], result['error_message']
        tracking = result['tracking_ref']
        if status == 'ok' and not tracking:
            # NEDEN: takip no'suz "başarı" ile created yazılırsa iptal/takip yapılamaz; kayıt firmada olabilir.
            status, message = 'uncertain', _('Kargo firması başarı döndü ama takip numarası vermedi.')
        if status == 'ok':
            sudo.write({'state': 'created', 'tracking_ref': tracking})
        elif status == 'error':
            sudo.write({'state': 'failed', 'error_code': code, 'error_message': message})
        else:
            sudo.write({'state': 'uncertain', 'error_message': message})
        self._cargo_commit()

        if status == 'ok':
            self._cargo_after_created(result['labels'])
            text = _('Kargo gönderisi oluşturuldu. Takip no: %s', tracking)
        elif status == 'error':
            text = _('Kargo firması gönderiyi reddetti: %s', self._cargo_error_text(code, message))
            self._cargo_side_job('chatter', self._cargo_post, text)
        else:
            text = _('Gönderinin sonucu belirsiz: %s. Kargo firmasında oluşmuş olabilir; yeniden göndermeyin, '
                     'birkaç dakika sonra "Uzlaştır" ile sorgulayın.', message or _('yanıt alınamadı'))
            self._cargo_side_job('chatter', self._cargo_post, text)
        self._cargo_commit()
        return {'status': status, 'message': text}

    def _cargo_reconcile(self):
        """Belirsiz (ya da 15 dk'dan eski takılı sending) gönderiyi kargo firmasında referansla sorgular.

        Yeniden gönderim YAPMAZ (K-21). DIKKAT: find çağrısı satır kilidi tutulurken yapılır; aynı gönderiyi
        iki oturum birden uzlaştıramaz.
        """
        self.ensure_one()
        self._cargo_check_user()
        state = self._cargo_lock()
        age = fields.Datetime.now() - self.sent_at if self.sent_at else RECONCILE_MIN_AGE
        if state == 'sending' and age < RECONCILE_MIN_AGE:
            raise UserError(_('Gönderi zaten işleniyor; sonucu birkaç saniye içinde görünür. Sayfayı yenileyin.'))
        # NEDEN (S1): sonucu yazılamadan kalmış (sunucu/DB hatası) sending kaydının başka çıkışı yoktur.
        if state not in ('uncertain', 'sending'):
            raise UserError(_('Yalnız sonucu belirsiz gönderi uzlaştırılabilir.'))
        sudo = self.sudo()
        result = self._cargo_provider_call('find')
        status, tracking, message = result['status'], result['tracking_ref'], result['error_message']
        if status == 'found' and not tracking:
            status, message = 'error', _('Kargo firması kaydı buldu ama takip numarası vermedi.')
        if status == 'found':
            sudo.write({'state': 'created', 'tracking_ref': tracking, 'label_missing': True,
                        'error_code': False, 'error_message': False})
            text = _('Uzlaştırma: gönderi kargo firmasında bulundu. Takip no: %s. Etiket alınamadı; etiketi '
                     'kargo firmasının panelinden alın.', tracking)
            count = result['count']
            if count > 1:
                text += ' ' + _('Kargo firmasında bu referansla %s kayıt var; fazlasını firmanın panelinden iptal edin.',
                                count)
        elif status == 'not_found' and age >= RECONCILE_MIN_AGE:
            text = _('Uzlaştırma: gönderi kargo firmasında bulunamadı. Gönderi hatalı sayıldı; yeniden gönderebilirsiniz.')
            sudo.write({'state': 'failed', 'error_code': False, 'error_message': text})
        elif status == 'not_found':
            minutes = math.ceil((RECONCILE_MIN_AGE - age).total_seconds() / 60)
            text = _('Gönderi kargo firmasında henüz görünmüyor; kesin karar için %s dk sonra tekrar deneyin.', minutes)
            status = 'uncertain'
        else:
            text = _('Kargo firması sorgulanamadı: %s. Durum belirsiz kaldı; sonra tekrar deneyin.',
                     message or _('yanıt alınamadı'))
            sudo.write({'state': 'uncertain', 'error_message': message})
            status = 'uncertain'
        self._cargo_commit()
        if status == 'found':
            self._cargo_side_job('chatter', self._cargo_post, text)
            self._cargo_side_job('transfer', self._cargo_write_picking_tracking)
            status = 'ok'
        elif status == 'not_found':
            self._cargo_side_job('chatter', self._cargo_post, text)
            status = 'error'
        self._cargo_commit()
        return {'status': status, 'message': text}

    def _cargo_cancel(self):
        """Oluşturulmuş gönderiyi kargo firmasında iptal eder (KK-23/24). Hata/belirsizde durum değişmez."""
        self.ensure_one()
        self._cargo_check_user()
        # NEDEN: kargoya verilmiş gönderide kilit/dış çağrı yapılmadan reddedilir (KK-24).
        if self.state in _SHIPPED_STATES:
            raise UserError(_('Kargoya verilmiş gönderi iptal edilemez.'))
        state = self._cargo_lock()
        if state in _SHIPPED_STATES:
            raise UserError(_('Kargoya verilmiş gönderi iptal edilemez.'))
        if state == 'cancelled':
            raise UserError(_('Gönderi zaten iptal edilmiş.'))
        if state != 'created':
            raise UserError(_('Yalnız oluşturulmuş gönderi iptal edilebilir.'))
        result = self._cargo_provider_call('cancel')
        status = result['status']
        reason = self._cargo_error_text(result['error_code'], result['error_message'])
        if status == 'ok':
            self.sudo().write({'state': 'cancelled', 'cancelled_at': fields.Datetime.now()})
            self._cargo_commit()
            text = _('Kargo gönderisi iptal edildi. Takip no: %s', self.tracking_ref)
            self._cargo_side_job('transfer', self._cargo_clear_picking_tracking)
        elif status == 'error':
            text = _('İptal edilemedi: %s', reason)
        else:
            text = _('İptal sonucu belirsiz: %s. Gönderi durumu değişmedi; tekrar deneyin.', reason)
        self._cargo_side_job('chatter', self._cargo_post, text)
        self._cargo_commit()
        return {'status': status, 'message': text}

    # ------------------------------------------------------------------ akış yardımcıları
    def _cargo_check_user(self):
        # NEDEN: akış sistem alanlarını sudo() ile yazar; yetki kayıt kuralına bırakılamaz. sudo() altında da
        # env.user gerçek kullanıcıdır. Okuma denetimi şirket kuralını uygular (SQL kilidi kuralı atlar).
        if not self.env.user.has_group('cargo.group_cargo_user'):
            raise AccessError(_('Kargo gönderisi işlemleri için "Kargo / Kullanıcı" yetkisi gerekir.'))
        self.check_access('read')

    def _cargo_commit(self):
        """Akışın ara noktasını kalıcı yapar (K-21: sending, sağlayıcıdan ÖNCE başka oturumlarca görülmeli).

        DIKKAT: savepoint içinden çağrılmaz; çağıranın o ana kadarki işlemi de kalıcı olur. Testlerde yamalanır.
        """
        self.env.flush_all()
        self.env.cr.commit()

    def _cargo_lock(self):
        """Gönderi satırını ``FOR UPDATE NOWAIT`` ile kilitler ve SQL'deki güncel durumu döner (KK-12).

        DIKKAT: kilit/serileştirme hatası yakalanmazsa Odoo ``retrying()`` tüm isteği 5 kez tekrarlar (DERSLER).
        Kilit ilk commit'te bırakılır; sonrasında koruma commit'li ``sending`` durumudur.
        """
        self.ensure_one()
        self.flush_recordset()
        cr = self.env.cr
        try:
            with cr.savepoint(flush=False):
                cr.execute('SELECT state FROM cargo_shipment WHERE id = %s FOR UPDATE NOWAIT', [self.id],
                           log_exceptions=False)
                row = cr.fetchone()
        except (pg_errors.LockNotAvailable, pg_errors.SerializationFailure):
            raise UserError(_('Gönderi zaten işleniyor (başka bir oturumda). Birkaç saniye sonra sayfayı yenileyin.')) from None
        if not row:
            raise UserError(_('Gönderi bulunamadı.'))
        self.invalidate_recordset()
        return row[0]

    def _cargo_state_error(self, state):
        if state == 'sending':
            return _('Gönderi zaten işleniyor; sonucu birkaç saniye içinde görünür. Sayfayı yenileyin.')
        if state == 'uncertain':
            return _('Gönderinin sonucu belirsiz; yeniden gönderilemez. Önce "Uzlaştır" ile kargo firmasında sorgulayın.')
        if state == 'cancelled':
            return _('Gönderi iptal edilmiş; yeniden gönderilemez. Yeni bir gönderi açın.')
        return _('Gönderi zaten oluşturuldu; yeniden gönderilemez.')

    def _cargo_provider_call(self, op):
        """Sağlayıcıyı çağırır; dönüşü her zaman tam anahtarlı ve izinli durumlu bir sözlüktür.

        NEDEN: sağlayıcı istisna fırlatmamalı (G9 §2) ama fırlatırsa send/cancel'da "belirsiz" sayılır (istek
        firmaya ulaşmış olabilir), find'da "hata". İstisna METNİ log'a/kayda yazılmaz: sır içerebilir (KK-3).
        """
        fallback = 'error' if op == 'find' else 'uncertain'
        try:
            with self.env.cr.savepoint():
                result = self.sudo().carrier_id._cargo_call(op, self.sudo())
        except Exception as error:      # noqa: BLE001 - dış çağrı sonrası raise yok (K-21)
            _logger.warning('cargo.shipment %s: %s çağrısı istisna verdi (%s)', self.id, op, type(error).__name__)
            result = {'status': fallback, 'error_message': _('Kargo firması çağrısı beklenmedik biçimde kesildi.')}
        if not isinstance(result, dict) or result.get('status') not in _PROVIDER_STATUSES[op]:
            _logger.warning('cargo.shipment %s: %s çağrısı geçersiz yanıt döndü', self.id, op)
            result = {'status': fallback, 'error_message': _('Kargo firmasından geçersiz yanıt alındı.')}
        count = result.get('count')
        return {
            'status': result['status'],
            'tracking_ref': str(result.get('tracking_ref') or '').strip(),
            'labels': list(result.get('labels') or []),
            'error_code': str(result.get('error_code') or '')[:64],
            'error_message': str(result.get('error_message') or '')[:ERROR_MESSAGE_MAX],
            'count': count if isinstance(count, int) else 0,
        }

    @staticmethod
    def _cargo_error_text(code, message):
        return ' '.join(part for part in (code and '[%s]' % code, message) if part) or _('ayrıntı verilmedi')

    def _cargo_side_job(self, label, func, *args):
        """Yan iş (chatter, ek, transfer): ayrı savepoint; hatası gönderi durumunu bozmaz (K-21)."""
        try:
            with self.env.cr.savepoint():
                return func(*args)
        except Exception as error:      # noqa: BLE001 - durum zaten commit'li; yan iş kaybı log'lanır
            _logger.warning('cargo.shipment %s: yan iş "%s" başarısız (%s)', self.id, label, type(error).__name__)
            return None

    def _cargo_post(self, body):
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

    def _cargo_after_created(self, labels):
        """created sonrası yan işler (her biri ayrı savepoint)."""
        stored = self._cargo_side_job('etiket', self._cargo_store_labels, labels) or 0
        if stored:
            # NEDEN: PDF oluşturma anında da üretilir ki create_and_send çağıranı eki hemen okuyabilsin (K-23).
            # Başarısızsa PNG'ler duruyordur; "Etiketi Bas" PDF'i yeniden üretir.
            self._cargo_side_job('etiket pdf', self._cargo_build_label_pdf)
        else:
            self._cargo_side_job('etiket', self.sudo().write, {'label_missing': True})
        self._cargo_side_job('chatter', self._cargo_post_created, stored)
        self._cargo_side_job('transfer', self._cargo_write_picking_tracking)

    def _cargo_store_labels(self, labels):
        """Geçerli PNG etiketlerini sağlayıcıdan geldiği gibi ``<name>-<n>.png`` eki olarak saklar; sayısını döner."""
        valid = [data for data in labels if isinstance(data, bytes) and data.startswith(_PNG_MAGIC)]
        if valid:
            attachments = self.env['ir.attachment'].sudo().create([{
                'name': '%s-%d.png' % (self.name, index), 'raw': data, 'mimetype': 'image/png',
                'res_model': self._name, 'res_id': self.id,
            } for index, data in enumerate(valid, 1)])
            self.sudo().write({'label_png_ids': [Command.set(attachments.ids)]})
        return len(valid)

    def _cargo_build_label_pdf(self):
        """Saklanan PNG'lerden PDF üretir, ``label_pdf_id`` ekine yazar (yoksa açar) ve eki döner; PNG yoksa boş."""
        # NEDEN: sıra = sağlayıcının verdiği paket sırası (ek id sırası); ad ya da res_id ile arama yapılmaz.
        pngs = self.sudo().label_png_ids.sorted('id')
        if not pngs:
            return self.env['ir.attachment']
        data = build_label_pdf([att.raw for att in pngs], self.company_id.cargo_label_size)
        pdf = self.label_pdf_id.sudo()
        # NEDEN: yalnız bu gönderiye bağlı ek yeniden yazılır; label_pdf_id bir yoldan yabancı eke işaret ederse
        # sudo yazım o eki ezerdi (K1). Yabancı ek bırakılır, yeni ek açılır.
        if pdf and (pdf.res_model, pdf.res_id) == (self._name, self.id):
            pdf.write({'raw': data})
        else:
            pdf = self.env['ir.attachment'].sudo().create({
                'name': '%s.pdf' % self.name, 'raw': data, 'mimetype': 'application/pdf',
                'res_model': self._name, 'res_id': self.id})
            self.sudo().write({'label_pdf_id': pdf.id})
        return pdf

    def _cargo_post_created(self, stored):
        body = _('Kargo gönderisi oluşturuldu. Takip no: %s', self.tracking_ref)
        if self.test_mode:
            body += ' ' + _('(Test ortamı: gerçek gönderi değildir.)')
        if stored < self.package_count:
            body += ' ' + _('Etiket eksik: %(got)s/%(want)s paket etiketi alındı; eksik etiketi kargo firmasının '
                            'panelinden alın.', got=stored, want=self.package_count)
        self._cargo_post(body)

    def _cargo_picking_tracking_allowed(self):
        """Takip no transfere yazılsın mı? Test gönderisinde ve pazaryeri (Shopify dahil) transferinde hayır."""
        self.ensure_one()
        picking = self.sudo().picking_id
        # NEDEN: test ucu takip no'su gerçek değildir; transfer üzerinden müşteriye/pazaryerine gitmemeli (K-26).
        # NEDEN: pazaryeri kancaları carrier_tracking_ref'i pazaryerine kargo takip no diye gönderir (K-20).
        return bool(picking) and not self.test_mode and not picking.cargo_marketplace_name

    def _cargo_write_picking_tracking(self):
        if self._cargo_picking_tracking_allowed():
            self.sudo().picking_id.write({'carrier_id': self.carrier_id.id, 'carrier_tracking_ref': self.tracking_ref})

    def _cargo_clear_picking_tracking(self):
        # NEDEN: transferdeki takip no başka bir (yeni) gönderiye ait olabilir; yalnız bizimki silinir.
        picking = self.sudo().picking_id
        if picking and self.tracking_ref and picking.carrier_tracking_ref == self.tracking_ref:
            picking.carrier_tracking_ref = False

    def _cargo_notification(self, result):
        kind = {'ok': 'success', 'error': 'danger'}.get(result['status'], 'warning')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': result['message'],
                'type': kind,
                'sticky': kind != 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

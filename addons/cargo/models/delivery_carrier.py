# -*- coding: utf-8 -*-
"""Kargo firması = ``delivery.carrier`` (KARARLAR K-20).

Sağlayıcı eklentisi ``delivery_type``'a kendi değerini ekler ve şu metotları tanımlar
(``<tip>`` = ``delivery_type``; hepsi ``@api.private``):
``<tip>_cargo_send``, ``<tip>_cargo_cancel``, ``<tip>_cargo_find``, ``<tip>_cargo_track``,
isteğe bağlı ``<tip>_cargo_cod_code``. ``<tip>_cargo_send`` tanımlı olan firma
"yönetilen"dir. Çekirdek sağlayıcı adını bilmez; yönlendirme ``getattr`` iledir
(Odoo ``delivery``'nin ``<tip>_send_shipping`` kalıbı).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_CARGO_OPS = ('send', 'cancel', 'find', 'track', 'cod_code')
# NEDEN: yönetilen firmada bu alanlar faturalanan hesabı, test/canlı ucunu ve gönderinin açılıp açılamayacağını
# belirler; çekirdek ACL stok/satış yöneticisine de delivery.carrier yazımı verir (05-guvenlik O-1).
# Sağlayıcıya özgü hizmet alanları sağlayıcı eklentisinde ``groups`` ile korunur.
_CARGO_PROTECTED_FIELDS = frozenset((
    'prod_environment', 'delivery_type', 'integration_level', 'active', 'company_id', 'product_id'))


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    # Kapıda ödeme (ODP) bayrakları firma/hesap başınadır; ödeme koşulu hesaba bağlıdır.
    # Hepsi yönetici grubundadır (kullanıcı ne açık olduğunu okuyamaz, değiştiremez).
    # Gönderi akışı bunları sudo() ile okur.
    # NEDEN: çekirdek varsayılanı False; yeni/başka bir firma kaydı güvenli başlar. Bayrak
    # ir.config_parameter'da değil firma alanındadır: hesap bazlıdır, K-8'deki "0/False
    # değeri parametreyi siler" tuzağı oluşmaz.
    cargo_cod_enabled = fields.Boolean(
        string='Kapıda ödeme (ODP) açık', default=False, groups='cargo.group_cargo_manager',
        help='Bu hesapta kapıda ödeme tanımlıysa açın. Kapalıyken tahsilat tutarlı gönderi reddedilir.')
    cargo_cod_allow_cash = fields.Boolean(
        string='ODP: nakit', default=True, groups='cargo.group_cargo_manager')
    cargo_cod_allow_card = fields.Boolean(
        string='ODP: kredi kartı', default=False, groups='cargo.group_cargo_manager',
        help='Sağlayıcıda kart tahsil kodu canlıda doğrulanmadan açmayın.')
    cargo_cod_allow_check = fields.Boolean(
        string='ODP: çek', default=False, groups='cargo.group_cargo_manager',
        help='Sağlayıcıda çek tahsil kodu canlıda doğrulanmadan açmayın.')
    # Form görünürlüğü için: sağlayıcı kodu Python'da olduğundan görünüm bunu koşulla bilemez.
    cargo_managed = fields.Boolean(compute='_compute_cargo_managed', string='Kargo yönetimli')

    # ------------------------------------------------------------------ yönetilen firma
    def _cargo_is_managed(self):
        """True: bu firma tipi için ``<tip>_cargo_send`` tanımlı (kargo çekirdeği yönetir)."""
        self.ensure_one()
        return hasattr(self, f'{self.delivery_type}_cargo_send')

    @api.model
    def _cargo_managed_types(self):
        """Yönetilen ``delivery_type`` değerleri (varsayılan firma domain'i için)."""
        return [value for value, _label in self._fields['delivery_type'].selection
                if hasattr(self, f'{value}_cargo_send')]

    @api.model
    def _cargo_type_is_managed(self, delivery_type):
        return bool(delivery_type) and hasattr(self, f'{delivery_type}_cargo_send')

    def _cargo_check_protected_write(self, vals=None):
        """Yönetilen firmanın korunan alanlarına (ya da kaydın kendisine) yalnız Kargo / Yönetici dokunur.

        ``vals`` None: silme. DIKKAT: super()'den ÖNCE çağrılır (DERSLER 4); env.su (kurulum verisi) muaftır.
        """
        if self.env.su or self.env.user.has_group('cargo.group_cargo_manager'):
            return
        if vals is not None and _CARGO_PROTECTED_FIELDS.isdisjoint(vals):
            return
        managed = any(carrier._cargo_is_managed() for carrier in self) or (
            vals is not None and self._cargo_type_is_managed(vals.get('delivery_type')))
        if managed:
            raise AccessError(_(
                'Kargo firmasının test/canlı, tip, entegrasyon, etkinlik, şirket ve ürün ayarlarını yalnız '
                '"Kargo / Yönetici" değiştirebilir.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            delivery_type = vals.get('delivery_type') or self.default_get(['delivery_type']).get('delivery_type')
            if self._cargo_type_is_managed(delivery_type):
                self.browse()._cargo_check_protected_write(dict(vals, delivery_type=delivery_type))
        return super().create(vals_list)

    def write(self, vals):
        self._cargo_check_protected_write(vals)
        return super().write(vals)

    def unlink(self):
        self._cargo_check_protected_write()
        return super().unlink()

    def copy_data(self, default=None):
        # NEDEN: copy_data copy=True olan her alanı okur; groups'lu alanlar (ODP bayrakları, sağlayıcı hizmet
        # alanları) üyesi olmayan stok/satış yöneticisinde AccessError verip HİÇBİR firmanın çoğaltılmasına
        # izin vermiyordu. Okuyamadığı alan kopyada atlanır; yeni kayıt alanın varsayılanını (güvenli) alır.
        default = dict(default or {})
        hidden = [name for name, field in self._fields.items()
                  if field.copy and field.groups and name not in default and not self._has_field_access(field, 'read')]
        # yer tutucu: copy_data default'taki alanı okumaz; sonra vals'tan çıkarılır
        default.update(dict.fromkeys(hidden, False))
        return [vals and {key: value for key, value in vals.items() if key not in hidden}
                for vals in super().copy_data(default)]

    # ------------------------------------------------------------------ stock_delivery yolları
    def send_shipping(self, pickings):
        # NEDEN: yönetilen firmada ``<tip>_send_shipping`` yok; Odoo None döner ve ``send_to_shipper``
        # ``None[0]`` ile traceback verir (05-inceleme Ö3). Gönderi yalnız kargo gönderisi formundan açılır
        # (adres/ODP doğrulaması, mükerrer koruması orada).
        self.ensure_one()
        if self._cargo_is_managed():
            raise UserError(_('"%s" ile gönderi buradan açılamaz. Transferdeki "Kargo gönderisi" düğmesiyle '
                              'kargo gönderisi formundan gönderin.', self.display_name))
        return super().send_shipping(pickings)

    def cancel_shipment(self, pickings):
        # NEDEN: transferin "İptal" düğmesi kargo gönderisini bilmez; firmada iptal edip gönderiyi açık bırakırdı.
        # DIKKAT: cargo_ups testleri bu metnin 'Kargo gönderisi formundan iptal edin' kısmını arar.
        self.ensure_one()
        if self._cargo_is_managed():
            raise UserError(_('"%s" gönderisi buradan iptal edilemez. Kargo gönderisi formundan iptal edin.',
                              self.display_name))
        return super().cancel_shipment(pickings)

    @api.depends('delivery_type')
    def _compute_cargo_managed(self):
        for carrier in self:
            carrier.cargo_managed = carrier._cargo_is_managed()

    def _cargo_call(self, op, *args, **kwargs):
        """Sağlayıcı metodunu çağırır: ``getattr(self, f'{delivery_type}_cargo_{op}')``.

        Yönetilmeyen firmada UserError verir.
        NEDEN: ``prod_environment`` kapalıyken çağrıyı ENGELLEMEZ. Kapalı bayrak "sağlayıcının
        test ortamı" demektir; uç seçimi sağlayıcının işidir (bkz. KARARLAR K-26). Test ucu
        olmayan sağlayıcı, bayrak kapalıyken kendisi UserError vermelidir.
        DIKKAT: sağlayıcı istisna fırlatmamalıdır (sonucu dict olarak döner); beklenmeyen
        istisnayı çağıran (gönderi akışı) send'de "belirsiz", diğerlerinde "hata" sayar.
        """
        self.ensure_one()
        if op not in _CARGO_OPS:
            raise UserError(_('Bilinmeyen kargo işlemi: %s', op))
        method = getattr(self, f'{self.delivery_type}_cargo_{op}', None)
        if method is None:
            raise UserError(_('"%s" kargo firması kargo gönderisi için ayarlı değil.', self.display_name))
        return method(*args, **kwargs)

    @api.constrains('integration_level', 'delivery_type')
    def _check_cargo_integration_level(self):
        # NEDEN: yönetilen firmada "Get Rate and Create Shipment" kapalı olmalı. Aksi halde
        # stock_delivery picking onayında send_to_shipper ile kargoyu OTOMATİK açar; gönderi
        # (ücretli, geri alınamaz) yalnız kullanıcı eylemiyle açılır (KARARLAR K-20, KK-33).
        for carrier in self:
            if carrier.integration_level != 'rate' and carrier._cargo_is_managed():
                raise ValidationError(_(
                    '"%s" kargo firmasında entegrasyon düzeyi "Get Rate" olmalıdır: kargo gönderisi '
                    'sevkiyat onayında otomatik açılmaz, Kargo menüsünden açılır.', carrier.display_name))

    @api.onchange('delivery_type')
    def _onchange_delivery_type_cargo(self):
        # Yönetilen tipi seçince kayıt kaydedilirken kısıt hatasına düşmesin.
        if self.delivery_type and self._cargo_is_managed():
            self.integration_level = 'rate'

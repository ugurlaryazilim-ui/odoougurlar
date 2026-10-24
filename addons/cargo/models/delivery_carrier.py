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
from odoo.exceptions import UserError, ValidationError

_CARGO_OPS = ('send', 'cancel', 'find', 'track', 'cod_code')


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

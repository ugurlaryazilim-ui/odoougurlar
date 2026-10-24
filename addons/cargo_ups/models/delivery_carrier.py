# -*- coding: utf-8 -*-
"""UPS Türkiye kargo firması = ``delivery.carrier`` (``delivery_type='ups_tr'``, KARARLAR K-20).

Bu dosya iskelettir: hesap/hizmet alanları ve Odoo ``delivery`` kancaları. SOAP istemcisi ve
``ups_tr_cargo_send|cancel|find`` gerçek uygulaması G9'dadır.
"""
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_MANAGER = 'cargo.group_cargo_manager'


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    # NEDEN: anahtar 'ups' değil 'ups_tr'; Enterprise delivery_ups modülünün 'ups' anahtarıyla
    # çakışmaz. ondelete modül kaldırılırken ups_tr firmalarını fixed + arşivli yapar, böylece
    # picking'lerdeki carrier_id kalır ama firma seçilemez olur.
    delivery_type = fields.Selection(
        selection_add=[('ups_tr', 'UPS Türkiye')],
        ondelete={'ups_tr': lambda carriers: carriers.write({'delivery_type': 'fixed', 'active': False})})

    # NEDEN: hesap bilgileri firma alanındadır ve yalnız Kargo / Yönetici okur-yazar (DERSLER:
    # groups'lu alan RPC'de iç kullanıcıya kapalı). copy=False: kopyalanan firma sır taşımaz.
    # DIKKAT: ayar ekranına (res.config.settings) sır EKLEME; çekirdek default_get groups'lu parametreleri sızdırır.
    ups_tr_customer_number = fields.Char('UPS müşteri no', groups=_MANAGER, copy=False)
    ups_tr_shipper_account = fields.Char('UPS gönderici hesap no', groups=_MANAGER, copy=False)
    ups_tr_username = fields.Char('UPS kullanıcı adı', groups=_MANAGER, copy=False)
    ups_tr_password = fields.Char('UPS şifre', groups=_MANAGER, copy=False)
    # Takip servisi kimliği boşsa gönderi kimliği kullanılır (AS-2); hizmet A2'de gelir.
    ups_tr_track_username = fields.Char('UPS takip kullanıcı adı', groups=_MANAGER, copy=False)
    ups_tr_track_password = fields.Char('UPS takip şifre', groups=_MANAGER, copy=False)

    # Hizmet seçenekleri sır değildir (UPS WSDL: ServiceLevel/PaymentType/PackageType/SmsToConsignee).
    ups_tr_service_level = fields.Selection([
        ('1', 'Domestic Express Plus 09:00'), ('3', 'Domestic Standard'), ('4', 'Domestic Express 10:30'),
        ('5', 'Domestic Express 12:00'), ('6', 'Domestic Express Saver')],
        string='UPS hizmet', default='3')
    ups_tr_payment_type = fields.Selection([
        ('1', 'Alıcı öder'), ('2', 'Gönderici öder'), ('4', 'Üçüncü taraf öder')],
        string='UPS ödeme türü', default='2')
    ups_tr_package_type = fields.Selection(
        [('D', 'Zarf'), ('K', 'Paket')], string='UPS paket türü', default='K')
    ups_tr_sms_to_consignee = fields.Boolean('Alıcıya SMS (UPS)', default=False)

    # ------------------------------------------------------------------ Odoo delivery kancaları
    def ups_tr_rate_shipment(self, order):
        # NEDEN: fiyat hesaplanmaz; UPS sözleşme fiyatı API'den alınmaz ve satışta kargo tutarı
        # bu firmadan gelmez (K-20: yönetilen firma yalnız elle açılan gönderi için).
        return {'success': False, 'price': 0.0, 'error_message': _('Fiyat hesaplanmaz'), 'warning_message': False}

    def ups_tr_cancel_shipment(self, pickings):
        # NEDEN: stock_delivery'nin "Cancel" düğmesi bu kancayı çağırır; gönderi picking'e değil
        # cargo.shipment'a bağlıdır, iptal kayıt durumunu ve uzlaştırmayı oradan yönetir (K-21).
        raise UserError(_('UPS gönderisi buradan iptal edilemez. Kargo gönderisi formundan iptal edin.'))

    def ups_tr_get_tracking_link(self, picking):
        # NEDEN: herkese açık UPS takip sayfası; bağlantıda oturum/kimlik/LabelKey yoktur.
        # DIKKAT: adres canlıda doğrulanmadı (CD listesi); değişirse yalnız burası güncellenir.
        return 'https://www.ups.com/track?loc=tr_TR&tracknum=%s' % quote(picking.carrier_tracking_ref or '')

    # ------------------------------------------------------------------ çekirdek sağlayıcı kancaları (G9 gerçekler)
    # NEDEN: kancaların varlığı firmayı "yönetilen" yapar (cargo _cargo_is_managed: ups_tr_cargo_send var mı).
    # G9 SOAP istemcisini yazana kadar hiçbir UPS çağrısı yapılmaz; sonuç "error" olarak döner.
    # DIKKAT: G9 bu üç metodun GÖVDESİNİ değiştirir; adlarını silmek firmayı yönetilen olmaktan çıkarır
    # (integration_level kısıtı ve gönderi akışı devre dışı kalır).
    @api.private
    def ups_tr_cargo_send(self, shipment):
        return {'status': 'error', 'error_message': _('UPS istemcisi henüz kurulu değil.')}

    @api.private
    def ups_tr_cargo_cancel(self, shipment):
        return {'status': 'error', 'error_message': _('UPS istemcisi henüz kurulu değil.')}

    @api.private
    def ups_tr_cargo_find(self, shipment):
        return {'status': 'error', 'error_message': _('UPS istemcisi henüz kurulu değil.')}

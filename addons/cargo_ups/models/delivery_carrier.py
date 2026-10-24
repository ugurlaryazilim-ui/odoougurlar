# -*- coding: utf-8 -*-
"""UPS Türkiye kargo firması = ``delivery.carrier`` (``delivery_type='ups_tr'``, KARARLAR K-20).

Hesap/hizmet alanları, Odoo ``delivery`` kancaları ve çekirdek sağlayıcı kancaları
(``ups_tr_cargo_send|cancel|find|cod_code``, sözleşme 02-tasarim §4.5). SOAP ayrıntısı ``services/ups_soap``.
"""
import logging
import re
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_repr

from ..services import ups_soap

_logger = logging.getLogger(__name__)

_MANAGER = 'cargo.group_cargo_manager'
# NEDEN: UPS cep telefonunu ayrı alanda ister; 5xx xxx xx xx (başında 0 ya da 90 olabilir) cep sayılır.
_MOBILE = re.compile(r'(?:90|0)?5\d{9}')
# C# örneği / WSDL: ValueOfGoodsPaymentType 1 nakit, 2 çek, 3 kredi kartı.
_COD_CODES = {'cash': '1', 'check': '2', 'card': '3'}


def _phones(raw):
    """-> (cep, sabit); yalnız biri dolu, en çok 16 rakam."""
    digits = re.sub(r'\D', '', raw or '')[:16]
    return (digits, '') if _MOBILE.fullmatch(digits) else ('', digits)


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
    # NEDEN (O-1, 05-guvenlik): ödeme türü/hizmet düzeyi faturayı belirler ve değişiklik iz bırakmaz
    # (delivery.carrier mail.thread değil). delivery.carrier ACL'si stok ve satış yöneticisine yazma verir;
    # koruma alan groups'udur. Gönderi akışı bu alanları sudo ile okur (_ups_tr_shipment_info).
    # DIKKAT: groups kaldırılırsa stok yöneticisi "Alıcı öder"/Express seçebilir. Çekirdek alanlar
    # (prod_environment, delivery_type, active, company_id) cargo'daki write denetimindedir.
    ups_tr_service_level = fields.Selection([
        ('1', 'Domestic Express Plus 09:00'), ('3', 'Domestic Standard'), ('4', 'Domestic Express 10:30'),
        ('5', 'Domestic Express 12:00'), ('6', 'Domestic Express Saver')],
        string='UPS hizmet', default='3', groups=_MANAGER)
    ups_tr_payment_type = fields.Selection([
        ('1', 'Alıcı öder'), ('2', 'Gönderici öder'), ('4', 'Üçüncü taraf öder')],
        string='UPS ödeme türü', default='2', groups=_MANAGER)
    ups_tr_package_type = fields.Selection(
        [('D', 'Zarf'), ('K', 'Paket')], string='UPS paket türü', default='K', groups=_MANAGER)
    ups_tr_sms_to_consignee = fields.Boolean('Alıcıya SMS (UPS)', default=False, groups=_MANAGER)

    # ------------------------------------------------------------------ Odoo delivery kancaları
    def ups_tr_rate_shipment(self, order):
        # NEDEN: fiyat hesaplanmaz; UPS sözleşme fiyatı API'den alınmaz ve satışta kargo tutarı
        # bu firmadan gelmez (K-20: yönetilen firma yalnız elle açılan gönderi için).
        return {'success': False, 'price': 0.0, 'error_message': _('Fiyat hesaplanmaz'), 'warning_message': False}

    def ups_tr_cancel_shipment(self, pickings):
        # NEDEN: stock_delivery'nin "Cancel" düğmesi bu kancayı çağırır; gönderi picking'e değil
        # cargo.shipment'a bağlıdır, iptal kayıt durumunu ve uzlaştırmayı oradan yönetir (K-21).
        # NEDEN (bilinçli yedek): cargo'nun cancel_shipment override'ı yönetilen firmada önce raise eder, bu kanca
        # normal akışta erişilmez; override kaldırılırsa çekirdek bu kancayı çağırır ve UPS'te iptal edip gönderiyi
        # açık bırakmasın diye kalır. KK-33 kabul testi (test_kabul_ups_kurulum) kancayı doğrudan çağırır.
        raise UserError(_('UPS gönderisi buradan iptal edilemez. Kargo gönderisi formundan iptal edin.'))

    def ups_tr_get_tracking_link(self, picking):
        # NEDEN: herkese açık UPS takip sayfası; bağlantıda oturum/kimlik/LabelKey yoktur.
        # DIKKAT: adres canlıda doğrulanmadı (CD listesi); değişirse yalnız burası güncellenir.
        return 'https://www.ups.com/track?loc=tr_TR&tracknum=%s' % quote(picking.carrier_tracking_ref or '')

    # ------------------------------------------------------------------ çekirdek sağlayıcı kancaları
    # NEDEN: kancaların varlığı firmayı "yönetilen" yapar (cargo _cargo_is_managed: ups_tr_cargo_send var mı).
    # DIKKAT: adlarını silmek firmayı yönetilen olmaktan çıkarır (integration_level kısıtı ve gönderi akışı
    # devre dışı kalır). Sözleşme: istisna fırlatmazlar, her anahtarı dolu sözlük dönerler.
    # DIKKAT: uç (canlı/test) gönderinin ``test_mode`` alanından seçilir, firma bayrağından değil: gönderi
    # hangi uçta açıldıysa iptal/uzlaştırma da oraya gider (çekirdek gönderimde test_mode'u tazeler).
    @api.private
    def ups_tr_cargo_cod_code(self, method):
        return _COD_CODES.get(method, '')

    @api.private
    def ups_tr_cargo_send(self, shipment):
        self.ensure_one()
        shipment = shipment.sudo()
        stage = 'prepare'
        try:
            client = self._ups_tr_client(shipment.test_mode)
            info, dimensions = self._ups_tr_shipment_info(shipment)
            stage = 'login'
            session = client.login()
            stage = 'create'
            tracking, labels = client.create_shipment(session, info, dimensions)
        except ups_soap.UpsError as err:
            return self._ups_tr_log(shipment, 'send', {
                'status': err.kind, 'tracking_ref': '', 'labels': [], 'error_code': err.code,
                'error_message': err.message})
        except Exception as exc:  # noqa: BLE001 - sözleşme: sağlayıcı istisna fırlatmaz
            # NEDEN: Create gönderildikten sonra beklenmeyen hata UPS'te gönderi açılmış olabilir demektir.
            status = 'uncertain' if stage == 'create' else 'error'
            return self._ups_tr_log(shipment, 'send', {
                'status': status, 'tracking_ref': '', 'labels': [], 'error_code': type(exc).__name__,
                'error_message': _('UPS gönderisi beklenmeyen hata verdi (%s).', type(exc).__name__)})
        return self._ups_tr_log(shipment, 'send', {
            'status': 'ok', 'tracking_ref': tracking, 'labels': labels, 'error_code': '', 'error_message': ''})

    @api.private
    def ups_tr_cargo_cancel(self, shipment):
        self.ensure_one()
        shipment = shipment.sudo()
        if not shipment.tracking_ref:
            return {'status': 'error', 'error_code': '',
                    'error_message': _('Takip numarası olmayan gönderi UPS\'te iptal edilemez.')}
        stage = 'prepare'
        try:
            client = self._ups_tr_client(shipment.test_mode)
            session = client.login()
            stage = 'cancel'
            client.cancel(session, shipment.tracking_ref)
        except ups_soap.UpsError as err:
            return self._ups_tr_log(shipment, 'cancel', {
                'status': err.kind, 'error_code': err.code, 'error_message': err.message})
        except Exception as exc:  # noqa: BLE001
            status = 'uncertain' if stage == 'cancel' else 'error'
            return self._ups_tr_log(shipment, 'cancel', {
                'status': status, 'error_code': type(exc).__name__,
                'error_message': _('UPS iptali beklenmeyen hata verdi (%s).', type(exc).__name__)})
        return self._ups_tr_log(shipment, 'cancel', {'status': 'ok', 'error_code': '', 'error_message': ''})

    @api.private
    def ups_tr_cargo_find(self, shipment):
        self.ensure_one()
        shipment = shipment.sudo()
        if shipment.test_mode:
            # NEDEN: UPS sorgu servisinin test ucu yok (tasarım §4.7); test gönderisi bulunamadı sayılır,
            # çekirdek 15 dk kuralıyla karar verir.
            return {'status': 'not_found', 'tracking_ref': '', 'count': 0, 'error_message': ''}
        try:
            client = self._ups_tr_client(False)
            numbers = client.find_by_reference(client.query_login(), shipment.name)
        except ups_soap.UpsError as err:
            return self._ups_tr_log(shipment, 'find', {
                'status': 'error', 'tracking_ref': '', 'count': 0, 'error_message': err.message})
        except Exception as exc:  # noqa: BLE001
            return self._ups_tr_log(shipment, 'find', {
                'status': 'error', 'tracking_ref': '', 'count': 0,
                'error_message': _('UPS sorgusu beklenmeyen hata verdi (%s).', type(exc).__name__)})
        if not numbers:
            return self._ups_tr_log(shipment, 'find', {
                'status': 'not_found', 'tracking_ref': '', 'count': 0, 'error_message': ''})
        return self._ups_tr_log(shipment, 'find', {
            'status': 'found', 'tracking_ref': numbers[0], 'count': len(numbers), 'error_message': ''})

    # ------------------------------------------------------------------ yardımcılar
    def _ups_tr_client(self, test_mode):
        carrier = self.sudo()
        return ups_soap.UpsClient(
            carrier.ups_tr_customer_number, carrier.ups_tr_username, carrier.ups_tr_password,
            test_mode=test_mode, track_username=carrier.ups_tr_track_username,
            track_password=carrier.ups_tr_track_password, masked=[carrier.ups_tr_shipper_account])

    def _ups_tr_shipment_info(self, shipment):
        """-> (ShipmentInfo alanları, paket listesi). Veri hatası UpsError('error') olur (UPS'e gidilmez)."""
        carrier = self.sudo()
        company = shipment.company_id
        # NEDEN: çekirdekteki gönderici kuralının kendisi (tek kural, 05-inceleme ÖNERİ 8); çekirdek doğrulaması
        # dışından çağrılırsa diye boşluk burada da UPS'e gitmeden hataya çevrilir.
        sender_area = shipment._cargo_sender_area()
        if not sender_area:
            raise ups_soap.UpsError('error', '', _('Şirket adresinin ilçesi eşleşmedi: %(state)s/%(city)s.',
                                                   state=company.state_id.name or '?', city=company.city or '?'))
        area = shipment.area_id
        if not area or area.provider != 'ups_tr':
            raise ups_soap.UpsError('error', '', _('Alıcı ilçesi UPS ilçe listesinde eşleşmedi.'))
        cod = float_compare(shipment.cod_amount or 0.0, 0.0, precision_digits=2) > 0
        cod_code = self.ups_tr_cargo_cod_code(shipment.cod_method) if cod else '0'
        if not cod_code:
            raise ups_soap.UpsError('error', '', _('Kapıda ödeme tahsil şekli UPS için geçersiz.'))
        sender_mobile, sender_phone = _phones(company.phone)
        mobile, phone = _phones(shipment.recipient_phone)
        info = {
            'ShipperAccountNumber': carrier.ups_tr_shipper_account or '',
            'ShipperName': (company.name or '')[:40],
            'ShipperAddress': ' '.join(filter(None, (company.street, company.street2)))[:255],
            'ShipperCityCode': sender_area.city_code, 'ShipperAreaCode': sender_area.area_code,
            'ShipperPhoneNumber': sender_phone, 'ShipperMobilePhoneNumber': sender_mobile,
            'ShipperEMail': (company.email or '')[:64],
            'ConsigneeName': (shipment.recipient_name or '')[:40],
            'ConsigneeAddress': (shipment.recipient_street or '')[:255],
            'ConsigneeCityCode': area.city_code, 'ConsigneeAreaCode': area.area_code,
            'ConsigneePhoneNumber': phone, 'ConsigneeMobilePhoneNumber': mobile,
            'ConsigneeEMail': (shipment.recipient_email or '')[:64],
            'ServiceLevel': carrier.ups_tr_service_level or '3',
            # EKIP-BORC: '4' (üçüncü taraf öder) için ThirdPartyAccountNumber alanı yok; UPS bu durumda hata
            # döner (failed). Gerekirse firmaya ups_tr_third_party_account alanı eklenip buraya bağlanmalı.
            'PaymentType': carrier.ups_tr_payment_type or '2',
            'PackageType': carrier.ups_tr_package_type or 'K',
            'NumberOfPackages': shipment.package_count,
            'CustomerReferance': shipment.name,
            'CustomerInvoiceNumber': shipment.invoice_no or '',
            # NEDEN: KVKK - UPS alıcıya e-posta bildirimi göndermez (02-tasarim §4.7).
            'DeliveryNotificationEmail': '',
            'IdControlFlag': 0, 'PhonePrealertFlag': 0, 'SmsToShipper': 0,
            'SmsToConsignee': 1 if carrier.ups_tr_sms_to_consignee else 0,
            # NEDEN: ValueOfGoods sigorta beyanı değildir; sigorta değeri hep 0 (KK-16).
            'InsuranceValue': 0,
            'ValueOfGoods': float_repr(shipment.cod_amount, 2) if cod else '0',
            'ValueOfGoodsCurrency': 'TL' if cod else '',
            'ValueOfGoodsPaymentType': cod_code,
        }
        dimension = {'DescriptionOfGoods': (shipment.description or '')[:120], 'Length': 0, 'Height': 0,
                     'Width': 0, 'Weight': float_repr(shipment.package_weight, 3)}
        return info, [dimension] * shipment.package_count

    def _ups_tr_log(self, shipment, op, result):
        # DIKKAT: yalnız işlem, gönderi no, durum, takip no ve hata kodu; mesaj/telefon/gövde loglanmaz.
        _logger.info('UPS %s %s: %s %s %s', op, shipment.name, result['status'],
                     result.get('tracking_ref') or '', result.get('error_code') or '')
        return result

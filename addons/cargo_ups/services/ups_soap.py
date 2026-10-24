# -*- coding: utf-8 -*-
"""UPS Türkiye SOAP istemcisi (wsCreateShipment + QueryPackageInfo). Odoo'dan bağımsızdır.

Tasarım 02-tasarim §1.3 (hata sınıfları), §4.7 (işlemler, uçlar). Sözleşme: sozlesme-G9.md.
Her hata ``UpsError(kind, code, message)`` olarak yükselir; ``kind`` 'error' (UPS'te iş yapılmadı,
yeniden denemek güvenli) ya da 'uncertain' (UPS'te yapılmış olabilir). ``message`` her zaman
``_scrub``'dan geçmiştir; istek/yanıt gövdesi ve istisna metni hiçbir yere yazılmaz.
"""
import base64
import binascii
import logging
import re
import time

import requests
from lxml import etree

_logger = logging.getLogger(__name__)

URL_SHIP_LIVE = 'https://ws.ups.com.tr/wsCreateShipment/wsCreateShipment.asmx'
URL_SHIP_TEST = 'https://ws.ups.com.tr/wsCreateShipmenttest/wsCreateShipment.asmx'
# NEDEN: sorgu servisinin test ucu yok; test modunda sorgu hiç yapılmaz (çağıran karar verir).
URL_QUERY = 'https://ws.ups.com.tr/QueryPackageInfo/wsQueryPackagesInfo.asmx'
# DIKKAT: iki servisin ad alanı ve SOAPAction biçimi farklıdır (WSDL): gönderi ad alanı '/' ile
# bitmez, SOAPAction = ns + '/' + op; sorgu ad alanı '/' ile biter, SOAPAction = ns + op.
NS_SHIP = 'https://ws.ups.com.tr/wsCreateShipment'
NS_QUERY = 'https://ws.ups.com.tr/wsPaketIslemSorgulamaEng/'
NS_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
NS_XSI = 'http://www.w3.org/2001/XMLSchema-instance'
# NEDEN: (bağlantı, okuma) saniye. Bağlantı zaman aşımında istek gitmemiştir (güvenli hata);
# okuma zaman aşımında UPS isteği işlemiş olabilir (belirsiz).
TIMEOUT = (5, 25)
SCRUB_MAX = 500
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

# WSDL ShipmentInfo_Type3 alan sırası. DIKKAT: .asmx sıralı (xs:sequence) bekler; sırayı değiştirme.
SHIPMENT_INFO_FIELDS = (
    'ShipperAccountNumber', 'ShipperName', 'ShipperContactName', 'ShipperAddress', 'ShipperCityCode',
    'ShipperAreaCode', 'ShipperPostalCode', 'ShipperPhoneNumber', 'ShipperPhoneExtension',
    'ShipperMobilePhoneNumber', 'ShipperEMail', 'ShipperExpenseCode',
    'ConsigneeAccountNumber', 'ConsigneeName', 'ConsigneeContactName', 'ConsigneeAddress', 'ConsigneeCityCode',
    'ConsigneeAreaCode', 'ConsigneePostalCode', 'ConsigneePhoneNumber', 'ConsigneePhoneExtension',
    'ConsigneeMobilePhoneNumber', 'ConsigneeEMail', 'ConsigneeExpenseCode',
    'ServiceLevel', 'PaymentType', 'PackageType', 'NumberOfPackages', 'CustomerReferance',
    'CustomerInvoiceNumber', 'DeliveryNotificationEmail', 'IdControlFlag', 'PhonePrealertFlag', 'SmsToShipper',
    'SmsToConsignee', 'InsuranceValue', 'InsuranceValueCurrency', 'ValueOfGoods', 'ValueOfGoodsCurrency',
    'ValueOfGoodsPaymentType', 'DeliveryByTally', 'ThirdPartyAccountNumber', 'ThirdPartyExpenseCode',
)
DIMENSION_FIELDS = ('DescriptionOfGoods', 'Length', 'Height', 'Width', 'Weight')

# XML 1.0'da yazılamayan karakterler; lxml bunlarda ValueError verir (ör. adrese yapışmış \x0b).
_XML_INVALID = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]')
_LABEL_KEY = re.compile(r'\S*labelkey\S*', re.IGNORECASE)
_GUID = re.compile(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', re.IGNORECASE)
# NEDEN: istemcinin bilmediği oturum kimliği de (ör. Login hatası metninde) gizlenir: anahtar sözcükten
# sonraki rakamlı belirteç silinir. Rakamsız sözcük kalır ("Oturum süresi doldu" bozulmaz).
_SESSION_TOKEN = re.compile(r'\b(session\s*id|session|oturum)(\s*[:=]?\s*)(?=\S*\d)\S+', re.IGNORECASE)
# NEDEN: XXE/entity genişletme ve ağdan DTD çekme kapalı; yanıt güvenilmeyen dış veridir.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


class UpsError(Exception):
    def __init__(self, kind, code, message):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message


def _scrub(text, secrets=(), masked=()):
    """Metinden sırları siler. ``secrets`` tamamen ``***`` olur, ``masked`` (müşteri/hesap no) son 2 hanesiyle kalır."""
    text = str(text or '')
    text = _LABEL_KEY.sub('***', text)
    text = _GUID.sub('***', text)
    text = _SESSION_TOKEN.sub(r'\1\2***', text)
    # NEDEN: 3 karakterden kısa değer metni anlamsızlaştırır (ör. '1'); gerçek kimlikler daha uzundur.
    for value in sorted({s for s in secrets if s and len(s) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(value), '***', text, flags=re.IGNORECASE)
    for value in sorted({s for s in masked if s and len(s) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(value), '***' + value[-2:], text, flags=re.IGNORECASE)
    return text[:SCRUB_MAX]


def _text(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return _XML_INVALID.sub('', str(value))


def _fill(parent, ns, fields):
    for name, value in fields:
        node = etree.SubElement(parent, etree.QName(ns, name))
        if value is None:
            node.set(etree.QName(NS_XSI, 'nil'), 'true')
        elif isinstance(value, list):
            _fill(node, ns, value)
        else:
            node.text = _text(value)


def _envelope(ns, op, fields):
    """SOAP 1.1 zarfı. ``fields``: [(ad, değer)]; değer None -> xsi:nil, liste -> iç içe öğe.

    DIKKAT: zarf string birleştirmeyle kurulmaz; kullanıcı verisindeki < & kaçışlarını lxml yapar.
    """
    root = etree.Element(etree.QName(NS_SOAP, 'Envelope'), nsmap={'soap': NS_SOAP, 'xsi': NS_XSI})
    body = etree.SubElement(root, etree.QName(NS_SOAP, 'Body'))
    # NEDEN: .asmx işlem öğesini varsayılan ad alanıyla bekler (örnek zarf); alt öğeler aynı ad alanında.
    operation = etree.SubElement(body, etree.QName(ns, op), nsmap={None: ns})
    _fill(operation, ns, fields)
    return etree.tostring(root, xml_declaration=True, encoding='utf-8')


def _int(text):
    try:
        return int((text or '').strip())
    except ValueError:
        return None


class UpsClient:
    """Tek işlemlik istemci. Oturum önbelleğe alınmaz: her işlem kendi Login'ini yapar (SessionID 5 dk)."""

    def __init__(self, customer, username, password, *, test_mode, track_username='', track_password='', masked=()):
        self.customer = customer or ''
        self.username = username or ''
        self.password = password or ''
        # Takip kimliği boşsa gönderi kimliği kullanılır (AS-2).
        if track_username:
            self.track_username, self.track_password = track_username, track_password or ''
        else:
            self.track_username, self.track_password = self.username, self.password
        self.test_mode = bool(test_mode)
        self.ship_url = URL_SHIP_TEST if self.test_mode else URL_SHIP_LIVE
        self._secrets = [self.password, self.username, self.track_password, self.track_username]
        self._masked = [self.customer] + [m for m in masked if m]

    def scrub(self, text):
        return _scrub(text, self._secrets, self._masked)

    # ------------------------------------------------------------------ taşıma
    def _unsure(self, unsafe, code, message):
        # NEDEN: Create/Cancel yanıtı alınamadıysa UPS işlemi yapmış olabilir (K-21); Login/sorgu yan etkisizdir.
        if unsafe:
            return UpsError('uncertain', code, message + ' İşlem UPS\'te gerçekleşmiş olabilir; durumu kontrol edin.')
        return UpsError('error', code, message)

    def _call(self, url, ns, op, fields, unsafe):
        """İstek gönderir, ``<op>Result`` öğesini döner; her hata UpsError'dur."""
        try:
            data = _envelope(ns, op, fields)
        except Exception as exc:  # noqa: BLE001 - istek gitmedi, güvenli hata
            raise UpsError('error', type(exc).__name__, 'UPS isteği hazırlanamadı (%s).' % type(exc).__name__)
        action = ns + op if ns.endswith('/') else ns + '/' + op
        started = time.monotonic()
        http_status = '-'
        outcome = 'ok'
        try:
            try:
                response = requests.post(
                    url, data=data, timeout=TIMEOUT, allow_redirects=False,
                    headers={'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': '"%s"' % action})
            # DIKKAT: ConnectTimeout, ConnectionError'ın alt sınıfıdır; önce yakalanmalı (istek hiç gitmedi).
            except requests.ConnectTimeout:
                raise UpsError('error', 'ConnectTimeout', 'UPS\'e bağlanılamadı (zaman aşımı); istek gitmedi.')
            except Exception as exc:  # noqa: BLE001 - ReadTimeout, ConnectionError, SSLError, beklenmeyen
                # NEDEN: str(exc) URL/gövde parçası taşıyabilir; yalnız sınıf adı kullanılır.
                raise self._unsure(unsafe, type(exc).__name__, 'UPS yanıtı alınamadı (%s).' % type(exc).__name__)
            http_status = response.status_code
            try:
                return self._result(response, op, unsafe)
            except UpsError:
                raise
            except Exception as exc:  # noqa: BLE001 - yanıt geldi ama işlenemedi
                raise self._unsure(unsafe, 'XML', 'UPS yanıtı işlenemedi (%s).' % type(exc).__name__)
        except UpsError as err:
            outcome = err.code
            raise
        finally:
            _logger.info('UPS %s (%s): HTTP %s, sonuç %s, %d ms', op, 'test' if self.test_mode else 'canli',
                         http_status, outcome, (time.monotonic() - started) * 1000)

    def _result(self, response, op, unsafe):
        content = response.content or b''
        root = None
        if content.strip():
            try:
                # NEDEN: bayt verilir; str + encoding bildirimi lxml'de ValueError olur.
                root = etree.fromstring(content, _PARSER)
            except (etree.XMLSyntaxError, ValueError):
                root = None
        if root is not None:
            fault = root.find('.//{*}Fault')
            if fault is not None:
                # NEDEN: Fault = sunucu isteği işlemedi (CD-9); yeniden göndermek güvenli kabul edilir.
                reason = fault.findtext('{*}faultstring') or fault.findtext('.//{*}Text') or ''
                raise UpsError('error', 'SOAP Fault', self.scrub('UPS isteği reddetti: %s' % reason.strip()))
        if response.status_code != 200:
            raise self._unsure(unsafe, 'HTTP %s' % response.status_code,
                               'UPS beklenmeyen yanıt verdi (HTTP %s).' % response.status_code)
        result = root.find('.//{*}%sResult' % op) if root is not None else None
        if result is None:
            raise self._unsure(unsafe, 'XML', 'UPS yanıtı okunamadı.')
        return result

    def _check(self, result, unsafe):
        code = _int(result.findtext('{*}ErrorCode'))
        if code is None:
            raise self._unsure(unsafe, 'XML', 'UPS yanıtında hata kodu okunamadı.')
        if code != 0:
            definition = (result.findtext('{*}ErrorDefinition') or '').strip()
            raise UpsError('error', str(code), self.scrub('UPS hata %s: %s' % (code, definition)))

    def _login(self, url, ns, op, username, password):
        result = self._call(url, ns, op, [('CustomerNumber', self.customer), ('UserName', username),
                                          ('Password', password)], unsafe=False)
        self._check(result, unsafe=False)
        session = (result.findtext('{*}SessionID') or '').strip()
        if not session:
            raise UpsError('error', 'Login', 'UPS oturumu açılamadı (oturum kimliği boş).')
        self._secrets.append(session)
        return session

    # ------------------------------------------------------------------ işlemler
    def login(self):
        return self._login(self.ship_url, NS_SHIP, 'Login_Type1', self.username, self.password)

    def query_login(self):
        return self._login(URL_QUERY, NS_QUERY, 'Login_V1', self.track_username, self.track_password)

    def create_shipment(self, session, info, dimensions):
        """-> (takip no, [PNG bayt]). ``info``: SHIPMENT_INFO_FIELDS anahtarlı sözlük, ``dimensions``: paket başına sözlük."""
        unknown = set(info) - set(SHIPMENT_INFO_FIELDS)
        if unknown:
            raise UpsError('error', 'ValueError', 'UPS isteği hazırlanamadı (bilinmeyen alan).')
        shipment_info = [(name, None if name == 'DeliveryByTally' else info.get(name, ''))
                         for name in SHIPMENT_INFO_FIELDS]
        shipment_info.append(('PackageDimensions', [
            ('DimensionInfo', [(name, dim.get(name, '')) for name in DIMENSION_FIELDS]) for dim in dimensions]))
        result = self._call(self.ship_url, NS_SHIP, 'CreateShipment_Type3', [
            ('SessionID', session), ('ShipmentInfo', shipment_info),
            # NEDEN: ReturnLabelLink=false -> LabelKey'li bağlantı istenmez (K-23); etiket PNG olarak gelir.
            ('ReturnLabelLink', False), ('ReturnLabelImage', True)], unsafe=True)
        self._check(result, unsafe=True)
        tracking = (result.findtext('{*}ShipmentNo') or '').strip()
        if not tracking:
            raise UpsError('uncertain', 'ShipmentNo',
                           'UPS başarılı yanıt verdi ama takip numarası yok. Durumu kontrol edin.')
        # DIKKAT: yalnız BarkodArrayPng/string; LinkForLabelPrinting (LabelKey) okunmaz, saklanmaz.
        labels = []
        for node in result.iterfind('{*}BarkodArrayPng/{*}string'):
            try:
                data = base64.b64decode(re.sub(r'\s+', '', node.text or ''), validate=True)
            except (binascii.Error, ValueError):
                continue
            if data.startswith(PNG_MAGIC):
                labels.append(data)
        return tracking, labels

    def cancel(self, session, waybill):
        # NEDEN: Cancel_Shipment_V1 parametreleri WSDL'de küçük harfle başlar.
        result = self._call(self.ship_url, NS_SHIP, 'Cancel_Shipment_V1', [
            ('sessionId', session), ('customerCode', self.customer), ('waybillNumber', waybill)], unsafe=True)
        self._check(result, unsafe=True)

    def find_by_reference(self, session, reference):
        """-> farklı gönderi numaraları (sıralı). Boş liste = bulunamadı (belgesiz biçim: boş dizi varsayımı)."""
        result = self._call(URL_QUERY, NS_QUERY, 'GetPackageInfoByReferance_V1', [
            ('SessionID', session), ('InformationLevel', 1), ('Referance', reference)], unsafe=False)
        items = list(result.iterfind('{*}PackageInformation'))
        good = [item for item in items if _int(item.findtext('{*}ErrorCode')) == 0]
        if items and not good:
            definition = (items[0].findtext('{*}ErrorDefinition') or '').strip()
            raise UpsError('error', (items[0].findtext('{*}ErrorCode') or '').strip(),
                           self.scrub('UPS sorgu hatası: %s' % definition))
        numbers = []
        for item in good:
            # NEDEN: çok paketli gönderi paket başına bir öğe döner; gönderi = ShipmentNo.
            number = (item.findtext('{*}ShipmentNo') or item.findtext('{*}TrackingNumber') or '').strip()
            if not number:
                # NEDEN: kayıt var ama numarasız; "bulunamadı" demek mükerrer gönderiye yol açar.
                raise UpsError('error', 'XML', 'UPS sorgu yanıtında gönderi numarası yok.')
            if number not in numbers:
                numbers.append(number)
        return numbers

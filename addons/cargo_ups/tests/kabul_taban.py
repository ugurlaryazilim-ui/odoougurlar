# -*- coding: utf-8 -*-
"""cargo_ups A1 KABUL testleri ortak tabani (test-muhendisi; uygulama kodu degildir, silinmemeli).

SENTETIK UPS SOAP fikstur'lari: yapi tasarim 4.7'deki ornek zarflardan alinmistir, DEGERLERIN HEPSI UYDURMADIR
(gercek SessionID/LabelKey/hesap no/sifre yok). Sir sizintisi testleri icin bilerek taninabilir sentetik sirlar kullanilir.
"""
import base64

import requests
from lxml import etree

from odoo.addons.cargo.tests.kabul_taban import CargoKabulCase, make_label_png

SECRETS = {
    'customer': '4817263', 'shipper': 'A1B2C3D4', 'user': 'kabul_ups_kullanici', 'password': 'KabulSifre!99',
    'track_user': 'kabul_takip_kullanici', 'track_password': 'TakipSifre!77', 'session': 'SESS-FAKE-0001',
}
NS_SHIP = 'https://ws.ups.com.tr/wsCreateShipment'
NS_QUERY = 'https://ws.ups.com.tr/wsPaketIslemSorgulamaEng/'
URL_LIVE = 'https://ws.ups.com.tr/wsCreateShipment/wsCreateShipment.asmx'
URL_TEST = 'https://ws.ups.com.tr/wsCreateShipmenttest/wsCreateShipment.asmx'
URL_QUERY = 'https://ws.ups.com.tr/QueryPackageInfo/wsQueryPackagesInfo.asmx'
LINK_WITH_KEY = 'https://ws.ups.com.tr/label/print?LabelKey=' + SECRETS['session'] + '&lang=tr'


def envelope(inner):
    return ('<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            '<soap:Body>%s</soap:Body></soap:Envelope>' % inner)


def login_ok(session=SECRETS['session']):
    return envelope('<Login_Type1Response xmlns="%s"><Login_Type1Result><SessionID>%s</SessionID><ErrorCode>0</ErrorCode>'
                    '<ErrorDefinition /></Login_Type1Result></Login_Type1Response>' % (NS_SHIP, session))


def login_err(code=100, text='Kullanici adi veya sifre hatali'):
    return envelope('<Login_Type1Response xmlns="%s"><Login_Type1Result><SessionID /><ErrorCode>%s</ErrorCode>'
                    '<ErrorDefinition>%s</ErrorDefinition></Login_Type1Result></Login_Type1Response>' % (NS_SHIP, code, text))


def create_ok(n=1, tracking='1ZFIXTURE0001', link=LINK_WITH_KEY):
    pngs = ''.join('<string>%s</string>' % base64.b64encode(make_label_png(i)).decode() for i in range(n))
    return envelope('<CreateShipment_Type3Response xmlns="%s"><CreateShipment_Type3Result><ShipmentNo>%s</ShipmentNo>'
                    '<LinkForLabelPrinting>%s</LinkForLabelPrinting><BarkodArrayPng>%s</BarkodArrayPng>'
                    '<DiagnosticArray><string>BU-PNG-DEGIL</string></DiagnosticArray>'
                    '<ErrorCode>0</ErrorCode><ErrorDefinition /></CreateShipment_Type3Result></CreateShipment_Type3Response>'
                    % (NS_SHIP, tracking, link.replace('&', '&amp;'), pngs))


def create_err(code=12345, text='Alici adresi hatali (fixture)'):
    return envelope('<CreateShipment_Type3Response xmlns="%s"><CreateShipment_Type3Result><ShipmentNo /><LinkForLabelPrinting />'
                    '<BarkodArrayPng /><ErrorCode>%s</ErrorCode><ErrorDefinition>%s</ErrorDefinition>'
                    '</CreateShipment_Type3Result></CreateShipment_Type3Response>' % (NS_SHIP, code, text))


def cancel_result(code=0, text=''):
    return envelope('<Cancel_Shipment_V1Response xmlns="%s"><Cancel_Shipment_V1Result><ErrorCode>%s</ErrorCode>'
                    '<ErrorDefinition>%s</ErrorDefinition></Cancel_Shipment_V1Result></Cancel_Shipment_V1Response>'
                    % (NS_SHIP, code, text))


def soap_fault():
    return envelope('<soap:Fault><faultcode>soap:Server</faultcode><faultstring>Sunucu istegi isleyemedi (fixture)'
                    '</faultstring></soap:Fault>')


def query_login_ok(session=SECRETS['session']):
    return envelope('<Login_V1Response xmlns="%s"><Login_V1Result><SessionID>%s</SessionID><ErrorCode>0</ErrorCode>'
                    '<ErrorDefinition /></Login_V1Result></Login_V1Response>' % (NS_QUERY, session))


def query_packages(items):
    """items: [(tracking, shipment_no, reference)] ; bos liste = bulunamadi (belgesiz bicim: bos dizi varsayimi)."""
    body = ''.join('<PackageInformation><TrackingNumber>%s</TrackingNumber><ShipmentNo>%s</ShipmentNo>'
                   '<CustomerReferance>%s</CustomerReferance><ErrorCode>0</ErrorCode></PackageInformation>' % item
                   for item in items)
    return envelope('<GetPackageInfoByReferance_V1Response xmlns="%s"><GetPackageInfoByReferance_V1Result>%s'
                    '</GetPackageInfoByReferance_V1Result></GetPackageInfoByReferance_V1Response>' % (NS_QUERY, body))


def query_error(code=55, text='Sorgu hatasi (fixture)'):
    return envelope('<GetPackageInfoByReferance_V1Response xmlns="%s"><GetPackageInfoByReferance_V1Result>'
                    '<PackageInformation><ErrorCode>%s</ErrorCode><ErrorDefinition>%s</ErrorDefinition></PackageInformation>'
                    '</GetPackageInfoByReferance_V1Result></GetPackageInfoByReferance_V1Response>' % (NS_QUERY, code, text))


def make_response(body, status=200):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode('utf-8') if isinstance(body, str) else body
    response.headers['Content-Type'] = 'text/xml; charset=utf-8'
    response.encoding = 'utf-8'
    return response


def parse(request):
    body = request['body'] if isinstance(request, dict) else request.body
    if isinstance(body, str):
        body = body.encode('utf-8')
    return etree.fromstring(body)


def find_all(root, name):
    return root.xpath('//*[local-name()="%s"]' % name)


def find_text(root, name, default=None):
    nodes = find_all(root, name)
    return (nodes[0].text or '') if nodes else default


def operation(request):
    action = request['headers'].get('SOAPAction') or request['headers'].get('soapaction') or ''
    return action.strip('"').rsplit('/', 1)[-1]


class UpsCase(CargoKabulCase):
    """cargo + cargo_ups kurulu; sahte HTTP yonlendiricisi + gercek ups_tr saglayicisi (sahte saglayici yok)."""
    PROVIDER_TYPES = ()

    @classmethod
    def _eksik_parcalar(cls):
        eksik = super()._eksik_parcalar()
        if 'delivery.carrier' in cls.env.registry:
            selection = dict(cls.env['delivery.carrier']._fields['delivery_type'].selection)
            if 'ups_tr' not in selection:
                eksik.append("delivery_type 'ups_tr' (cargo_ups) tanimli degil")
        return eksik

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.ups = cls.env['delivery.carrier'].create({
            'name': 'KK UPS Test', 'delivery_type': 'ups_tr', 'product_id': cls._service_product().id,
            'integration_level': 'rate', 'prod_environment': False,
            'ups_tr_customer_number': SECRETS['customer'], 'ups_tr_shipper_account': SECRETS['shipper'],
            'ups_tr_username': SECRETS['user'], 'ups_tr_password': SECRETS['password'],
            'ups_tr_track_username': SECRETS['track_user'], 'ups_tr_track_password': SECRETS['track_password'],
            'cargo_cod_enabled': True,
        })
        cls.company.cargo_default_carrier_id = cls.ups
        Area = cls.env['cargo.area']
        cls.ups_cankaya = Area._match('ups_tr', cls.st('06'), 'Cankaya')
        cls.ups_kadikoy = Area._match('ups_tr', cls.st('34'), 'Kadikoy')

    def setUp(self):
        super().setUp()
        self.plan = {}        # op -> callable(request_dict) -> Response | str(body) | Exception
        self.net.router = self.route

    def route(self, prepared, **kwargs):
        request = self.net.requests[-1]
        url = request['url']
        if url not in (URL_LIVE, URL_TEST, URL_QUERY):
            self.net.unexpected.append(url)
            raise AssertionError('beklenmeyen UPS ucu: %s' % url)
        op = operation(request)
        # NEDEN: requests.Response 4xx/5xx'te falsy (__bool__ = .ok); `or` planlı hata yanıtını yutardı.
        handler = self.plan[op] if op in self.plan else self.default(op, request)
        result = handler(request) if callable(handler) else handler
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, str):
            result = make_response(result)
        return result

    def default(self, op, request):
        if op == 'Login_Type1':
            return login_ok()
        if op == 'CreateShipment_Type3':
            return create_ok(n=len(find_all(parse(request), 'DimensionInfo')))
        if op == 'Cancel_Shipment_V1':
            return cancel_result()
        if op == 'Login_V1':
            return query_login_ok()
        if op == 'GetPackageInfoByReferance_V1':
            return query_packages([])
        raise AssertionError('tanimsiz UPS islemi: %r' % op)

    def ups_requests(self, op=None):
        return [r for r in self.net.requests if op is None or operation(r) == op]

    def ups_vals(self, **over):
        vals = self.vals(carrier_id=self.ups.id)
        vals.update(over)
        return vals

    def ups_sent(self, **over):
        shipment = self.mk(**{k: v for k, v in self.ups_vals(**over).items()})
        shipment.action_send()
        return shipment

# -*- coding: utf-8 -*-
"""G9: services/ups_soap istemcisi (Odoo'suz katman). Gerçek ağ yok: ``requests.Session.send`` yamalıdır."""
import base64
from unittest.mock import patch

import requests
from lxml import etree

from odoo.tests import BaseCase, tagged

from ..services import ups_soap
from ..services.ups_soap import NS_QUERY, NS_SHIP, UpsClient, UpsError, _scrub
from . import fixtures
from .kabul_taban import envelope, make_response

# WSDL'den (2026-10-24) bağımsız yazılmış beklenen sıra; servis sabitine bakılmaz.
WSDL_SHIPMENT_INFO = (
    'ShipperAccountNumber ShipperName ShipperContactName ShipperAddress ShipperCityCode ShipperAreaCode '
    'ShipperPostalCode ShipperPhoneNumber ShipperPhoneExtension ShipperMobilePhoneNumber ShipperEMail '
    'ShipperExpenseCode ConsigneeAccountNumber ConsigneeName ConsigneeContactName ConsigneeAddress '
    'ConsigneeCityCode ConsigneeAreaCode ConsigneePostalCode ConsigneePhoneNumber ConsigneePhoneExtension '
    'ConsigneeMobilePhoneNumber ConsigneeEMail ConsigneeExpenseCode ServiceLevel PaymentType PackageType '
    'NumberOfPackages CustomerReferance CustomerInvoiceNumber DeliveryNotificationEmail IdControlFlag '
    'PhonePrealertFlag SmsToShipper SmsToConsignee InsuranceValue InsuranceValueCurrency ValueOfGoods '
    'ValueOfGoodsCurrency ValueOfGoodsPaymentType DeliveryByTally ThirdPartyAccountNumber ThirdPartyExpenseCode '
    'PackageDimensions').split()
XSI_NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'
INFO = {'ShipperAccountNumber': 'HESAP12', 'ConsigneeName': 'Ali Veli', 'ConsigneeCityCode': 6,
        'ConsigneeAreaCode': 1234, 'NumberOfPackages': 1, 'ServiceLevel': '3', 'PaymentType': '2'}
DIM = {'DescriptionOfGoods': 'esya', 'Length': 0, 'Height': 0, 'Width': 0, 'Weight': '1.500'}
QUERY_OP = 'GetPackageInfoByReferance_V1'


def result_body(op, inner):
    ns = NS_QUERY if op in ('Login_V1', QUERY_OP) else NS_SHIP
    return envelope('<%sResponse xmlns="%s"><%sResult>%s</%sResult></%sResponse>' % (op, ns, op, inner, op, op))


def code_body(op, code, definition='UPS tanimi'):
    inner = '<ErrorCode>%s</ErrorCode><ErrorDefinition>%s</ErrorDefinition>' % (code, definition)
    if op == QUERY_OP:
        inner = '<PackageInformation>%s</PackageInformation>' % inner
    return result_body(op, inner)


def fault_response(faultcode, status=500):
    code = '<faultcode>%s</faultcode>' % faultcode if faultcode is not None else ''
    return make_response(envelope('<soap:Fault>%s<faultstring>red</faultstring></soap:Fault>' % code), status)


def fault12_response(value, status=500):
    # NEDEN: SOAP 1.2 Fault biçimi (Code/Value, Reason/Text); .asmx 1.2 ucunda böyle döner.
    return make_response(envelope('<soap:Fault><soap:Code><soap:Value>%s</soap:Value></soap:Code>'
                                  '<soap:Reason><soap:Text>red</soap:Text></soap:Reason></soap:Fault>' % value), status)


def local(node):
    return etree.QName(node).localname


class Net:
    """``requests.Session.send`` yaması; ``reply`` Response, str gövde ya da istisna."""

    def __init__(self, test):
        self.requests = []
        self.reply = None
        net = self

        def send(session, request, **kwargs):
            net.requests.append({'url': request.url, 'headers': dict(request.headers), 'body': request.body,
                                 'kwargs': kwargs})
            reply = net.reply(request) if callable(net.reply) else net.reply
            if isinstance(reply, BaseException):
                raise reply
            return make_response(reply) if isinstance(reply, str) else reply
        patcher = patch.object(requests.Session, 'send', send)
        patcher.start()
        test.addCleanup(patcher.stop)

    def root(self, index=-1):
        return etree.fromstring(self.requests[index]['body'])

    def operation_node(self, index=-1):
        return self.root(index).find('{*}Body')[0]


OPS = {
    'Login_Type1': (False, lambda c: c.login()),
    'CreateShipment_Type3': (True, lambda c: c.create_shipment('S-1', INFO, [DIM])),
    'Cancel_Shipment_V1': (True, lambda c: c.cancel('S-1', '1ZABC')),
    'Login_V1': (False, lambda c: c.query_login()),
    QUERY_OP: (False, lambda c: c.find_by_reference('S-1', 'KG/00001')),
}


@tagged('post_install', '-at_install', 'cargo_ups')
class TestUpsSoap(BaseCase):

    def setUp(self):
        super().setUp()
        self.net = Net(self)
        self.client = UpsClient('CUST123', 'g9kullanici', 'g9sifre', test_mode=True,
                                track_username='g9takip', track_password='g9takipsifre', masked=['HESAP12'])

    def test_zarf_login_ad_alani(self):
        self.net.reply = fixtures.LOGIN_RESPONSE
        self.assertEqual(self.client.login(), fixtures.FIXTURE_SESSION)
        node = self.net.operation_node()
        self.assertEqual(node.tag, '{%s}Login_Type1' % NS_SHIP)
        self.assertEqual(node.nsmap.get(None), NS_SHIP, 'işlem öğesi varsayılan ad alanında')
        self.assertEqual([(local(c), c.text) for c in node],
                         [('CustomerNumber', 'CUST123'), ('UserName', 'g9kullanici'), ('Password', 'g9sifre')])

    def test_zarf_create_wsdl_alan_sirasi(self):
        self.net.reply = fixtures.CREATE_RESPONSE
        self.client.create_shipment('S-1', INFO, [DIM, DIM])
        node = self.net.operation_node()
        self.assertEqual([local(c) for c in node], ['SessionID', 'ShipmentInfo', 'ReturnLabelLink', 'ReturnLabelImage'])
        self.assertEqual((node[2].text, node[3].text), ('false', 'true'), 'LabelKey bağlantısı istenmez (K-23)')
        info = node[1]
        self.assertEqual([local(c) for c in info], WSDL_SHIPMENT_INFO)
        tally = info.find('{*}DeliveryByTally')
        self.assertEqual((tally.get(XSI_NIL), tally.text), ('true', None))
        self.assertEqual(info.findtext('{*}ConsigneeAreaCode'), '1234')
        self.assertEqual(info.findtext('{*}CustomerReferance'), '', 'verilmeyen alan boş gider')
        dims = info.find('{*}PackageDimensions')
        self.assertEqual([local(c) for c in dims], ['DimensionInfo', 'DimensionInfo'])
        self.assertEqual([local(c) for c in dims[0]], ['DescriptionOfGoods', 'Length', 'Height', 'Width', 'Weight'])
        self.assertEqual(dims[0].findtext('{*}Weight'), '1.500')
        with self.assertRaises(UpsError) as ctx:
            self.client.create_shipment('S-1', dict(INFO, Bilinmeyen='x'), [DIM])
        self.assertEqual(ctx.exception.kind, 'error')

    def test_zarf_kacislama_ve_denetim_karakteri(self):
        self.net.reply = fixtures.CREATE_RESPONSE
        self.client.create_shipment('S-1', dict(INFO, ConsigneeAddress='A <b> & "c"\x0b\x00 d￾'), [DIM])
        body = self.net.requests[-1]['body']
        self.assertIsInstance(body, bytes)
        self.assertNotIn(b'<b>', body)
        self.assertEqual(self.net.root().findtext('.//{*}ConsigneeAddress'), 'A <b> & "c" d')

    def test_cancel_kucuk_harf_parametreler(self):
        self.net.reply = code_body('Cancel_Shipment_V1', 0, '')
        self.client.cancel('S-1', '1ZABC')
        node = self.net.operation_node()
        self.assertEqual(node.tag, '{%s}Cancel_Shipment_V1' % NS_SHIP)
        self.assertEqual([(local(c), c.text) for c in node],
                         [('sessionId', 'S-1'), ('customerCode', 'CUST123'), ('waybillNumber', '1ZABC')])

    def test_soapaction_ve_uc_secimi(self):
        live = UpsClient('C', 'u', 'p', test_mode=False)
        cases = (
            (self.client, 'Login_Type1', lambda c: c.login(), ups_soap.URL_SHIP_TEST, NS_SHIP + '/Login_Type1'),
            (live, 'Login_Type1', lambda c: c.login(), ups_soap.URL_SHIP_LIVE, NS_SHIP + '/Login_Type1'),
            (live, 'Cancel_Shipment_V1', lambda c: c.cancel('S', 'T'), ups_soap.URL_SHIP_LIVE,
             NS_SHIP + '/Cancel_Shipment_V1'),
            # NEDEN: sorgu servisi tek uçludur; test modundaki istemci de aynı uca gider (çağıran engeller).
            (self.client, 'Login_V1', lambda c: c.query_login(), ups_soap.URL_QUERY, NS_QUERY + 'Login_V1'),
            (live, QUERY_OP, lambda c: c.find_by_reference('S', 'R'), ups_soap.URL_QUERY, NS_QUERY + QUERY_OP),
        )
        for client, op, call, url, action in cases:
            with self.subTest(op=op, url=url):
                self.net.reply = (result_body(op, '') if op == QUERY_OP else
                                  code_body(op, 0, '').replace('<ErrorCode>', '<SessionID>S</SessionID><ErrorCode>', 1))
                call(client)
                request = self.net.requests[-1]
                self.assertEqual(request['url'], url)
                self.assertEqual(request['headers']['SOAPAction'], '"%s"' % action)
                self.assertEqual(request['headers']['Content-Type'], 'text/xml; charset=utf-8')
                self.assertEqual(request['kwargs']['timeout'], (5, 25))
                self.assertFalse(request['kwargs']['allow_redirects'])
        self.assertEqual(self.net.operation_node().tag, '{%s}%s' % (NS_QUERY, QUERY_OP))
        self.assertEqual(self.net.operation_node().findtext('{*}InformationLevel'), '1')

    def test_gercek_ornek_yanit_fiksturu(self):
        """UPS örnek dökümünün yapısı: girintili, boş ErrorDefinition, &amp;'lı bağlantı, tek PNG."""
        self.net.reply = fixtures.CREATE_RESPONSE
        tracking, labels = self.client.create_shipment('S-1', INFO, [DIM])
        self.assertEqual(tracking, fixtures.FIXTURE_SHIPMENT_NO)
        self.assertEqual(labels, [base64.b64decode(fixtures.TINY_PNG_B64)])
        self.assertTrue(labels[0].startswith(ups_soap.PNG_MAGIC))
        for text in (fixtures.LOGIN_RESPONSE, fixtures.CREATE_RESPONSE):
            self.assertNotIn('LabelKey', text, 'fikstür sır taşımaz')
            self.assertIsNone(ups_soap._GUID.search(text))

    def test_siniflandirma_matrisi(self):
        """Tasarım §1.3 / sözleşme §4: işlem x gözlem -> error | uncertain."""
        other_op = result_body('BaskaIslem', '<ErrorCode>0</ErrorCode>')
        observations = {
            'ConnectTimeout': (requests.ConnectTimeout('x'), 'error'),
            'ReadTimeout': (requests.ReadTimeout('x'), 'unsafe'),
            'ConnectionError': (requests.ConnectionError('x'), 'unsafe'),
            'SSLError': (requests.exceptions.SSLError('x'), 'unsafe'),
            'RuntimeError': (RuntimeError('x'), 'unsafe'),
            # K-27: yalnız istemci Fault'u (Client / 1.2 Sender) error; Server, bilinmeyen ve kodsuz Fault belirsiz.
            'Fault Client 500': (fault_response('soap:Client'), 'error'),
            'Fault Client alt kod 500': (fault_response('soap:Client.Authentication'), 'error'),
            'Fault Client 200': (fault_response('soap:Client', 200), 'error'),
            'Fault 1.2 Sender': (fault12_response('soap:Sender'), 'error'),
            'Fault Server 500': (fault_response('soap:Server'), 'unsafe'),
            'Fault Server 200': (fault_response('soap:Server', 200), 'unsafe'),
            'Fault 1.2 Receiver': (fault12_response('soap:Receiver'), 'unsafe'),
            'Fault bilinmeyen kod': (fault_response('soap:Baska'), 'unsafe'),
            'Fault kodsuz 500': (fault_response(None), 'unsafe'),
            'Fault ClientX benzeri': (fault_response('soap:Clientish'), 'unsafe'),
            '502 govdesiz': (make_response('', 502), 'unsafe'),
            '503 html': (make_response('<html>Service Unavailable</html>', 503), 'unsafe'),
            '302': (make_response('', 302), 'unsafe'),
            'bos 200': (make_response('', 200), 'unsafe'),
            'bozuk 200': (make_response('<soap:Envelope><bozuk', 200), 'unsafe'),
            'Result yok': (make_response(other_op, 200), 'unsafe'),
        }
        for op, (unsafe, call) in OPS.items():
            observations_op = dict(observations)
            observations_op['ErrorCode okunamaz'] = (code_body(op, 'abc'), 'error' if op == QUERY_OP else 'unsafe')
            observations_op['ErrorCode 12'] = (code_body(op, 12, 'Adres <hatali>'.replace('<', '&lt;')), 'error')
            for name, (reply, expected) in observations_op.items():
                with self.subTest(op=op, gozlem=name):
                    self.net.reply = reply
                    with self.assertRaises(UpsError) as ctx:
                        call(self.client)
                    kind = ('uncertain' if unsafe else 'error') if expected == 'unsafe' else expected
                    self.assertEqual(ctx.exception.kind, kind)
                    if name == 'ErrorCode 12':
                        self.assertEqual(ctx.exception.code, '12')
                        self.assertIn('Adres <hatali>', ctx.exception.message)
                    if name.startswith('Fault'):
                        self.assertEqual(ctx.exception.code, 'SOAP Fault')
                        self.assertIn('red', ctx.exception.message)
                    self.assertNotIn("'x'", ctx.exception.message, 'istisna metni mesaja girmez')

    def test_basarili_yanit_kenar_durumlari(self):
        cases = (
            ('Login_Type1', result_body('Login_Type1', '<SessionID /><ErrorCode>0</ErrorCode>'), 'error'),
            ('CreateShipment_Type3', result_body('CreateShipment_Type3', '<ShipmentNo /><ErrorCode>0</ErrorCode>'),
             'uncertain'),
        )
        for op, body, kind in cases:
            with self.subTest(op=op):
                self.net.reply = body
                with self.assertRaises(UpsError) as ctx:
                    OPS[op][1](self.client)
                self.assertEqual(ctx.exception.kind, kind)
        item = '<PackageInformation><TrackingNumber>%s</TrackingNumber><ShipmentNo>%s</ShipmentNo><ErrorCode>%s</ErrorCode></PackageInformation>'
        self.net.reply = result_body(QUERY_OP, '')
        self.assertEqual(self.client.find_by_reference('S', 'R'), [], 'boş dizi = bulunamadı')
        self.net.reply = result_body(QUERY_OP, item % ('1ZP1', '1ZG', 0) + item % ('1ZP2', '1ZG', 0)
                                     + item % ('', '', 7) + item % ('1ZT', '', 0))
        self.assertEqual(self.client.find_by_reference('S', 'R'), ['1ZG', '1ZT'],
                         'paket başına öğe tek gönderi; hatalı öğe atlanır; ShipmentNo yoksa takip no')
        self.net.reply = result_body(QUERY_OP, item % ('', '', 0))
        with self.assertRaises(UpsError, msg='numarasız kayıt bulunamadı sayılmaz') as ctx:
            self.client.find_by_reference('S', 'R')
        self.assertEqual(ctx.exception.kind, 'error')

    def test_scrub(self):
        secrets = ['Sifre!9', 'kullanici', '', 'ab']
        text = ('Kullanici sifre!9 hata; https://x/Barcode.aspx?ShipmentNo=1&LabelKey=abc ok '
                'oturum 3f2504e0-4f89-11d3-9a0c-0305e82c3301 musteri 4817263 hesap a1b2c3d4 ab')
        out = _scrub(text, secrets, masked=['4817263', 'A1B2C3D4', None])
        for gone in ('sifre!9', 'Kullanici', 'LabelKey', 'Barcode.aspx', '3f2504e0', '48172', 'a1b2c3'):
            self.assertNotIn(gone.lower(), out.lower())
        self.assertIn('***63', out)
        self.assertIn('***D4', out, 'son 2 hane kayıtlı değerden')
        self.assertIn(' ab', out, 'kısa değer silinmez (metni bozmasın)')
        self.assertEqual(len(_scrub('x' * 2000)), ups_soap.SCRUB_MAX)
        self.assertEqual(_scrub(None), '')
        self.assertEqual(_scrub('Login: SessionID=SESS-77 gecersiz; Oturum süresi doldu'),
                         'Login: SessionID=*** gecersiz; Oturum süresi doldu', 'bilinmeyen oturum kimliği de gizlenir')
        # oturum kimliği Login sonrası sır listesine girer
        self.net.reply = fixtures.LOGIN_RESPONSE
        self.client.login()
        self.assertNotIn(fixtures.FIXTURE_SESSION, self.client.scrub('oturum %s' % fixtures.FIXTURE_SESSION))

    def test_yanit_bayt_ve_bildirimli(self):
        """Bildirimli yanıt bayt olarak ayrıştırılır (str + bildirim lxml'de ValueError olurdu); utf-16 da okunur."""
        login = fixtures.LOGIN_RESPONSE
        self.net.reply = make_response(login.replace('utf-8', 'utf-16').encode('utf-16'))
        self.assertEqual(self.client.login(), fixtures.FIXTURE_SESSION)
        self.net.reply = make_response(code_body('Login_Type1', 3, 'Şifre İptal').encode('utf-8'))
        with self.assertRaises(UpsError) as ctx:
            self.client.login()
        self.assertIn('Şifre İptal', ctx.exception.message)

    def test_xxe_entity_cozulmez(self):
        body = ('<?xml version="1.0" encoding="utf-8"?><!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">'
                '<!ENTITY ic "GENISLEDI">]>' + code_body('Login_Type1', 9, 'a&xxe;b&ic;c').split('?>', 1)[1])
        self.net.reply = make_response(body)
        with self.assertRaises(UpsError) as ctx:
            self.client.login()
        self.assertNotIn('root:', ctx.exception.message)
        self.assertNotIn('GENISLEDI', ctx.exception.message)

# -*- coding: utf-8 -*-
"""KABUL: UPS SOAP istemcisi (cargo_ups) - KK-3, KK-6, KK-9, KK-10, KK-16, KK-17, KK-23 (UPS tarafi).

Tum UPS cagrilari ``requests.Session.send`` seviyesinde SENTETIK yanitlarla yakalanir (``kabul_taban.UpsCase``);
gercek UPS'e HICBIR cagri gitmez. Yesile donecegi gorev: G9 (UPS SOAP), G8'e (iskelet/1014 veri) bagli.

Test edilen sey ``services/ups_soap.py`` ic ayrintisi degil, DISARI giden zarf ve geri donen gonderi durumudur.
"""
import base64
import logging

import requests
from odoo.exceptions import UserError
from odoo.tests import tagged

from .kabul_taban import (
    LINK_WITH_KEY, SECRETS, URL_LIVE, URL_QUERY, URL_TEST, UpsCase, cancel_result, create_err, create_ok, find_all,
    find_text, login_err, login_ok, make_label_png, make_response, operation, parse, query_error, query_packages,
    soap_fault,
)

SECRET_VALUES = [SECRETS[k] for k in ('password', 'user', 'track_password', 'track_user', 'session', 'customer', 'shipper')]


class LogTap:
    """Tum loglari (DEBUG dahil) toplar; kabul testi log sizintisi icin."""

    NAMES = ('', 'odoo', 'odoo.addons', 'odoo.addons.cargo', 'odoo.addons.cargo_ups')

    def __enter__(self):
        self.lines = []
        tap = self

        class Handler(logging.Handler):
            def emit(self, record):
                tap.lines.append(logging.Formatter().format(record))
        self.handler = Handler(level=logging.DEBUG)
        self.saved = {}
        for name in self.NAMES:
            logger = logging.getLogger(name)
            self.saved[name] = logger.level
            logger.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self.handler)
        for name, level in self.saved.items():
            logging.getLogger(name).setLevel(level)
        return False

    @property
    def text(self):
        return '\n'.join(self.lines)


class UpsBase(UpsCase):
    """Ortak yardimcilar."""

    def create_root(self, index=-1):
        return parse(self.ups_requests('CreateShipment_Type3')[index])

    def all_text(self, shipment):
        """Sizinti taramasi icin gonderinin gorunen her yeri (alanlar, chatter, ek adlari)."""
        shipment = shipment.sudo()
        parts = [str(shipment.read()), self.chatter(shipment)]
        for attachment in self.attachments(shipment):
            parts.append('%s %s' % (attachment.name, attachment.mimetype))
        return '\n'.join(parts)

    def assert_no_secrets(self, text, msg=''):
        for secret in SECRET_VALUES:
            self.assertNotIn(secret, text, 'sir sizdi (%s): %r' % (msg, secret))
        self.assertNotIn('LabelKey', text, 'LabelKey sizdi (%s)' % msg)
        self.assertNotIn(LINK_WITH_KEY, text, 'LinkForLabelPrinting sizdi (%s)' % msg)

    def send_with(self, plan=None, **over):
        self.plan.update(plan or {})
        shipment = self.mk(**self.ups_vals(**over))
        shipment.action_send()
        return shipment


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsOlusturma(UpsBase):

    def test_islem_sirasi_ve_basari(self):
        """KK-6: Login_Type1 -> CreateShipment_Type3; takip no, paket basina PNG, PDF; test ucu."""
        shipment = self.send_with(package_count=2)
        self.assertEqual([operation(r) for r in self.net.requests], ['Login_Type1', 'CreateShipment_Type3'])
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(shipment.tracking_ref, '1ZFIXTURE0001')
        self.assertTrue(shipment.test_mode, 'prod_environment kapali -> test gonderisi')
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_TEST})
        pngs = self.attachments(shipment, 'image/png')
        self.assertEqual(pngs.mapped('name'), ['%s-1.png' % shipment.name, '%s-2.png' % shipment.name])
        self.assertEqual(base64.b64decode(pngs[0].datas), make_label_png(0))
        self.assertTrue(shipment.label_pdf_id)
        self.assertEqual(base64.b64decode(shipment.label_pdf_id.datas)[:5], b'%PDF-')

    def test_canli_uc(self):
        self.ups.prod_environment = True
        shipment = self.send_with()
        self.assertEqual(shipment.state, 'created')
        self.assertFalse(shipment.test_mode)
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_LIVE})

    def test_http_ayrintilari(self):
        self.send_with()
        for request in self.net.requests:
            op = operation(request)
            self.assertEqual(request['method'], 'POST')
            self.assertEqual(request['headers'].get('Content-Type'), 'text/xml; charset=utf-8')
            self.assertEqual(request['headers'].get('SOAPAction'), '"https://ws.ups.com.tr/wsCreateShipment/%s"' % op)
            self.assertEqual(request['timeout'], (5, 25), op)

    def test_login_istegi(self):
        self.send_with()
        root = parse(self.ups_requests('Login_Type1')[0])
        self.assertEqual(find_text(root, 'CustomerNumber'), SECRETS['customer'])
        self.assertEqual(find_text(root, 'UserName'), SECRETS['user'])
        self.assertEqual(find_text(root, 'Password'), SECRETS['password'])
        self.assertEqual(find_all(root, 'Login_Type1')[0].nsmap.get(None), 'https://ws.ups.com.tr/wsCreateShipment')

    def test_gonderi_icerigi(self):
        shipment = self.send_with(package_count=2, package_weight=2.5)
        root = self.create_root()
        self.assertEqual(find_text(root, 'SessionID'), SECRETS['session'])
        self.assertEqual(find_text(root, 'ReturnLabelLink').lower(), 'false', 'LabelKey istenmez (K-23)')
        self.assertEqual(find_text(root, 'ReturnLabelImage').lower(), 'true')
        self.assertEqual(find_text(root, 'CustomerReferance'), shipment.name)
        self.assertEqual(find_text(root, 'ShipperAccountNumber'), SECRETS['shipper'])
        self.assertEqual(find_text(root, 'ConsigneeName'), 'Ali Veli')
        self.assertEqual(find_text(root, 'ConsigneeAddress'), 'Ataturk Mah. Gul Sk. No:5 D:3')
        self.assertEqual(find_text(root, 'ConsigneeAreaCode'), str(self.ups_cankaya.area_code))
        self.assertEqual(find_text(root, 'ConsigneeCityCode'), str(self.ups_cankaya.city_code))
        self.assertEqual(find_text(root, 'ShipperAreaCode'), str(self.ups_kadikoy.area_code), 'gonderici = sirket adresi (Kadikoy)')
        self.assertEqual(find_text(root, 'ShipperCityCode'), str(self.ups_kadikoy.city_code))
        self.assertEqual((find_text(root, 'ServiceLevel'), find_text(root, 'PaymentType'), find_text(root, 'PackageType')),
                         ('3', '2', 'K'), 'firma varsayilanlari')
        dims = find_all(root, 'DimensionInfo')
        self.assertEqual(len(dims), 2)
        self.assertEqual(find_text(root, 'NumberOfPackages'), '2')
        for dim in dims:
            self.assertGreater(float(find_text(dim, 'Weight')), 0.0)
        self.assertEqual(float(find_text(root, 'InsuranceValue') or 0), 0.0, 'ValueOfGoods sigorta beyani degildir')

    def test_odp_nakit(self):
        """KK-16: tutar 2 ondalik, TL, nakit = 1."""
        self.send_with(cod_amount=1249.9, cod_method='cash')
        root = self.create_root()
        self.assertEqual(find_text(root, 'ValueOfGoods'), '1249.90')
        self.assertEqual(find_text(root, 'ValueOfGoodsCurrency'), 'TL')
        self.assertEqual(find_text(root, 'ValueOfGoodsPaymentType'), '1')

    def test_odp_cek_ve_kart_kodlari(self):
        """check=2, card=3 (yonetici ilgili izni actiginda)."""
        self.ups.with_user(self.manager).write({'cargo_cod_allow_check': True, 'cargo_cod_allow_card': True})
        for method, code in (('check', '2'), ('card', '3')):
            with self.subTest(method=method):
                self.send_with(cod_amount=300.0, cod_method=method)
                self.assertEqual(find_text(self.create_root(), 'ValueOfGoodsPaymentType'), code)

    def test_odp_yok(self):
        """KK-17: tutar 0 -> ValueOfGoods 0, odeme tipi 0, para birimi bos."""
        for cod in (0.0, False):
            with self.subTest(cod=cod):
                self.send_with(cod_amount=cod)
                root = self.create_root()
                self.assertEqual(float(find_text(root, 'ValueOfGoods') or 0), 0.0)
                self.assertEqual(find_text(root, 'ValueOfGoodsPaymentType'), '0')
                self.assertFalse(find_text(root, 'ValueOfGoodsCurrency'))

    def test_telefon_cep_ve_sabit(self):
        cases = (('05321234567', 'ConsigneeMobilePhoneNumber', 'ConsigneePhoneNumber'),
                 ('5321234567', 'ConsigneeMobilePhoneNumber', 'ConsigneePhoneNumber'),
                 ('02121234567', 'ConsigneePhoneNumber', 'ConsigneeMobilePhoneNumber'))
        for phone, filled, empty in cases:
            with self.subTest(phone=phone):
                self.send_with(recipient_phone=phone)
                root = self.create_root()
                digits = find_text(root, filled)
                self.assertTrue(digits and digits.endswith(phone[-10:]), '%s -> %s dolu olmali' % (phone, filled))
                self.assertLessEqual(len(digits), 16)
                self.assertFalse(find_text(root, empty), '%s -> %s bos olmali' % (phone, empty))

    def test_xml_kacislama(self):
        """Adres/ad alanindaki < & \" XML'i bozmaz ve aynen geri okunur."""
        street = 'Ataturk Mah. <A&B> Sk. "5" No:7'
        self.send_with(recipient_street=street)
        request = self.ups_requests('CreateShipment_Type3')[0]
        self.assertNotIn('<A&B>', request['body'], 'ham < & zarfa girmemeli')
        self.assertEqual(find_text(parse(request), 'ConsigneeAddress'), street)

    def test_barkod_yalniz_barkod_dizisinden(self):
        """Yanitta baska string dizileri olsa da yalniz BarkodArrayPng/string etiket olur."""
        shipment = self.send_with(package_count=3)
        self.assertEqual(len(self.attachments(shipment, 'image/png')), 3)
        for attachment in self.attachments(shipment):
            self.assertNotIn('BU-PNG-DEGIL', str(attachment.name))

    def test_gonderici_ilcesi_eslesmezse(self):
        """Tasarim 4.5/4.7: 'Sirket adresinin ilcesi eslesmedi' UserError; HTTP cagrisi yok."""
        self.company.city = 'Bilinmeyenilce'
        shipment = self.mk(**self.ups_vals())
        with self.assertRaisesRegex(UserError, 'Şirket adresinin ilçesi eşleşmedi'):
            shipment.action_send()
        self.assertEqual(self.net.requests, [])
        self.assertEqual(shipment.state, 'draft')

    def test_oturum_onbelleklenmez(self):
        """Her islemde yeniden Login; ikinci gonderi ikinci oturumu kullanir."""
        sessions = iter(['SESS-A-1', 'SESS-B-2'])
        self.plan['Login_Type1'] = lambda r: login_ok(next(sessions))
        self.send_with()
        self.send_with()
        self.assertEqual(len(self.ups_requests('Login_Type1')), 2)
        creates = self.ups_requests('CreateShipment_Type3')
        self.assertEqual([find_text(parse(r), 'SessionID') for r in creates], ['SESS-A-1', 'SESS-B-2'])


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsHataSiniflari(UpsBase):
    """KK-9/KK-10: hata siniflandirmasi (tasarim 1.3)."""

    def assert_outcome(self, plan, state, creates, msg):
        self.net.requests.clear()
        shipment = self.send_with(plan=plan)
        self.assertEqual(shipment.state, state, msg)
        self.assertEqual(len(self.ups_requests('CreateShipment_Type3')), creates, msg)
        return shipment

    def test_login_hatasi_error_ve_create_gitmez(self):
        shipment = self.assert_outcome({'Login_Type1': login_err(100, 'Kimlik reddedildi')}, 'failed', 0, 'Login ErrorCode')
        self.assertIn('Kimlik reddedildi', shipment.error_message)

    def test_login_tasima_hatalari_error(self):
        for exc in (requests.ConnectTimeout('x'), requests.ReadTimeout('x'), requests.ConnectionError('x')):
            with self.subTest(exc=type(exc).__name__):
                self.assert_outcome({'Login_Type1': exc}, 'failed', 0, 'Login tasima hatasi guvenli -> error')

    def test_login_5xx_error(self):
        self.assert_outcome({'Login_Type1': make_response('', 503)}, 'failed', 0, 'Login 503')

    def test_create_baglanti_kurulamadi_error(self):
        self.assert_outcome({'CreateShipment_Type3': requests.ConnectTimeout('baglanti yok')}, 'failed', 1, 'ConnectTimeout')

    def test_create_belirsiz_durumlar(self):
        cases = {
            'ReadTimeout': requests.ReadTimeout('yanit gelmedi'),
            'ConnectionError': requests.ConnectionError('koptu'),
            '502 govdesiz': make_response('', 502),
            '503 html': make_response('<html>Service Unavailable</html>', 503),
            'bozuk xml 200': make_response('<soap:Envelope><bozuk', 200),
            'bos govde 200': make_response('', 200),
            'beklenmeyen istisna': RuntimeError('beklenmeyen'),
        }
        for name, plan in cases.items():
            with self.subTest(name):
                shipment = self.assert_outcome({'CreateShipment_Type3': plan}, 'uncertain', 1, name)
                self.assertFalse(shipment.tracking_ref)

    def test_create_errorcode_error(self):
        shipment = self.assert_outcome({'CreateShipment_Type3': create_err(777, 'Alici adresi hatali (fixture)')}, 'failed', 1,
                                       'ErrorCode != 0')
        self.assertIn('Alici adresi hatali (fixture)', shipment.error_message)
        self.assertFalse(self.attachments(shipment, 'image/png'))

    def test_soap_fault_server_belirsiz(self):
        """K-27 (K-21'i daraltir): soap:Server Fault web metodu icindeki istisnadir; gonderi UPS'e yazildiktan
        sonra da olusabilir -> uncertain (eskiden failed: yeniden gonderim mukerrer gonderi acardi)."""
        shipment = self.assert_outcome({'CreateShipment_Type3': make_response(soap_fault(), 500)}, 'uncertain', 1,
                                       'SOAP Server Fault')
        self.assertIn('Sunucu istegi isleyemedi', shipment.error_message)
        self.assertFalse(shipment.tracking_ref)

    def test_soap_fault_client_error(self):
        """K-27: soap:Client Fault = istek okunamadi, islenmedi -> failed (yeniden gonderim guvenli)."""
        shipment = self.assert_outcome({'CreateShipment_Type3': make_response(soap_fault('soap:Client'), 500)}, 'failed',
                                       1, 'SOAP Client Fault')
        self.assertIn('Sunucu istegi isleyemedi', shipment.error_message)

    def test_odp_server_fault_ikinci_gonderi_acilmaz(self):
        """K-27: canli ucta kapida odemeli gonderide Server Fault sonrasi ikinci Create gitmez (cift tahsilat
        riski); gonderi UPS'te acilmissa uzlastirma onu bulur."""
        self.ups.prod_environment = True
        shipment = self.send_with(plan={'CreateShipment_Type3': make_response(soap_fault(), 500)},
                                  cod_amount=1249.9, cod_method='cash')
        self.assertEqual(shipment.state, 'uncertain')
        self.assertEqual(find_text(self.create_root(), 'ValueOfGoods'), '1249.90', 'ODP gonderisi')
        self.plan.pop('CreateShipment_Type3')
        for action in (shipment.action_send, shipment.action_reconcile):
            with self.subTest(action=action.__name__):
                self.try_call(action)
                self.assertEqual(len(self.ups_requests('CreateShipment_Type3')), 1, 'ikinci Create gitmemeli')
                self.assertEqual(shipment.state, 'uncertain', 'bulunamadi + 15 dk\'dan genc: uncertain kalir')
        self.plan['GetPackageInfoByReferance_V1'] = lambda r: query_packages(
            [('1ZSERVERFAULT1', '1ZSERVERFAULT1', find_text(parse(r), 'Referance'))])
        shipment.action_reconcile()
        self.assertEqual((shipment.state, shipment.tracking_ref), ('created', '1ZSERVERFAULT1'))
        self.assertEqual(len(self.ups_requests('CreateShipment_Type3')), 1)

    def test_basarili_yanit_etiketsiz_failed_olmaz(self):
        """ErrorCode 0 ama barkod yok (VARSAYIM: tasarimda belgesiz): gonderi UPS'te acilmistir -> 'failed' OLMAMALI
        (yeniden gonderim mukerrer gonderi acar). created ya da uncertain kabul."""
        body = create_ok(n=1).replace('<BarkodArrayPng>', '<BarkodArrayPngX>').replace('</BarkodArrayPng>', '</BarkodArrayPngX>')
        self.plan['CreateShipment_Type3'] = body
        shipment = self.send_with()
        self.assertIn(shipment.state, ('created', 'uncertain'), 'barkodsuz basarili yanit failed olmamali')
        self.assertFalse(self.attachments(shipment, 'image/png'))

    def test_belirsiz_gonderi_yeniden_gonderilmez(self):
        shipment = self.send_with(plan={'CreateShipment_Type3': requests.ReadTimeout('x')})
        self.assertEqual(shipment.state, 'uncertain')
        before = len(self.net.requests)
        self.try_call(shipment.action_send)
        self.assertEqual(len(self.net.requests), before, 'uncertain durumda UPS\'e yeni cagri gitmemeli')
        self.assertEqual(shipment.state, 'uncertain')


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsSirlar(UpsBase):
    """KK-3: log, chatter, kayit ve hata metni sir icermez."""

    def test_basarili_cagri_sizdirmaz(self):
        with LogTap() as logs:
            shipment = self.send_with(package_count=2)
        self.assertEqual(shipment.state, 'created')
        self.assert_no_secrets(logs.text, 'log')
        self.assert_no_secrets(self.all_text(shipment), 'kayit')
        # yanit tekrar okunmamis olmali: LinkForLabelPrinting hicbir alanda yok
        self.assertNotIn('label/print', self.all_text(shipment))

    def test_hatali_cagrilar_sizdirmaz(self):
        leaky = ('Kullanici %(user)s sifre %(password)s musteri %(customer)s hesap %(shipper)s oturum %(session)s '
                 'takip %(track_user)s %(track_password)s' % SECRETS)
        plans = (
            {'Login_Type1': login_err(5, leaky)},
            {'CreateShipment_Type3': create_err(9, leaky + ' ' + LINK_WITH_KEY)},
            {'CreateShipment_Type3': make_response(soap_fault().replace('Sunucu istegi', leaky), 500)},
            {'CreateShipment_Type3': requests.ReadTimeout(leaky)},
            {'CreateShipment_Type3': RuntimeError(leaky)},
        )
        for plan in plans:
            with self.subTest(plan=list(plan)[0]):
                self.plan.clear()
                with LogTap() as logs:
                    shipment = self.send_with(plan=plan)
                self.assertIn(shipment.state, ('failed', 'uncertain'))
                self.assert_no_secrets(logs.text, 'log')
                self.assert_no_secrets(self.all_text(shipment), 'kayit/chatter/hata')

    def test_iptal_ve_sorgu_sizdirmaz(self):
        self.ups.prod_environment = True
        shipment = self.send_with()
        self.plan['Cancel_Shipment_V1'] = lambda r: cancel_result(4, 'hata ' + SECRETS['password'] + ' ' + SECRETS['session'])
        with LogTap() as logs:
            self.try_call(shipment.action_cancel)
        self.assert_no_secrets(logs.text, 'iptal log')
        self.assert_no_secrets(self.all_text(shipment), 'iptal kayit')
        uncertain = self.send_with(plan={'CreateShipment_Type3': requests.ReadTimeout('x')})
        self.plan['GetPackageInfoByReferance_V1'] = make_response(query_error(5, 'q ' + SECRETS['track_password']))
        with LogTap() as logs:
            self.try_call(uncertain.action_reconcile)
        self.assert_no_secrets(logs.text, 'sorgu log')
        self.assert_no_secrets(self.all_text(uncertain), 'sorgu kayit')

    def test_musteri_hesap_no_en_fazla_son_iki_hane(self):
        """Chatter/hata metninde hesap numaralari maskeli: tam deger yok (son 2 hane gorunebilir)."""
        shipment = self.send_with(plan={'CreateShipment_Type3': create_err(9, 'Hesap %s hatali' % SECRETS['shipper'])})
        text = self.all_text(shipment)
        for key in ('customer', 'shipper'):
            self.assertNotIn(SECRETS[key], text)
            self.assertNotIn(SECRETS[key][:-2], text, 'yalniz son 2 hane gorunebilir (%s)' % key)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsIptal(UpsBase):
    """KK-23 (UPS tarafi)."""

    def test_iptal_istegi_ve_sonuc(self):
        shipment = self.send_with()
        self.net.requests.clear()
        shipment.action_cancel()
        self.assertEqual([operation(r) for r in self.net.requests], ['Login_Type1', 'Cancel_Shipment_V1'])
        root = parse(self.ups_requests('Cancel_Shipment_V1')[0])
        self.assertEqual(find_text(root, 'sessionId'), SECRETS['session'], 'kucuk harfli parametre adlari (WSDL)')
        self.assertEqual(find_text(root, 'customerCode'), SECRETS['customer'])
        self.assertEqual(find_text(root, 'waybillNumber'), '1ZFIXTURE0001')
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_TEST}, 'test modu -> test ucu')
        self.assertEqual(shipment.state, 'cancelled')

    def test_iptal_errorcode_durum_degismez(self):
        shipment = self.send_with()
        self.plan['Cancel_Shipment_V1'] = cancel_result(41, 'Gonderi kargoya verilmis (fixture)')
        _result, error = self.try_call(shipment.action_cancel)
        self.assertEqual(shipment.state, 'created')
        shown = (str(error) if error else '') + self.chatter(shipment) + (shipment.error_message or '')
        self.assertIn('Gonderi kargoya verilmis (fixture)', shown, 'UPS hata metni kullaniciya gosterilmeli')

    def test_iptal_tasima_hatasi_durum_degismez(self):
        shipment = self.send_with()
        for exc in (requests.ReadTimeout('x'), requests.ConnectTimeout('x')):
            with self.subTest(exc=type(exc).__name__):
                self.plan['Cancel_Shipment_V1'] = exc
                self.try_call(shipment.action_cancel)
                self.assertEqual(shipment.state, 'created', 'iptal belirsiz/basarisiz: cancelled yazilmamali')

    def test_iptal_soap_fault_siniflari(self):
        """K-27: iptalde Server Fault belirsiz, Client Fault hata; ikisinde de cancelled yazilmaz, metin gorunur."""
        shipment = self.send_with()
        for faultcode in ('soap:Server', 'soap:Client'):
            with self.subTest(faultcode=faultcode):
                self.plan['Cancel_Shipment_V1'] = make_response(soap_fault(faultcode), 500)
                _result, error = self.try_call(shipment.action_cancel)
                self.assertEqual(shipment.state, 'created')
                shown = (str(error) if error else '') + self.chatter(shipment) + (shipment.error_message or '')
                self.assertIn('Sunucu istegi isleyemedi', shown)
        self.assertEqual(self.ups.ups_tr_cargo_cancel(shipment)['status'], 'error', 'Client Fault -> error')
        self.plan['Cancel_Shipment_V1'] = make_response(soap_fault(), 500)
        self.assertEqual(self.ups.ups_tr_cargo_cancel(shipment)['status'], 'uncertain', 'Server Fault -> uncertain')

    def test_iptal_login_hatasi(self):
        shipment = self.send_with()
        self.plan['Login_Type1'] = login_err(100, 'Kimlik reddedildi')
        self.try_call(shipment.action_cancel)
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.ups_requests('Cancel_Shipment_V1'), [])

    def test_kargoya_verilmis_iptal_edilmez(self):
        """KK-24: dis cagri yok."""
        shipment = self.send_with()
        shipment.sudo().write({'state': 'in_transit'})
        self.net.requests.clear()
        with self.assertRaisesRegex(UserError, 'Kargoya verilmiş gönderi iptal edilemez'):
            shipment.action_cancel()
        self.assertEqual(self.net.requests, [])


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsUzlastirma(UpsBase):
    """KK-10: uzlastirma (GetPackageInfoByReferance_V1; yalniz canli uc)."""

    def uncertain(self):
        shipment = self.send_with(plan={'CreateShipment_Type3': requests.ReadTimeout('x')})
        self.assertEqual(shipment.state, 'uncertain')
        self.net.requests.clear()
        return shipment

    def test_test_modunda_sorgu_yapilmaz(self):
        shipment = self.uncertain()
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual(result['status'], 'not_found')
        self.assertEqual(self.net.requests, [], 'sorgu servisinin test ucu yok -> HTTP yok')

    def test_test_modunda_genc_gonderi_belirsiz_kalir_eski_failed(self):
        shipment = self.uncertain()
        self.try_call(shipment.action_reconcile)
        self.assertEqual(shipment.state, 'uncertain', '15 dk\'dan genc: uncertain kalir')
        shipment.sudo().write({'sent_at': self.minutes_ago(20)})
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'failed', '15 dk\'dan eski ve bulunamadi: failed (yeniden gonderilebilir)')
        self.assertEqual(self.net.requests, [])

    def test_canli_bulundu(self):
        self.ups.prod_environment = True
        shipment = self.uncertain()
        self.plan['GetPackageInfoByReferance_V1'] = lambda r: query_packages(
            [('1ZRECON0001', '1ZRECON0001', find_text(parse(r), 'Referance'))])
        shipment.action_reconcile()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(shipment.tracking_ref, '1ZRECON0001')
        self.assertEqual([operation(r) for r in self.net.requests], ['Login_V1', 'GetPackageInfoByReferance_V1'])
        self.assertEqual({r['url'] for r in self.net.requests}, {URL_QUERY})
        root = parse(self.ups_requests('GetPackageInfoByReferance_V1')[0])
        self.assertEqual(find_text(root, 'Referance'), shipment.name)
        self.assertEqual(find_text(root, 'InformationLevel'), '1')
        login = parse(self.ups_requests('Login_V1')[0])
        self.assertEqual(find_text(login, 'UserName'), SECRETS['track_user'], 'takip kimligi kullanilir')
        self.assertEqual(find_text(login, 'Password'), SECRETS['track_password'])
        self.assertEqual(find_text(root, 'SessionID'), SECRETS['session'])

    def test_canli_takip_kimligi_bossa_gonderi_kimligi(self):
        self.ups.prod_environment = True
        self.ups.write({'ups_tr_track_username': False, 'ups_tr_track_password': False})
        shipment = self.uncertain()
        self.ups.ups_tr_cargo_find(shipment)
        login = parse(self.ups_requests('Login_V1')[0])
        self.assertEqual(find_text(login, 'UserName'), SECRETS['user'])
        self.assertEqual(find_text(login, 'Password'), SECRETS['password'])

    def test_canli_bulunamadi_bos_dizi(self):
        self.ups.prod_environment = True
        shipment = self.uncertain()
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual((result['status'], result.get('count', 0)), ('not_found', 0))

    def test_canli_birden_cok_kayit(self):
        self.ups.prod_environment = True
        shipment = self.uncertain()
        self.plan['GetPackageInfoByReferance_V1'] = query_packages([('1ZA', '1ZA', 'R'), ('1ZB', '1ZB', 'R')])
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual((result['status'], result['count'], result['tracking_ref']), ('found', 2, '1ZA'))

    def test_canli_sorgu_hatalari(self):
        self.ups.prod_environment = True
        shipment = self.uncertain()
        cases = (query_error(55, 'Sorgu hatasi (fixture)'), make_response('', 500), requests.ReadTimeout('x'),
                 requests.ConnectionError('x'))
        for plan in cases:
            with self.subTest(plan=str(type(plan).__name__)):
                self.plan['GetPackageInfoByReferance_V1'] = plan
                result = self.ups.ups_tr_cargo_find(shipment)
                self.assertEqual(result['status'], 'error')
                self.assertNotEqual(shipment.state, 'failed', 'sorgu hatasi gonderiyi failed yapmaz')

    def test_canli_login_hatasi_sorguda(self):
        self.ups.prod_environment = True
        shipment = self.uncertain()
        self.plan['Login_V1'] = make_response(login_err(100, 'Kimlik reddedildi').replace('Login_Type1', 'Login_V1'))
        result = self.ups.ups_tr_cargo_find(shipment)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.ups_requests('GetPackageInfoByReferance_V1'), [])

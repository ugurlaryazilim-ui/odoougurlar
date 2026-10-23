# -*- coding: utf-8 -*-
"""Mail Order kart sayfası Aşama 2: ``POST /sanal_pos/mail_order/bin`` ucu, CSP ``connect-src`` (B-1),
kapatma anahtarı (D-4) ve kart sayfası işaretleme sözleşmesi (KK-2.x, K-19).

Kaynak: .ekip/20261023-mo-kart-pro/01-gereksinimler.md, 02-tasarim.md §4, spike-bin-sonuc.md.
Gerçek HTTP (HttpCase.url_open) + taklit Paratika (QUERYBIN / QUERYPAYMENTSYSTEMS). Tüm BIN/PAN
değerleri herkese açık Paratika test değeridir; gerçek spike verisi yoktur.

Tarayıcı davranışı (betik, DOM, HAR, erişilebilirlik) burada SINANAMAZ: ``mail_order_card.test.mjs``
(node) ve ``04-kabul-testleri.md`` içindeki Playwright listesi (A2-G3/G4).
"""
import json
import re
import threading
import time
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg2
from lxml import html as lxml_html

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import config

from .common import (
    LEAK_BIN, LEAK_PAN, MAIL_ORDER_BIN_PATH, MAIL_ORDER_PAY_PATH, RawResponse, err_body, ok_body,
    paymentsystems_body, querybin_body, timeout_exc,
)
from .test_mail_order_card import CardPageCase, norm
from .test_mail_order_http import MoHttpCase

SCRIPT_ICP = 'sanal_pos.mail_order_script'
JSON_HEADERS = {'Content-Type': 'application/json'}
OK_KEYS = {'ok', 'card_type', 'foreign', 'bank', 'program', 'brand', 'detected', 'installments',
           'note', 'rows'}
ROW_KEYS = {'count', 'label', 'total_text', 'monthly_text', 'rate_text', 'surcharge_text', 'networks'}
NOTE_DEBIT = 'Banka kartıyla taksit yapılamaz.'
NOTE_PREPAID = 'Ön ödemeli kartla taksit yapılamaz.'
NOTE_FOREIGN = 'Yurt dışı kartla taksit yapılamaz.'
NOTE_NONE = 'Bu kartla taksit yapılamaz.'
ERRORS = {400: 'bad_request', 403: 'forbidden', 404: 'not_found', 409: 'closed', 429: 'rate_limited',
          502: 'provider', 500: 'server'}


def _tools():
    from odoo.addons.sanal_pos import tools
    return tools


class BinHttpCase(MoHttpCase):

    def setUp(self):
        super().setUp()
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT'))

    # -- istek yardımcıları -------------------------------------------------------------
    def post_raw(self, data, headers=None, user=None, timeout=12, login=True):
        if login:
            self.login_as(user or self.user_sp)
        return self.url_open(MAIL_ORDER_BIN_PATH, data=data, headers=JSON_HEADERS if headers is None else headers,
                             method='POST', allow_redirects=False, timeout=timeout)

    def post_bin(self, payment_id, bin_value=LEAK_BIN, user=None, **kw):
        payload = json.dumps({'payment_id': payment_id, 'bin': bin_value})
        return self.post_raw(payload, user=user, **kw)

    def lookup(self, payment, bin_value=LEAK_BIN, user=None):
        return self.post_bin(payment.id, bin_value, user=user)

    def assertError(self, response, status):
        self.assertEqual(response.status_code, status, response.text[:200])
        self.assertEqual(response.json(), {'ok': False, 'error': ERRORS[status]})
        self.assertTrue(response.headers.get('Content-Type', '').startswith('application/json'))
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))

    def qbin_logs(self):
        return self.env['sanal.pos.log'].sudo().search([('action', '=', 'QUERYBIN')])

    def credit_card(self, rates=((2, 0), (3, 1.5), (6, 3.0)), **kw):
        kw.setdefault('country', 'TUR')
        self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT', 'AKBANK', 'AXESS', 'VISA', **kw))
        self.mock.default('QUERYPAYMENTSYSTEMS', lambda p: paymentsystems_body(list(rates)))


# ======================================================================================
# Sözleşme: başarılı yanıtlar (KK-2.1..2.4, K-19)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointResult(BinHttpCase):

    def test_kredi_karti_programin_taksitleri_programin_oraniyla(self):
        self.credit_card(rates=((2, 0), (3, 1.5), (6, 3.0)))
        payment = self.make_mail_order(amount=9000.0)
        response = self.lookup(payment)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        body = response.json()
        self.assertEqual(set(body), OK_KEYS, 'yanıt anahtarları sözleşmedeki küme; fazla alan (BIN, issuer...) yok')
        self.assertIs(body['ok'], True)
        self.assertEqual(body['card_type'], 'credit')
        self.assertIs(body['foreign'], False)
        self.assertEqual(body['bank'], 'Akbank')
        self.assertEqual(body['program'], 'Axess')
        self.assertEqual(str(body['brand']).lower(), 'visa')
        self.assertEqual(body['detected'], 'Akbank · Axess · Kredi kartı')
        self.assertIs(body['installments'], True)
        self.assertEqual(body['note'], '')
        rows = body['rows']
        self.assertEqual([r['count'] for r in rows], [1, 2, 3, 6], 'Tek çekim ilk, yalnız programın taksitleri')
        for row in rows:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertEqual(row['networks'], [], 'program detected satırında; satırda ağ listesi yok')
        by_count = {r['count']: r for r in rows}
        self.assertEqual(by_count[1]['label'], 'Tek çekim')
        self.assertEqual(by_count[1]['total_text'], '9.000,00 TL')
        self.assertEqual(by_count[2]['rate_text'], 'Vade farkı yok')
        self.assertEqual(by_count[3]['label'], '3 taksit')
        self.assertEqual(by_count[3]['rate_text'], '%1,50')
        self.assertEqual(by_count[3]['total_text'], '9.135,00 TL')
        self.assertEqual(by_count[3]['monthly_text'], '3.045,00 TL')
        self.assertEqual(by_count[3]['surcharge_text'], '135,00 TL')
        self.assertEqual(by_count[6]['rate_text'], '%3,00')
        self.assertEqual(by_count[6]['total_text'], '9.270,00 TL')
        self.assertEqual(by_count[6]['monthly_text'], '1.545,00 TL')
        self.assertEqual(by_count[6]['surcharge_text'], '270,00 TL')
        self.assertEqual(self.mock.actions, ['QUERYBIN', 'QUERYPAYMENTSYSTEMS'])

    def test_satirlar_installment_table_ile_ayni_hesap(self):
        options = [{'count': 2, 'networks': [], 'rate': 0.0}, {'count': 9, 'networks': [], 'rate': 4.5},
                   {'count': 12, 'networks': [], 'rate': 6.0}]
        self.credit_card(rates=((2, 0), (9, 4.5), (12, 6)))
        payment = self.make_mail_order(amount=1234.56)
        rows = self.lookup(payment).json()['rows']
        expected = _tools().installment_table(1234.56, options)['rows']
        self.assertEqual(rows, expected, 'rows = tools.installment_table(amount, options)["rows"] (tek hesap)')
        self.assertNotIn('select_text', rows[0])

    def test_yalniz_programin_sayilari_isyeri_listesinden_gelmez(self):
        """Program 3 ve 6 verir; işyerinde 12 de olsa BIN yolunda görünmez; QUERYINSTALLMENT çağrılmaz."""
        self.mock.default('QUERYINSTALLMENT', lambda p: ok_body(paymentSystemList=[{
            'name': 'X', 'installmentList': [{'count': '12', 'customerCostCommissionRate': 9}]}]))
        self.credit_card(rates=((3, 1.5), (6, 3.0)))
        counts = [r['count'] for r in self.lookup(self.make_mail_order()).json()['rows']]
        self.assertEqual(counts, [1, 3, 6])
        self.assertNotIn('QUERYINSTALLMENT', self.mock.actions)

    def test_not_on_us_atlanir(self):
        self.credit_card(rates=((2, 0), ('NOT_ON_US', 0), (3, 1.5)))
        counts = [r['count'] for r in self.lookup(self.make_mail_order()).json()['rows']]
        self.assertEqual(counts, [1, 2, 3])

    def test_banka_karti_yalniz_tek_cekim_paratika_tek_cagri(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT', 'AKBANK', 'AXESS', 'MC'))
        response = self.lookup(self.make_mail_order(amount=9000.0))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['card_type'], 'debit')
        self.assertIs(body['installments'], False)
        self.assertEqual([r['count'] for r in body['rows']], [1])
        self.assertEqual(body['note'], NOTE_DEBIT)
        self.assertEqual(body['detected'], 'Akbank · Banka kartı', 'banka kartında program yazılmaz')
        self.assertEqual(self.mock.actions, ['QUERYBIN'], 'hesap kartında tek Paratika çağrısı')

    def test_on_odemeli_kart(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('PREPAID', 'AKBANK', 'AXESS'))
        body = self.lookup(self.make_mail_order()).json()
        self.assertEqual(body['card_type'], 'prepaid')
        self.assertIs(body['installments'], False)
        self.assertEqual([r['count'] for r in body['rows']], [1])
        self.assertEqual(body['note'], NOTE_PREPAID)
        self.assertEqual(body['detected'], 'Akbank · Ön ödemeli kart')
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

    def test_yabanci_kredi_karti_yalniz_tek_cekim(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT', 'AKBANK', 'AXESS', 'VISA', 'USA'))
        body = self.lookup(self.make_mail_order()).json()
        self.assertIs(body['foreign'], True)
        self.assertEqual(body['card_type'], 'credit')
        self.assertIs(body['installments'], False)
        self.assertEqual([r['count'] for r in body['rows']], [1])
        self.assertEqual(body['note'], NOTE_FOREIGN)
        self.assertTrue(body['detected'].startswith('Akbank · '), body['detected'])
        self.assertIn('Kredi kartı', body['detected'])
        self.assertTrue(body['detected'].endswith(' · Yurt dışı'), body['detected'])
        self.assertEqual(self.mock.actions, ['QUERYBIN'], 'yabancı kartta ikinci çağrı yok')

    def test_yabanci_banka_karti_taksitsiz(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT', country='DEU'))
        body = self.lookup(self.make_mail_order()).json()
        self.assertIs(body['foreign'], True)
        self.assertIs(body['installments'], False)
        self.assertEqual([r['count'] for r in body['rows']], [1])
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

    def test_ulke_bos_yurt_ici_sayilir_ikinci_cagri_yapilir(self):
        self.credit_card(rates=((2, 0),), country='')
        body = self.lookup(self.make_mail_order()).json()
        self.assertIs(body['foreign'], False)
        self.assertEqual([r['count'] for r in body['rows']], [1, 2])
        self.assertEqual(self.mock.actions, ['QUERYBIN', 'QUERYPAYMENTSYSTEMS'])

    def test_kredi_karti_taksitsiz_program(self):
        variants = {
            'bos_liste': paymentsystems_body([]),
            'yalniz_not_on_us': paymentsystems_body([('NOT_ON_US', 0)]),
            'sistem_yok': paymentsystems_body(installment_system=False),
        }
        for index, (name, qps) in enumerate(variants.items()):
            with self.subTest(durum=name):
                self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT'))
                self.mock.default('QUERYPAYMENTSYSTEMS', lambda p, qps=qps: qps)
                payment = self.make_mail_order(invoice_no='NT-%d' % index, merchant_payment_id='NT-%d-1' % index)
                response = self.lookup(payment)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertIs(body['installments'], False)
                self.assertEqual([r['count'] for r in body['rows']], [1])
                self.assertEqual(body['note'], NOTE_NONE)
                self.assertEqual(body['detected'], 'Akbank · Axess · Kredi kartı')

    def test_baska_banka_ve_program_kodu_goruntusu(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT', 'YENI_BANKA', 'WORLD', 'MC'))
        self.mock.default('QUERYPAYMENTSYSTEMS', lambda p: paymentsystems_body([(2, 0)]))
        body = self.lookup(self.make_mail_order()).json()
        self.assertEqual(body['bank'], 'Yeni Banka', 'bilinmeyen banka kodu başlık biçimiyle gösterilir')
        self.assertEqual(body['detected'], 'Yeni Banka · World · Kredi kartı')

    def test_bos_banka_kodu_olmayan_parca_yazilmaz(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT', issuer='', network=''))
        self.mock.default('QUERYPAYMENTSYSTEMS', lambda p: paymentsystems_body([(2, 0)]))
        body = self.lookup(self.make_mail_order()).json()
        self.assertEqual(body['bank'], '')
        self.assertEqual(body['detected'], 'Kredi kartı')

    def test_paratika_istekleri_bin_tasir_kart_alani_tasimaz(self):
        self.credit_card(rates=((2, 0),))
        self.lookup(self.make_mail_order())
        for call in self.mock.calls:
            self.assertEqual(call.params.get('BIN'), LEAK_BIN)
            self.assertNotIn(LEAK_PAN, call.body_text)
            self.assertLessEqual(len(call.params.get('BIN', '')), 8)

    def test_yanit_ve_url_bin_yankilamaz(self):
        self.credit_card(rates=((2, 0), (3, 1)))
        response = self.lookup(self.make_mail_order())
        self.assertNotIn(LEAK_BIN, response.text)
        self.assertNotIn(LEAK_BIN, str(response.headers))
        self.assertEqual(urlsplit(response.url).path, MAIL_ORDER_BIN_PATH)
        self.assertEqual(urlsplit(response.url).query, '', 'BIN URL\'de taşınmaz')

    def test_manager_de_kullanabilir(self):
        self.credit_card(rates=((2, 0),))
        self.assertEqual(self.lookup(self.make_mail_order(), user=self.user_mgr).status_code, 200)

    def test_get_istegi_kabul_edilmez(self):
        self.login_as(self.user_sp)
        response = self.url_open(MAIL_ORDER_BIN_PATH, allow_redirects=False)
        self.assertIn(response.status_code, (404, 405))
        self.assertNoParatikaCalls()


# ======================================================================================
# Sağlayıcı hataları -> 502 provider
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointProviderErrors(BinHttpCase):

    def assertProviderError(self, response):
        self.assertError(response, 502)
        self.assertNotIn(LEAK_BIN, response.text)

    def test_querybin_hatalari(self):
        cases = {
            'zaman_asimi': timeout_exc(),
            'http_500': RawResponse(500, 'hata'),
            'api_hatasi': err_body('ERR10010', 'hata'),
            'json_degil': RawResponse(200, 'tamam', 'text/plain'),
            'bin_nesnesi_yok': ok_body(),
            'tur_bos': querybin_body(''),
            'tur_taninmiyor': querybin_body('CHARGE'),
        }
        for index, (name, response) in enumerate(cases.items()):
            with self.subTest(durum=name):
                self.mock.default('QUERYBIN', lambda p, r=response: r)
                payment = self.make_mail_order(invoice_no='PE-%d' % index, merchant_payment_id='PE-%d-1' % index)
                self.assertProviderError(self.lookup(payment))
        self.assertNotIn('QUERYPAYMENTSYSTEMS', self.mock.actions, 'tür belirsizken ikinci çağrı yapılmaz')

    def test_ikinci_cagri_hatalari(self):
        cases = {
            'zaman_asimi': timeout_exc(),
            'http_500': RawResponse(500, 'hata'),
            'api_hatasi': err_body('ERR1', 'x'),
            'anlasilmaz_yanit': RawResponse(200, 'garip', 'text/plain'),
        }
        for index, (name, response) in enumerate(cases.items()):
            with self.subTest(durum=name):
                self.mock.default('QUERYBIN', lambda p: querybin_body('CREDIT'))
                self.mock.default('QUERYPAYMENTSYSTEMS', lambda p, r=response: r)
                payment = self.make_mail_order(invoice_no='PF-%d' % index, merchant_payment_id='PF-%d-1' % index)
                self.assertProviderError(self.lookup(payment))

    def test_yavas_ilk_cagri_ikinci_cagri_yapilmaz_502(self):
        offset = [0.0]
        real = time.monotonic

        def slow(params):
            offset[0] += 1.2
            return querybin_body('CREDIT')

        self.mock.default('QUERYBIN', slow)
        self.mock.default('QUERYPAYMENTSYSTEMS', lambda p: paymentsystems_body([(2, 0)]))
        with patch('time.monotonic', lambda: real() + offset[0]):
            response = self.lookup(self.make_mail_order())
        self.assertProviderError(response)
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

    def test_hizli_ilk_cagri_normal_calisir(self):
        offset = [0.0]
        real = time.monotonic

        def quick(params):
            offset[0] += 0.4
            return querybin_body('CREDIT')

        self.mock.default('QUERYBIN', quick)
        self.mock.default('QUERYPAYMENTSYSTEMS', lambda p: paymentsystems_body([(2, 0)]))
        with patch('time.monotonic', lambda: real() + offset[0]):
            response = self.lookup(self.make_mail_order())
        self.assertEqual(response.status_code, 200, response.text)

    def test_sagalyici_hatasi_sonrasi_ayar_eksikligi_de_502_ya_da_500_degil_json(self):
        """Paratika ayarları eksikse (CONFIG) uç yine JSON hata döner; HTML hata sayfası dönmez."""
        self.env['ir.config_parameter'].sudo().set_param('sanal_pos.paratika_merchant', '')
        response = self.lookup(self.make_mail_order())
        self.assertIn(response.status_code, (502, 500))
        self.assertTrue(response.headers['Content-Type'].startswith('application/json'))
        self.assertEqual(response.json()['ok'], False)
        self.assertNoParatikaCalls()

    def test_beklenmeyen_istisna_500_server_sizinti_yok(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        model = type(self.env['sanal.pos.payment'])
        with patch.object(model, '_mail_order_bin_lookup',
                          side_effect=RuntimeError('beklenmeyen %s ayrinti' % LEAK_BIN)):
            with self.capture_logs() as records:
                response = self.post_bin(payment.id, login=False)
        self.assertError(response, 500)
        self.assertNotIn('beklenmeyen', response.text)
        self.assertNotIn('Traceback', response.text)
        text = '\n'.join(records)
        self.assertNotIn(LEAK_BIN, text)
        self.assertNotIn('beklenmeyen', text, '_logger.error yalnız istisna sınıf adını yazar')
        self.assertIn('RuntimeError', text)


# ======================================================================================
# Girdi doğrulama (KK-2.7): her şey Paratika'dan ÖNCE
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointValidation(BinHttpCase):

    def setUp(self):
        super().setUp()
        self.payment = self.make_mail_order()
        self.pid = self.payment.id

    def body(self, **over):
        data = {'payment_id': self.pid, 'bin': LEAK_BIN}
        data.update(over)
        return json.dumps(data)

    def assertBad(self, response):
        self.assertError(response, 400)

    def test_gecerli_istek_olumlu_capa(self):
        self.assertEqual(self.post_raw(self.body()).status_code, 200)

    def test_icerik_turu_json_degilse_400(self):
        cases = {
            'text/plain': {'Content-Type': 'text/plain'},
            'form': {'Content-Type': 'application/x-www-form-urlencoded'},
            'baslik_yok': {},
            'xml': {'Content-Type': 'application/xml'},
            'json_benzeri': {'Content-Type': 'application/jsonx'},
        }
        for name, headers in cases.items():
            with self.subTest(icerik_turu=name):
                self.assertBad(self.post_raw(self.body(), headers=headers))
        self.assertBad(self.post_raw('payment_id=%d&bin=%s' % (self.pid, LEAK_BIN),
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'}))
        self.assertNoParatikaCalls()

    def test_charset_parametreli_json_kabul(self):
        response = self.post_raw(self.body(), headers={'Content-Type': 'application/json; charset=utf-8'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_bozuk_json_ve_kok_tipleri(self):
        for name, raw in (('bos', ''), ('bozuk', '{"payment_id": '), ('dizi', '[]'), ('metin', '"x"'),
                          ('sayi', '5'), ('null', 'null'), ('bool', 'true'), ('bos_nesne', '{}'),
                          ('tek_tirnak', "{'payment_id': 1}")):
            with self.subTest(govde=name):
                self.assertBad(self.post_raw(raw))
        self.assertBad(self.post_raw(b'\xff\xfe\x00{'))
        self.assertNoParatikaCalls()

    def test_anahtar_seti_tam_olmali(self):
        cases = {
            'bin_yok': json.dumps({'payment_id': self.pid}),
            'payment_id_yok': json.dumps({'bin': LEAK_BIN}),
            'fazla_anahtar': self.body(extra=1),
            'fazla_anahtar_pan': self.body(pan=LEAK_PAN),
            'yanlis_buyuk_harf': json.dumps({'payment_id': self.pid, 'Bin': LEAK_BIN}),
            'camel_case': json.dumps({'paymentId': self.pid, 'bin': LEAK_BIN}),
        }
        for name, raw in cases.items():
            with self.subTest(durum=name):
                self.assertBad(self.post_raw(raw))
        self.assertNoParatikaCalls()

    def test_payment_id_tipi_ve_araligi(self):
        for name, value in (('metin', str(self.pid)), ('sifir', 0), ('negatif', -1), ('bool', True),
                            ('ondalik', float(self.pid) + 0.5), ('null', None), ('liste', [self.pid]),
                            ('nesne', {'id': self.pid})):
            with self.subTest(payment_id=name):
                self.assertBad(self.post_raw(self.body(payment_id=value)))
        self.assertNoParatikaCalls()

    def test_cok_buyuk_payment_id_500_vermez(self):
        for value in (10 ** 30, 2 ** 63, 2 ** 31):
            with self.subTest(deger=value):
                response = self.post_raw(self.body(payment_id=value))
                self.assertIn(response.status_code, (400, 404), response.text)
                self.assertEqual(response.json()['ok'], False)
        self.assertNoParatikaCalls()

    def test_bin_bicimi_tam_sekiz_ascii_rakam(self):
        bad = {
            '6_hane': '435508', '7_hane': '4355084', '9_hane': '435508435', '16_hane_pan': LEAK_PAN,
            'bos': '', 'bosluk_basta': ' 4355084', 'bosluk_sonda': '4355084 ', 'bosluk_icinde': '4355 084',
            'harf': '4355084A', 'harf_basta': 'a4355084', 'tire': '4355-084', 'nokta': '4355.084',
            'yeni_satir_sonda': LEAK_BIN + '\n', 'yeni_satir_basta': '\n' + LEAK_BIN,
            'sekme': '4355084\t', 'unicode_rakam': '٤٣٥٥٠٨٤٣', 'tam_genislik': '４３５５０８４３',
            'ust_simge': '43550843'.replace('4', '⁴'), 'eksi': '-4355084', 'arti': '+4355084',
            'onaltili': '0x435508', 'bilimsel': '4.35e+07', 'sql': "1' OR '1'='1",
            'html': '<b>4355</b>', 'null_bayt': LEAK_BIN + '\x00',
        }
        for name, value in bad.items():
            with self.subTest(bin=name):
                response = self.post_bin(self.pid, value)
                self.assertBad(response)
                if value.strip():
                    self.assertNotIn(value.strip()[:6], response.text, 'hata yanıtı girdiyi yankılamaz')
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs(), 'geçersiz girdi hiçbir kayıt bırakmaz')

    def test_bin_tipi_metin_olmali(self):
        for name, value in (('tam_sayi', int(LEAK_BIN)), ('ondalik', float(LEAK_BIN)), ('null', None),
                            ('liste', [LEAK_BIN]), ('nesne', {'bin': LEAK_BIN}), ('bool', True)):
            with self.subTest(bin=name):
                self.assertBad(self.post_bin(self.pid, value))
        self.assertNoParatikaCalls()

    def test_amex_oneki_34_37_reddedilir(self):
        for value in ('34000000', '34123456', '37000000', '37999999'):
            with self.subTest(bin=value):
                self.assertBad(self.post_bin(self.pid, value))
        self.assertNoParatikaCalls()

    def test_diners_oneki_300_305_36_38_39_reddedilir(self):
        """R6: 14-15 haneli ağlar (Amex ve Diners) için BIN sorgusu yapılmaz, uç 400."""
        for value in ('30000000', '30012345', '30299999', '30500000', '30599999',
                      '36000000', '36123456', '38000000', '38999999', '39000000', '39999999'):
            with self.subTest(bin=value):
                self.assertBad(self.post_bin(self.pid, value))
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs(), 'reddedilen önek kayıt bırakmaz')

    def test_amex_disi_oneks_kabul_edilir(self):
        # 306/307 Diners aralığı (300-305) dışında; 35 JCB; 33 ve 00/99 genel önekler
        for index, value in enumerate(('35000000', '33000000', '30600000', '30999999', '00000000', '99999999')):
            with self.subTest(bin=value):
                response = self.post_bin(self.pid, value)
                self.assertEqual(response.status_code, 200, response.text)

    def test_govde_boyutu_sinirI_256_bayt(self):
        base = '{"payment_id": %d, "bin": "%s"%%s}' % (self.pid, LEAK_BIN)
        exact = base % (' ' * (256 - len(base % '')))
        self.assertEqual(len(exact.encode()), 256)
        self.assertEqual(self.post_raw(exact).status_code, 200, '256 bayt sınırda kabul edilir')
        over = base % (' ' * (257 - len(base % '')))
        self.assertEqual(len(over.encode()), 257)
        self.assertBad(self.post_raw(over))
        self.assertBad(self.post_raw(base % (' ' * 5000)))
        self.assertBad(self.post_raw('{"payment_id": %d, "bin": "%s", "x": "%s"}' % (self.pid, LEAK_BIN, 'a' * 400)))

    def test_dogrulama_hata_sirasi_400_yetki_ve_anahtardan_once(self):
        """Doğrulama (400) grup denetiminden (403) ve kapatma anahtarından (409) önce gelir."""
        self.env['ir.config_parameter'].sudo().set_param(SCRIPT_ICP, 'false')
        self.assertBad(self.post_bin(self.pid, '123'))
        self.assertBad(self.post_bin(self.pid, '123', user=self.user_plain))
        self.assertBad(self.post_raw(self.body(), headers={'Content-Type': 'text/plain'}, user=self.user_plain))
        self.assertNoParatikaCalls()

    def test_gecersiz_istekler_hiz_sinirina_sayilmaz(self):
        for _ in range(25):
            self.post_bin(self.pid, 'abc')
        self.assertFalse(self.qbin_logs())
        self.assertEqual(self.post_bin(self.pid).status_code, 200)


# ======================================================================================
# Yetki ve durum (403/404/409)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointAccess(BinHttpCase):

    def test_oturumsuz_giris_yonlendirmesi_ya_da_401(self):
        payment = self.make_mail_order()
        response = self.url_open(MAIL_ORDER_BIN_PATH, data=json.dumps({'payment_id': payment.id, 'bin': LEAK_BIN}),
                                 headers=JSON_HEADERS, method='POST', allow_redirects=False)
        self.assertIn(response.status_code, (301, 302, 303, 307, 401))
        if response.status_code != 401:
            self.assertIn('/web/login', response.headers.get('Location', ''))
        self.assertNotIn(LEAK_BIN, response.text)
        self.assertNoParatikaCalls()

    def test_sanal_pos_grubu_olmayan_403(self):
        payment = self.make_mail_order()
        response = self.lookup(payment, user=self.user_plain)
        self.assertError(response, 403)
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs())

    def test_grup_denetimi_kayit_aramasindan_once_yok_kayit_icin_de_403(self):
        """Yetkisiz kullanıcı kayıt var mı yok mu öğrenemez (varlık sızıntısı yok)."""
        existing = self.lookup(self.make_mail_order(), user=self.user_plain)
        missing = self.post_bin(987654321, user=self.user_plain)
        self.assertError(existing, 403)
        self.assertError(missing, 403)

    def test_kayit_yok_404(self):
        self.assertError(self.post_bin(987654321), 404)
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs())

    def test_okuma_hakki_yoksa_403(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        model = type(self.env['sanal.pos.payment'])
        with patch.object(model, 'check_access', side_effect=AccessError('yok')):
            response = self.post_bin(payment.id, login=False)
        self.assertError(response, 403)
        self.assertNoParatikaCalls()

    def test_kapali_kayitlar_409_paratika_yok(self):
        cases = {
            'suresi_dolmus_durum': {'state': 'expired'},
            'odendi': {'state': 'paid'},
            'iptal': {'state': 'link_cancelled'},
            'hata': {'state': 'error'},
            'sure_gecmis': {'expires_at': fields.Datetime.now() - timedelta(minutes=1)},
            'token_yok': {'provider_token': False},
            'link_odemesi': {'payment_method': 'link'},
        }
        for index, (name, vals) in enumerate(cases.items()):
            with self.subTest(durum=name):
                payment = self.make_mail_order(invoice_no='CL-%d' % index, merchant_payment_id='CL-%d-1' % index,
                                               **vals)
                self.assertError(self.lookup(payment), 409)
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs())

    def test_acik_kayit_olumlu_capa(self):
        self.assertEqual(self.lookup(self.make_mail_order()).status_code, 200)


# ======================================================================================
# Kapatma anahtarı (D-4)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointKillSwitch(BinHttpCase, CardPageCase):

    def test_kapali_degerlerde_409_closed_paratika_yok(self):
        params = self.env['ir.config_parameter'].sudo()
        for index, value in enumerate(('false', 'False', '0', 'no', 'off', 'hayır', 'kapalı', '', '   ',
                                       ' FALSE ', 'bilinmiyor', '2')):
            with self.subTest(deger=value):
                params.set_param(SCRIPT_ICP, value)
                payment = self.make_mail_order(invoice_no='KS-%d' % index, merchant_payment_id='KS-%d-1' % index)
                self.assertError(self.lookup(payment), 409)
        self.assertNoParatikaCalls()
        self.assertFalse(self.qbin_logs())

    def test_acik_degerlerde_ve_anahtar_yoksa_calisir(self):
        params = self.env['ir.config_parameter'].sudo()
        for index, value in enumerate(('true', 'True', '1', 'yes', 'evet', ' TRUE ', 'Evet')):
            with self.subTest(deger=value):
                params.set_param(SCRIPT_ICP, value)
                payment = self.make_mail_order(invoice_no='KA-%d' % index, merchant_payment_id='KA-%d-1' % index)
                self.assertEqual(self.lookup(payment).status_code, 200)
        params.search([('key', '=', SCRIPT_ICP)]).unlink()
        payment = self.make_mail_order(invoice_no='KA-YOK')
        self.assertEqual(self.lookup(payment).status_code, 200, 'anahtar yok = açık')

    def test_sayfa_ile_uc_ayni_anahtara_bakar(self):
        params = self.env['ir.config_parameter'].sudo()
        for value, is_open in (('false', False), ('evet', True), ('', False), ('1', True)):
            with self.subTest(deger=value):
                params.set_param(SCRIPT_ICP, value)
                payment = self.make_mail_order(invoice_no='KP-%s' % (value or 'bos'),
                                               merchant_payment_id='KP-%s-1' % (value or 'bos'))
                page = self.page(payment)
                self.assertEqual('<script' in self.body(page).lower(), is_open)
                self.assertEqual(self.lookup(payment).status_code, 200 if is_open else 409)


# ======================================================================================
# Hız sınırı (KK-2.6): 20 / kayıt-saat, 60 / kullanıcı-saat
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointRateLimit(BinHttpCase):

    def fire(self, payment, times, user=None):
        return [self.lookup(payment, user=user).status_code for _ in range(times)]

    def test_kayit_basina_20_sonra_429(self):
        payment = self.make_mail_order()
        statuses = self.fire(payment, 20)
        self.assertEqual(statuses, [200] * 20)
        response = self.lookup(payment)
        self.assertError(response, 429)
        self.assertEqual(self.mock.count('QUERYBIN'), 20, 'reddedilen istek Paratika\'ya gitmez')

    def test_reddedilen_istekler_sayilmaz_ve_sayac_buyumez(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        for _ in range(5):
            self.assertError(self.lookup(payment), 429)
        self.assertEqual(len(self.qbin_logs()), 20)

    def test_querypaymentsystems_sayilmaz_kredi_kartiyla_20_istek(self):
        self.credit_card(rates=((2, 0),))
        payment = self.make_mail_order()
        self.assertEqual(self.fire(payment, 20), [200] * 20, 'ikinci çağrı sayaca eklenmez')
        self.assertError(self.lookup(payment), 429)
        self.assertEqual(self.mock.count('QUERYPAYMENTSYSTEMS'), 20)

    def test_hata_veren_sorgular_da_sayilir(self):
        payment = self.make_mail_order()
        self.mock.default('QUERYBIN', lambda p: timeout_exc())
        self.assertEqual(self.fire(payment, 20), [502] * 20)
        self.assertError(self.lookup(payment), 429)

    def test_ayni_kayit_baska_kullanici_icin_de_dolu(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        self.assertError(self.lookup(payment, user=self.user_mgr), 429)

    def test_baska_kayit_sayaci_bagimsiz(self):
        first = self.make_mail_order(invoice_no='RL-A', merchant_payment_id='RL-A-1')
        second = self.make_mail_order(invoice_no='RL-B', merchant_payment_id='RL-B-1')
        self.fire(first, 20)
        self.assertError(self.lookup(first), 429)
        self.assertEqual(self.lookup(second).status_code, 200)

    def test_kullanici_basina_60_sonra_429(self):
        payments = [self.make_mail_order(invoice_no='RU-%d' % i, merchant_payment_id='RU-%d-1' % i)
                    for i in range(5)]
        for payment in payments[:3]:
            self.assertEqual(self.fire(payment, 20), [200] * 20)
        response = self.lookup(payments[3])
        self.assertError(response, 429)
        self.assertEqual(self.mock.count('QUERYBIN'), 60)
        # başka kullanıcı etkilenmez (olumlu çapa)
        self.assertEqual(self.lookup(payments[4], user=self.user_mgr).status_code, 200)

    def test_pencere_bir_saat_eski_kayitlar_sayilmaz(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        self.assertError(self.lookup(payment), 429)
        # 59 dk önce: hâlâ sayılır
        for rec in self.qbin_logs():
            self.set_create_date(rec, fields.Datetime.now() - timedelta(minutes=59))
        self.assertError(self.lookup(payment), 429)
        # 61 dk önce: pencere dışı
        for rec in self.qbin_logs():
            self.set_create_date(rec, fields.Datetime.now() - timedelta(minutes=61))
        self.assertEqual(self.lookup(payment).status_code, 200)

    def test_asimda_tek_bin_rate_limit_satiri_ve_tek_uyari(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        with self.assertLogs('odoo.addons.sanal_pos', level='WARNING') as captured:
            for _ in range(4):
                self.assertError(self.lookup(payment), 429)
        rows = self.env['sanal.pos.log'].sudo().search([('action', '=', 'BIN_RATE_LIMIT')])
        self.assertEqual(len(rows), 1, 'aynı pencerede kullanıcı için tek satır')
        self.assertFalse(rows.payment_id, 'payment_id=False')
        self.assertEqual(rows.create_uid, self.user_sp)
        blob = (rows.request_body or '') + (rows.response_body or '')
        self.assertIn(str(payment.id), blob, 'kayıt kimliği gövdede')
        self.assertIn(str(self.user_sp.id), blob, 'kullanıcı kimliği gövdede')
        self.assertNotIn(LEAK_BIN, blob)
        warnings = [r for r in captured.records if r.levelname == 'WARNING']
        self.assertEqual(len(warnings), 1, 'uyarı yalnız bir kez')
        self.assertNotIn(LEAK_BIN, warnings[0].getMessage())

    def test_yeni_pencerede_yeniden_satir_yazilir(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        self.assertError(self.lookup(payment), 429)
        for rec in self.env['sanal.pos.log'].sudo().search([('action', 'in', ('QUERYBIN', 'BIN_RATE_LIMIT'))]):
            self.set_create_date(rec, fields.Datetime.now() - timedelta(minutes=70))
        self.fire(payment, 20)
        self.assertError(self.lookup(payment), 429)
        rows = self.env['sanal.pos.log'].sudo().search([('action', '=', 'BIN_RATE_LIMIT')])
        self.assertEqual(len(rows), 2)

    def test_429_cevap_biciminde_bin_yok(self):
        payment = self.make_mail_order()
        self.fire(payment, 20)
        response = self.lookup(payment)
        self.assertError(response, 429)
        self.assertNotIn(LEAK_BIN, response.text)


# ======================================================================================
# Yan etkisizlik, kayıt değişmezliği ve BIN sızıntısı (KK-2.8, KK-2.9)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointNoSideEffects(BinHttpCase):

    def snapshot(self, payment):
        self.env.cr.execute('SELECT * FROM sanal_pos_payment WHERE id = %s', [payment.id])
        row = self.env.cr.fetchone()
        self.env.cr.execute("SELECT count(*) FROM mail_message WHERE model = 'sanal.pos.payment' AND res_id = %s",
                            [payment.id])
        return row, self.env.cr.fetchone()[0]

    def test_odeme_kaydi_ve_sohbet_degismez(self):
        self.credit_card(rates=((2, 0), (3, 1.5)))
        payment = self.make_mail_order()
        before = self.snapshot(payment)
        triggers = self.cron_trigger_count()
        for _ in range(3):
            self.assertEqual(self.lookup(payment).status_code, 200)
        self.assertEqual(self.snapshot(payment), before, 'ödeme satırı ve chatter hiç değişmez (write/message_post yok)')
        self.assertEqual(self.cron_trigger_count(), triggers)

    def test_bin_hicbir_kalici_yerde_yok(self):
        self.credit_card(rates=((2, 0), (3, 1.5)))
        payment = self.make_mail_order()
        self.assertEqual(self.lookup(payment).status_code, 200)
        self.mock.default('QUERYBIN', lambda p: RawResponse(200, 'garip %s yanit' % LEAK_BIN, 'text/plain'))
        self.assertEqual(self.lookup(payment).status_code, 502)
        self.mock.default('QUERYBIN', lambda p: err_body('E1', 'BIN %s yok' % LEAK_BIN))
        self.assertEqual(self.lookup(payment).status_code, 502)
        self.assertNotIn(LEAK_BIN, self.all_log_text())
        self.assertNotIn(LEAK_BIN, self.chatter(payment))
        self.env.cr.execute("SELECT string_agg(COALESCE(body, ''), ' ') FROM mail_message")
        self.assertNotIn(LEAK_BIN, self.env.cr.fetchone()[0] or '')
        self.env.cr.execute("SELECT row_to_json(p)::text FROM sanal_pos_payment p WHERE id = %s", [payment.id])
        self.assertNotIn(LEAK_BIN, self.env.cr.fetchone()[0])

    def test_uygulama_logger_ciktisinda_bin_yok(self):
        self.credit_card(rates=((2, 0),))
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        with self.capture_logs() as records:
            self.post_bin(payment.id, login=False)
            self.post_bin(payment.id, '123', login=False)
            self.mock.default('QUERYBIN', lambda p: timeout_exc())
            self.post_bin(payment.id, login=False)
        self.assertNotIn(LEAK_BIN, '\n'.join(records))

    def test_log_satiri_qurybin_kayit_ve_maskeli(self):
        payment = self.make_mail_order()
        self.assertEqual(self.lookup(payment).status_code, 200)
        rows = self.qbin_logs()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.payment_id, 'Ö-3/KK-2.8: satır ödemeye FK ile bağlanmaz')
        self.assertTrue((rows.request_body or '').endswith('"_payment_id": %d}' % payment.id), rows.request_body)
        self.assertEqual(rows.create_uid, self.user_sp, 'kullanıcı sayacı create_uid ile tutulur')
        self.assertNotIn(LEAK_BIN, (rows.request_body or '') + (rows.response_body or ''))

    def test_uc_chatterda_islem_notu_birakmaz_kart_sayfasi_notu_ayri(self):
        payment = self.make_mail_order()
        self.lookup(payment)
        self.assertNotIn('BIN', self.chatter(payment))


# ======================================================================================
# KK-2.8: uç ödeme satırını KİLİTLEMEZ (gerçek ikinci bağlantıyla)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinEndpointLock(BinHttpCase):
    """Başka bir işlem ödeme satırını ``FOR UPDATE`` ile tutarken BIN ucu beklemez.

    HttpCase sınıf imlecinin işlemi REPEATABLE READ'dir ve HTTP isteği aynı işlemi kullanır: başka bağlantıda
    SONRADAN commit edilen satır uçta görünmez (404). Bu yüzden kilitlenecek satır, test imleci açılmadan
    ÖNCE (``setUpClass`` içinde ``super()`` çağrısından önce) ayrı bir bağlantıda commit edilir; böylece hem uç
    hem kilidi tutan ikinci bağlantı aynı satırı görür. Kullanıcı: commit'li yönetici (id 2); grup ve parola
    test işleminde verilir.
    """
    LOCK_REF = 'LOCKREAL-A2'

    @classmethod
    def _real_cursor(cls):
        from odoo import sql_db
        from odoo.tests.common import get_db_name
        return sql_db.db_connect(get_db_name()).cursor()

    @classmethod
    def _purge_lock_rows(cls):
        cr = cls._real_cursor()
        try:
            cr.execute("SET lock_timeout = '5s'")
            cr.execute("DELETE FROM sanal_pos_log WHERE payment_id IN "
                       "(SELECT id FROM sanal_pos_payment WHERE invoice_no = %s)", [cls.LOCK_REF])
            cr.execute('DELETE FROM sanal_pos_payment WHERE invoice_no = %s', [cls.LOCK_REF])
            cr.commit()
        finally:
            cr.close()

    @classmethod
    def setUpClass(cls):
        from odoo import SUPERUSER_ID, api
        cls._purge_lock_rows()                       # önceki yarım kalmış koşudan artık varsa
        cr = cls._real_cursor()
        try:
            env = api.Environment(cr, SUPERUSER_ID, {})
            now = fields.Datetime.now()
            payment = env['sanal.pos.payment'].create({
                'provider': 'paratika', 'environment': 'test', 'invoice_source': 'nebim',
                'invoice_no': cls.LOCK_REF, 'invoice_ref': '0A1B2C3D-0000-4000-8000-0000000000A2',
                'customer_code': 'M-555', 'customer_name': 'Kilit Testi', 'customer_phone': '5321112233',
                'customer_email': 'kilit@example.com', 'amount': 9000.0,
                'currency_id': env.ref('base.TRY').id, 'channel_sms': False, 'channel_email': False,
                'expiry_hours': 1, 'state': 'sent', 'attempt_no': 1, 'merchant_payment_id': cls.LOCK_REF + '-1',
                'provider_token': 'MOT-LOCK-A2', 'sent_at': now, 'expires_at': now + timedelta(minutes=55),
                'user_id': 2, 'payment_method': 'mail_order',
            })
            cr.execute('UPDATE sanal_pos_payment SET create_uid = 2 WHERE id = %s', [payment.id])
            cls.lock_payment_id = payment.id
            cr.commit()
        finally:
            cr.close()
        try:
            super().setUpClass()
        except BaseException:
            cls._purge_lock_rows()
            raise
        cls.addClassCleanup(cls._purge_lock_rows)

    def setUp(self):
        super().setUp()
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [(4, self.env.ref('sanal_pos.group_sanal_pos_user').id)]})
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT'))
        self.assertTrue(self.env['sanal.pos.payment'].sudo().browse(self.lock_payment_id).exists(),
                        'commit li satır test işleminde görünür (setUpClass içinde, imleçten önce)')

    def real_connection(self):
        from odoo import sql_db
        from odoo.tests.common import get_db_name
        _name, info = sql_db.connection_info_for(get_db_name())
        conn = psycopg2.connect(info['dsn']) if 'dsn' in info else psycopg2.connect(**info)
        conn.autocommit = False
        return conn

    def hold_lock(self):
        holder = self.real_connection()
        cur = holder.cursor()
        cur.execute('SELECT id FROM sanal_pos_payment WHERE id = %s FOR UPDATE', [self.lock_payment_id])
        self.assertEqual(cur.fetchone()[0], self.lock_payment_id, 'kilitlenecek satır ikinci bağlantıda görünür')
        return holder

    def lookup_locked(self, times=1):
        started = time.monotonic()
        responses = [self.post_bin(self.lock_payment_id, user=self.admin, timeout=10) for _ in range(times)]
        return responses, time.monotonic() - started

    def test_satir_kilitsizken_uc_gorur_ve_log_payment_a_baglanir(self):
        """Olumlu çapa: kilit yokken uç satırı görür (200); QUERYBIN günlüğü ödemeye FK ile bağlanmaz
        (payment_id boş), ödeme yalnız ``_payment_id`` işaretiyle izlenir; BIN kayıtta yok."""
        responses, _elapsed = self.lookup_locked()
        self.assertEqual(responses[0].status_code, 200, responses[0].text)
        rows = self.qbin_logs()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.payment_id)
        self.assertTrue((rows.request_body or '').endswith('"_payment_id": %d}' % self.lock_payment_id),
                        rows.request_body)
        self.assertNotIn(LEAK_BIN, (rows.request_body or '') + (rows.response_body or ''))

    def test_baska_islem_odeme_satirini_for_update_tutarken_uc_bloklanmaz(self):
        holder = self.hold_lock()
        try:
            responses, elapsed = self.lookup_locked()
        finally:
            holder.rollback()
            holder.close()
        response = responses[0]
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(elapsed, 4.0, 'uç kilit nedeniyle beklemez: %.1f sn' % elapsed)
        rows = self.qbin_logs()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.payment_id, 'kilit alınamadı: günlük satırı payment_id=False ile yazılır')
        self.assertEqual(rows.create_uid, self.admin)
        self.assertNotIn(LEAK_BIN, (rows.request_body or '') + (rows.response_body or ''))

    def test_kilit_varken_hiz_siniri_sayaci_kullanici_uzerinden_calisir(self):
        holder = self.hold_lock()
        try:
            responses, elapsed = self.lookup_locked(times=2)
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertLess(elapsed, 8.0)
        self.assertEqual(len(self.qbin_logs()), 2, 'payment_id\'siz satırlar kullanıcı sayacında görünür')

    def test_uc_sonrasi_odeme_satirinda_fk_kilidi_kalmaz(self):
        """Ö-3/KK-2.8: uç işlemi açıkken başka işlem ödeme satırını NOWAIT ile kilitleyebilir.

        Eski davranışta QUERYBIN satırının FK denetimi satırda işlem sonuna kadar ``FOR KEY SHARE``
        tutuyordu; cron/Kapat/dönüşün ``FOR UPDATE NOWAIT``'i bu yüzden düşerdi."""
        self.credit_card()
        responses, _elapsed = self.lookup_locked()
        self.assertEqual(responses[0].status_code, 200, responses[0].text)
        self.assertEqual(len(self.qbin_logs()), 1, 'önkoşul: satır bu (açık) işlemde yazıldı')
        holder = self.real_connection()
        try:
            cur = holder.cursor()
            cur.execute('SELECT id FROM sanal_pos_payment WHERE id = %s FOR UPDATE NOWAIT', [self.lock_payment_id])
            self.assertEqual(cur.fetchone()[0], self.lock_payment_id)
        finally:
            holder.rollback()
            holder.close()

    def test_kilit_varken_odeme_satiri_degismez(self):
        holder = self.hold_lock()
        try:
            self.lookup_locked()
        finally:
            holder.rollback()
            holder.close()
        self.env.cr.execute('SELECT state, provider_token FROM sanal_pos_payment WHERE id = %s',
                            [self.lock_payment_id])
        self.assertEqual(self.env.cr.fetchone(), ('sent', 'MOT-LOCK-A2'))


# ======================================================================================
# Kart sayfası işaretleme ve CSP connect-src (B-1)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardPageBinMarkup(CardPageCase):

    def form(self, response):
        return self.doc(response).xpath('//form[@id="mo-form"]')[0]

    def test_form_data_payment_id_ve_data_bin(self):
        payment = self.make_mail_order()
        form = self.form(self.page(payment))
        self.assertEqual(form.get('data-payment-id'), str(payment.id))
        self.assertEqual(form.get('data-bin'), '1')

    def test_durum_yuvalari_var_ve_erisilebilir(self):
        doc = self.doc(self.page(self.make_mail_order()))
        for element_id in ('mo-detected', 'mo-bin-status', 'mo-inst-note'):
            found = doc.xpath('//*[@id="%s"]' % element_id)
            self.assertEqual(len(found), 1, element_id)
        status = doc.xpath('//*[@id="mo-bin-status"]')[0]
        self.assertEqual(status.get('aria-live'), 'polite', 'yükleniyor/uyarı metni ekran okuyucuya duyurulur')
        self.assertEqual(norm(status.text_content()), '', 'sayfa açılışında boş')
        self.assertEqual(norm(doc.xpath('//*[@id="mo-detected"]')[0].text_content()), '')
        self.assertEqual(norm(doc.xpath('//*[@id="mo-inst-note"]')[0].text_content()), '')

    def test_yuvalar_form_icinde_ve_kart_alanlari_degismez(self):
        form = self.form(self.page(self.make_mail_order()))
        for element_id in ('mo-detected', 'mo-bin-status', 'mo-inst-note'):
            self.assertTrue(form.xpath('.//*[@id="%s"]' % element_id), '%s form içinde olmalı' % element_id)
        names = {el.get('name') for el in form.xpath('.//input|.//select|.//textarea') if el.get('name')}
        self.assertEqual(names, {'cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv', 'installmentCount'},
                         'yeni yuvalar form alanı (name) eklemez; Paratika\'ya fazladan alan gitmez')

    def test_taksit_kartlari_sayfada_var_ve_data_nitelikleri_korunur(self):
        self.mock.default('QUERYINSTALLMENT', lambda p: ok_body(paymentSystemList=[{
            'name': 'X', 'paymentSystemNetwork': 'AXESS',
            'installmentList': [{'count': '3', 'customerCostCommissionRate': 1.5}]}]))
        form = self.form(self.page(self.make_mail_order(amount=9000.0)))
        radios = form.xpath('.//input[@name="installmentCount"]')
        self.assertEqual([r.get('value') for r in radios], ['1', '3'])
        for radio in radios:
            for attr in ('data-total', 'data-monthly'):
                self.assertIsNotNone(radio.get(attr), attr)
        self.assertIsNotNone(radios[1].get('data-surcharge'), 'vade farkı olan satırda data-surcharge var')

    def test_kapali_anahtarda_data_bin_ve_connect_src_yok(self):
        self.env['ir.config_parameter'].sudo().set_param(SCRIPT_ICP, 'false')
        response = self.page(self.make_mail_order())
        self.assertNotIn('connect-src', self.csp(response))
        self.assertIsNone(self.form(response).get('data-bin'))

    def test_betik_dosyasi_yoksa_connect_src_ve_data_bin_yok(self):
        from .test_mail_order_card import script_file
        with script_file(None):
            response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('connect-src', self.csp(response))
        self.assertIsNone(self.form(response).get('data-bin'))

    def test_hata_ve_donus_sayfalarinda_connect_src_yok(self):
        self.login_as(self.user_sp)
        pages = [self.page(self.make_mail_order(invoice_no='CS-1', state='expired')),
                 self.url_open(MAIL_ORDER_PAY_PATH % 99999999, allow_redirects=False)]
        for response in pages:
            self.assertNotIn('connect-src', self.csp(response))
            self.assertNotIn('data-bin', self.body(response))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestConnectSrc(CardPageCase):
    """B-1: ``connect-src`` değeri istek ana makinesinden (``request.httprequest.host_url``) türer."""

    def setUp(self):
        super().setUp()
        self.payment = self.make_mail_order()

    def proxied(self, host, proto='https'):
        old = config['proxy_mode']
        config['proxy_mode'] = True
        self.addCleanup(config.__setitem__, 'proxy_mode', old)
        return self.page(self.payment, headers={'X-Forwarded-Host': host, 'X-Forwarded-Proto': proto})

    def form(self, response):
        return self.doc(response).xpath('//form[@id="mo-form"]')[0]

    def assertConnect(self, response, expected):
        self.assertEqual(response.status_code, 200, self.body(response)[:200])
        policy = self.csp(response)
        self.assertEqual(policy.get('connect-src'), [expected])
        self.assertEqual(self.form(response).get('data-bin'), '1')

    def assertNoConnect(self, response):
        self.assertEqual(response.status_code, 200, self.body(response)[:200])
        self.assertNotIn('connect-src', self.csp(response))
        self.assertIsNone(self.form(response).get('data-bin'), 'connect-src yoksa data-bin de yok')
        header = response.headers.get('Content-Security-Policy', '')
        self.assertNotIn('evil', header)

    def test_https_proxy_ana_makinesi(self):
        self.assertConnect(self.proxied('odoo.ugurlar.test'), 'https://odoo.ugurlar.test/sanal_pos/mail_order/bin')

    def test_https_port_kabul(self):
        self.assertConnect(self.proxied('odoo.ugurlar.test:8443'),
                           'https://odoo.ugurlar.test:8443/sanal_pos/mail_order/bin')

    def test_https_buyuk_harf_ve_ic_ag_adi(self):
        self.assertConnect(self.proxied('Odoo-1.Ugurlar.Test'),
                           'https://Odoo-1.Ugurlar.Test/sanal_pos/mail_order/bin')

    def test_http_loopback_kabul_httpcase_varsayilani(self):
        response = self.page(self.payment)
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(response.url))
        self.assertTrue(origin.startswith('http://127.0.0.1:'), origin)
        self.assertConnect(response, origin + '/sanal_pos/mail_order/bin')

    def test_http_loopback_disi_ana_makine_reddedilir(self):
        self.assertNoConnect(self.proxied('odoo.ugurlar.test', proto='http'))

    def test_gecersiz_ana_makine_degerleri_reddedilir_enjeksiyon_yok(self):
        bad_hosts = ['a.b/x;script-src *', 'evil.com;default-src *', 'evil.com *', 'user@evil.com',
                     'evil.com/yol', 'evil.com?x=1', 'evil.com#x', "evil.com'", 'evil.com,', 'ev il.com',
                     'evil.com:abc', 'evil.com:123456', '[::1]x', 'evil_host.com:80x']
        for host in bad_hosts:
            with self.subTest(host=host):
                response = self.proxied(host)
                if response.status_code in (400, 500):
                    # Odoo çekirdeği (http.py) bozuk Host'u addon'a girmeden 400/500 ile reddeder: güvenli yön,
                    # sayfa/CSP/betik hiç sunulmaz (connect-src'de host yok, enjeksiyon yok).
                    self.assertNotIn('connect-src', response.headers.get('Content-Security-Policy', ''))
                    self.assertNotIn('evil', response.headers.get('Content-Security-Policy', ''))
                    continue
                self.assertNoConnect(response)
                policy = self.csp(response)
                self.assertEqual(policy.get('script-src', [''])[0][:8], "'sha256-", 'script-src enjekte edilmedi')
                self.assertEqual(len(policy.get('script-src', [])), 1)
                self.assertEqual(policy.get('default-src'), ["'none'"])

    def test_gecersiz_host_uyari_loglar_yalniz_host_bin_yok(self):
        """Geçerli ana makine ama http (loopback değil): connect-src basılmaz, uyarı yalnız host'u yazar (R18)."""
        with self.assertLogs('odoo.addons.sanal_pos', level='WARNING') as captured:
            response = self.proxied('odoo.ugurlar.test', proto='http')
        self.assertEqual(response.status_code, 200)
        text = '\n'.join(r.getMessage() for r in captured.records)
        self.assertIn('odoo.ugurlar.test', text)
        self.assertNotIn(LEAK_BIN, text)
        self.assertNotIn(LEAK_PAN, text)

    def test_connect_src_yalniz_tek_kaynak_ve_yol_sabit(self):
        response = self.proxied('odoo.ugurlar.test')
        sources = self.csp(response)['connect-src']
        self.assertEqual(len(sources), 1)
        self.assertNotIn('*', sources[0])
        self.assertNotIn("'self'", sources[0])
        self.assertTrue(sources[0].endswith('/sanal_pos/mail_order/bin'))
        self.assertFalse(sources[0].endswith('/'))


# ======================================================================================
# card_page_csp birimi (connect_src doğrulaması; _CSP_SOURCE_RE daraltması)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardPageCspUnit(BinHttpCase):

    def csp_func(self):
        from odoo.addons.sanal_pos.controllers.mail_order import card_page_csp
        return card_page_csp

    def parse(self, header):
        policy = {}
        for part in header.split(';'):
            tokens = part.strip().split()
            if tokens:
                policy[tokens[0]] = tokens[1:]
        return policy

    def test_gecerli_connect_src_basilir(self):
        csp = self.csp_func()
        header = csp('https://secure.paratika.com.tr', script_hash='A' * 43 + '=',
                     connect_src='https://odoo.ugurlar.test/sanal_pos/mail_order/bin')
        self.assertEqual(self.parse(header)['connect-src'], ['https://odoo.ugurlar.test/sanal_pos/mail_order/bin'])

    def test_connect_src_verilmezse_direktif_yok(self):
        csp = self.csp_func()
        self.assertNotIn('connect-src', self.parse(csp('https://secure.paratika.com.tr')))
        self.assertNotIn('connect-src', self.parse(csp()))

    def test_gecersiz_connect_src_value_error(self):
        csp = self.csp_func()
        for bad in ('http://evil.com', 'http://odoo.ugurlar.test/sanal_pos/mail_order/bin',
                    'https://a.b/x;', 'https://a.b/x y', 'https://a.b/x;script-src *', 'https://*.a.b/x',
                    'https://user@a.b/x', 'ftp://a.b/x', '//a.b/x', "https://a.b/x'", 'https://a.b/x,https://c.d/y',
                    'https://a b/x', 'javascript:alert(1)', 'https://'):
            with self.subTest(deger=bad):
                with self.assertRaises(ValueError):
                    csp('https://secure.paratika.com.tr', connect_src=bad)

    def test_http_yalniz_loopback(self):
        csp = self.csp_func()
        for ok in ('http://localhost/sanal_pos/mail_order/bin', 'http://127.0.0.1:8069/sanal_pos/mail_order/bin',
                   'http://localhost:8069/sanal_pos/mail_order/bin'):
            with self.subTest(deger=ok):
                self.assertEqual(self.parse(csp('https://secure.paratika.com.tr', connect_src=ok))['connect-src'],
                                 [ok])

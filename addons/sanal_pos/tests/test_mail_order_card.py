# -*- coding: utf-8 -*-
"""Mail Order kart sayfası Aşama 1 kabul testleri (KK-1.1..1.19, NFR-1.x).

Kaynak: .ekip/20261023-mo-kart-pro/01-gereksinimler.md (KK-1.x) ve 02-tasarim.md §3.

Bu dosya DIŞARIDAN gözlenen davranışı sınar: gerçek HTTP yanıtı (HttpCase), gerçek CSP başlığı,
gerçek HTML. İşaretleme kimlikleri (``#mo-form``, ``#pan``, ``#mo-pay-text`` ...) tasarım §3.4
sözleşmesidir. Tarayıcıda çalışan davranışlar (PAN gruplama, Luhn, canlı marka, toplam yansıması,
sayaç, koyu mod, mobil, CSP ihlali yok, tek POST) burada SINANAMAZ; ``04-kabul-testleri.md``
içindeki "Playwright ile doğrulanacak" listesindedir (A1-G4).

``tools.mail_order_script`` / ``MAIL_ORDER_JS_FILE`` henüz yokken yalnız ilgili testler kırmızı
olsun diye ``tools`` içe aktarması fonksiyonlar içinde yapılır.
"""
import base64
import hashlib
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from itertools import count
from unittest.mock import patch
from urllib.parse import urlsplit

import pytz
from lxml import html as lxml_html

from odoo.tests import tagged

from .common import (
    CUSTOMER_NAME, EMAIL, INV_NO, LEAK_PAN, MAIL_ORDER_PAY_PATH, MAIL_ORDER_RETURN_PATH,
    TEST_URL_PREFIX, SanalPosCase, installment_body, timeout_exc,
)
from .test_mail_order_http import MoHttpCase

SCRIPT_RE = re.compile(r'<script\b[^>]*>(.*?)</script>', re.S | re.I)
SHA_SOURCE_RE = re.compile(r"^'sha256-[A-Za-z0-9+/]{43}='$")
PARATIKA_TEST_ORIGIN = '{0.scheme}://{0.netloc}'.format(urlsplit(TEST_URL_PREFIX))
SCRIPT_ICP = 'sanal_pos.mail_order_script'
PARATIKA_TEST_CARD = '4355084355084358'
_NS = count(1)


def sha256_b64(text):
    return base64.b64encode(hashlib.sha256(text.encode('utf-8')).digest()).decode('ascii')


def norm(text):
    return ' '.join(text.split())


def _tools():
    from odoo.addons.sanal_pos import tools
    return tools


@contextmanager
def script_file(content, approve=True):
    """``tools.MAIL_ORDER_JS_FILE`` geçici bir dosyaya yönlendirilir (``content``: bayt ya da None).

    ``None`` -> var olmayan dosya. mtime her seferinde benzersiz (süreç içi önbellek anahtarı).
    ``approve``: içerik okunabiliyorsa onaylı hash (``MAIL_ORDER_SCRIPT_SHA256``) de ona yamalanır
    (kod incelemesinden geçmiş betiği taklit eder); ``False`` -> onaysız değişiklik (D-2).
    """
    tools = _tools()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'mail_order_card.js')
        if content is not None:
            with open(path, 'wb') as handle:
                handle.write(content)
            stamp = time.time_ns() + next(_NS) * 10 ** 9
            os.utime(path, ns=(stamp, stamp))
        with patch.object(tools, 'MAIL_ORDER_JS_FILE', path):
            pin = tools.MAIL_ORDER_SCRIPT_SHA256
            if approve:
                try:
                    pin = tools._read_mail_order_script()[1]
                except (OSError, ValueError):
                    pass                        # bozuk/yok: denetim zaten okumada düşer
            with patch.object(tools, 'MAIL_ORDER_SCRIPT_SHA256', pin):
                yield path


class CardPageCase(MoHttpCase):

    def page(self, payment, user=None, **kw):
        self.login_as(user or self.user_sp)
        return self.url_open(MAIL_ORDER_PAY_PATH % payment.id, allow_redirects=False, **kw)

    def body(self, response):
        """Ham yanıt gövdesi (requests satır sonlarını çevirmez; bayt -> UTF-8)."""
        return response.content.decode('utf-8')

    def doc(self, response):
        return lxml_html.fromstring(self.body(response))

    def script_blocks(self, response):
        return SCRIPT_RE.findall(self.body(response))

    def text_of(self, response, xpath='//main'):
        return norm(self.doc(response).xpath(xpath)[0].text_content())

    def without_script(self, response):
        return SCRIPT_RE.sub('<script></script>', self.body(response))


# ======================================================================================
# KK-1.14 / KK-1.19 / NFR-1.2: script, CSP, hash (gerçek yanıt)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardPageScriptCsp(CardPageCase):

    def test_kk_1_14a_tam_bir_script_head_icinde_ve_harici_kaynak_yok(self):
        response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 200)
        body = self.body(response)
        self.assertEqual(body.lower().count('<script'), 1, 'sayfada tam 1 <script> olmalı')
        doc = self.doc(response)
        scripts = doc.xpath('//script')
        self.assertEqual(len(scripts), 1)
        self.assertEqual(len(doc.xpath('//head/script')), 1, 'script <head> içinde olmalı')
        self.assertEqual(scripts[0].attrib.get('src'), None, 'harici (src) script yok')
        self.assertNotIn('mail_order_card.js', body, 'JS dosyası adresle çağrılmaz; içerik satır içi')
        self.assertTrue((scripts[0].text or '').strip(), 'script boş olmamalı')

    def test_kk_1_14b_csp_script_src_yalniz_tek_sha256(self):
        response = self.page(self.make_mail_order())
        policy = self.csp(response)
        self.assertIn('script-src', policy)
        self.assertEqual(len(policy['script-src']), 1, policy['script-src'])
        self.assertRegex(policy['script-src'][0], SHA_SOURCE_RE)
        header = response.headers['Content-Security-Policy']
        for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "'strict-dynamic'", 'https:', 'http:',
                          '*', "'self'", 'data:', "'unsafe-hashes'", "'nonce-"):
            self.assertNotIn(forbidden, ' '.join(policy['script-src']), forbidden)
        self.assertNotIn("'unsafe-inline'", header)
        self.assertNotIn("'unsafe-eval'", header)
        self.assertNotIn("'strict-dynamic'", header)

    def test_kk_1_14b_hash_servis_edilen_script_icerigine_esit(self):
        response = self.page(self.make_mail_order())
        blocks = self.script_blocks(response)
        self.assertEqual(len(blocks), 1)
        content = blocks[0]
        self.assertNotIn('\r', content, 'tarayıcı CRLF\'yi LF yapar; basılan metin LF olmalı')
        self.assertNotEqual(content.strip(), '')
        self.assertEqual(self.csp(response)['script-src'], ["'sha256-%s'" % sha256_b64(content)])

    def test_nfr_1_2_html_betigi_ve_hash_tek_kaynaktan_tools_mail_order_script(self):
        tools = _tools()
        text, digest = tools.mail_order_script()
        response = self.page(self.make_mail_order())
        content = self.script_blocks(response)[0]
        self.assertEqual(content, text, 'HTML\'deki script, tools.mail_order_script() ile bayt bayt aynı olmalı')
        self.assertEqual(self.csp(response)['script-src'], ["'sha256-%s'" % digest])
        self.assertEqual(digest, sha256_b64(text))

    def test_nfr_1_2_dosya_degisince_icerik_ve_hash_birlikte_degisir_crlf_bom(self):
        payload = 'void 0;\r\n/* ç ğ ş */\r\n'.encode('utf-8')
        with script_file(b'\xef\xbb\xbf' + payload):
            response = self.page(self.make_mail_order())
            self.assertEqual(response.status_code, 200)
            blocks = self.script_blocks(response)
            self.assertEqual(blocks, ['void 0;\n/* ç ğ ş */\n'])
            self.assertEqual(self.csp(response)['script-src'],
                             ["'sha256-%s'" % sha256_b64('void 0;\n/* ç ğ ş */\n')])

    def test_kk_1_14c_connect_src_yalniz_bin_ucu_default_src_none(self):
        """A2 (B-1): Aşama 1'deki "connect-src yok" sözleşmesi değişti. Script'li sayfada
        ``connect-src`` TAM olarak ``<host_url>/sanal_pos/mail_order/bin`` olur (başka kaynak yok);
        ``default-src 'none'`` korunur. HttpCase loopback (http://127.0.0.1:port) olduğu için http kabul."""
        response = self.page(self.make_mail_order())
        policy = self.csp(response)
        host_url = '{0.scheme}://{0.netloc}'.format(urlsplit(response.url))
        self.assertEqual(policy.get('connect-src'), [host_url + '/sanal_pos/mail_order/bin'])
        self.assertEqual(policy.get('default-src'), ["'none'"])

    def test_kk_1_14e_diger_basliklar_degismez(self):
        response = self.page(self.make_mail_order())
        policy = self.csp(response)
        self.assertEqual(policy.get('form-action'), [PARATIKA_TEST_ORIGIN], 'form-action yalnız Paratika')
        self.assertEqual(policy.get('frame-ancestors'), ["'none'"])
        self.assertEqual(policy.get('base-uri'), ["'none'"])
        self.assertEqual(policy.get('style-src'), ["'self'"])
        self.assertEqual(policy.get('img-src'), ["'self'"])
        self.assertEqual(sorted(policy), ['base-uri', 'connect-src', 'default-src', 'form-action',
                                          'frame-ancestors', 'img-src', 'script-src', 'style-src'],
                         'Aşama 2\'de CSP\'ye script-src (A1) ve connect-src (A2) eklenir')
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Cross-Origin-Opener-Policy'), 'same-origin')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(response.headers.get('Referrer-Policy'), 'no-referrer')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')

    def test_kk_1_14d_satir_ici_olay_isleyici_ve_stil_yok(self):
        response = self.page(self.make_mail_order())
        markup = self.without_script(response).lower()
        self.assertIsNone(re.search(r'\son[a-z]+\s*=', markup), 'satır içi olay işleyicisi')
        self.assertNotIn(' style=', markup)
        self.assertNotIn('<style', markup)
        self.assertNotIn('javascript:', markup)
        self.assertNotIn('<iframe', markup)
        self.assertNotIn('/web/assets', markup)

    def test_kk_1_14f_hata_403_ve_donus_sayfalari_scriptsiz_csp_ayni(self):
        self.login_as(self.user_sp)
        pages = {
            'suresi_dolmus_409': self.page(self.make_mail_order(invoice_no='S-1', state='expired')),
            'odendi_409': self.page(self.make_mail_order(invoice_no='S-2', state='paid')),
            'yok_404': self.url_open(MAIL_ORDER_PAY_PATH % 99999999, allow_redirects=False),
            'yetkisiz_403': self.page(self.make_mail_order(invoice_no='S-3'), self.user_plain),
            'mo_return': self.url_open(MAIL_ORDER_RETURN_PATH, data={'MERCHANTPAYMENTID': 'X-1-1'},
                                       method='POST'),
        }
        for name, response in pages.items():
            with self.subTest(sayfa=name):
                self.assertNotIn('<script', self.body(response).lower())
                policy = self.csp(response)
                self.assertNotIn('script-src', policy)
                self.assertNotIn('connect-src', policy)
                self.assertEqual(policy.get('default-src'), ["'none'"])
                self.assertEqual(policy.get('frame-ancestors'), ["'none'"])
        self.assertEqual(pages['suresi_dolmus_409'].status_code, 409)
        self.assertEqual(pages['yetkisiz_403'].status_code, 403)
        self.assertEqual(self.csp(pages['mo_return']).get('style-src'), ["'self'"])

    def test_hatali_paratika_adresi_500_sayfasi_scriptsiz(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'sanal_pos.paratika_test_url', 'https://paratika.evil.example/paratika/api/v2')
        response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('<script', self.body(response).lower())
        self.assertNotIn('script-src', self.csp(response))
        self.assertEqual(self.csp(response).get('form-action'), ["'none'"])

    def test_kk_1_19_kart_alanlarinda_value_yok_form_action_sale3d(self):
        payment = self.make_mail_order(provider_token='TOK-A1')
        doc = self.doc(self.page(payment))
        forms = doc.xpath('//form')
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form.get('id'), 'mo-form')
        self.assertEqual(form.get('method', '').lower(), 'post')
        self.assertEqual(form.get('action'), TEST_URL_PREFIX + '/post/sale3d/TOK-A1')
        self.assertEqual((form.get('autocomplete') or '').lower(), 'off')
        for field_id in ('cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv'):
            found = form.xpath('.//*[@id="%s"]' % field_id)
            self.assertEqual(len(found), 1, field_id)
            self.assertEqual(found[0].get('name'), field_id)
            self.assertFalse(found[0].get('value'), '%s alanında value var' % field_id)
            self.assertFalse(found[0].xpath('.//option[@selected]'), field_id)
        names = {el.get('name') for el in form.xpath('.//input|.//select|.//textarea') if el.get('name')}
        self.assertEqual(names, {'cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv', 'installmentCount'})

    def test_sunucu_mo_js_sinifini_yazmaz_script_acar(self):
        # Script'siz mod varsayılandır; ``html.mo-js`` yalnız başarılı kurulumdan sonra script ekler
        html_class = self.doc(self.page(self.make_mail_order())).xpath('//html/@class')
        self.assertNotIn('mo-js', ' '.join(html_class))

    def test_kullanici_verisinden_ikinci_script_enjekte_edilemez(self):
        payment = self.make_mail_order(customer_name='<script>alert(1)</script><img src=x onerror=alert(2)>')
        response = self.page(payment)
        self.assertEqual(response.status_code, 200)
        body = self.body(response)
        self.assertEqual(body.lower().count('<script'), 1)
        self.assertEqual(len(self.doc(response).xpath('//img[@onerror]|//*[@src="x"]')), 0)
        self.assertNotIn('<script>alert', body)
        self.assertIn('&lt;script&gt;alert(1)', body)

    # ---- kapatma anahtarı (geri alma, §3.9)
    def test_kapatma_anahtari_false_scriptsiz_sayfa_calismaya_devam_eder(self):
        self.env['ir.config_parameter'].sudo().set_param(SCRIPT_ICP, 'False')
        payment = self.make_mail_order(provider_token='TOK-OFF')
        response = self.page(payment)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script', self.body(response).lower())
        policy = self.csp(response)
        self.assertNotIn('script-src', policy)
        self.assertNotIn('connect-src', policy)
        self.assertEqual(policy.get('default-src'), ["'none'"])
        self.assertEqual(policy.get('form-action'), [PARATIKA_TEST_ORIGIN])
        form = self.doc(response).xpath('//form[@id="mo-form"]')[0]
        self.assertEqual(form.get('action'), TEST_URL_PREFIX + '/post/sale3d/TOK-OFF')
        self.assertEqual(len(form.xpath('.//input[@name="pan"]')), 1)
        self.assertEqual(len(form.xpath('.//input[@name="installmentCount"]')), 1)

    def test_kapatma_anahtari_bool_bicimleri_kapatir_d1(self):
        """D-1/Ö-2: anahtar get_bool_param ile okunur; elle yazılan 'false'/'0' de kapatır."""
        params = self.env['ir.config_parameter'].sudo()
        # D-4 (A2): izin listesi dışındaki HER değer kapatır (yazım hatası, boş, boşluk dahil)
        for value in ('false', '0', 'FALSE', ' False', 'no', 'off', 'hayır', 'kapalı', '', '   ',
                      'tru', 'acik', '2'):
            with self.subTest(deger=value):
                params.set_param(SCRIPT_ICP, value)
                response = self.page(self.make_mail_order(invoice_no='OFF-%s' % value.strip()))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('<script', self.body(response).lower())
                self.assertNotIn('script-src', self.csp(response))
                self.assertNotIn('connect-src', self.csp(response))
                form = self.doc(response).xpath('//form[@id="mo-form"]')[0]
                self.assertIsNone(form.get('data-bin'), 'betik yokken data-bin da olmaz')

    def test_kapatma_anahtari_acikken_script_var_yalniz_izin_listesi(self):
        params = self.env['ir.config_parameter'].sudo()
        for value in ('True', '1', 'evet', 'yes', ' TRUE ', 'Evet'):
            with self.subTest(deger=value):
                params.set_param(SCRIPT_ICP, value)
                response = self.page(self.make_mail_order(invoice_no='ON-%s' % value.strip()))
                self.assertEqual(self.body(response).lower().count('<script'), 1)
                self.assertIn('script-src', self.csp(response))
                self.assertIn('connect-src', self.csp(response))

    def test_kapatma_anahtari_yoksa_script_acik_d4(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', SCRIPT_ICP)]).unlink()
        response = self.page(self.make_mail_order(invoice_no='ON-YOK'))
        self.assertEqual(self.body(response).lower().count('<script'), 1)
        self.assertIn('script-src', self.csp(response))

    def test_get_bool_param_genel_davranisi_degismez_d4(self):
        """D-4 yalnız kapatma anahtarını sıkılaştırır; ``get_bool_param`` ortak davranışı (yok ->
        varsayılan, '', 'false', '0', 'no', 'none' dışı -> True) aynı kalır (başka ayarlar ona bağlı)."""
        from odoo.addons.sanal_pos.models.res_config_settings import get_bool_param
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('sanal_pos.test_anahtar_d4', 'acik')
        self.assertTrue(get_bool_param(self.env, 'sanal_pos.test_anahtar_d4', default=False))
        params.set_param('sanal_pos.test_anahtar_d4', 'False')
        self.assertFalse(get_bool_param(self.env, 'sanal_pos.test_anahtar_d4', default=True))
        self.assertTrue(get_bool_param(self.env, 'sanal_pos.test_anahtar_yok_d4', default=True))

    def test_script_dosyasi_yoksa_sayfa_scriptsiz_acilir(self):
        with script_file(None):
            response = self.page(self.make_mail_order(provider_token='TOK-NOFILE'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script', self.body(response).lower())
        self.assertNotIn('script-src', self.csp(response))
        self.assertEqual(self.doc(response).xpath('//form/@action'), [TEST_URL_PREFIX + '/post/sale3d/TOK-NOFILE'])

    def test_onaysiz_betik_sunulmaz_scriptsiz_acilir_ve_loglanir_d2(self):
        """D-2 (PCI 11.6.1): geçerli ama onaylı hash'i tutmayan betik çalışma anında reddedilir."""
        with script_file(b'var onaysiz = 1;\n', approve=False), \
                self.assertLogs('odoo.addons.sanal_pos.controllers.mail_order', 'ERROR') as logs:
            response = self.page(self.make_mail_order(provider_token='TOK-UNPINNED'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script', self.body(response).lower())
        self.assertNotIn('script-src', self.csp(response))
        self.assertIn('MailOrderScriptHashMismatch', '\n'.join(logs.output))
        self.assertNotIn('onaysiz', '\n'.join(logs.output))       # içerik loglanmaz

    def test_script_dosyasi_bozuksa_sayfa_scriptsiz_acilir(self):
        for name, content in (('script_kapatan', b'var x = "</script><b>";'),
                              ('html_yorumu', b'var y = "<!--";'),
                              ('buyuk_harf', b'var z = "</SCRIPT >";')):
            with self.subTest(durum=name), script_file(content):
                response = self.page(self.make_mail_order(invoice_no='BAD-%s' % name))
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('<script', self.body(response).lower())
                self.assertNotIn('script-src', self.csp(response))
                self.assertNotIn('<b>', self.body(response))


# ======================================================================================
# KK-1.1 .. KK-1.12: işaretleme, metinler, taksit kartları, özet
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardPageMarkup(CardPageCase):

    # ---- KK-1.1 PAN örnek metni/ipucu tutarlılığı
    def test_kk_1_1_pan_ornek_metin_desen_ve_ipucu_tutarli(self):
        response = self.page(self.make_mail_order())
        doc = self.doc(response)
        pan = doc.xpath('//input[@id="pan"]')[0]
        self.assertEqual(pan.get('placeholder'), '1234567812345678')
        self.assertNotEqual(pan.get('placeholder'), PARATIKA_TEST_CARD)
        self.assertEqual(pan.get('pattern'), '[0-9]{12,19}')
        self.assertEqual(pan.get('maxlength'), '19')
        self.assertEqual(pan.get('inputmode'), 'numeric')
        self.assertEqual(pan.get('autocomplete'), 'off')
        self.assertEqual(pan.get('aria-describedby'), 'pan-hint')
        self.assertRegex(pan.get('placeholder'), r'^%s$' % pan.get('pattern'),
                         'örnek metin kendi deseninden geçmeli (çelişki yok)')
        self.assertNotIn(PARATIKA_TEST_CARD, self.body(response), 'Paratika test kartı sayfada geçmemeli')
        hint = doc.xpath('//*[@id="pan-hint"]')[0]
        nojs = hint.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " mo-nojs-only ")]')
        js = hint.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " mo-js-only ")]')
        self.assertTrue(nojs and js, 'ipucu iki modun metnini de taşır; CSS seçer')
        nojs_text = norm(' '.join(e.text_content() for e in nojs))
        js_text = norm(' '.join(e.text_content() for e in js))
        self.assertIn('Yalnız rakam, boşluksuz (12-19 hane)', nojs_text)
        self.assertIn('1234567812345678', nojs_text)
        self.assertIn('Rakamlar otomatik gruplanır', js_text)
        self.assertIn('0000 0000 0000 0000', js_text)
        self.assertNotIn('Rakamlar otomatik gruplanır', nojs_text)
        self.assertNotIn('Yalnız rakam, boşluksuz', js_text)

    # ---- KK-1.2 CVV ipucu, Amex, logolar
    def test_kk_1_2_cvv_ipucu_amex_ifadesi_yok_logolar_visa_mastercard_troy(self):
        response = self.page(self.make_mail_order())
        doc = self.doc(response)
        main_text = self.text_of(response)
        self.assertIn('Kartın arkasındaki 3 haneli kod', main_text)
        self.assertNotIn('Amex', main_text)
        self.assertNotIn('4 hane', main_text)
        self.assertEqual(sorted(doc.xpath('//span[contains(@class,"mo-cards")]/img/@alt')),
                         ['Mastercard', 'Troy', 'Visa'])
        self.assertEqual(sorted(doc.xpath('//*[contains(@class,"mo-cards")]//img/@data-brand')),
                         ['mastercard', 'troy', 'visa'])
        self.assertTrue(doc.xpath('//*[contains(@class,"mo-cards")][@data-brand]'),
                        'script marka yazabilsin: .mo-cards[data-brand]')
        cvv = doc.xpath('//input[@id="cvv"]')[0]
        self.assertEqual(cvv.get('type'), 'password')
        self.assertEqual(cvv.get('pattern'), '[0-9]{3,4}')
        self.assertEqual(cvv.get('maxlength'), '4')
        self.assertEqual(cvv.get('inputmode'), 'numeric')
        amex = doc.xpath('//*[@id="mo-amex"]')
        self.assertEqual(len(amex), 1)
        self.assertIsNotNone(amex[0].get('hidden'), 'uyarı varsayılan gizli')
        self.assertIn('American Express kabul edilmeyebilir', norm(amex[0].text_content()))

    # ---- KK-1.3 taksit radyo kartları
    def test_kk_1_3_taksit_secenekleri_radyo_kartlari_select_ve_tablo_yok(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(2, 0), (3, 1.5), (6, 3.0)])))
        payment = self.make_mail_order()
        response = self.page(payment)
        doc = self.doc(response)
        self.assertFalse(doc.xpath('//select[@name="installmentCount"]'), 'açılır liste kalkar')
        self.assertFalse(doc.xpath('//main//details'), 'katlanabilir taksit tablosu kalkar')
        self.assertFalse(doc.xpath('//main//table'), 'taksit tablosu kalkar')
        radios = doc.xpath('//form[@id="mo-form"]//fieldset//input[@type="radio"][@name="installmentCount"]')
        self.assertEqual([r.get('value') for r in radios], ['1', '2', '3', '6'])
        self.assertEqual([r.get('value') for r in radios if r.get('checked') is not None], ['1'],
                         'açılışta yalnız Tek çekim seçili')
        self.assertTrue(doc.xpath('//fieldset[contains(@class,"mo-inst")]/legend'))
        for radio in radios:
            self.assertEqual(len(radio.xpath('./ancestor::label[contains(@class,"mo-inst-card")]')), 1)
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 1)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)

    def test_kk_1_3_kart_degerleri_installment_table_ile_ayni(self):
        tools = _tools()
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(2, 0), (3, 1.5), (6, 3.0)])))
        payment = self.make_mail_order(amount=1450.0)
        doc = self.doc(self.page(payment))
        expected = tools.installment_table(1450.0, [
            {'count': 2, 'networks': ['AXESS'], 'rate': 0},
            {'count': 3, 'networks': ['AXESS'], 'rate': 1.5},
            {'count': 6, 'networks': ['AXESS'], 'rate': 3.0}])['rows']
        radios = doc.xpath('//input[@type="radio"][@name="installmentCount"]')
        self.assertEqual(len(radios), len(expected))
        for radio, row in zip(radios, expected):
            with self.subTest(taksit=row['count']):
                label = norm(radio.xpath('./ancestor::label')[0].text_content())
                self.assertEqual(radio.get('value'), str(row['count']))
                self.assertEqual(radio.get('data-label'), row['label'])
                for attr, key in (('data-total', 'total_text'), ('data-monthly', 'monthly_text')):
                    number = row[key].replace(' TL', '')
                    self.assertIn(number, radio.get(attr) or '', attr)
                    self.assertIn(number, label, '%s kartta görünmeli' % key)
                self.assertEqual(bool(row['surcharge_text']), bool(radio.get('data-surcharge')))
                self.assertIn(row['label'], label)
                if row['count'] > 1:
                    self.assertIn(row['rate_text'], label)     # oran ya da "Vade farkı yok"

    def test_kk_1_4_ornek_3_taksit_1450_tl_kartta_ve_veri_ozniteliklerinde(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(3, 13.57)])))
        payment = self.make_mail_order(amount=1450.0)
        doc = self.doc(self.page(payment))
        radio = doc.xpath('//input[@type="radio"][@name="installmentCount"][@value="3"]')[0]
        self.assertIn('1.646,77', radio.get('data-total'))
        self.assertIn('548,92', radio.get('data-monthly'))
        self.assertIn('196,77', radio.get('data-surcharge'))
        self.assertEqual(radio.get('data-label'), '3 taksit')
        label = norm(radio.xpath('./ancestor::label')[0].text_content())
        for needle in ('3 taksit', '548,92', '1.646,77', '%13,57', '196,77'):
            self.assertIn(needle, label)
        single = doc.xpath('//input[@type="radio"][@value="1"]')[0]
        self.assertEqual(single.get('data-label'), 'Tek çekim')
        self.assertIn('1.450,00', single.get('data-total'))
        self.assertFalse(single.get('data-surcharge'), 'tek çekimde vade farkı yok')

    def test_kk_1_3_programlar_satir_satir_farkliysa_kartta_program_adi(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(
            ('A', 'PARAF', [(2, 0), (3, 1.5)]), ('B', 'BONUS', [(2, 0)])))
        doc = self.doc(self.page(self.make_mail_order()))
        cards = {r.get('value'): norm(r.xpath('./ancestor::label')[0].text_content())
                 for r in doc.xpath('//input[@type="radio"][@name="installmentCount"]')}
        self.assertEqual(sorted(cards), ['1', '2', '3'])
        self.assertIn('Paraf', cards['2'])
        self.assertIn('Bonus', cards['2'])
        self.assertIn('Paraf', cards['3'])
        self.assertNotIn('Bonus', cards['3'])
        self.assertNotIn('Paraf', cards['1'])

    def test_kk_1_3_ortak_program_kartlarda_tekrarlanmaz_ham_ad_gorunmez(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(
            ('A', 'PARAF', [(2, 0), (3, 1.5)]), ('B', 'UNKNOWN', [(2, 0), (3, 1.5)]),
            ('C', 'KVY_NTW', [(2, 0), (3, 1.5)])))
        response = self.page(self.make_mail_order())
        doc = self.doc(response)
        text = self.text_of(response)
        self.assertIn('Paraf', text)
        self.assertIn('Kuveyt Türk (Sağlam Kart)', text)
        self.assertNotIn('UNKNOWN', text)
        self.assertNotIn('KVY_NTW', text)
        for radio in doc.xpath('//input[@type="radio"][@name="installmentCount"]'):
            card = norm(radio.xpath('./ancestor::label')[0].text_content())
            self.assertNotIn('Paraf', card, 'ortak program her kartta tekrarlanmaz')
        self.assertEqual([r.get('value') for r in doc.xpath('//input[@type="radio"]')], ['1', '2', '3'])

    # ---- KK-1.5 sorgu hatası / boş
    def test_kk_1_5_sorgu_hatasinda_yalniz_tek_cekim_ve_not(self):
        self.mock.queue('QUERYINSTALLMENT', timeout_exc())
        response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 200)
        doc = self.doc(response)
        radios = doc.xpath('//input[@type="radio"][@name="installmentCount"]')
        self.assertEqual([(r.get('value'), r.get('checked') is not None) for r in radios], [('1', True)])
        self.assertIn('Taksit seçenekleri alınamadı; tek çekim yapılabilir.', self.text_of(response))
        self.assertEqual(len(doc.xpath('//input[@name="pan"]')), 1)

    def test_kk_1_5_bos_taksit_listesinde_de_not_ve_tek_cekim(self):
        response = self.page(self.make_mail_order())         # mock varsayılanı: boş liste
        radios = self.doc(response).xpath('//input[@type="radio"][@name="installmentCount"]')
        self.assertEqual([r.get('value') for r in radios], ['1'])
        self.assertIn('Taksit seçenekleri alınamadı; tek çekim yapılabilir.', self.text_of(response))

    def test_kk_1_5_taksit_varken_alinamadi_notu_yok(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(2, 0)])))
        self.assertNotIn('Taksit seçenekleri alınamadı', self.text_of(self.page(self.make_mail_order())))

    # ---- KK-1.6
    def test_kk_1_6_kesin_tutar_notu_korunur(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(2, 0), (3, 1.5)])))
        text = self.text_of(self.page(self.make_mail_order())).lower()
        self.assertIn('kesin tutar banka sayfasında görünür', text)

    # ---- KK-1.7 adım şeridi
    def test_kk_1_7_adim_seridi_uc_adim_ilk_adim_etkin(self):
        doc = self.doc(self.page(self.make_mail_order()))
        steps = doc.xpath('//ol[contains(@class,"mo-steps")]/li')
        self.assertEqual(len(steps), 3)
        texts = [norm(s.text_content()) for s in steps]
        self.assertIn('Kart bilgisi', texts[0])
        self.assertIn('Banka SMS doğrulaması', texts[1])
        self.assertIn('Sonuç', texts[2])
        self.assertEqual([s.get('aria-current') for s in steps], ['step', None, None])

    # ---- KK-1.8 SKT / CVV grupları
    def test_kk_1_8_skt_ve_guvenlik_kodu_gruplari_cvv_ikonu(self):
        response = self.page(self.make_mail_order())
        doc = self.doc(response)
        text = self.text_of(response)
        self.assertIn('Son kullanma tarihi', text)
        self.assertIn('Güvenlik kodu', text)
        for field_id in ('cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv'):
            self.assertTrue(doc.xpath('//label[@for="%s"]' % field_id), 'etiket: %s' % field_id)
        svgs = doc.xpath('//form[@id="mo-form"]//svg')
        self.assertTrue(svgs, 'CVV yanında satır içi kart-arkası SVG ikonu')
        for svg in svgs:
            self.assertTrue(svg.get('width', '').isdigit() and svg.get('height', '').isdigit())
        self.assertFalse(doc.xpath('//form//img[contains(@src,"cvv")]'))

    # ---- KK-1.9 hata satırları (sunucu tarafı iskelet)
    def test_kk_1_9_alan_hata_satirlari_gizli_ve_erisilebilir(self):
        doc = self.doc(self.page(self.make_mail_order()))
        for name in ('cardOwner', 'pan', 'expiry', 'cvv'):
            with self.subTest(alan=name):
                rows = doc.xpath('//*[@id="%s-error"]' % name)
                self.assertEqual(len(rows), 1)
                self.assertIn('mo-error', rows[0].get('class', ''))
                self.assertIsNotNone(rows[0].get('hidden'), 'hata satırı varsayılan gizli')
                self.assertEqual(norm(rows[0].text_content()), '', 'başlangıçta boş (script doldurur)')
        for name in ('cardOwner', 'pan', 'cvv'):
            self.assertIsNone(doc.xpath('//*[@id="%s"]' % name)[0].get('aria-invalid'),
                              'başlangıçta aria-invalid yok')

    # ---- KK-1.10 güvenlik listesi
    def test_kk_1_10_guvenlik_uyarisi_en_cok_4_maddelik_liste(self):
        response = self.page(self.make_mail_order())
        doc = self.doc(response)
        items = [norm(li.text_content()) for li in doc.xpath('//main//ul/li')]
        self.assertTrue(items, 'güvenlik uyarısı <ul> olmalı')
        self.assertLessEqual(len(items), 4)
        joined = ' | '.join(items)
        for fragment in ('Kartı yalnız bu sayfaya girin',
                         'Kart bilgisini not almayın, mesajla/e-postayla almayın',
                         'Tarayıcıya kart kaydettirmeyin',
                         'SMS kodunu yalnız banka sayfasına girin'):
            self.assertIn(fragment, joined)
        self.assertIn('Güvenlik uyarısı', self.text_of(response))

    # ---- KK-1.4 / 1.12: düğme, özet, sayaç iskeleti (script'siz mod)
    def test_kk_1_4_scriptsiz_dugme_metni_ve_ozet_fatura_tutarini_gosterir(self):
        payment = self.make_mail_order(amount=1450.0)
        doc = self.doc(self.page(payment))
        button = doc.xpath('//form[@id="mo-form"]//button[@id="mo-pay"]')
        self.assertEqual(len(button), 1)
        self.assertEqual(button[0].get('type'), 'submit')
        self.assertEqual(len(button[0].xpath('./span[@id="mo-pay-text"]')), 1)
        self.assertEqual(norm(doc.xpath('//*[@id="mo-pay-text"]')[0].text_content()), 'Öde · 3D Secure')
        self.assertIn('1.450,00 TL', norm(doc.xpath('//*[@id="mo-sum-total"]')[0].text_content()))
        detail = doc.xpath('//*[@id="mo-sum-detail"]')
        self.assertEqual(len(detail), 1)
        self.assertTrue(detail[0].get('hidden') is not None or not norm(detail[0].text_content()),
                        'tek çekimde taksit ayrıntısı gizli/boş')

    def test_kk_1_12_kalan_sure_iskeleti_ve_sunucu_metni(self):
        payment = self.make_mail_order(expires_at=datetime.utcnow() + timedelta(minutes=42, seconds=30))
        response = self.page(payment)
        doc = self.doc(response)
        remaining = doc.xpath('//*[@id="mo-remaining"]')
        self.assertEqual(len(remaining), 1)
        seconds = int(remaining[0].get('data-seconds'))
        self.assertTrue(2500 <= seconds <= 2552, seconds)
        expired = doc.xpath('//*[@id="mo-expired"]')
        self.assertEqual(len(expired), 1)
        self.assertIsNotNone(expired[0].get('hidden'))
        self.assertIn('Oturum süresi doldu', norm(expired[0].text_content()))
        self.assertRegex(self.text_of(response), r'Son geçerlilik \d{2}:\d{2} · 4[23] dk kaldı')

    def test_a1_g3_betik_baglama_noktalari_now_ym_genel_hata_satiri(self):
        """Betik bunlardan biri eksikse kurulmaz (script'siz mod); sessiz gerilemeyi burada yakala."""
        doc = self.doc(self.page(self.make_mail_order()))
        istanbul_now = datetime.now(pytz.timezone('Europe/Istanbul'))
        form = doc.xpath('//form[@id="mo-form"]')[0]
        self.assertEqual(form.get('data-now-ym'), istanbul_now.strftime('%Y-%m'))
        years = doc.xpath('//select[@id="expiryYear"]/option[@value!=""]/@value')
        self.assertEqual(years[0], str(istanbul_now.year), 'yıl listesi ve now-ym aynı andan')
        error = form.xpath('.//*[@id="mo-form-error"]')
        self.assertEqual(len(error), 1)
        self.assertIsNotNone(error[0].get('hidden'))
        self.assertEqual((error[0].get('role'), error[0].get('class')), ('alert', 'mo-error'))
        expired = doc.xpath('//*[@id="mo-expired"]')[0]
        self.assertIn('kayda dönüp yeni deneme açın', norm(expired.text_content()))     # KK-1.12

    def test_kalan_sure_sifirken_data_seconds_0_basilir_o1(self):
        """Ö-1: QWeb t-att-* 0'ı basmaz; öznitelik düşerse betik kurulmaz ve kilit (KK-1.12) çalışmaz."""
        model = type(self.env['sanal.pos.payment'])
        with patch.object(model, '_mail_order_remaining',
                          lambda rec: {'remaining_seconds': 0, 'remaining_text': 'Süre doldu'}):
            doc = self.doc(self.page(self.make_mail_order()))
        remaining = doc.xpath('//*[@id="mo-remaining"]')[0]
        self.assertEqual(remaining.get('data-seconds'), '0')
        self.assertEqual(norm(remaining.text_content()), 'Süre doldu')

    def test_mjs_fikstur_kimlik_ve_data_oznitelikleri_sunucuda_basilir_o1(self):
        """Ö-1 GÖZLEM: mjs DOM taklidinin varsaydığı her kimlik/data-* sunucu HTML'inde gerçekten var.

        Kimlikler mjs'teki ``const ids = [...]`` listesinden okunur (fikstür değişirse bu test izler);
        data-* listesi mjs ``page()``/``radio()`` yardımcılarının yazdıklarıdır.
        """
        mjs = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'tests',
                           'mail_order_card.test.mjs')
        with open(mjs, encoding='utf-8') as handle:
            block = re.search(r'const ids = \[(.*?)\];', handle.read(), re.S).group(1)
        ids = re.findall(r"'([\w-]+)'", block)
        self.assertIn('mo-remaining', ids)
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(3, 13.57)])))
        doc = self.doc(self.page(self.make_mail_order(amount=1450.0)))
        for element_id in ids:
            self.assertEqual(len(doc.xpath('//*[@id="%s"]' % element_id)), 1, element_id)
        self.assertRegex(doc.xpath('//form[@id="mo-form"]/@data-now-ym')[0], r'^\d{4}-\d{2}$')
        self.assertRegex(doc.xpath('//*[@id="mo-remaining"]/@data-seconds')[0], r'^\d+$')
        self.assertEqual(doc.xpath('//*[contains(@class, "mo-cards")]/@data-brand'), [''])
        radios = doc.xpath('//form[@id="mo-form"]//input[@name="installmentCount"]')
        self.assertEqual([r.get('value') for r in radios], ['1', '3'])
        for radio in radios:
            for attr in ('data-label', 'data-total', 'data-monthly'):
                self.assertTrue(radio.get(attr), (radio.get('value'), attr))
        self.assertIsNone(radios[0].get('data-surcharge'))           # tek çekim: betik "Vade farkı yok"
        self.assertTrue(radios[1].get('data-surcharge'))

    # ---- KK-1.11 özet kartı + maskeleme
    def test_kk_1_11_ozet_kartinda_maskeli_telefon_eposta_aciklama_olusturan(self):
        payment = self.make_mail_order(customer_phone='5321112233', customer_email=EMAIL)
        response = self.page(payment)
        text = self.text_of(response)
        for needle in (INV_NO, CUSTOMER_NAME, '******2233', '***@example.com',
                       'Fatura %s tahsilatı · Ödeme no %s' % (INV_NO, payment.merchant_payment_id),
                       self.user_sp.name, 'Son geçerlilik', 'kaldı'):
            self.assertIn(needle, text)
        body = self.body(response)
        self.assertNotIn('5321112233', body, 'tam telefon HTML\'de olmamalı')
        self.assertNotIn(EMAIL, body, 'tam e-posta HTML\'de olmamalı')
        self.assertNotIn('cagri.sahin', body)

    def test_kk_1_11_degeri_olmayan_satir_gizlenir(self):
        payment = self.make_mail_order(customer_phone=False, customer_email=False)
        response = self.page(payment)
        self.assertEqual(response.status_code, 200)
        text = self.text_of(response)
        self.assertNotIn('******', text)
        self.assertNotIn('***@', text)
        self.assertNotIn('Telefon', text)
        self.assertNotIn('E-posta', text)
        self.assertNotIn('False', text)
        self.assertNotIn('None', text)

    def test_kk_1_11_olusturan_adi_yoksa_satir_gizlenir_o6(self):
        model = type(self.env['sanal.pos.payment'])
        original = model._mail_order_card_values
        with patch.object(model, '_mail_order_card_values',
                          lambda rec: {**original(rec), 'creator_name': ''}):
            response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Talebi oluşturan', self.text_of(response))

    def test_kk_1_11_telefon_eposta_kullanici_degeri_kacislanir(self):
        payment = self.make_mail_order(customer_name='Ali <i>Veli</i> & "Y"')
        response = self.page(payment)
        self.assertNotIn('<i>Veli</i>', self.body(response))
        self.assertIn('Ali &lt;i&gt;Veli&lt;/i&gt;', self.body(response))

    # ---- KK-1.19 gerileme: sorgu parametreleri/CSS sürümü
    def test_kk_1_19_sorgu_parametreleri_yansimaz_pan_deseni_degismez(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        query = '?pan=%s&cvv=123&cardOwner=ABC+XYZ&x=%%3Cb%%3E' % LEAK_PAN
        response = self.url_open(MAIL_ORDER_PAY_PATH % payment.id + query, allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        body = self.body(response)
        self.assertNotIn(LEAK_PAN, body)
        self.assertNotIn('ABC XYZ', body)
        self.assertNotIn('<b>', self.without_script(response))
        self.assertEqual(self.csp(response)['script-src'][0][:8], "'sha256-")


# ======================================================================================
# KK-1.11: model değerleri (_mail_order_card_values)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardValuesStage1(SanalPosCase):

    def values(self, payment):
        return payment.with_user(self.user_sp)._mail_order_card_values()

    def test_yeni_anahtarlar_maskeli_ve_aciklama(self):
        payment = self.make_mail_order()
        values = self.values(payment)
        self.assertEqual(values['phone_masked'], '******2233')
        self.assertEqual(values['email_masked'], '***@example.com')
        self.assertEqual(values['description'],
                         'Fatura %s tahsilatı · Ödeme no %s' % (INV_NO, payment.merchant_payment_id))
        self.assertEqual(values['merchant_payment_id'], payment.merchant_payment_id)
        self.assertEqual(values['creator_name'], self.user_sp.name)
        for key in ('payment_id', 'payment_name', 'form_action', 'invoice_no', 'customer_name', 'amount',
                    'amount_text', 'expires_at', 'expires_local', 'is_test', 'installments'):
            self.assertIn(key, values, 'mevcut anahtar korunur: %s' % key)

    def test_tam_telefon_ve_eposta_degerlere_girmez(self):
        values = self.values(self.make_mail_order())
        blob = repr(values)
        self.assertNotIn('5321112233', blob)
        self.assertNotIn(EMAIL, blob)
        self.assertNotIn('cagri.sahin', blob)

    def test_degeri_olmayan_alanlar_bos(self):
        values = self.values(self.make_mail_order(customer_phone=False, customer_email=False))
        self.assertFalse(values['phone_masked'])
        self.assertFalse(values['email_masked'])

    def test_olusturan_user_id_yoksa_create_uid(self):
        payment = self.make_mail_order()
        payment.sudo().write({'user_id': False})
        self.assertEqual(self.values(payment)['creator_name'], payment.sudo().create_uid.name)

    def test_son_gecerlilik_istanbul_saati_ve_kalan_sure(self):
        expires = (datetime.utcnow() + timedelta(minutes=42, seconds=30)).replace(microsecond=0)
        payment = self.make_mail_order(expires_at=expires)
        values = self.values(payment)
        local = pytz.UTC.localize(expires).astimezone(pytz.timezone('Europe/Istanbul')).strftime('%H:%M')
        self.assertEqual(values['expires_hm'], local)
        self.assertIsInstance(values['remaining_seconds'], int)
        self.assertTrue(2500 <= values['remaining_seconds'] <= 2552, values['remaining_seconds'])
        self.assertRegex(values['remaining_text'], r'^4[23] dk kaldı$')

    def test_kalan_sure_negatif_olmaz_ve_saat_birimi(self):
        """Ö-11: geçmiş son geçerlilik -> (0, 'Süre doldu'); saat birimi tam metinle."""
        payment = self.make_mail_order(expires_at=datetime.utcnow() + timedelta(hours=3, minutes=10))
        self.assertEqual(payment._mail_order_remaining()['remaining_text'], '3 sa 10 dk kaldı')
        payment.sudo().write({'expires_at': datetime.utcnow() - timedelta(minutes=5)})
        self.assertEqual(payment._mail_order_remaining(),
                         {'remaining_seconds': 0, 'remaining_text': 'Süre doldu'})
    def test_kart_verisi_alani_yok_degerlerde(self):
        values = self.values(self.make_mail_order())
        for key in values:
            self.assertFalse(re.search(r'(^|_)(pan|cvv|cvc)(_|$)|card_?(no|number)', key), key)

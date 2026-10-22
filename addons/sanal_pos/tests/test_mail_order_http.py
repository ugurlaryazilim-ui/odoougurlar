# -*- coding: utf-8 -*-
"""Mail Order HTTP testleri: kart sayfası, ``mo_return`` ve ``result`` rotaları (KK-1, KK-8, KK-11,
KK-17, KK-18 otomatik kısmı).

Gerçek HTTP (HttpCase.url_open). Tarayıcı davranışı (CSP ihlali, aynı sekme) elle doğrulanır.
"""
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from lxml import html as lxml_html

from odoo.tests import tagged

from .common import (
    CRON_SYNC_FLAGGED, CUSTOMER_NAME, EMAIL, INV_NO, LEAK_CVV, LEAK_OWNER, LEAK_PAN, LIVE_URL_PREFIX,
    MAIL_ORDER_PAY_PATH, MAIL_ORDER_RESULT_PATH, MAIL_ORDER_RETURN_PATH, TEST_URL_PREFIX,
    SanalPosHttpCase, installment_body, timeout_exc, tran,
)

PW = 'Mo!Test-9981'
LINK_ACTIONS = ('PAYBYLINKPAYMENT', 'PAYBYLINKPAYMENTRESEND', 'PAYBYLINKPAYMENTCANCEL',
                'QUERYPAYBYLINKPAYMENT')
WARNING_TEXT = ('Kart bilgisini yalnız bu ekrandan açılan kart sayfasına girin; not almayın, '
                'e-posta/mesajla almayın, tarayıcıya kaydettirmeyin. Banka doğrulama (SMS) kodunu '
                'müşteriden alıp yalnız banka sayfasına girin.')
CARD_FIELDS = {'cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv', 'installmentCount'}
PAYMENT_LIST = '/odoo/action-sanal_pos.action_sanal_pos_payment'
BODY_CARD = {'pan': LEAK_PAN, 'cvv': LEAK_CVV, 'cardOwner': LEAK_OWNER,
             'expiryMonth': '12', 'expiryYear': '2030'}


class MoHttpCase(SanalPosHttpCase):

    def login_as(self, user):
        user.sudo().write({'password': PW})
        self.authenticate(user.login, PW)

    def reload(self, record):
        record.invalidate_recordset()
        return record

    def link_calls(self):
        return self.mock.count(*LINK_ACTIONS)

    def csp(self, response):
        header = response.headers.get('Content-Security-Policy', '')
        policy = {}
        for part in header.split(';'):
            tokens = part.strip().split()
            if tokens:
                policy[tokens[0]] = tokens[1:]
        return policy


# ======================================================================================
# Kart sayfası
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardPage(MoHttpCase):

    def page(self, payment, user=None, **kw):
        self.login_as(user or self.user_sp)
        return self.url_open(MAIL_ORDER_PAY_PATH % payment.id, allow_redirects=False, **kw)

    def doc(self, response):
        return lxml_html.fromstring(response.text)

    def test_oturumsuz_giris_yonlendirmesi(self):
        payment = self.make_mail_order()
        response = self.url_open(MAIL_ORDER_PAY_PATH % payment.id, allow_redirects=False)
        self.assertIn(response.status_code, (301, 302, 303, 307))
        self.assertIn('/web/login', response.headers.get('Location', ''))
        self.assertNotIn('name="pan"', response.text)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)

    def test_grupsuz_kullanici_goremez_yetkili_gorur(self):
        payment = self.make_mail_order()
        response = self.page(payment, self.user_plain)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn('name="pan"', response.text)
        self.assertEqual(self.page(payment, self.user_sp).status_code, 200)       # olumlu çapa

    def test_basliklar(self):
        payment = self.make_mail_order()
        response = self.page(payment)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['Content-Type'])
        policy = self.csp(response)
        self.assertEqual(policy.get('default-src'), ["'none'"])
        self.assertEqual(policy.get('style-src'), ["'self'"])
        self.assertEqual(policy.get('img-src'), ["'self'"])
        self.assertEqual(policy.get('frame-ancestors'), ["'none'"])
        self.assertEqual(policy.get('base-uri'), ["'none'"])
        self.assertIn('https://test.paratika.com.tr', ' '.join(policy.get('form-action', [])))
        self.assertNotIn('script-src', policy)
        self.assertNotIn("'unsafe-inline'", response.headers['Content-Security-Policy'])
        self.assertNotIn("'unsafe-eval'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Referrer-Policy'), 'no-referrer')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')

    def test_form_yapisi(self):
        payment = self.make_mail_order(provider_token='TOK-FORM')
        doc = self.doc(self.page(payment))
        forms = doc.xpath('//form')
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form.get('method', '').lower(), 'post')
        self.assertEqual(form.get('action'), TEST_URL_PREFIX + '/post/sale3d/TOK-FORM')
        self.assertEqual((form.get('autocomplete') or '').lower(), 'off')
        names = {el.get('name') for el in form.xpath('.//input|.//select|.//textarea') if el.get('name')}
        self.assertEqual(names, CARD_FIELDS)
        for name in ('cardOwner', 'pan', 'expiryMonth', 'expiryYear', 'cvv'):
            el = form.xpath('.//*[@name="%s"]' % name)[0]
            self.assertFalse(el.get('value'), '%s alanında önceden doldurulmuş değer var' % name)
        self.assertEqual(form.xpath('.//*[@name="cvv"]')[0].get('type'), 'password')
        self.assertEqual(form.xpath('.//*[@name="pan"]')[0].get('inputmode'), 'numeric')
        self.assertTrue(form.xpath('.//button[@type="submit"]|.//input[@type="submit"]'))

    def test_aktif_icerik_ve_dis_kaynak_yok(self):
        text = self.page(self.make_mail_order()).text
        lowered = text.lower()
        for needle in ('<script', '/web/assets', '<iframe', 'javascript:', 'csrf_token', '<object',
                       '<embed'):
            self.assertNotIn(needle, lowered, needle)
        self.assertIsNone(re.search(r'\son[a-z]+\s*=', lowered), 'satır içi olay işleyicisi')
        doc = lxml_html.fromstring(text)
        links = doc.xpath('//link/@href')
        self.assertEqual(links, ['/sanal_pos/static/src/css/mail_order.css'])
        self.assertFalse(doc.xpath('//img[not(starts-with(@src,"/"))]'))

    def test_css_servisi_calisir(self):
        response = self.url_open('/sanal_pos/static/src/css/mail_order.css')
        self.assertEqual(response.status_code, 200)
        self.assertIn('css', response.headers.get('Content-Type', ''))

    def test_uyari_test_bandi_ve_musteri_adi(self):
        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', self.page(self.make_mail_order()).text))
        self.assertIn(WARNING_TEXT, text)
        self.assertIn('TEST', text)

    def test_canlida_test_bandi_yok(self):
        payment = self.make_mail_order(environment='live', provider_token='TOK-LIVE')
        response = self.page(payment)
        self.assertEqual(response.status_code, 200)
        form = self.doc(response).xpath('//form')[0]
        # G4 düzeltmesi (test hatası): canlı kök modülde ve test_mail_order'da vpos.paratika.com.tr
        # (LIVE_URL_PREFIX, kaynaklar/paratika-direct-post.md §8); www.paratika.com.tr hiçbir yerde yok.
        self.assertEqual(form.get('action'), LIVE_URL_PREFIX + '/post/sale3d/TOK-LIVE')
        self.assertNotIn('test.paratika.com.tr', form.get('action'))

    def test_taksit_secenekleri(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(2, 0), (3, 1.5), (6, 3.0)])))
        doc = self.doc(self.page(self.make_mail_order()))
        values = doc.xpath('//select[@name="installmentCount"]/option/@value')
        self.assertEqual(values[0], '1')
        self.assertEqual(sorted(int(v) for v in values), [1, 2, 3, 6])
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 1)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.link_calls(), 0)

    def test_taksit_sorgusu_hatasinda_tek_cekim(self):
        self.mock.queue('QUERYINSTALLMENT', timeout_exc())
        response = self.page(self.make_mail_order())
        self.assertEqual(response.status_code, 200)
        doc = self.doc(response)
        values = doc.xpath('//select[@name="installmentCount"]/option/@value')
        self.assertEqual(values, ['1'])
        self.assertEqual(len(doc.xpath('//input[@name="pan"]')), 1)

    def test_hata_durumlari_form_gostermez_sessiontoken_yok(self):
        self.make_mail_order(invoice_no='OK-ANCHOR')
        cases = {
            'suresi_dolmus': self.make_mail_order(invoice_no='H-1', expires_at=datetime.utcnow() - timedelta(minutes=5)),
            'odendi': self.make_mail_order(invoice_no='H-2', state='paid'),
            'hata': self.make_mail_order(invoice_no='H-3', state='error'),
            'expired': self.make_mail_order(invoice_no='H-4', state='expired'),
            'link': self.make_payment(invoice_no='H-5'),
        }
        for name, payment in cases.items():
            with self.subTest(case=name):
                response = self.page(payment)
                self.assertNotIn('name="pan"', response.text)
                self.assertNotIn('/post/sale3d/', response.text)
                self.assertFalse(self.doc(response).xpath('//form[contains(@action,"sale3d")]')
                                 if response.text.strip() else False)
        missing = self.url_open(MAIL_ORDER_PAY_PATH % 99999999, allow_redirects=False)
        self.assertNotIn('name="pan"', missing.text)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.link_calls(), 0)

    def test_post_405(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        response = self.url_open(MAIL_ORDER_PAY_PATH % payment.id, data={'pan': LEAK_PAN, 'cvv': LEAK_CVV})
        self.assertEqual(response.status_code, 405)
        self.assertNotIn(LEAK_PAN, response.text)

    def test_sorgu_parametreleri_html_ye_yansimaz(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        query = '?pan=%s&cvv=%s&cardOwner=%s&x=%%3Cb%%3E' % (LEAK_PAN, LEAK_CVV, LEAK_OWNER.replace(' ', '+'))
        response = self.url_open(MAIL_ORDER_PAY_PATH % payment.id + query, allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        for needle in (LEAK_PAN, LEAK_OWNER, '<b>'):
            self.assertNotIn(needle, response.text)
        self.assertFalse(self.doc(response).xpath('//input[@name="pan"]/@value'))

    def test_sayfa_acmak_durumu_ve_kayit_degistirmez(self):
        payment = self.make_mail_order()
        self.page(payment)
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertFalse(payment.sync_requested)


# ======================================================================================
# mo_return
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMoReturn(MoHttpCase):

    def post_return(self, mpid=None, **extra):
        data = dict(extra)
        if mpid is not None:
            data['MERCHANTPAYMENTID'] = mpid
        # G4 düzeltmesi (test hatası): url_open boş data ile GET gönderir (method verilmezse);
        # 'eksik numara' durumu boş POST'tur, GET değil (GET -> 405 ayrıca test_get_405'te).
        return self.url_open(MAIL_ORDER_RETURN_PATH, data=data, method='POST', allow_redirects=False)

    def test_get_405(self):
        self.assertEqual(self.url_open(MAIL_ORDER_RETURN_PATH, allow_redirects=False).status_code, 405)

    def test_sabit_yanit_ve_baglanti(self):
        payment = self.make_mail_order()
        response = self.post_return(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['Content-Type'])
        self.assertIn('/sanal_pos/mail_order/result?mpid=%s' % payment.merchant_payment_id, response.text)
        self.assertNotIn('session_id', response.cookies)
        self.assertNotIn('<script', response.text.lower())

    def test_basliklar(self):
        response = self.post_return(self.make_mail_order().merchant_payment_id)
        policy = self.csp(response)
        self.assertEqual(policy.get('default-src'), ["'none'"])
        self.assertEqual(policy.get('style-src'), ["'self'"])
        self.assertEqual(policy.get('frame-ancestors'), ["'none'"])
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('Referrer-Policy'), 'no-referrer')

    def test_yalniz_tetik_durum_degismez_paratika_yok(self):
        payment = self.make_mail_order()
        before = self.cron_trigger_count(CRON_SYNC_FLAGGED)
        self.post_return(payment.merchant_payment_id, STATUS='AP', AMOUNT='9000.00', responseCode='00')
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertTrue(payment.sync_requested)
        self.assertGreater(self.cron_trigger_count(CRON_SYNC_FLAGGED), before)
        self.assertNoParatikaCalls()

    def test_sonuc_yalniz_querytransaction_ile(self):
        payment = self.make_mail_order()
        self.post_return(payment.merchant_payment_id, STATUS='AP', AMOUNT='1.00')
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-RET', errorCode='ERR20051'))
        self.run_cron('sanal_pos.cron_sanal_pos_sync_flagged')
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertEqual(self.reload(payment).failed_attempt_count, 1)
        self.assertEqual(self.link_calls(), 0)

    def test_bilinen_ve_bilinmeyen_ayni_yanit_durumu(self):
        payment = self.make_mail_order()
        known = self.post_return(payment.merchant_payment_id)
        unknown = self.post_return('YOK-1-1')
        empty = self.post_return()
        self.assertEqual({known.status_code, unknown.status_code, empty.status_code}, {200})
        self.assertEqual(known.headers['Content-Type'], unknown.headers['Content-Type'])
        self.assertNotIn('sync_requested', known.text)

    def test_kart_degerleri_govdede_olsa_bile_hicbir_yerde_yok(self):
        payment = self.make_mail_order()
        clean = self.post_return(payment.merchant_payment_id)
        with self.capture_logs() as records:
            dirty = self.post_return(payment.merchant_payment_id, **BODY_CARD)
        self.assertEqual(dirty.status_code, 200)
        self.assertEqual(dirty.text, clean.text)
        for secret in (LEAK_PAN, LEAK_OWNER):
            self.assertNotIn(secret, dirty.text)
            self.assertNotIn(secret, '\n'.join(records))
            self.assertNotIn(secret, self.all_log_text())
        cr = self.env.cr
        cr.execute("SELECT count(*) FROM mail_message WHERE body ILIKE %s OR subject ILIKE %s OR body ILIKE %s",
                   ('%' + LEAK_PAN + '%', '%' + LEAK_PAN + '%', '%' + LEAK_OWNER + '%'))
        self.assertEqual(cr.fetchone()[0], 0)
        cr.execute("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_name LIKE 'sanal_pos_%'""")
        for (table,) in cr.fetchall():
            cr.execute('SELECT t::text FROM "%s" t' % table)
            for (row,) in cr.fetchall():
                self.assertNotIn(LEAK_PAN, row, table)
                self.assertNotIn(LEAK_OWNER, row, table)
        self.assertEqual(self.reload(payment).state, 'sent')

    def test_xss_mpid_kacirilir_ve_baglanti_yalniz_gecerli_mpid(self):
        payload = '"><script>alert(1)</script>'
        response = self.post_return(payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)', response.text)
        self.assertNotIn(payload, response.text)
        self.assertNotIn('mpid=%s' % payload, response.text)
        # olumlu çapa: geçerli MPID bağlantıda görünür
        ok = self.post_return(self.make_mail_order().merchant_payment_id)
        self.assertIn('mpid=%s-1' % INV_NO, ok.text)

    def test_buyuk_govde_413(self):
        response = self.url_open(MAIL_ORDER_RETURN_PATH, data={'MERCHANTPAYMENTID': 'A-1-1', 'junk': 'x' * 20000},
                                 allow_redirects=False)
        self.assertEqual(response.status_code, 413)
        small = self.post_return(self.make_mail_order().merchant_payment_id)
        self.assertEqual(small.status_code, 200)


# ======================================================================================
# result
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMoResult(MoHttpCase):

    def result(self, mpid=None, user=None):
        if user is not False:
            self.login_as(user or self.user_sp)
        path = MAIL_ORDER_RESULT_PATH + ('?mpid=%s' % mpid if mpid is not None else '')
        return self.url_open(path, allow_redirects=False)

    def target(self, payment):
        return '/odoo/action-sanal_pos.action_sanal_pos_payment/%d' % payment.id

    def test_sorgular_ve_kayda_yonlendirir(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-R1', last4='4242'))
        response = self.result(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(self.target(payment)))
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(self.link_calls(), 0)

    def test_son_10_saniyede_sorgusuz_yonlendirir(self):
        payment = self.make_mail_order(last_checked_at=datetime.utcnow() - timedelta(seconds=3))
        response = self.result(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(self.target(payment)))
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)
        # olumlu çapa: eski kontrol zamanında sorgu yapılır
        old = self.make_mail_order(invoice_no='R-OLD', last_checked_at=datetime.utcnow() - timedelta(seconds=60))
        self.result(old.merchant_payment_id)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kilitliyse_sorgusuz_yonlendirir(self):
        payment = self.make_mail_order()
        with patch.object(type(self.env['sanal.pos.payment']), '_try_lock_nowait', return_value=False):
            response = self.result(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(self.target(payment)))
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_bilinmeyen_link_ve_eksik_mpid_listeye_gider_paratika_yok(self):
        link = self.make_payment(invoice_no='R-LINK')
        for name, mpid in (('bilinmeyen', 'YOK-1-1'), ('link', link.merchant_payment_id), ('eksik', None)):
            with self.subTest(case=name):
                response = self.result(mpid)
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response.headers['Location'].endswith(PAYMENT_LIST))
        self.assertNoParatikaCalls()

    def test_sent_olmayan_kayit_sorgusuz_yonlendirir(self):
        # Kardeş yol (G4): ödenmiş/kapanmış kayıtta sonuç sayfası yenilense de Paratika sorgusu yok
        paid = self.make_mail_order(state='paid', invoice_no='R-PAID')
        response = self.result(paid.merchant_payment_id)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith(self.target(paid)))
        self.assertNoParatikaCalls()
        self.assertEqual(self.reload(paid).state, 'paid')

    def test_oturumsuz_giris_gerekir_grupsuz_reddedilir(self):
        payment = self.make_mail_order()
        anon = self.result(payment.merchant_payment_id, user=False)
        self.assertIn(anon.status_code, (301, 302, 303, 307))
        self.assertIn('/web/login', anon.headers.get('Location', ''))
        plain = self.result(payment.merchant_payment_id, user=self.user_plain)
        self.assertNotEqual(plain.status_code, 303 if self.target(payment) in plain.headers.get('Location', '') else 0)
        self.assertNotIn(self.target(payment), plain.headers.get('Location', ''))
        self.assertNoParatikaCalls()
        self.assertEqual(self.result(payment.merchant_payment_id, user=self.user_sp).status_code, 303)

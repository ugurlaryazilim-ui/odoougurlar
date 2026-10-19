# -*- coding: utf-8 -*-
"""G8 / webhook ve dönüş uç noktaları. KK-22 (200 + tetik), KK-23, KK-29, KK-38.

Gerçek HTTP (HttpCase.url_open): public kullanıcı, CSRF'siz POST, GET reddi, gövde sınırı.
Uç nokta Paratika'ya ASLA çağrı yapmaz; yalnız ``sync_requested`` bayrağı + cron tetiği.
"""
import time
from unittest.mock import patch

from odoo.tests import tagged

from .common import (
    CRON_SYNC, CRON_SYNC_FLAGGED, CUSTOMER_NAME, EMAIL, INV_NO, PASSWORD, SanalPosHttpCase, tran,
)

NOTIFY = '/sanal_pos/paratika/notify'
RETURN = '/sanal_pos/paratika/return'
RETURN_TEXT = 'İşleminiz alındı. Sonuç mağazamız tarafından size iletilecektir.'


class HookCase(SanalPosHttpCase):

    def post(self, path, data=None, **kw):
        return self.url_open(path, data=data, **kw)

    def notify(self, mpid, **extra):
        data = {'NOTIFICATIONTYPE': 'TRANSACTIONAPPROVED', 'MERCHANTPAYMENTID': mpid}
        data.update(extra)
        return self.post(NOTIFY, data)

    def reload(self, payment):
        payment.invalidate_recordset()
        return payment


@tagged('post_install', '-at_install', 'sanal_pos')
class TestNotifyEndpoint(HookCase):

    def test_kk22_post_200_ok_bayrak_ve_tetik(self):
        payment = self.make_payment(state='sent')
        before = self.cron_trigger_count(CRON_SYNC_FLAGGED)
        started = time.monotonic()
        response = self.notify(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.strip(), 'OK')
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(self.reload(payment).sync_requested)
        self.assertGreater(self.cron_trigger_count(CRON_SYNC_FLAGGED), before)
        self.assertEqual(payment.state, 'sent')

    def test_y1_kilitli_satirda_bildirim_kaybolmaz(self):
        payment = self.make_payment(state='sent')
        with patch.object(type(self.env['sanal.pos.payment']), '_try_lock_nowait',
                          return_value=False):
            response = self.notify(payment.merchant_payment_id)
        self.assertEqual(response.text.strip(), 'OK')
        self.assertFalse(self.reload(payment).sync_requested)
        log = self.env['sanal.pos.log'].sudo().search(
            [('payment_id', '=', payment.id), ('action', '=', 'NOTIFY')], limit=1)
        self.assertEqual(log.error_code, 'SYNC_DEFERRED')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-Y1-HTTP'))
        self.run_cron(CRON_SYNC_FLAGGED)
        self.assertEqual(self.reload(payment).state, 'paid')

    def test_kk22_uc_nokta_paratikaya_cagri_yapmaz(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id)
        self.assertNoParatikaCalls()

    def test_kk22_yanit_duz_metin(self):
        payment = self.make_payment(state='sent')
        response = self.notify(payment.merchant_payment_id)
        self.assertIn('text/plain', response.headers.get('Content-Type', ''))

    def test_kk22_csrf_belirteci_gerekmez_ve_oturum_acilmaz(self):
        payment = self.make_payment(state='sent')
        response = self.notify(payment.merchant_payment_id)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('session_id', response.cookies)

    def test_kk22_tekrarlanan_bildirim_idempotent(self):
        payment = self.make_payment(state='sent')
        for _ in range(3):
            response = self.notify(payment.merchant_payment_id)
            self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))
        self.assertTrue(self.reload(payment).sync_requested)
        self.assertEqual(payment.state, 'sent')

    def test_kk22_kucuk_harfli_alan_adi_da_kabul(self):
        payment = self.make_payment(state='sent')
        response = self.post(NOTIFY, {'merchantPaymentId': payment.merchant_payment_id})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.reload(payment).sync_requested)

    def test_kk22_bildirimden_sonra_cron_sorguyla_odendi_yapar(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-HOOK'))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(payment.provider_tran_ref, 'PG-HOOK')
        self.assertFalse(payment.sync_requested)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestNotifyIsOnlyATrigger(HookCase):
    """KK-23: gövdedeki tutar/durum alanlarına hiçbir koşulda güvenilmez."""

    def test_kk23_govdede_onayli_durum_olsa_bile_degismez(self):
        payment = self.make_payment(state='sent')
        response = self.notify(payment.merchant_payment_id, STATUS='AP', AMOUNT='9000.00',
                               PGTRANSACTIONID='FORGED-1', INSTALLMENTCOUNT='1')
        self.assertEqual(response.status_code, 200)
        self.reload(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertFalse(payment.provider_tran_ref)
        self.assertFalse(payment.paid_at)

    def test_kk23_sahte_bildirim_sorgu_ap_donmeyince_odendi_olmaz(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id, STATUS='AP', AMOUNT='9000.00')
        self.run_cron(CRON_SYNC)        # QUERYTRANSACTION boş döner
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertFalse(payment.sync_requested)

    def test_kk23_govde_tutari_farkliysa_kayit_tutari_degismez(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id, AMOUNT='1.00', STATUS='AP')
        self.assertEqual(self.reload(payment).amount, 9000.0)
        self.assertEqual(payment.state, 'sent')

    def test_kk23_bilinmeyen_mpid_yine_200_ok(self):
        known = self.make_payment(state='sent')
        response = self.notify('YOK-123-9')
        self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))
        self.assertFalse(self.reload(known).sync_requested)

    def test_kk23_bilinmeyen_mpid_olay_kaydi_yazilir(self):
        before = self.env['sanal.pos.log'].sudo().search_count([('action', '=', 'NOTIFY')])
        self.notify('YOK-123-9')
        logs = self.env['sanal.pos.log'].sudo().search([('action', '=', 'NOTIFY')])
        self.assertEqual(len(logs), before + 1)
        self.assertFalse(logs[:1].payment_id)

    def test_kk23_bilinen_mpid_olay_kaydi_odemeye_baglanir(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id)
        logs = self.env['sanal.pos.log'].sudo().search([('action', '=', 'NOTIFY'),
                                                         ('payment_id', '=', payment.id)])
        self.assertTrue(logs)

    def test_kk23_yanit_bilgi_sizdirmaz(self):
        payment = self.make_payment(state='sent')
        known = self.notify(payment.merchant_payment_id)
        unknown = self.notify('YOK-123-9')
        self.assertEqual(known.text, unknown.text)
        self.assertEqual(known.status_code, unknown.status_code)
        for needle in (CUSTOMER_NAME, EMAIL, '9000', INV_NO):
            self.assertNotIn(needle, known.text)

    def test_kk23_eksik_mpid_200_ok(self):
        response = self.post(NOTIFY, {'NOTIFICATIONTYPE': 'TRANSACTIONAPPROVED'})
        self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))

    def test_kk23_alakasiz_govde_200_ok(self):
        response = self.post(NOTIFY, {'foo': 'bar'})
        self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))

    def test_kk23_mpid_tam_eslesme_joker_isleme_girmez(self):
        payment = self.make_payment(state='sent')
        for attack in ('%', '%-1', "' OR 1=1 --", '%s%%' % INV_NO, INV_NO, '_' * 5):
            with self.subTest(mpid=attack):
                response = self.notify(attack)
                self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))
                self.assertFalse(self.reload(payment).sync_requested,
                                 'tam eşleşme dışındaki MPID kaydı tetiklememeli')

    def test_kk23_uzun_mpid_patlatmaz(self):
        response = self.notify('A' * 4000)
        self.assertEqual((response.status_code, response.text.strip()), (200, 'OK'))

    def test_kk39_bildirim_logunda_sir_yok(self):
        payment = self.make_payment(state='sent')
        self.notify(payment.merchant_payment_id, MERCHANTPASSWORD=PASSWORD, CUSTOMEREMAIL=EMAIL)
        self.assertNotIn(PASSWORD, self.all_log_text())


@tagged('post_install', '-at_install', 'sanal_pos')
class TestNotifyHardening(HookCase):

    def test_kk38_yalniz_post(self):
        for method in ('GET', 'PUT', 'DELETE'):
            with self.subTest(method=method):
                response = self.opener.request(method, self.base_url() + NOTIFY, timeout=12)
                self.assertEqual(response.status_code, 405)

    def test_kk38_govde_siniri_413(self):
        payment = self.make_payment(state='sent')
        big = {'MERCHANTPAYMENTID': payment.merchant_payment_id, 'JUNK': 'x' * (11 * 1024)}
        response = self.post(NOTIFY, big)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(self.reload(payment).sync_requested, 'çok büyük gövdede işlem yapılmamalı')

    def test_kk38_sinira_yakin_govde_kabul(self):
        payment = self.make_payment(state='sent')
        data = {'MERCHANTPAYMENTID': payment.merchant_payment_id, 'JUNK': 'x' * 2048}
        self.assertEqual(self.post(NOTIFY, data).status_code, 200)

    def test_kk38_oturum_gerektirmez(self):
        """Giriş yapmadan (public) erişilir; /web/login'e yönlenmez."""
        payment = self.make_payment(state='sent')
        response = self.post(NOTIFY, {'MERCHANTPAYMENTID': payment.merchant_payment_id}, allow_redirects=False)
        self.assertEqual(response.status_code, 200)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReturnEndpoint(HookCase):

    def test_kk29_donus_sayfasi_metni(self):
        payment = self.make_payment(state='sent')
        response = self.post(RETURN, {'merchantPaymentId': payment.merchant_payment_id})
        self.assertEqual(response.status_code, 200)
        self.assertIn(RETURN_TEXT, response.text)
        self.assertIn('text/html', response.headers.get('Content-Type', ''))
        self.assertIn('utf-8', response.headers.get('Content-Type', '').lower())

    def test_kk29_sayfada_kisisel_veri_tutar_hata_yok(self):
        payment = self.make_payment(state='sent', last_error_message='Kart reddedildi detay')
        response = self.post(RETURN, {'MERCHANTPAYMENTID': payment.merchant_payment_id,
                                      'STATUS': 'AP', 'AMOUNT': '9000.00', 'CARDNO': '4242'})
        for needle in (CUSTOMER_NAME, EMAIL, '5321112233', '9000', '9.000', INV_NO,
                       payment.merchant_payment_id, 'Kart reddedildi', '4242'):
            self.assertNotIn(needle, response.text, needle)

    def test_kk29_post_yalniz_dogrulama_tetikler_durumu_degistirmez(self):
        payment = self.make_payment(state='sent')
        before = self.cron_trigger_count(CRON_SYNC_FLAGGED)
        self.post(RETURN, {'MERCHANTPAYMENTID': payment.merchant_payment_id, 'STATUS': 'AP', 'AMOUNT': '9000.00'})
        self.reload(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertTrue(payment.sync_requested)
        self.assertGreater(self.cron_trigger_count(CRON_SYNC_FLAGGED), before)
        self.assertNoParatikaCalls()

    def test_kk29_bilinmeyen_kayitta_ayni_sayfa(self):
        payment = self.make_payment(state='sent')
        known = self.post(RETURN, {'MERCHANTPAYMENTID': payment.merchant_payment_id})
        unknown = self.post(RETURN, {'MERCHANTPAYMENTID': 'YOK-1-1'})
        empty = self.post(RETURN, {'foo': 'bar'})
        self.assertEqual(known.text, unknown.text)
        self.assertEqual(known.text, empty.text)
        self.assertEqual((known.status_code, unknown.status_code, empty.status_code), (200, 200, 200))

    def test_kk29_get_405(self):
        self.assertEqual(self.url_open(RETURN).status_code, 405)

    def test_kk29_donusten_sonra_cron_gercek_durumu_belirler(self):
        payment = self.make_payment(state='sent')
        self.post(RETURN, {'MERCHANTPAYMENTID': payment.merchant_payment_id})
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-RET'))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'paid')

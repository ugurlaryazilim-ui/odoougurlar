# -*- coding: utf-8 -*-
"""G9 / link yönetimi. KK-31 (yeniden gönder), KK-32 (link iptali), KK-35 (kullanıcı yetkisi)."""
from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import (
    LIVE_URL_PREFIX, SanalPosCase, err_body, ok_body, timeout_exc, tran,
)

RESEND_WIZARD = 'sanal.pos.payment.resend.wizard'
NOT_SENT = ('sending', 'unknown', 'error', 'expired', 'link_cancelled', 'paid', 'review',
            'partial_refund', 'refunded', 'voided')


class ActionCase(SanalPosCase):

    def sent(self, **vals):
        return self.make_payment(state='sent', **vals)

    def as_user(self, payment):
        return payment.with_user(self.user_sp)

    def call_safely(self, func, *args):
        """UserError'ı yutar, mesajını döndürür (sonuç Paratika'da gerçekleşmiş olabilir)."""
        try:
            func(*args)
        except UserError as exc:
            return str(exc.args[0])
        return None


@tagged('post_install', '-at_install', 'sanal_pos')
class TestResend(ActionCase):

    def test_kk31_sms_yeniden_gonder(self):
        payment = self.sent()
        self.as_user(payment).action_resend(['sms'])
        call = self.mock.last('PAYBYLINKPAYMENTRESEND')
        self.assertIsNotNone(call)
        self.assertEqual(call.params['PAYBYLINKTOKEN'], payment.provider_token)
        self.assertEqual(call.params['NOTIFICATIONCHANNELS'], 'SMS')
        self.assertIn('Yeniden gönderildi (SMS)', self.chatter(payment))
        self.assertEqual(payment.state, 'sent')

    def test_kk31_eposta_ve_cift_kanal(self):
        payment = self.sent()
        self.as_user(payment).action_resend(['email'])
        self.assertEqual(self.mock.last('PAYBYLINKPAYMENTRESEND').params['NOTIFICATIONCHANNELS'], 'EMAIL')
        self.assertIn('Yeniden gönderildi (E-posta)', self.chatter(payment))
        self.as_user(payment).action_resend(['sms', 'email'])
        self.assertEqual(self.mock.last('PAYBYLINKPAYMENTRESEND').params['NOTIFICATIONCHANNELS'], 'EMAIL,SMS')
        self.assertIn('Yeniden gönderildi (SMS+E-posta)', self.chatter(payment))

    def test_kk31_hata_donerse_not_dusmez_ve_hata_gosterilir(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTRESEND', err_body('ERR10199', 'invalid phone'))
        message = self.call_safely(self.as_user(payment).action_resend, ['sms'])
        payment.invalidate_recordset()
        shown = (message or '') + (payment.last_error_message or '')
        self.assertIn('telefon', shown.lower(), 'Türkçe hata kullanıcıya gösterilmeli')
        self.assertNotIn('Yeniden gönderildi', self.chatter(payment))
        self.assertEqual(payment.state, 'sent')

    def test_kk31_zaman_asimi_durumu_bozmaz(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTRESEND', timeout_exc())
        self.call_safely(self.as_user(payment).action_resend, ['sms'])
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')
        self.assertNotIn('Yeniden gönderildi', self.chatter(payment))

    def test_kk31_yalniz_gonderildi_durumunda(self):
        for i, state in enumerate(NOT_SENT):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, invoice_no='RS%d' % i)
                with self.assertRaises(UserError):
                    self.as_user(payment).action_resend(['sms'])
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENTRESEND'), 0)

    def test_kk31_suresi_dolmus_kayitta_yok(self):
        past = datetime.utcnow() - timedelta(minutes=5)
        payment = self.sent(sent_at=past - timedelta(hours=168), expires_at=past)
        with self.assertRaises(UserError):
            self.as_user(payment).action_resend(['sms'])
        self.assertNoParatikaCalls()

    def test_kk31_kanal_secilmediyse_hata(self):
        payment = self.sent()
        with self.assertRaises(UserError):
            self.as_user(payment).action_resend([])
        self.assertNoParatikaCalls()

    def test_kk31_yetkisiz_kullanici(self):
        payment = self.sent()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_plain).action_resend(['sms'])
        self.assertNoParatikaCalls()

    def test_kk31_baska_kullanicinin_kaydini_da_yeniden_gonderebilir(self):
        """KK-35: grup üyeleri TÜM talepler üzerinde işlem yapar (S-4)."""
        payment = self.sent()
        payment.with_user(self.user_sp2).action_resend(['sms'])
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENTRESEND'), 1)

    def test_kk52_kayit_ortamina_gonderilir(self):
        payment = self.sent(environment='live')
        self.as_user(payment).action_resend(['sms'])
        self.assertTrue(self.mock.last('PAYBYLINKPAYMENTRESEND').url.startswith(LIVE_URL_PREFIX))

    def test_kk31_sihirbaz_akisi(self):
        payment = self.sent()
        wiz = self.env[RESEND_WIZARD].with_user(self.user_sp).create({
            'payment_id': payment.id, 'channel_sms': True, 'channel_email': False})
        method = next((m for m in ('action_resend', 'action_confirm', 'action_send') if hasattr(wiz, m)), None)
        self.assertIsNotNone(method, 'sihirbazda onay eylemi bulunamadı (action_resend/action_confirm/action_send)')
        getattr(wiz, method)()
        self.assertEqual(self.mock.last('PAYBYLINKPAYMENTRESEND').params['NOTIFICATIONCHANNELS'], 'SMS')
        self.assertIn('Yeniden gönderildi (SMS)', self.chatter(payment))

    def test_kk31_sihirbaz_yetkisiz_olusturamaz(self):
        payment = self.sent()
        with self.assertRaises(AccessError):
            self.env[RESEND_WIZARD].with_user(self.user_plain).create({'payment_id': payment.id})

    def test_kk31_yeniden_gonderim_link_adresini_ifsa_etmez(self):
        payment = self.sent()
        self.as_user(payment).action_resend(['sms'])
        self.assertNotIn(payment.provider_token, self.chatter(payment))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCancelLink(ActionCase):

    def test_kk32_iptal_basarili(self):
        payment = self.sent()
        self.as_user(payment).action_cancel_link()
        call = self.mock.last('PAYBYLINKPAYMENTCANCEL')
        self.assertIsNotNone(call)
        self.assertEqual(call.params['PAYBYLINKTOKEN'], payment.provider_token)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'link_cancelled')
        self.assertIn('iptal', self.chatter(payment).lower())

    def test_kk32_iptal_sonrasi_yeni_link_acilabilir(self):
        self.create_link(channel_sms=True, channel_email=True)
        payment = self.last_payment()
        self.as_user(payment).action_cancel_link()
        self.create_link(channel_sms=True, channel_email=True)
        self.assertEqual(self.last_payment().attempt_no, 2)
        self.assertEqual(self.last_payment().state, 'sent')

    def test_kk32_yalniz_gonderildi_durumunda(self):
        for i, state in enumerate(NOT_SENT):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, invoice_no='CN%d' % i)
                with self.assertRaises(UserError):
                    self.as_user(payment).action_cancel_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENTCANCEL'), 0)

    def test_kk32_zaten_odenmis_err10143_gercek_durum_odendi(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10143', 'already paid or cancelled'))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-PAID'))
        result = self.as_user(payment).action_cancel_link()      # raise etmemeli: durum yazılmalı
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.provider_tran_ref, 'PG-PAID')
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        shown = (str(result) + self.chatter(payment)).lower()
        self.assertIn('öde', shown, 'kullanıcıya/kayda gerçek durum bildirilmeli')

    def test_kk32_zaten_iptal_err10143_link_iptal(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10143', 'already cancelled'))
        self.as_user(payment).action_cancel_link()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'link_cancelled')
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk32_diger_hata_durumu_degistirmez(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10001', 'x'))
        message = self.call_safely(self.as_user(payment).action_cancel_link)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')
        self.assertTrue(message or payment.last_error_message)

    def test_kk32_zaman_asimi_iptal_sayilmaz(self):
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', timeout_exc())
        self.call_safely(self.as_user(payment).action_cancel_link)
        payment.invalidate_recordset()
        self.assertNotEqual(payment.state, 'link_cancelled', 'yanıt alınmadan iptal edilmiş sayılmamalı')

    def test_kk32_odenmis_link_iptal_edilemez_ve_odenen_kayit_bozulmaz(self):
        payment = self.make_paid()
        with self.assertRaises(UserError):
            self.as_user(payment).action_cancel_link()
        self.assertEqual(payment.state, 'paid')
        self.assertNoParatikaCalls()

    def test_kk35_yetkisiz_kullanici(self):
        payment = self.sent()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_plain).action_cancel_link()
        self.assertNoParatikaCalls()

    def test_kk35_grup_uyesi_baskasinin_kaydini_iptal_edebilir(self):
        payment = self.sent()
        payment.with_user(self.user_sp2).action_cancel_link()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'link_cancelled')

    def test_kk52_kayit_ortamina_gonderilir(self):
        payment = self.sent(environment='live')
        self.as_user(payment).action_cancel_link()
        self.assertTrue(self.mock.last('PAYBYLINKPAYMENTCANCEL').url.startswith(LIVE_URL_PREFIX))

    def test_kk32_iptal_yanit_govdesi_basarili_ok(self):
        """Paratika 00 dönerse (varsayılan taklit) ek alan beklenmez."""
        payment = self.sent()
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', ok_body())
        self.as_user(payment).action_cancel_link()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'link_cancelled')

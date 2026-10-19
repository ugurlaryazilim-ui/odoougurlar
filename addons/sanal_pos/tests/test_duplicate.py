# -*- coding: utf-8 -*-
"""G7 / mükerrer link önleme. KK-18, KK-19, KK-20, KK-21 (+ blocking_message ön bilgisi).

Gerçek iki-cursor eşzamanlılığı TransactionCase'de kurulamaz (04-kabul-testleri.md,
"otomatik kapsanamayanlar"); burada çift tıklama, iki kullanıcı ve "kontrolü atlayan
yarış" (DB indeksine düşme) davranışları gözlemlenir.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import (
    INV_NO, OPEN_STATES, PAID_STATES, REUSABLE_STATES, SanalPosCase, invoice_rows, timeout_exc, tran,
)

BOTH = {'channel_sms': True, 'channel_email': True}
OPEN_MSG = 'Bu faturaya ait açık bir link var'
PAID_MSG = 'Bu fatura için ödeme alınmış/incelemede; yeni link oluşturulamaz.'


class DupCase(SanalPosCase):

    def attempt(self, **kw):
        """Link Oluştur'a basar; UserError metnini döndürür (başarılıysa None)."""
        try:
            self.wizard(**dict(BOTH, **kw)).action_create_link()
        except UserError as exc:
            return str(exc.args[0])
        return None

    def assertBlocked(self, text):
        n_before = len(self.payments())
        self.mock.calls.clear()
        message = self.attempt()
        self.assertIsNotNone(message, 'yeni link engellenmeliydi')
        self.assertIn(text, message)
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0, 'engellenen denemede Paratika isteği gitti')
        self.assertEqual(len(self.payments()), n_before, 'engellenen denemede kayıt oluştu')
        return message


@tagged('post_install', '-at_install', 'sanal_pos')
class TestOpenLinkBlocks(DupCase):

    def test_kk18_acik_durumlar_engeller(self):
        for i, state in enumerate(OPEN_STATES, start=1):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, attempt_no=i)
                self.assertBlocked(OPEN_MSG)
                payment.sudo().write({'state': 'link_cancelled'})
                payment.flush_recordset()  # sıradaki INSERT açık-link indeksinde eski satırı görmesin

    def test_kk18_mesaj_olusturan_ve_tarihi_icerir(self):
        self.make_payment(state='sent')
        message = self.assertBlocked(OPEN_MSG)
        self.assertIn(self.user_sp.name, message)
        self.assertIn(str(fields.Date.today().year), message)
        self.assertIn('Yeniden gönderin veya iptal edin.', message)

    def test_kk18_baska_kullanici_olusturduysa_onun_adi(self):
        self.create_link(**BOTH)                       # user_sp
        self.mock.calls.clear()
        with self.assertRaises(UserError) as ctx:
            self.wizard(user=self.user_sp2, **BOTH).action_create_link()
        message = str(ctx.exception.args[0])
        self.assertIn(OPEN_MSG, message)
        self.assertIn(self.user_sp.name, message)
        self.assertNoParatikaCalls()

    def test_kk18_ikinci_kullanici_sihirbazi_once_acmis_olsa_da_engellenir(self):
        """İki kullanıcı aynı anda sihirbazı açtı (ikisi de boş görüyor); biri bitirince diğeri engellenir."""
        wiz1 = self.wizard(user=self.user_sp, **BOTH)
        wiz2 = self.wizard(user=self.user_sp2, **BOTH)
        wiz1.action_create_link()
        with self.assertRaises(UserError) as ctx:
            wiz2.action_create_link()
        self.assertIn(OPEN_MSG, str(ctx.exception.args[0]))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 1)
        self.assertEqual(len(self.payments()), 1)

    def test_kk18_suresi_dolmus_gonderildi_once_senkronlanir(self):
        """Süresi geçmiş 'Gönderildi' kaydı sorguyla Süresi doldu olur ve yeni link açılır."""
        past = datetime.utcnow() - timedelta(hours=2)
        old = self.make_payment(state='sent', sent_at=past - timedelta(hours=168), expires_at=past)
        self.assertIsNone(self.attempt())
        self.assertEqual(old.state, 'expired')
        new = self.last_payment()
        self.assertEqual((new.state, new.attempt_no, new.merchant_payment_id), ('sent', 2, '%s-2' % INV_NO))
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk18_suresi_dolmus_ama_odenmis_ise_kk19(self):
        """Süresi geçmiş görünen kayıt aslında ödenmişse (sorgu AP) KK-19 mesajı; yeni link yok."""
        past = datetime.utcnow() - timedelta(hours=2)
        old = self.make_payment(state='sent', sent_at=past - timedelta(hours=168), expires_at=past)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T-LATE'))
        self.assertBlocked(PAID_MSG)
        self.assertEqual(old.state, 'paid')

    def test_kk18_acik_link_baska_faturayi_engellemez(self):
        self.make_payment(state='sent')
        self.set_invoice(invoice_rows('OTHER1'), invoice_no='OTHER1')
        self.wizard(invoice_no='OTHER1', **BOTH).action_create_link()
        self.assertEqual(self.last_payment('OTHER1').state, 'sent')

    def test_kk18_blocking_message_on_bilgi(self):
        self.make_payment(state='sent')
        wiz = self.env['sanal.pos.payment.create.wizard'].with_user(self.user_sp).create({'invoice_no': INV_NO})
        wiz.action_fetch_invoice()
        self.assertIn(OPEN_MSG, wiz.blocking_message or '')

    def test_kk18_blocking_message_bos_fatura_icin_bos(self):
        wiz = self.wizard()
        self.assertFalse(wiz.blocking_message)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPaidBlocks(DupCase):

    def test_kk19_odenmis_durumlar_engeller(self):
        for i, state in enumerate(PAID_STATES, start=1):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, attempt_no=i)
                self.assertBlocked(PAID_MSG)
                payment.sudo().write({'state': 'link_cancelled'})

    def test_kk19_blocking_message_on_bilgi(self):
        self.make_paid()
        wiz = self.wizard()
        self.assertIn(PAID_MSG, wiz.blocking_message or '')

    def test_kk19_onay_kutusu_odenmisi_gecirmez(self):
        self.make_paid()
        message = self.attempt(confirm_prior_refund=True)
        self.assertIn(PAID_MSG, message or '')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReusableStates(DupCase):

    def test_kk20_eski_kayit_durumlari_yeni_linke_izin_verir(self):
        for i, state in enumerate(('expired', 'link_cancelled', 'error'), start=1):
            with self.subTest(state=state):
                self.make_payment(state=state, attempt_no=2 * i - 1)
                self.assertIsNone(self.attempt())
                new = self.last_payment()
                self.assertEqual(new.state, 'sent')
                self.assertEqual(new.attempt_no, 2 * i)
                self.assertEqual(new.merchant_payment_id, '%s-%d' % (INV_NO, 2 * i))
                new.sudo().write({'state': 'link_cancelled'})

    def test_kk20_sonek_tum_denemelerin_maksimumunun_bir_fazlasi(self):
        self.make_payment(state='expired', attempt_no=1)
        self.make_payment(state='error', attempt_no=3)
        self.make_payment(state='link_cancelled', attempt_no=2)
        self.assertIsNone(self.attempt())
        self.assertEqual(self.last_payment().merchant_payment_id, '%s-4' % INV_NO)
        self.assertEqual(self.mock.calls[0].params['MERCHANTPAYMENTID'], '%s-4' % INV_NO)

    def test_kk20_iade_edilmis_fatura_onay_ister(self):
        for n, state in enumerate(('voided', 'refunded'), start=1):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, attempt_no=n, provider_tran_ref='T-OLD%d' % n)
                message = self.assertBlocked('iade')
                self.assertNotIn(OPEN_MSG, message)
                payment.sudo().write({'state': 'expired'})

    def test_kk20_onayla_iadeli_faturaya_yeni_link(self):
        for state in ('voided', 'refunded'):
            with self.subTest(state=state):
                self.mock.calls.clear()
                payment = self.make_payment(state=state, attempt_no=1 if state == 'voided' else 10)
                self.assertIsNone(self.attempt(confirm_prior_refund=True))
                new = self.last_payment()
                self.assertEqual(new.state, 'sent')
                self.assertGreater(new.attempt_no, payment.attempt_no)
                new.sudo().write({'state': 'link_cancelled'})

    def test_kk20_prior_refunded_hesaplanir(self):
        self.make_payment(state='refunded')
        wiz = self.wizard()
        self.assertTrue(wiz.prior_refunded)
        self.assertFalse(self.env['sanal.pos.payment.create.wizard'].with_user(self.user_sp)
                         .create({'invoice_no': 'XYZ999'}).prior_refunded)

    def test_kk20_hata_kaydi_onay_istemez(self):
        self.make_payment(state='error')
        self.assertIsNone(self.attempt())

    def test_kk20_yeniden_kullanilabilir_durumlar_tam_liste(self):
        """REUSABLE_STATES içinde olup onay gerektirmeyenler (iade hariç) yeni linke izin verir."""
        free = [s for s in REUSABLE_STATES if s not in ('voided', 'refunded')]
        self.assertEqual(sorted(free), ['error', 'expired', 'link_cancelled'])


@tagged('post_install', '-at_install', 'sanal_pos')
class TestConcurrency(DupCase):

    def test_kk21_cift_tiklama_tek_istek(self):
        """Aynı sihirbazda iki kez art arda 'Link Oluştur': yalnız bir Paratika isteği."""
        wiz = self.wizard(**BOTH)
        wiz.action_create_link()
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_link()
        self.assertIn(OPEN_MSG, str(ctx.exception.args[0]))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 1)
        self.assertEqual(len(self.payments()), 1)

    def test_kk21_cift_tiklama_iki_ayri_sihirbaz(self):
        wiz1 = self.wizard(**BOTH)
        wiz2 = self.wizard(**BOTH)
        wiz1.action_create_link()
        with self.assertRaises(UserError):
            wiz2.action_create_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 1)
        self.assertEqual(len(self.payments()), 1)

    def test_kk21_belirsiz_durumda_cift_tiklama(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        wiz = self.wizard(**BOTH)
        wiz.action_create_link()
        with self.assertRaises(UserError):
            wiz.action_create_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 1)

    def test_kk21_on_kontrol_atlansa_bile_db_indeksi_engeller(self):
        """Yarış: ikinci işlem açık kaydı göremedi (ön kontrol boş döndü). DB tekilliği
        yakalar, kullanıcı ham IntegrityError değil Türkçe UserError (KK-18) görür;
        Paratika'ya istek gitmez, ikinci kayıt kalmaz."""
        self.make_payment(state='sending', attempt_no=1)
        wiz = self.wizard(**BOTH)
        Payment = type(self.env['sanal.pos.payment'])
        with patch.object(Payment, 'search', lambda this, *a, **k: this.browse()), \
                patch.object(Payment, 'search_count', lambda this, *a, **k: 0):
            with self.assertRaises(UserError) as ctx:
                wiz.action_create_link()
        self.assertIn(OPEN_MSG, str(ctx.exception.args[0]))
        self.assertNoParatikaCalls()
        self.assertEqual(len(self.payments()), 1)

    def test_kk21_yaris_sonrasi_sistem_tutarli_kalir(self):
        """UserError sonrası aynı işlemde yeni bir fatura için link yine oluşturulabilir (savepoint temiz)."""
        self.make_payment(state='sending', attempt_no=1)
        wiz = self.wizard(**BOTH)
        Payment = type(self.env['sanal.pos.payment'])
        with patch.object(Payment, 'search', lambda this, *a, **k: this.browse()), \
                patch.object(Payment, 'search_count', lambda this, *a, **k: 0):
            with self.assertRaises(UserError):
                wiz.action_create_link()
        self.set_invoice(invoice_rows('AFTER01'), invoice_no='AFTER01')
        self.wizard(invoice_no='AFTER01', **BOTH).action_create_link()
        self.assertEqual(self.last_payment('AFTER01').state, 'sent')

    def test_kk21_farkli_faturalar_birbirini_engellemez(self):
        for n in ('PAR0001', 'PAR0002', 'PAR0003'):
            self.set_invoice(invoice_rows(n), invoice_no=n)
            self.wizard(invoice_no=n, **BOTH).action_create_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 3)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCanonicalInvoiceNo(DupCase):
    """G-3: fatura no her yerde kaynağın döndürdüğü kanonik değerdir; harf/boşluk farkı ve
    context default'ları çift açık link açtıramaz."""

    LOWER = INV_NO.lower()

    def setUp(self):
        super().setUp()
        # MSSQL harmanlaması büyük/küçük harfe duyarsız: küçük harfle sorgu aynı satırı döndürür
        self.invoices[self.LOWER] = invoice_rows()

    def test_g3_kucuk_harf_ve_bosluklu_fatura_no_ikinci_link_acamaz(self):
        first = self.create_link(**BOTH)
        self.assertEqual(first.state, 'sent')
        self.mock.calls.clear()
        wiz = self.wizard(invoice_no='  %s ' % self.LOWER, **BOTH)
        self.assertEqual(wiz.fetched_invoice_no, INV_NO)
        with self.assertRaises(UserError) as cm:
            wiz.action_create_link()
        self.assertIn(OPEN_MSG, str(cm.exception))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)
        self.assertEqual(len(self.env['sanal.pos.payment'].sudo().search(
            [('invoice_no', '=ilike', INV_NO)])), 1)

    def test_g3_context_default_ile_getir_denetimi_atlatilamaz(self):
        self.create_link(**BOTH)
        self.mock.calls.clear()
        Wizard = self.env(user=self.user_sp)['sanal.pos.payment.create.wizard'].with_context(
            default_fetched=True, default_fetched_invoice_no=self.LOWER, default_fetched_amount=9000.0)
        try:
            wiz = Wizard.create({'invoice_no': self.LOWER, 'customer_email': 'a@example.com', **BOTH})
        except UserError:
            wiz = None
        if wiz:
            self.assertFalse(wiz.fetched or wiz.fetched_invoice_no or wiz.fetched_amount,
                             'context default korumalı alanı doldurdu')
            with self.assertRaises(UserError):
                wiz.action_create_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)
        self.assertFalse(self.env['sanal.pos.payment'].sudo().search([('invoice_no', '=', self.LOWER)]))

    def test_g3_link_kaynagin_kanonik_numarasiyla_acilir(self):
        """Getirilen no kanonik değilse (eski/manipüle sihirbaz) yeniden okuma reddeder."""
        wiz = self.wizard(**BOTH)
        wiz._write_fetched({'invoice_no': self.LOWER, 'fetched_invoice_no': self.LOWER})
        with self.assertRaises(UserError) as cm:
            wiz.action_create_link()
        self.assertIn('faturayı yeniden getirin', str(cm.exception))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)
        self.assertFalse(self.env['sanal.pos.payment'].sudo().search([('invoice_no', '=', self.LOWER)]))

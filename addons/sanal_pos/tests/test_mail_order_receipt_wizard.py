# -*- coding: utf-8 -*-
"""A4-G3 ek testleri: elle dekont gönderiminin sertleştirmesi (KK-4.4/4.5).

Kabul testleri (test_mail_order_receipt.TestReceiptWizard) ana akışı sınar; burada adres enjeksiyonu,
hazırlık hatası, kilitten sonra durum değişimi, cron ile yarış ve düğme eylemlerinin yetkisi sınanır.

DIKKAT: gerçek iki bağlantılı kilit yarışı TransactionCase'te üretilemez; kilit/yarış yamalarla taklit
edilir (A4-G2 kardeş yol testleriyle aynı sınır).
"""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import SanalPosCase
from .test_mail_order_receipt import CRON_RECEIPT, SECRET_EXC, WIZARD, ReceiptMixin

NEW_ADDRESS = 'yeni.adres@example.com'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptWizardHardening(ReceiptMixin, SanalPosCase):

    def wiz(self, payment, email, user=None):
        return self.env(user=user or self.user_sp)[WIZARD].create({'payment_id': payment.id, 'email': email})

    def reload(self, payment):
        payment.invalidate_recordset()
        return payment

    def test_birden_cok_alici_ya_da_ayrac_iceren_adres_reddedilir(self):
        payment = self.paid_order()
        for bad in ('a@example.com,b@example.com', 'a@example.com;b@example.com',
                    'Ad <a@example.com>', '"a"@example.com', 'a@example.com\nBcc: x@example.com',
                    'a@example.com b@example.com'):
            with self.subTest(email=bad):
                with self.assertRaises(UserError):
                    self.wiz(payment, bad).action_send()
        self.assertFalse(self.queued_mails(payment))
        self.assertFalse(self.reload(payment).receipt_state)

    def test_adres_bosluklari_kirpilir(self):
        payment = self.paid_order()
        self.wiz(payment, '  %s  ' % NEW_ADDRESS).action_send()
        self.assertIn(NEW_ADDRESS, self.queued_mails(payment).email_to)

    def test_buyuk_kucuk_harf_farki_adres_degisikligi_sayilmaz(self):
        payment = self.paid_order()
        self.wiz(payment, payment.customer_email.upper()).action_send()
        self.assertNotIn('kayıttaki adres', self.chatter(payment))

    def test_hazirlik_hatasi_genel_mesaj_verir_durum_ve_not_degismez(self):
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': 'failed'})
        wizard = self.wiz(payment, NEW_ADDRESS)

        def broken(this, *args, **kwargs):
            raise RuntimeError(SECRET_EXC)

        with patch.object(type(self.env['mail.template']), 'send_mail', broken), \
                self.capture_logs() as records:
            with self.assertRaises(UserError) as ctx:
                wizard.action_send()
        logs = '\n'.join(records)
        self.assertNotIn(SECRET_EXC, str(ctx.exception))
        self.assertNotIn(SECRET_EXC, logs, 'istisna metni loglanmaz, yalnız sınıf adı')
        self.assertIn('RuntimeError', logs)
        self.assertEqual(self.reload(payment).receipt_state, 'failed')
        self.assertNotIn('adresine gönderildi', self.chatter(payment))

    def test_kilitten_sonra_durum_paid_degilse_gonderilmez(self):
        payment = self.paid_order()
        wizard = self.wiz(payment, NEW_ADDRESS)

        def lock_then_void(this):
            this.write({'state': 'voided'})
            this.flush_recordset()
            return True

        with patch.object(type(payment), '_lock_for_provider_call', lock_then_void):
            with self.assertRaises(UserError):
                wizard.action_send()
        self.assertNotEqual(self.reload(payment).receipt_state, 'sent')
        self.assertNotIn('adresine gönderildi', self.chatter(payment))

    def test_cron_gonderimdeyken_elle_gonderim_sent_yazar_cron_ezmez(self):
        """sending -> elle gönderim sent yazar -> cron sonucu (failed) yazmaz (sözleşme A4-G2)."""
        payment = self.paid_order()
        payment.sudo().write({'receipt_state': 'pending'})

        def manual_during_send(this, email):
            self.wiz(this, NEW_ADDRESS).action_send()   # claim commit'inden SONRA, kilitsiz
            return False                                # cron SMTP hatası görür

        with patch.object(type(payment), '_send_receipt_mail', manual_during_send):
            self.run_cron(CRON_RECEIPT)
        self.assertEqual(self.reload(payment).receipt_state, 'sent', 'cron elle gönderimin sent\'ini ezmedi')

    def test_form_dugmeleri_grupsuz_kullaniciya_calismaz_ve_paid_disinda_usererror(self):
        payment = self.paid_order()
        for method in ('action_receipt_download', 'action_receipt_send'):
            with self.subTest(method=method):
                with self.assertRaises(AccessError):
                    getattr(payment.with_user(self.user_plain), method)()
                self.assertTrue(getattr(payment.with_user(self.user_sp), method)())
        payment.sudo().write({'state': 'voided'})
        for method in ('action_receipt_download', 'action_receipt_send'):
            with self.subTest(method=method, state='voided'):
                with self.assertRaises(UserError):
                    getattr(payment.with_user(self.user_sp), method)()

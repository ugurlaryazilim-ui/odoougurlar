# -*- coding: utf-8 -*-
"""A4-G2 kardeş yol testleri: otomatik dekont e-postası (K-18; sözleşme-A4-G2 "Kardeş yollar").

Kabul testleri (test_mail_order_receipt.TestReceiptMail) ana akışı sınar; burada paid'e giren diğer
yollar (Kapat, K-15 yeniden açma, senkron cron'u), girmemesi gerekenler (iade reddi dönüşü, aynı
sorguda iptal, Aşama 4 öncesi paid) ve yan iş/yarış hataları (DERSLER-14, REPEATABLE READ) sınanır.

DIKKAT: gerçek iki bağlantılı SKIP LOCKED/serileştirme yarışı TransactionCase'te üretilemez
(veri commit edilmez); hata yolları yamalarla taklit edilir (BORC: iki bağlantılı PoC).
"""
import smtplib
from unittest.mock import patch

from psycopg2 import errors as pg_errors

from odoo.tests import tagged

from .common import EMAIL, tran
from .test_mail_order import MailOrderCase
from .test_mail_order_receipt import CRON_RECEIPT, PAYMENT, ReceiptMixin

QUEUE_FAILED_NOTE = 'otomatik gönderim için kuyruğa alınamadı'
SENT_NOTE = 'Dekont %s adresine gönderildi' % EMAIL


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReceiptSiblings(ReceiptMixin, MailOrderCase):

    def model_class(self):
        return type(self.env[PAYMENT])

    def serialization_failure(self):
        return pg_errors.SerializationFailure('could not serialize access due to concurrent update')

    # -- paid'e giren diğer yollar ------------------------------------------------------
    def test_kapat_sonucu_paid_bir_kez_kuyruga_alir(self):
        payment = self.create_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-KAPAT', last4='4358'))
        payment.with_user(self.user_sp).action_mail_order_close()
        self.reload(payment)
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'pending'))
        self.run_receipt_cron()
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')

    def test_k15_yeniden_acma_onay_bulursa_kuyruga_alir(self):
        payment = self.create_mail_order()
        payment.with_user(self.user_sp).action_mail_order_close()
        self.assertEqual(self.reload(payment).state, 'expired')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-OLD', last4='4358'))
        self.mail_order_wizard().action_create_mail_order()      # _reopen_mail_order -> _apply_open_status
        self.reload(payment)
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'pending'))
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)

    def test_cron_senkronu_paid_yapinca_kuyruga_alir(self):
        payment = self.make_mail_order(invoice_no=self.next_inv())
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-CRON', last4='4358'))
        self.run_cron()                                          # 10 dakikalık senkron cron'u
        self.reload(payment)
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'pending'))

    # -- kuyruğa girmemesi gerekenler ---------------------------------------------------
    def test_ayni_senkronda_iptal_edilen_odeme_kuyruga_alinmaz(self):
        payment = self.make_mail_order(invoice_no=self.next_inv())
        self.sync_to(payment, tran('AP', 'SALE', '9000.00', 'PG-SALE', last4='4358'),
                     tran('AP', 'VOID', '9000.00', 'PG-V'))
        self.assertEqual(payment.state, 'voided')
        self.assertFalse(payment.receipt_state, 'yalnız paid kayda dekont (çelişki kararı 2)')
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])

    def test_iade_reddi_sonrasi_paid_donusu_kuyruga_almaz(self):
        for start in (False, 'sent'):
            with self.subTest(receipt_state=start):
                payment = self.paid_order(invoice_no=self.next_inv())
                payment.sudo().write({'receipt_state': start})
                line = self.make_refund_line(payment, 500.0, state='pending_approval', provider_ref='R-%s' % start)
                payment._recompute_refund_state()
                self.assertEqual(payment.state, 'refund_pending')
                line.sudo().write({'state': 'rejected'})
                payment._recompute_refund_state()
                self.assertEqual(payment.state, 'paid')
                self.assertEqual(payment.receipt_state, start, 'dekont ilk ödemede gönderildi (KK-4.7)')
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])

    def test_deploy_oncesi_paid_kayit_geriye_donuk_gonderilmez(self):
        payment = self.paid_order()                              # receipt_state NULL (Aşama 4 öncesi)
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertFalse(self.reload(payment).receipt_state)

    # -- yan iş hataları (DERSLER-14) ---------------------------------------------------
    def test_kuyruk_yazimi_hata_verirse_odeme_paid_kalir_not_duser(self):
        Model = self.model_class()
        original = Model.write

        def failing(this, vals):
            if vals.get('receipt_state') == 'pending':
                raise ValueError('kuyruk yazımı patladı')
            return original(this, vals)

        with patch.object(Model, 'write', failing), self.capture_logs() as records:
            payment = self.paid_via_sync(invoice_no=self.next_inv())
        self.reload(payment)
        self.assertEqual(payment.state, 'paid', 'yan iş hatası ödemeyi geri almaz')
        self.assertFalse(payment.receipt_state)
        self.assertEqual(self.count_notes(payment, QUEUE_FAILED_NOTE), 1, 'personel elle göndersin')
        self.assertTrue(any('ValueError' in r for r in records))
        self.assertFalse(any('patladı' in r for r in records), 'yalnız sınıf adı loglanır')
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])

    def test_cron_tetigi_kurulamazsa_pending_kalir_periyodik_gonderir(self):
        Cron = type(self.env['ir.cron'])

        def failing(this, at=None):
            raise RuntimeError('tetik kurulamadı')

        with patch.object(Cron, '_trigger', failing):
            payment = self.paid_via_sync(invoice_no=self.next_inv())
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'pending'))
        self.assertEqual(self.cron_trigger_count(CRON_RECEIPT), 0)
        self.run_receipt_cron()                                  # periyodik (10 dk) çalışma
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')

    # -- claim / sonuç yazımı yarışları --------------------------------------------------
    def test_commit_claimden_sonra_gonderimden_once(self):
        payment = self.paid_via_sync()
        Model = self.model_class()
        original = Model._send_receipt_mail
        seen = []

        def spy(this, email):
            seen.append(self.commit_count)
            return original(this, email)

        before = self.commit_count
        with patch.object(Model, '_send_receipt_mail', spy):
            self.run_receipt_cron()
        self.assertEqual(seen, [before + 1], 'claim (sending) gönderimden önce commit edilir')
        self.assertEqual(self.commit_count, before + 2, 'sonuç da commit edilir')
        self.assertEqual(self.reload(payment).receipt_state, 'sent')

    def test_claim_alinamazsa_atlanir_sonraki_turda_gonderilir(self):
        payment = self.paid_via_sync()
        Cursor = type(self.env.cr)
        original = Cursor.execute
        test = self

        def racing(this, query, *args, **kwargs):
            if 'SKIP LOCKED' in str(query) and "receipt_state = 'pending'" in str(query):
                raise test.serialization_failure()               # RR: claim anında satır değişmiş
            return original(this, query, *args, **kwargs)

        with patch.object(Cursor, 'execute', racing):
            self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reload(payment).receipt_state, 'pending', 'kayıt kaybolmaz')
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')

    def test_sonuc_yazimi_serilestirme_hatasinda_bir_kez_yeniden_dener(self):
        payment = self.paid_via_sync()
        Model = self.model_class()
        original = Model._lock_receipt_sending
        calls = []

        def once(this):
            calls.append(self.commit_count)
            if len(calls) == 1:
                raise self.serialization_failure()
            return original(this)

        with patch.object(Model, '_lock_receipt_sending', once):
            self.run_receipt_cron()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], calls[0] + 1, 'yeniden denemeden önce commit (taze anlık görüntü)')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')
        self.assertEqual(self.count_notes(payment, SENT_NOTE), 1)

    def test_sonuc_yazimi_hep_serilestirme_hatasi_sending_kalir_yeniden_gonderilmez(self):
        payment = self.paid_via_sync()
        Model = self.model_class()
        test = self

        def always(this):
            raise test.serialization_failure()

        with patch.object(Model, '_lock_receipt_sending', always):
            self.run_receipt_cron()
        self.assertEqual(self.reload(payment).receipt_state, 'sending', 'çift e-posta yerine sessizlik (K-9)')
        self.assertEqual(self.count_notes(payment, SENT_NOTE), 1, 'gönderim yine kayda geçer')
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)

    def test_sonuc_elle_gonderim_sent_ini_ezmez(self):
        payment = self.paid_via_sync()
        self.smtp_error = smtplib.SMTPException('SMTP kapalı')
        Model = self.model_class()
        original = Model._send_receipt_mail
        test = self

        def manual_wins(this, email):
            ok = original(this, email)
            # A4-G3 sihirbazı cron gönderirken (kilitsiz aralıkta) elle gönderip 'sent' yazdı
            test.env.cr.execute("UPDATE sanal_pos_payment SET receipt_state = 'sent' WHERE id = %s", [this.id])
            return ok

        with patch.object(Model, '_send_receipt_mail', manual_wins):
            self.run_receipt_cron()
        self.reload(payment)
        self.assertEqual(payment.receipt_state, 'sent', "cron'un 'failed' sonucu elle gönderimi ezmez")
        self.assertEqual(self.count_notes(payment, 'Dekont gönderilemedi'), 1)

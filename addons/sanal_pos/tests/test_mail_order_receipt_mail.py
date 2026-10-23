# -*- coding: utf-8 -*-
"""A4-G2 kardeş yol testleri: otomatik dekont e-postası (K-18; sözleşme-A4-G2 "Kardeş yollar").

Kabul testleri (test_mail_order_receipt.TestReceiptMail) ana akışı sınar; burada paid'e giren diğer
yollar (Kapat, K-15 yeniden açma, senkron cron'u), girmemesi gerekenler (iade reddi dönüşü, aynı
sorguda iptal, Aşama 4 öncesi paid) ve yan iş/yarış hataları (DERSLER-14, REPEATABLE READ) sınanır.

DIKKAT: gerçek iki bağlantılı SKIP LOCKED/serileştirme yarışı TransactionCase'te üretilemez
(veri commit edilmez); hata yolları yamalarla taklit edilir (BORC: iki bağlantılı PoC).
"""
import smtplib
from datetime import datetime, timedelta
from unittest.mock import patch

from lxml import etree
from psycopg2 import errors as pg_errors

from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import CRON_DAILY, EMAIL, tran
from .test_mail_order import MailOrderCase
from .test_mail_order_receipt import CRON_RECEIPT, PAYMENT, WIZARD, ReceiptMixin

QUEUE_FAILED_NOTE = 'otomatik gönderim için kuyruğa alınamadı'
SENT_NOTE = 'Dekont %s adresine gönderildi' % EMAIL
FAILED_NOTE = 'Dekont gönderilemedi'


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

    # -- düzeltme turu #1 (Aşama 4 kalite kapıları) ---------------------------------------
    def test_r2_eposta_govdesi_tutari_pdf_ile_ayni_tr_bicimi(self):
        payment = self.paid_order()                              # tahsil 9120.4
        payment.sudo().write({'receipt_state': 'pending'})
        self.run_receipt_cron()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('9.120,40', self.sent[0].body, 'Ö-2/B-B: gövde TR biçimi (format_try)')
        self.assertNotIn('9,120.40', self.sent[0].body)
        self.assertIn('9.120,40', self.sent[0].attachments[0][1], 'PDF ile aynı metin')

    def send_by_wizard(self, payment):
        self.env[WIZARD].with_user(self.user_sp).create(
            {'payment_id': payment.id, 'email': EMAIL}).action_send()
        self.assertEqual(self.reload(payment).receipt_state, 'sent', 'kuyruğa alındı')

    def test_r3_elle_gonderim_kuyruk_smtp_reddederse_failed_yeniden_denemede_sent(self):
        payment = self.paid_order()
        self.send_by_wizard(payment)
        self.smtp_error = smtplib.SMTPException('SMTP kapalı')
        self.queued_mails(payment).send()                        # posta kuyruğu cron'u
        self.reload(payment)
        self.assertEqual((payment.state, payment.receipt_state), ('paid', 'failed'), 'B-C')
        self.assertEqual(self.count_notes(payment, FAILED_NOTE), 1)
        self.assertEqual(self.queued_mails(payment).mapped('state'), ['exception'])
        # kuyruk yeniden dener (Ayarlar > Teknik > E-postalar "Yeniden dene") ve gönderir
        self.smtp_error = None
        mails = self.queued_mails(payment)
        mails.mark_outgoing()
        mails.send()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')
        self.assertEqual(self.count_notes(payment, SENT_NOTE), 2)
        self.assertEqual(self.count_notes(payment, FAILED_NOTE), 1)

    def test_r3_elle_gonderim_kuyruk_basariliysa_sent_kalir_ek_not_yok(self):
        payment = self.paid_order()
        self.send_by_wizard(payment)
        self.queued_mails(payment).send()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.reload(payment).receipt_state, 'sent')
        self.assertEqual(self.count_notes(payment, SENT_NOTE), 1)
        self.assertEqual(self.count_notes(payment, FAILED_NOTE), 0)
        self.assertFalse(self.queued_mails(payment), 'başarıda çekirdek siler (auto_delete)')

    def test_r3_cron_eposta_kaydi_silinmisse_gonderildi_sayilmaz(self):
        payment = self.paid_via_sync()
        MailMail = type(self.env['mail.mail'])

        def vanishing(this, *args, **kwargs):                    # Ö-3: geçersiz adreste auto_delete taklidi
            this.sudo().unlink()
            return True

        with patch.object(MailMail, '_send', vanishing):
            self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reload(payment).receipt_state, 'failed')
        self.assertEqual(self.count_notes(payment, FAILED_NOTE), 1)

    def test_r4_gunluk_cron_30_gunluk_basarisiz_dekont_epostasini_siler_durum_korunur(self):
        self.smtp_error = smtplib.SMTPException('SMTP kapalı')
        old = self.paid_via_sync(invoice_no=self.next_inv())
        fresh = self.paid_via_sync(tran_ref='PG-AP2', invoice_no=self.next_inv())
        self.run_receipt_cron()
        old_mail, fresh_mail = self.queued_mails(old), self.queued_mails(fresh)
        self.assertEqual((old_mail.state, fresh_mail.state), ('exception', 'exception'))
        message, attachments = old_mail.mail_message_id, old_mail.attachment_ids
        self.assertTrue(attachments, 'PDF eki var')
        notifications = self.env['mail.mail'].sudo().search(
            [('model', '=', PAYMENT), ('res_id', '=', old.id), ('is_notification', '=', True)])
        aged = datetime.utcnow() - timedelta(days=31)
        self.env.flush_all()
        self.env.cr.execute('UPDATE mail_mail SET create_date = %s WHERE id IN %s',
                            [aged, tuple((old_mail | notifications).ids)])
        self.env.invalidate_all()
        self.run_cron(CRON_DAILY)
        self.assertFalse(old_mail.exists(), 'G4-2: 30 günlük başarısız dekont e-postası silinir')
        self.assertFalse(message.exists())
        self.assertFalse(attachments.exists(), 'PDF eki de silinir')
        self.assertEqual(fresh_mail.exists(), fresh_mail, '30 günden yeni olan kalır')
        self.assertEqual(notifications.exists(), notifications, 'bildirim e-postalarına dokunulmaz')
        self.reload(old)
        self.assertEqual((old.state, old.receipt_state), ('paid', 'failed'), 'durum korunur')
        self.assertEqual(self.count_notes(old, FAILED_NOTE), 1, 'kayıt notu korunur')

    def test_r5_otomatik_gonderim_tek_adres_kurali_sihirbazla_ayni(self):
        payment = self.paid_via_sync(customer_email='a@example.com,b@example.com')
        self.run_receipt_cron()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.reload(payment).receipt_state, 'no_email')

    def test_r6_odemesi_iptal_edilen_kayitta_bekleyen_dekont_gorunmez(self):
        arch = etree.fromstring(self.env[PAYMENT].get_view(
            self.env.ref('sanal_pos.view_sanal_pos_payment_form').id, 'form')['arch'])
        expr = arch.xpath("//field[@name='receipt_state']")[0].get('invisible')
        for (method, state, receipt), hidden in (
                (('mail_order', 'voided', 'pending'), True),
                (('mail_order', 'refunded', 'sending'), True),
                (('mail_order', 'voided', 'sent'), False),
                (('mail_order', 'paid', 'pending'), False),
                (('mail_order', 'paid', 'failed'), False),
                (('link', 'paid', 'sent'), True)):
            with self.subTest(method=method, state=state, receipt=receipt):
                ctx = {'payment_method': method, 'state': state, 'receipt_state': receipt}
                self.assertEqual(bool(safe_eval(expr, ctx)), hidden)

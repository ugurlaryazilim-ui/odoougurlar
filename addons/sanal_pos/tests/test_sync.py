# -*- coding: utf-8 -*-
"""G9 / durum senkronu. KK-16 (uzlaştırma), KK-22 (karar), KK-23 (tutarsız), KK-24, KK-25,
KK-26, KK-27 (panel iade/iptal), KK-28, KK-30, KK-39 (log temizliği), KK-52 (ortam).

Durum kararı YALNIZ ``QUERYTRANSACTION`` yanıtından verilir; sağlayıcı bağlantısı
``requests`` düzeyinde taklit edilir. ``find_link`` şeması belgelenmediği için
uzlaştırma testlerinde sağlayıcı arayüzü (02-tasarim §5) yamalanır.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import (
    CRON_DAILY, CRON_SYNC, INV_NO, LIVE_URL_PREFIX, SanalPosCase, err_body, invoice_rows,
    qt_body, timeout_exc, tran,
)

PROVIDER = 'sanal.pos.provider.paratika'


class SyncCase(SanalPosCase):

    def sync(self, payment):
        payment.sudo()._sync_status()
        payment.invalidate_recordset()
        return payment

    def sent(self, **vals):
        return self.make_payment(state='sent', **vals)

    def approve_every_query(self):
        """Her ödeme için kendi MPID'sine bağlı onaylı satış döndürür."""
        self.mock.default('QUERYTRANSACTION', lambda p: qt_body(
            tran('AP', 'SALE', '9000.00', 'PG-' + p['MERCHANTPAYMENTID'])))

    def patch_find_link(self, **result):
        base = {'ok': True, 'timeout': False, 'error_code': None, 'error_message': None,
                'found': False, 'token': None, 'status': None}
        base.update(result)
        return patch.object(type(self.env[PROVIDER]), 'find_link', return_value=base)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestDecisionFromQuery(SyncCase):

    def test_kk22_ap_sale_esit_tutar_odendi(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-77', installments=3, last4='4242'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.provider_tran_ref, 'PG-77')
        self.assertEqual(payment.paid_amount, 9000.0)
        self.assertEqual(payment.installment_count, 3)
        self.assertEqual(payment.card_last4, '4242')
        self.assertTrue(payment.paid_at)
        self.assertLess(abs(datetime.utcnow() - payment.paid_at), timedelta(minutes=5))
        call = self.mock.last('QUERYTRANSACTION')
        self.assertEqual(call.params['MERCHANTPAYMENTID'], payment.merchant_payment_id)

    def test_kk22_tutar_kurus_duzeyinde_karsilastirilir(self):
        for amount in ('9000', '9000.0', '9000.00'):
            with self.subTest(amount=amount):
                payment = self.make_payment(state='sent', invoice_no='EQ%s' % len(amount))
                self.set_query_transactions(tran('AP', 'SALE', amount, 'PG-EQ'))
                self.sync(payment)
                self.assertEqual(payment.state, 'paid')

    def test_kk22_onaysiz_durumlar_degistirmez(self):
        for i, status in enumerate(('FA', 'CA', 'IP')):
            with self.subTest(status=status):
                payment = self.make_payment(state='sent', invoice_no='ST%d' % i)
                self.set_query_transactions(tran(status, 'SALE', '9000.00', 'PG-X%d' % i))
                self.sync(payment)
                self.assertEqual(payment.state, 'sent')
                self.assertFalse(payment.provider_tran_ref)

    def test_kk22_ap_ama_sale_degil(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'REFUND', '9000.00', 'PG-R'))
        self.sync(payment)
        self.assertNotEqual(payment.state, 'paid')

    def test_kk22_bos_sorgu_durumu_degistirmez(self):
        payment = self.sent()
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertTrue(payment.last_checked_at)

    def test_kk22_birden_cok_islem_basarisiz_sonra_onayli(self):
        payment = self.sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'), tran('AP', 'SALE', '9000.00', 'PG-2'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.provider_tran_ref, 'PG-2')

    def test_kk22_belirsiz_kayit_da_odendi_olur(self):
        payment = self.make_payment(state='unknown')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-U'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')

    def test_kk22_idempotent_ikinci_senkron_degistirmez(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-ID'))
        self.sync(payment)
        notes = self.chatter(payment)
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.provider_tran_ref, 'PG-ID')
        self.assertEqual(self.chatter(payment).count('ödendi'), notes.count('ödendi'),
                         'ikinci senkron ikinci “ödendi” notu yazmamalı')

    def test_kk22_odenmis_kayit_sonraki_bos_sorguyla_geri_donmez(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-KEEP'))
        self.sync(payment)
        self.set_query_transactions()
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')

    def test_kk22_sorgu_gecersiz_islem_kayitlari_tolere_edilir(self):
        """Zaman alanı yok / taksit yok: yine de ödendi, eksik alanlar patlatmaz."""
        payment = self.sent()
        item = tran('AP', 'SALE', '9000.00', 'PG-MIN')
        item.pop('installmentCount')
        item.pop('panLast4')
        self.set_query_transactions(item)
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')

    def test_kk22_para_birimi_try_degilse_inceleme(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-USD', currency='USD'))
        self.sync(payment)
        self.assertEqual(payment.state, 'review')

    def test_kk52_kayit_ortami_ayardan_bagimsiz(self):
        """Canlı ortamda açılmış kayıt, ayar sonradan test olsa bile canlı adrese sorulur."""
        payment = self.sent(environment='live')
        self.assertEqual(self.get_setting_value('environment'), 'test')
        self.sync(payment)
        self.assertTrue(self.mock.last('QUERYTRANSACTION').url.startswith(LIVE_URL_PREFIX))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestQueryFailures(SyncCase):

    def test_paratika_hatasi_durumu_degistirmez(self):
        payment = self.sent()
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10001', 'x'))
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertTrue(payment.last_checked_at)

    def test_zaman_asimi_durumu_degistirmez(self):
        payment = self.sent()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')

    def test_zaman_asimi_odenmisi_kaybetmez(self):
        payment = self.make_paid()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestAmountMismatch(SyncCase):

    def test_kk24_tutar_uyusmazligi_inceleme(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '8999.99', 'PG-MM'))
        self.sync(payment)
        self.assertEqual(payment.state, 'review')
        note = self.chatter(payment)
        self.assertIn('9.000,00', note)
        self.assertIn('8.999,99', note)

    def test_kk24_fazla_tahsilat_da_inceleme(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.01', 'PG-MM2'))
        self.sync(payment)
        self.assertEqual(payment.state, 'review')
        self.assertIn('9.000,01', self.chatter(payment))

    def test_kk24_olusturana_bildirim(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '100.00', 'PG-MM3'))
        self.sync(payment)
        self.assertIn(self.user_sp.partner_id, self.notified_partners(payment))

    def test_kk24_mr_incelemeye_alir(self):
        payment = self.sent()
        self.set_query_transactions(tran('MR', 'SALE', '9000.00', 'PG-MR'))
        self.sync(payment)
        self.assertEqual(payment.state, 'review')

    def test_kk24_gec_gelen_odeme_suresi_dolmus_kayitta_inceleme(self):
        for state in ('expired', 'link_cancelled'):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, invoice_no='LATE-%s' % state)
                self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LATE'))
                self.sync(payment)
                self.assertEqual(payment.state, 'review')
                self.assertIn('9.000,00', self.chatter(payment))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestExpiry(SyncCase):

    def past_sent(self, **vals):
        past = datetime.utcnow() - timedelta(minutes=30)
        return self.sent(sent_at=past - timedelta(hours=168), expires_at=past, **vals)

    def test_kk25_suresi_gecmis_onaysiz_kayit_expired(self):
        payment = self.past_sent()
        self.sync(payment)
        self.assertEqual(payment.state, 'expired')

    def test_kk25_suresi_gecmemis_kayit_sent_kalir(self):
        payment = self.sent()
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')

    def test_kk25_suresi_gecmis_ama_odenmis_paid_olur(self):
        payment = self.past_sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LE'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')

    def test_kk25_suresi_gecmis_basarisiz_denemeli_expired(self):
        payment = self.past_sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-F'))
        self.sync(payment)
        self.assertEqual(payment.state, 'expired')

    def test_kk25_expired_sonrasi_yeni_link_acilabilir(self):
        old = self.past_sent()
        self.sync(old)
        self.create_link(channel_sms=True, channel_email=True)
        self.assertEqual(self.last_payment().attempt_no, 2)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestFailedAttempts(SyncCase):

    def test_kk26_basarisiz_denemeler_sayilir_durum_sent(self):
        payment = self.sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'), tran('CA', 'SALE', '9000.00', 'PG-2'))
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.failed_attempt_count, 2)
        self.assertTrue(payment.last_error_message)

    def test_kk26_idempotent_sayim(self):
        payment = self.sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'))
        self.sync(payment)
        self.sync(payment)
        self.sync(payment)
        self.assertEqual(payment.failed_attempt_count, 1, 'aynı işlem her senkronda yeniden sayılmamalı')

    def test_kk26_yeni_basarisiz_islem_sayiyi_arttirir(self):
        payment = self.sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'))
        self.sync(payment)
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'), tran('FA', 'SALE', '9000.00', 'PG-2'))
        self.sync(payment)
        self.assertEqual(payment.failed_attempt_count, 2)

    def test_kk26_sonradan_odenirse_paid(self):
        payment = self.sent()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'))
        self.sync(payment)
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-1'), tran('AP', 'SALE', '9000.00', 'PG-2'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.failed_attempt_count, 1)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPanelRefunds(SyncCase):
    """KK-27: panelden yapılan iade/iptal Odoo geçmişine 'panel' kaynağıyla girer."""

    def paid(self, **kw):
        return self.make_paid(self.make_payment(**kw), tran_ref='PG-SALE')

    def test_kk27_panel_kismi_iade_satir_olur(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '1000.00', 'PG-R1'))
        self.sync(payment)
        lines = payment.refund_ids
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines.source, lines.state, lines.kind, lines.provider_ref),
                         ('panel', 'done', 'refund', 'PG-R1'))
        self.assertEqual(lines.amount, 1000.0)
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 1000.0)
        self.assertEqual(payment.refundable_amount, 8000.0)

    def test_kk27_idempotent_ayni_islem_iki_kez_eklenmez(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '1000.00', 'PG-R1'))
        self.sync(payment)
        self.sync(payment)
        self.sync(payment)
        self.assertEqual(len(payment.refund_ids), 1)
        self.assertEqual(payment.refunded_amount, 1000.0)

    def test_kk27_ptrefund_turu_de_desteklenir(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'PTREFUND', '500.00', 'PG-PT'))
        self.sync(payment)
        self.assertEqual(payment.refunded_amount, 500.0)
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk27_panel_tam_iade_refunded(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '9000.00', 'PG-RF'))
        self.sync(payment)
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refundable_amount, 0.0)

    def test_kk27_panel_iptal_voided_iki_bicim(self):
        for i, items in enumerate((
            [tran('AP', 'SALE', '9000.00', 'PG-SALE'), tran('AP', 'VOID', '9000.00', 'PG-V')],
            [tran('VD', 'SALE', '9000.00', 'PG-SALE')],
        )):
            with self.subTest(form=i):
                payment = self.paid(invoice_no='VD%d' % i)
                self.set_query_transactions(*items)
                self.sync(payment)
                self.assertEqual(payment.state, 'voided')
                self.assertTrue(payment.refund_ids.filtered(lambda r: r.kind == 'void' and r.source == 'panel'))

    def test_kk27_birden_cok_panel_iadesi_toplanir(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '1000.00', 'PG-A'),
                                    tran('AP', 'REFUND', '2500.50', 'PG-B'))
        self.sync(payment)
        self.assertEqual(len(payment.refund_ids), 2)
        self.assertEqual(payment.refunded_amount, 3500.5)
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk27_odoo_iadesi_panel_olarak_tekrar_eklenmez(self):
        payment = self.paid()
        line = self.make_refund_line(payment, 1000.0, state='done', source='odoo', provider_ref='PG-R1')
        payment._recompute_refund_state()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '1000.00', 'PG-R1'))
        self.sync(payment)
        self.assertEqual(payment.refund_ids, line)
        self.assertEqual(payment.refunded_amount, 1000.0)

    def test_kk27_reddedilmis_iade_sayilmaz(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('FA', 'REFUND', '1000.00', 'PG-RX'))
        self.sync(payment)
        self.assertFalse(payment.refund_ids)
        self.assertEqual(payment.state, 'paid')

    def test_kk27_gunluk_cron_son_30_gun_odenenleri_gunde_bir_kez_sorgular(self):
        recent = self.paid(invoice_no='DAILY1')
        old = self.make_paid(self.make_payment(invoice_no='DAILY2'), paid_at=datetime.utcnow() - timedelta(days=40),
                             tran_ref='PG-OLD')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '700.00', 'PG-D'))
        self.run_cron(CRON_DAILY)
        self.assertEqual(recent.refunded_amount, 700.0)
        self.assertFalse(old.refund_ids, '30 günden eski ödeme günlük panel senkronuna girmemeli')
        queries = self.mock.count('QUERYTRANSACTION')
        self.run_cron(CRON_DAILY)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), queries, 'aynı gün ikinci kez sorgulanmamalı')

    def test_kk27_iade_edilmis_kayit_sync_ile_geri_donmez(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '9000.00', 'PG-RF'))
        self.sync(payment)
        self.sync(payment)
        self.assertEqual(payment.state, 'refunded')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCheckStatusButton(SyncCase):

    def test_kk28_kullanici_durumu_sorgular(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-BTN'))
        payment.with_user(self.user_sp).action_check_status()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')

    def test_kk28_kapanmamis_eski_kayitta_calisir(self):
        payment = self.sent()
        self.set_create_date(payment, datetime.utcnow() - timedelta(days=45))
        payment.sudo().write({'sent_at': datetime.utcnow() - timedelta(days=45)})
        payment.with_user(self.user_sp).action_check_status()
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk28_kapanmis_30_gunden_eski_kayitta_sorgu_yok(self):
        old = datetime.utcnow() - timedelta(days=45)
        payment = self.make_payment(state='link_cancelled', sent_at=old, expires_at=old + timedelta(hours=168))
        self.set_create_date(payment, old)
        with self.assertRaises(UserError):
            payment.with_user(self.user_sp).action_check_status()
        self.assertNoParatikaCalls()

    def test_kk28_odenmis_yeni_kayitta_calisir(self):
        payment = self.make_paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SALE'),
                                    tran('AP', 'REFUND', '100.00', 'PG-P'))
        payment.with_user(self.user_sp).action_check_status()
        payment.invalidate_recordset()
        self.assertEqual(payment.refunded_amount, 100.0)

    def test_kk28_paratika_hatasinda_durum_degismez(self):
        payment = self.sent()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        try:
            payment.with_user(self.user_sp).action_check_status()
        except UserError:
            pass
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')

    def test_kk28_yetkisiz_kullanici_sorgulayamaz(self):
        payment = self.sent()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_plain).action_check_status()
        self.assertNoParatikaCalls()


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPaidNotification(SyncCase):

    def test_kk30_olusturana_bildirim_metni(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-N'))
        self.sync(payment)
        text = self.notification_texts(payment, self.user_sp.partner_id)
        self.assertIn('%s – 9.000,00 TL ödendi' % INV_NO, text)
        self.assertIn('9.000,00 TL', self.chatter(payment))

    def test_kk30_baska_kullaniciya_bildirim_gitmez(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-N2'))
        self.sync(payment)
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))
        self.assertNotIn(self.user_mgr.partner_id, self.notified_partners(payment))

    def test_kk30_musteriye_odoo_mesaji_gitmez(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-N3'))
        self.sync(payment)
        messages = self.env['mail.message'].sudo().search([('model', '=', 'sanal.pos.payment'),
                                                            ('res_id', '=', payment.id)])
        emails = set(messages.mapped('partner_ids.email')) | set(messages.mapped('email_from'))
        self.assertNotIn('cagri.sahin@example.com', emails)

    def test_kk30_ikinci_senkronda_ikinci_bildirim_yok(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-N4'))
        self.sync(payment)
        first = self.notification_texts(payment, self.user_sp.partner_id).count('ödendi')
        self.sync(payment)
        self.assertEqual(self.notification_texts(payment, self.user_sp.partner_id).count('ödendi'), first)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCronSync(SyncCase):

    def test_kk25_cron_gonderildi_kayitlari_isler(self):
        payment = self.sent()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-C'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')

    def test_kk25_cron_odenmis_veya_kapali_kayitlari_sorgulamaz(self):
        self.make_payment(state='expired', invoice_no='C-EXP')
        self.make_payment(state='link_cancelled', invoice_no='C-CAN')
        self.make_payment(state='error', invoice_no='C-ERR')
        self.make_paid(self.make_payment(invoice_no='C-PAID'))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_kk25_cron_en_fazla_200_kayit(self):
        for i in range(205):
            self.make_payment(state='sent', invoice_no='LIM%04d' % i)
        self.run_cron(CRON_SYNC)
        count = self.mock.count('QUERYTRANSACTION')
        self.assertGreater(count, 0)
        self.assertLessEqual(count, 200, 'tek çalıştırmada en fazla 200 kayıt işlenmeli')

    def test_kk25_ikinci_calistirma_kalanlari_isler(self):
        payments = [self.make_payment(state='sent', invoice_no='TWO%04d' % i) for i in range(205)]
        self.run_cron(CRON_SYNC)
        self.run_cron(CRON_SYNC)
        self.env['sanal.pos.payment'].invalidate_model()
        unchecked = [p for p in payments if not p.last_checked_at]
        self.assertEqual(unchecked, [], 'iki çalıştırmada tüm kayıtlar en az bir kez sorgulanmalı')

    def test_kk25_tek_kayit_hatasi_cron_u_durdurmaz(self):
        payments = [self.make_payment(state='sent', invoice_no='ERR%d' % i) for i in range(4)]
        self.approve_every_query()
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10001', 'x'))
        self.run_cron(CRON_SYNC)
        states = sorted(p.state for p in self.env['sanal.pos.payment'].browse([x.id for x in payments]))
        self.assertEqual(states, ['paid', 'paid', 'paid', 'sent'])

    def test_kk25_zaman_asimi_diger_kayitlari_etkilemez(self):
        payments = [self.make_payment(state='sent', invoice_no='TMO%d' % i) for i in range(3)]
        self.approve_every_query()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.run_cron(CRON_SYNC)
        states = sorted(p.state for p in self.env['sanal.pos.payment'].browse([x.id for x in payments]))
        self.assertEqual(states, ['paid', 'paid', 'sent'])

    def test_bayat_sending_unknown_olur(self):
        stale = self.make_payment(state='sending', sent_at=False, invoice_no='STALE1', provider_token=False)
        self.set_create_date(stale, datetime.utcnow() - timedelta(minutes=10))
        fresh = self.make_payment(state='sending', sent_at=False, invoice_no='FRESH1', provider_token=False)
        with self.patch_find_link():
            self.run_cron(CRON_SYNC)
        stale.invalidate_recordset()
        fresh.invalidate_recordset()
        self.assertIn(stale.state, ('unknown', 'error', 'sent'))
        self.assertNotEqual(stale.state, 'sending', 'bayat Gönderiliyor kaydı takılı kalmamalı')
        self.assertEqual(fresh.state, 'sending', 'yeni Gönderiliyor kaydına dokunulmamalı')

    def test_sync_requested_bayragi_islenir_ve_temizlenir(self):
        payment = self.sent(sync_requested=True)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-REQ'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertFalse(payment.sync_requested)

    def test_sync_requested_bayragi_odenmemisse_da_temizlenir(self):
        payment = self.sent(sync_requested=True)
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')
        self.assertFalse(payment.sync_requested)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestUnknownReconcile(SyncCase):
    """KK-16: zaman aşımından sonra 'Belirsiz' kayıt gerçek durumuna uzlaştırılır."""

    def test_kk16_link_bulunursa_gonderildi(self):
        payment = self.make_payment(state='unknown', provider_token=False, sent_at=False, expires_at=False)
        with self.patch_find_link(found=True, token='TOK-FOUND', status='ACTIVE'):
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.provider_token, 'TOK-FOUND')
        self.assertTrue(payment.expires_at)

    def test_kk16_link_bulunamazsa_hata(self):
        payment = self.make_payment(state='unknown', provider_token=False, sent_at=False, expires_at=False)
        with self.patch_find_link(found=False):
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')
        self.assertIn('Link', self.chatter(payment) + (payment.last_error_message or ''))

    def test_kk16_once_odeme_sorgusu_odenmisse_paid(self):
        payment = self.make_payment(state='unknown', provider_token=False)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-UNK'))
        with self.patch_find_link(found=False) as find:
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertFalse(find.called, 'ödenmiş belirsiz kayıtta link araması gerekmez')

    def test_kk16_arama_zaman_asimi_belirsiz_kalir(self):
        payment = self.make_payment(state='unknown', provider_token=False)
        with self.patch_find_link(ok=False, timeout=True, error_code='TIMEOUT'):
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'unknown')

    def test_kk16_uzlastirma_yeni_link_acilmasini_engellemez_ve_cift_istek_yok(self):
        """Belirsizken yeni link açılamaz; uzlaştırma sonucu hataysa yeniden açılabilir."""
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        self.set_invoice(invoice_rows())
        self.wizard(channel_sms=True, channel_email=True).action_create_link()
        payment = self.last_payment()
        self.assertEqual(payment.state, 'unknown')
        with self.patch_find_link(found=False):
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')
        self.wizard(channel_sms=True, channel_email=True).action_create_link()
        self.assertEqual(self.last_payment().attempt_no, 2)
        self.assertEqual(self.last_payment().state, 'sent')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReviewActions(SyncCase):

    def review(self):
        return self.make_payment(state='review', provider_tran_ref='PG-REV', paid_amount=8999.99)

    def test_yonetici_inceleme_odendi_kabul_eder(self):
        payment = self.review()
        payment.with_user(self.user_mgr).action_review_accept()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertIn(self.user_mgr.name, self.chatter(payment))

    def test_yonetici_inceleme_kapatir(self):
        payment = self.review()
        payment.with_user(self.user_mgr).action_review_close()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')

    def test_kullanici_inceleme_eylemlerini_yapamaz(self):
        payment = self.review()
        for method in ('action_review_accept', 'action_review_close'):
            with self.subTest(method=method):
                with self.assertRaises(AccessError):
                    getattr(payment.with_user(self.user_sp), method)()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')

    def test_inceleme_disindaki_kayitta_eylem_reddedilir(self):
        payment = self.make_payment(state='sent')
        for method in ('action_review_accept', 'action_review_close'):
            with self.subTest(method=method):
                with self.assertRaises(UserError):
                    getattr(payment.with_user(self.user_mgr), method)()
        self.assertEqual(payment.state, 'sent')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLogPurge(SyncCase):
    """KK-39: 180 günden eski log silinir, mali (VOID/REFUND) kayıtlar silinmez."""

    def make_log(self, days, financial=False, action='QUERYTRANSACTION'):
        log = self.env['sanal.pos.log'].sudo().create({
            'action': action, 'provider': 'paratika', 'environment': 'test',
            'success': True, 'is_financial': financial,
        })
        self.set_create_date(log, datetime.utcnow() - timedelta(days=days))
        return log

    def test_kk39_eski_log_silinir_mali_log_kalir(self):
        old = self.make_log(200)
        recent = self.make_log(10)
        edge = self.make_log(179)
        old_fin = self.make_log(400, financial=True, action='REFUND')
        self.run_cron(CRON_DAILY)
        existing = self.env['sanal.pos.log'].sudo().browse([old.id, recent.id, edge.id, old_fin.id]).exists()
        self.assertNotIn(old, existing)
        self.assertIn(recent, existing)
        self.assertIn(edge, existing)
        self.assertIn(old_fin, existing, 'mali işlem kayıtları temizlikten muaf olmalı')

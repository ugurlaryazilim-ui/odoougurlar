# -*- coding: utf-8 -*-
"""G8 / yönetici kararlarıyla eklenen senkron kuralları (08-sozlesme-G8.md).

* Risk 1: zaman aşımı/belirsizlik sonrası "link bulunamadı" yanıtı kaydı tek sorguda 'Hata'
  yapmaz; en az 2 ayrı sorgu VE ilk belirsizlikten >= 15 dk gerekir (çift tahsilat önlemi).
* Risk 2: webhook anında satır kilitliyse bayrak yazılmaz; sıradaki periyodik cron yakalar.
* Risk 3: inceleme "Kapat" kapatma notu ister; not chatter'a yazılır.
* Fark 1: hatalı/kapalı kayda geç ödeme -> İnceleme gerekli.
* Fark 2: link süresi dolmuş ve sorgu + arama onaylı işlem göstermiyorsa Belirsiz -> Süresi doldu.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CRON_DAILY, CRON_SYNC, invoice_rows, timeout_exc, tran
from .test_sync import SyncCase

NOT_FOUND = "Link Paratika'da bulunamadı; yeni link oluşturabilirsiniz."
AMBIGUOUS = 'birden fazla aday link'
BOTH = {'channel_sms': True, 'channel_email': True}


class RulesCase(SyncCase):

    def unknown(self, minutes_ago=0, **vals):
        vals.setdefault('unknown_since', datetime.utcnow() - timedelta(minutes=minutes_ago))
        return self.make_payment(state='unknown', provider_token=False, sent_at=False,
                                 expires_at=False, **vals)

    def reconcile(self, payment, **find):
        with self.patch_find_link(**find):
            payment.sudo()._reconcile_unknown_link()
        payment.invalidate_recordset()
        return payment


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLinkNotFoundRule(RulesCase):
    """Risk 1 (yönetici şartı)."""

    def test_tek_bulunamadi_yaniti_hata_yapmaz_ve_yeni_link_engelli_kalir(self):
        payment = self.unknown(minutes_ago=60)
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'unknown', 'tek "bulunamadı" yanıtı kaydı Hata yapmamalı')
        self.assertEqual(payment.link_not_found_count, 1)
        self.assertEqual(payment.last_error_code, 'LINK_NOT_FOUND_PENDING')
        self.set_invoice(invoice_rows())
        self.mock.calls.clear()
        with self.assertRaises(UserError):
            self.wizard(**BOTH).action_create_link()
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0, 'belirsizken yeni link isteği gitmemeli')

    def test_iki_bulunamadi_15_dk_dolmadan_hata_yapmaz(self):
        payment = self.unknown(minutes_ago=5)
        self.reconcile(payment, found=False)
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'unknown')
        self.assertEqual(payment.link_not_found_count, 2)

    def test_iki_bulunamadi_ve_15_dk_sonra_hata(self):
        payment = self.unknown(minutes_ago=16)
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'unknown')
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'error')
        self.assertEqual(payment.last_error_code, 'LINK_NOT_FOUND')
        self.assertIn(NOT_FOUND, self.chatter(payment))

    def test_belirsizlik_baslangici_yoksa_olusturma_zamani_esas(self):
        payment = self.unknown(unknown_since=False)
        self.set_create_date(payment, datetime.utcnow() - timedelta(minutes=30))
        self.reconcile(payment, found=False)
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'error')

    def test_bulunursa_sayac_sifirlanir(self):
        payment = self.unknown(minutes_ago=16)
        self.reconcile(payment, found=False)
        self.reconcile(payment, found=True, token='TOK-LATE', status='ACTIVE')
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.provider_token, 'TOK-LATE')
        self.assertEqual(payment.link_not_found_count, 0)

    def test_arama_zaman_asimi_sayaci_artirmaz(self):
        payment = self.unknown(minutes_ago=60)
        self.reconcile(payment, ok=False, timeout=True, error_code='TIMEOUT')
        self.reconcile(payment, ok=False, timeout=True, error_code='TIMEOUT')
        self.assertEqual(payment.state, 'unknown')
        self.assertEqual(payment.link_not_found_count, 0)

    def test_odeme_sorgusu_basarisizsa_arama_yapilmaz(self):
        payment = self.unknown(minutes_ago=60)
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        with self.patch_find_link(found=False) as find:
            payment.sudo()._reconcile_unknown_link()
        self.assertFalse(find.called, 'ödeme sorgusu yanıtsızken "bulunamadı" sayılmamalı')
        self.assertEqual(payment.link_not_found_count, 0)

    def test_g7_belirsiz_kayit_baslangic_zamani_yazar(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        self.set_invoice(invoice_rows())
        self.wizard(**BOTH).action_create_link()
        payment = self.last_payment()
        self.assertEqual(payment.state, 'unknown')
        self.assertTrue(payment.unknown_since)
        self.assertEqual(payment.link_not_found_count, 0)

    def test_cron_tek_turda_hata_yapmaz_ikinci_turda_yapar(self):
        payment = self.unknown(minutes_ago=20)
        with self.patch_find_link(found=False):
            self.run_cron(CRON_SYNC)
            payment.invalidate_recordset()
            self.assertEqual(payment.state, 'unknown')
            self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestAmbiguousAndExpiry(RulesCase):

    def test_ambiguous_notu_bir_kez_yazilir(self):
        payment = self.unknown()
        for _i in range(3):
            self.reconcile(payment, ok=False, timeout=True, ambiguous=True, error_code='AMBIGUOUS')
        self.assertEqual(payment.state, 'unknown')
        self.assertEqual(payment.last_error_code, 'AMBIGUOUS')
        self.assertEqual(self.chatter(payment).count(AMBIGUOUS), 1)

    def test_fark2_suresi_dolmus_belirsiz_kayit_expired(self):
        for i, find in enumerate(({'found': False},
                                  {'ok': False, 'timeout': True, 'ambiguous': True,
                                   'error_code': 'AMBIGUOUS'})):
            with self.subTest(find=find):
                payment = self.unknown(invoice_no='F2-%d' % i)
                self.set_create_date(payment, datetime.utcnow() - timedelta(hours=170))
                self.reconcile(payment, **find)
                self.assertEqual(payment.state, 'expired')

    def test_fark2_arama_yanitsizsa_belirsiz_kalir(self):
        payment = self.unknown()
        self.set_create_date(payment, datetime.utcnow() - timedelta(hours=170))
        self.reconcile(payment, ok=False, timeout=True, error_code='TIMEOUT')
        self.assertEqual(payment.state, 'unknown')

    def test_fark2_onayli_islem_varsa_expired_olmaz(self):
        payment = self.unknown()
        self.set_create_date(payment, datetime.utcnow() - timedelta(hours=170))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-F2'))
        self.reconcile(payment, found=False)
        self.assertEqual(payment.state, 'paid')

    def test_fark1_hatali_kayda_gec_odeme_inceleme(self):
        payment = self.make_payment(state='error', sync_requested=True)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-ERRLATE'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')
        self.assertIn('9.000,00', self.chatter(payment))
        self.assertIn(self.user_sp.partner_id, self.notified_partners(payment))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestWebhookFlag(RulesCase):
    """G9 arayüzü ``_mark_sync_requested`` (Risk 2)."""

    def test_bayrak_yazilir_cron_tetiklenir_dis_cagri_yok(self):
        payment = self.sent()
        before = self.cron_trigger_count()
        rec = self.env['sanal.pos.payment']._mark_sync_requested(payment.merchant_payment_id)
        self.assertEqual(rec, payment)
        payment.invalidate_recordset()
        self.assertTrue(payment.sync_requested)
        self.assertGreater(self.cron_trigger_count(), before)
        self.assertNoParatikaCalls()

    def test_bilinmeyen_odeme_numarasi_bos_doner(self):
        before = self.cron_trigger_count()
        rec = self.env['sanal.pos.payment']._mark_sync_requested('YOK-1')
        self.assertFalse(rec)
        self.assertEqual(self.cron_trigger_count(), before)

    def test_risk2_bayrak_yazilamasa_da_siradaki_cron_odemeyi_yakalar(self):
        payment = self.sent()
        Payment = type(self.env['sanal.pos.payment'])
        with patch.object(Payment, '_try_lock_nowait', return_value=False):
            rec = self.env['sanal.pos.payment']._mark_sync_requested(payment.merchant_payment_id)
        self.assertEqual(rec, payment)
        payment.invalidate_recordset()
        self.assertFalse(payment.sync_requested, 'kilitli satıra bayrak yazılmamalı')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-RISK2'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestReviewCloseNote(RulesCase):
    """Risk 3: kapatma notu zorunlu ve chatter'da."""

    def review(self):
        return self.make_payment(state='review', provider_tran_ref='PG-REV', paid_amount=8999.99)

    def close_wizard(self, payment, user, reason):
        action = payment.with_user(user).action_review_close()
        self.assertEqual(action['res_model'], 'sanal.pos.payment.review.close.wizard')
        return self.env[action['res_model']].with_user(user).with_context(
            action['context']).create({'reason': reason})

    def test_dugme_yalniz_sihirbaz_acar(self):
        payment = self.review()
        action = payment.with_user(self.user_mgr).action_review_close()
        self.assertEqual(action['target'], 'new')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')

    def test_kisa_not_reddedilir(self):
        payment = self.review()
        wizard = self.close_wizard(payment, self.user_mgr, '  ab ')
        with self.assertRaises(UserError):
            wizard.action_confirm()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')

    def test_not_chatter_a_yazilir(self):
        payment = self.review()
        reason = 'Panelde tahsilat yok, müşteriyle görüşüldü'
        self.close_wizard(payment, self.user_mgr, reason).action_confirm()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')
        text = self.chatter(payment)
        self.assertIn(reason, text)
        self.assertIn(self.user_mgr.name, text)

    def test_kullanici_kapatamaz(self):
        payment = self.review()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sp)._review_close('Yetkisiz kapatma denemesi')
        with self.assertRaises(AccessError):
            self.env['sanal.pos.payment.review.close.wizard'].with_user(self.user_sp).create(
                {'payment_id': payment.id, 'reason': 'Yetkisiz kapatma denemesi'})
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLocksAndButton(RulesCase):

    def test_cron_kilitli_kaydi_atlar(self):
        payment = self.sent()
        with patch.object(type(self.env['sanal.pos.payment']), '_try_lock_skip_locked',
                          return_value=False):
            self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')

    def test_buton_kilitliyse_mesgul_ve_cagri_yok(self):
        payment = self.sent()
        with patch.object(type(self.env['sanal.pos.payment']), '_lock_for_provider_call',
                          return_value=False):
            with self.assertRaises(UserError):
                payment.with_user(self.user_sp).action_check_status()
        self.assertNoParatikaCalls()

    def test_buton_belirsiz_kaydi_uzlastirir(self):
        payment = self.unknown()
        with self.patch_find_link(found=True, token='TOK-BTN', status='ACTIVE'):
            result = payment.with_user(self.user_sp).action_check_status()
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertTrue(self.commit_count, 'sonuç commit edilmeli')

    def test_buton_zaman_asiminda_raise_etmez(self):
        payment = self.sent()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        result = payment.with_user(self.user_sp).action_check_status()
        self.assertEqual(result['params']['type'], 'warning')

    def test_gunluk_cron_iade_senkron_zamani_gunde_bir_kez(self):
        payment = self.make_paid()
        self.run_cron(CRON_DAILY)
        payment.invalidate_recordset()
        self.assertTrue(payment.last_refund_sync_at)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.run_cron(CRON_DAILY)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

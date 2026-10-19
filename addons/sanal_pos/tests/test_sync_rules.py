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
class TestWebhookAmplification(RulesCase):
    """G-1: webhook kaynaklı sorgu çoğaltması (tetik tekilleştirme, 9 dk kuralı, hız sınırı)."""

    def now(self):
        return datetime.utcnow().replace(microsecond=0)

    def last_trigger_at(self):
        cron = self.env.ref(CRON_SYNC).sudo()
        trig = self.env['ir.cron.trigger'].sudo().search([('cron_id', '=', cron.id)],
                                                          order='id desc', limit=1)
        return trig.call_at

    def test_g1_ayni_odemeye_bes_bildirim_tek_tetik(self):
        payment = self.sent()
        before = self.cron_trigger_count()
        for _i in range(5):
            self.env['sanal.pos.payment']._mark_sync_requested(payment.merchant_payment_id)
        self.assertEqual(self.cron_trigger_count(), before + 1, 'tetik yalnız bayrak False->True geçişinde')
        payment.invalidate_recordset()
        self.assertTrue(payment.sync_requested)
        self.assertNoParatikaCalls()

    def test_g1_kilitliyse_bayrak_ve_tetik_yok(self):
        payment = self.sent()
        before = self.cron_trigger_count()
        with patch.object(type(self.env['sanal.pos.payment']), '_try_lock_nowait', return_value=False):
            self.env['sanal.pos.payment']._mark_sync_requested(payment.merchant_payment_id)
        self.assertEqual(self.cron_trigger_count(), before)

    def test_g1_yeni_sorgulanmis_odemenin_tetigi_hiz_siniri_kadar_ertelenir(self):
        checked = self.now() - timedelta(seconds=20)
        payment = self.sent(last_checked_at=checked)
        self.env['sanal.pos.payment']._mark_sync_requested(payment.merchant_payment_id)
        self.assertGreaterEqual(self.last_trigger_at(), checked + timedelta(minutes=1))

    def test_g1_tetiklenen_turda_yeni_sorgulanmis_bayraksiz_sent_atlanir(self):
        target = self.sent(invoice_no='UGRG1-0', last_checked_at=self.now() - timedelta(minutes=30))
        for i in range(1, 4):
            self.sent(invoice_no='UGRG1-%d' % i, last_checked_at=self.now() - timedelta(minutes=3))
        old = self.sent(invoice_no='UGRG1-9', last_checked_at=self.now() - timedelta(minutes=20))
        never = self.sent(invoice_no='UGRG1-8', last_checked_at=False)
        self.env['sanal.pos.payment']._mark_sync_requested(target.merchant_payment_id)
        self.run_cron(CRON_SYNC)
        queried = {c.params['MERCHANTPAYMENTID'] for c in self.mock.calls_for('QUERYTRANSACTION')}
        self.assertEqual(queried, {target.merchant_payment_id, old.merchant_payment_id,
                                   never.merchant_payment_id})

    def test_g1_bayrakli_odeme_hiz_siniri_icinde_sorgulanmaz_bayrak_korunur(self):
        payment = self.sent(sync_requested=True, last_checked_at=self.now() - timedelta(seconds=10))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)
        payment.invalidate_recordset()
        self.assertTrue(payment.sync_requested, 'bayrak sonraki tura korunmalı')
        payment.write({'last_checked_at': self.now() - timedelta(minutes=2)})
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        payment.invalidate_recordset()
        self.assertFalse(payment.sync_requested)

@tagged('post_install', '-at_install', 'sanal_pos')
class TestLinkNotFoundLateCheck(RulesCase):
    """Ö-C: 'Hata / link bulunamadı' kaydı link süresi + 1 gün boyunca seyrek sorgulanır ve aynı
    faturaya yeni link açılmadan önce mutlaka sorgulanır (geç ödeme çift tahsilata dönmesin)."""

    PAID = 'Bu fatura için ödeme alınmış/incelemede; yeni link oluşturulamaz.'

    def not_found(self, checked_ago=timedelta(hours=2), created_ago=timedelta(hours=1), **vals):
        now = datetime.utcnow().replace(microsecond=0)
        vals.setdefault('last_checked_at', now - checked_ago if checked_ago is not None else False)
        vals.setdefault('last_error_code', 'LINK_NOT_FOUND')
        payment = self.make_payment(
            state='error', provider_token=False, sent_at=False, expires_at=False,
            link_not_found_count=2, unknown_since=now - created_ago, **vals)
        self.set_create_date(payment, now - created_ago)
        return payment

    def test_oc_cron_hata_kaydini_sorgular_ve_seyreltir(self):
        payment = self.not_found()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1, 'saatte bir kez yeter')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'error')

    def test_oc_cron_gec_odemeyi_incelemeye_alir(self):
        payment = self.not_found()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-OC-LATE'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')
        self.assertIn(self.user_sp.partner_id, self.notified_partners(payment))

    def test_oc_link_suresi_ve_pencere_bitince_sorgulanmaz(self):
        self.not_found(created_ago=timedelta(hours=168 + 25))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_oc_kapatilmis_inceleme_yeniden_sorgulanmaz(self):
        self.not_found(last_error_code='REVIEW_CLOSED', paid_at=datetime.utcnow().replace(microsecond=0),
                       provider_tran_ref='PG-OLD')
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_oc_yeni_link_oncesi_sorgulanir_gec_odeme_varsa_engellenir(self):
        payment = self.not_found(checked_ago=timedelta(minutes=1))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-OC-NEW'))
        self.set_invoice(invoice_rows())
        commits = self.commit_count
        # assertRaises savepoint'i geri alır; üretimde sonuç _sp_commit ile kalıcıdır
        try:
            self.wizard(**BOTH).action_create_link()
        except UserError as exc:
            message = str(exc)
        else:
            self.fail('geç ödemeli faturaya yeni link açıldı')
        self.assertIn(self.PAID, message)
        self.assertGreater(self.commit_count, commits, 'inceleme durumu commit edilmeli')
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'review')

    def test_oc_yeni_link_oncesi_sorgu_yanitsizsa_engellenir(self):
        self.not_found(checked_ago=timedelta(minutes=1))
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.set_invoice(invoice_rows())
        with self.assertRaises(UserError) as cm:
            self.wizard(**BOTH).action_create_link()
        self.assertIn('doğrulanamadı', str(cm.exception))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)

    def test_oc_yeni_link_oncesi_odeme_yoksa_link_acilir(self):
        self.not_found(checked_ago=timedelta(minutes=1))
        self.set_invoice(invoice_rows())
        self.wizard(**BOTH).action_create_link()
        self.assertEqual(self.mock.actions[:2], ['QUERYTRANSACTION', 'PAYBYLINKPAYMENT'])
        self.assertEqual(self.last_payment().state, 'sent')

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

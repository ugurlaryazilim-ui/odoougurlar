"""KK-A15, A16, A17, A22, A26, A27: tekli gönderim, yeniden deneme, kuyruk ve kilit."""
import inspect
from unittest.mock import patch

import requests
from odoo.tests.common import tagged

from .common import FakeResponse, SmsTestCase

MAX_RETRY = 3


class DeliveryMixin:

    def send_queued(self, numbers='05321234567', body='Merhaba', **kw):
        try:
            return self.Message.send_sms(numbers, body, queue=True, **kw)
        except TypeError as e:
            self.fail('ARAYÜZ YOK: send_sms(queue=True): %s' % e)

    def cron_send_queued(self):
        method = getattr(self.Message, '_cron_send_queued', None)
        if method is None:
            self.fail('ARAYÜZ YOK: sms.system.message._cron_send_queued')
        return method()

    def patch_lock(self, fn):
        klass = type(self.Message)
        if not hasattr(klass, '_lock_for_send'):
            self.fail('ARAYÜZ YOK: sms.system.message._lock_for_send(ids, states)')
        return patch.object(klass, '_lock_for_send', fn)


@tagged('post_install', '-at_install')
class TestRetryClassification(DeliveryMixin, SmsTestCase):

    # ── KK-A15 ──
    def test_kk_a15_connect_timeout_error_ve_retry_count_1(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'error')
        self.assertEqual(msg.retry_count, 1)
        self.assertEqual(len(self.net.turatel_calls), 1)

    def test_kk_a15_cron_en_cok_3_denemeye_kadar_dener(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()] * 10
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        for expected_retry in (2, 3):
            self.Message._cron_retry_failed()
            msg.invalidate_recordset()
            self.assertEqual(msg.retry_count, expected_retry)
            self.assertEqual(msg.state, 'error')
        calls_after_three = len(self.net.turatel_calls)
        self.assertEqual(calls_after_three, 3)
        for _i in range(3):
            self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.turatel_calls), 3, '3. denemeden sonra yeni çağrı yapıldı')
        msg.invalidate_recordset()
        self.assertEqual((msg.state, msg.retry_count), ('error', 3))

    def test_kk_a15_gecici_hata_sonra_basari(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout(), 'ID:555']
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'error')
        self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual((msg.state, msg.provider_msg_id), ('sent', '555'))
        self.assertEqual(len(self.net.turatel_calls), 2)

    def test_kk_a15_kalici_hata_otomatik_denenmez(self):
        self.net.turatel_script = ['40']   # başlık hesapta yok
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual((msg.state, msg.retry_count), ('error', MAX_RETRY))
        self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.turatel_calls), 1)

    # ── KK-A16 ──
    def _assert_uncertain_never_resent(self, outcome):
        self.net.turatel_script = [outcome]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'uncertain', 'gidip gitmediği belli olmayan kayıt belirsiz olmalı')
        self.assertEqual(msg.retry_count, MAX_RETRY)
        for _i in range(3):
            self.Message._cron_retry_failed()
        msg.action_retry()
        msg.sudo().action_retry()
        method = getattr(self.Message, '_cron_send_queued', None)
        if method:
            method()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'uncertain')
        self.assertEqual(len(self.net.turatel_calls), 1, 'Belirsiz kayıt için yeni sağlayıcı çağrısı yapıldı')

    def test_kk_a16_read_timeout_belirsiz_ve_tekrar_gonderilmez(self):
        self._assert_uncertain_never_resent(requests.exceptions.ReadTimeout())

    def test_kk_a16_http_503_belirsiz_ve_tekrar_gonderilmez(self):
        self._assert_uncertain_never_resent(FakeResponse(503, 'Service Unavailable'))

    def test_kk_a16_http_500_belirsiz_ve_tekrar_gonderilmez(self):
        self._assert_uncertain_never_resent(FakeResponse(500, 'oops'))

    def test_kk_a16_belirsiz_kayit_hata_filtresine_girmez(self):
        self.net.turatel_script = [requests.exceptions.ReadTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertNotEqual(msg.state, 'error')
        self.assertEqual(msg.state, 'uncertain')
        self.assertTrue(msg.error, 'Belirsiz kayıtta açıklayıcı hata metni olmalı')

    # ── KK-A17 (K4) ──
    def test_kk_a17_kilitli_kayit_cron_ve_butonda_atlanir(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(len(self.net.turatel_calls), 1)
        with self.patch_lock(lambda this, ids, states: this.browse()):
            self.Message._cron_retry_failed()
            msg.action_retry()
            method = getattr(self.Message, '_cron_send_queued', None)
            if method:
                method()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'error', 'Kilitli kayıt işlenmemeli')
        self.assertEqual(len(self.net.turatel_calls), 1, 'Kilitli kayıt için sağlayıcı çağrısı yapıldı')

    def test_kk_a17_kilit_acilinca_toplam_cagri_1_artar(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout(), 'ID:777']
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        with self.patch_lock(lambda this, ids, states: this.browse()):
            msg.action_retry()
        self.assertEqual(len(self.net.turatel_calls), 1)
        msg.action_retry()            # kilitsiz: yalnız kuyruğa alır
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'queued', 'action_retry senkron göndermemeli, kuyruğa almalı')
        self.assertEqual(msg.retry_count, 1, 'action_retry retry_count değiştirmemeli')
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.cron_send_queued()
        msg.invalidate_recordset()
        self.assertEqual((msg.state, msg.provider_msg_id), ('sent', '777'))
        self.assertEqual(len(self.net.turatel_calls), 2)

    def test_kk_a17_lock_for_send_kaynakta_skip_locked(self):
        method = getattr(type(self.Message), '_lock_for_send', None)
        if method is None:
            self.fail('ARAYÜZ YOK: sms.system.message._lock_for_send(ids, states)')
        source = inspect.getsource(method)
        self.assertIn('FOR UPDATE SKIP LOCKED', source.upper())

    def test_kk_a17_lock_for_send_durum_kosulunu_kilit_altinda_dogrular(self):
        sent = self.make_message(state='sent')
        error = self.make_message(state='error', number='5329999999')
        locked = self.Message._lock_for_send((sent | error).ids, ('error',)) if hasattr(
            self.Message, '_lock_for_send') else self.fail('ARAYÜZ YOK: _lock_for_send')
        self.assertEqual(sorted(locked.ids if hasattr(locked, 'ids') else locked), [error.id])

    def test_kk_a17_action_retry_yalniz_error_i_kuyruga_alir(self):
        self.require_state('uncertain')
        error = self.make_message(state='error', retry_count=1)
        uncertain = self.make_message(state='uncertain', retry_count=MAX_RETRY, number='5329999999')
        sending = self.make_message(state='sending', number='5328888888')
        sent = self.make_message(state='sent', number='5327777777')
        (error | uncertain | sending | sent).action_retry()
        for rec in (error, uncertain, sending, sent):
            rec.invalidate_recordset()
        self.assertEqual(error.state, 'queued')
        self.assertEqual(uncertain.state, 'uncertain')
        self.assertEqual(sending.state, 'sending')
        self.assertEqual(sent.state, 'sent')
        self.assertEqual(self.net.calls, [])

    # ── KK-A17: sağlayıcı çağrısından ÖNCE 'sending' commit edilir (mükerrer penceresi) ──
    def test_kk_a17_sending_saglayici_cagrisindan_once_commit_edilir(self):
        msg = self.send_queued()
        self.assertEqual(msg.state, 'queued')
        seen = []

        def hook(call):
            seen.append({'db_state': self.db_state(msg, flush=False),
                         'commit_before': any(ev[0] == 'commit' for ev in self.events[:-1])})

        self.net.turatel_hook = hook
        self.cron_send_queued()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['db_state'], 'sending', 'Çağrı anında kayıt sending olmalı')
        self.assertTrue(seen[0]['commit_before'], "'sending' yazıldıktan sonra commit, çağrıdan önce olmalı")
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent')

    def test_kk_a17_retry_cron_da_sending_yazip_commit_eder(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        seen = []

        def hook(call):
            seen.append({'db_state': self.db_state(msg, flush=False),
                         'commit_before': any(ev[0] == 'commit' for ev in self.events[:-1])})

        self.net.turatel_hook = hook
        self.events.clear()
        self.Message._cron_retry_failed()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['db_state'], 'sending')
        self.assertTrue(seen[0]['commit_before'])


@tagged('post_install', '-at_install')
class TestQueue(DeliveryMixin, SmsTestCase):

    def test_kk_a17_queue_true_saglayiciya_gitmeden_queued_kaydi_olusturur(self):
        msg = self.send_queued()
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(self.net.calls, [])

    def test_kk_a17_queue_true_test_modunda_dogrudan_test(self):
        self.set_param('test_mode', 'True')
        msg = self.send_queued()
        self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    def test_kk_a22_queue_true_baslik_yoksa_error_ve_max_retry(self):
        self.set_param('turatel_originator', '')
        msg = self.send_queued()
        self.assertEqual((msg.state, msg.retry_count), ('error', MAX_RETRY))
        self.assertEqual(self.net.calls, [])

    def test_kk_a17_kuyruk_cron_queued_kaydi_gonderir(self):
        msg = self.send_queued()
        self.cron_send_queued()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.cron_send_queued()
        self.assertEqual(len(self.net.turatel_calls), 1, 'Gönderilmiş kayıt tekrar gönderildi')

    def test_kk_a17_retry_cron_once_kuyrugu_bosaltir(self):
        msg = self.send_queued()
        self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent')

    def test_kk_a17_kuyruk_cron_kampanya_kaydina_dokunmaz(self):
        campaign = self.env['sms.system.campaign'].create({'name': 'K', 'body': 'x'})
        rec = self.make_message(state='queued', campaign_id=campaign.id)
        self.cron_send_queued()
        rec.invalidate_recordset()
        self.assertEqual(rec.state, 'queued')
        self.assertEqual(self.net.calls, [])

    def test_kk_a16_kuyruk_cron_belirsiz_kaydi_gondermez(self):
        self.require_state('uncertain')
        rec = self.make_message(state='uncertain', retry_count=MAX_RETRY)
        self.cron_send_queued()
        self.Message._cron_retry_failed()
        rec.invalidate_recordset()
        self.assertEqual(rec.state, 'uncertain')
        self.assertEqual(self.net.calls, [])

    def test_kk_a16_15_dk_sending_tekli_kayit_belirsiz_olur(self):
        self.require_state('uncertain')
        old = self.make_message(state='sending', number='5321234567')
        recent = self.make_message(state='sending', number='5329999999')
        self.set_write_date(old, 16)
        self.set_write_date(recent, 14)
        self.cron_send_queued()
        old.invalidate_recordset()
        recent.invalidate_recordset()
        self.assertEqual(old.state, 'uncertain')
        self.assertEqual(old.retry_count, MAX_RETRY)
        self.assertEqual(recent.state, 'sending')
        self.assertEqual(self.net.calls, [], 'Takılı kayıt yeniden gönderilmemeli')

    def test_kk_a16_takili_sending_retry_cron_ile_de_gonderilmez(self):
        self.require_state('uncertain')
        old = self.make_message(state='sending')
        self.set_write_date(old, 30)
        for _i in range(3):
            self.Message._cron_retry_failed()
        old.invalidate_recordset()
        self.assertEqual(old.state, 'uncertain')
        self.assertEqual(self.net.calls, [])


@tagged('post_install', '-at_install')
class TestMissingOriginator(DeliveryMixin, SmsTestCase):

    # ── KK-A22 ──
    def test_kk_a22_baslik_bos_error_ve_max_retry(self):
        self.set_param('turatel_originator', '')
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'error')
        self.assertEqual(msg.retry_count, MAX_RETRY)
        self.assertEqual(self.net.calls, [])

    def test_kk_a22_baslik_sonradan_girilse_de_cron_gondermez(self):
        self.set_param('turatel_originator', '')
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.set_param('turatel_originator', 'TESTBASLIK')
        for _i in range(2):
            self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'error')
        self.assertEqual(self.net.calls, [], 'Başlıksız kayıt sonradan otomatik gönderildi')

    def test_kk_a22_baslik_parametresi_hic_yoksa(self):
        self.set_param('turatel_originator', None)
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual((msg.state, msg.retry_count), ('error', MAX_RETRY))


@tagged('post_install', '-at_install')
class TestSingleSmsInvariants(DeliveryMixin, SmsTestCase):

    # ── KK-A26 (K1): tekli yollarda SmartADM 0 ──
    def test_kk_a26_tekli_gonderimde_smartadm_cagrisi_yok(self):
        self.configure_sms(iys=True)
        self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(self.net.smartadm_calls, [])
        self.assertEqual(len(self.net.turatel_calls), 1)

    def test_kk_a26_retry_ve_kuyruk_yollarinda_smartadm_yok(self):
        self.configure_sms(iys=True)
        self.net.turatel_script = [requests.exceptions.ConnectTimeout(), 'ID:1']
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent')
        queued = self.send_queued('05329999999')
        self.cron_send_queued()
        queued.invalidate_recordset()
        self.assertEqual(queued.state, 'sent')
        self.assertEqual(self.net.smartadm_calls, [])

    def test_kk_a26_rehberde_ret_olan_numaraya_tekli_sms_gider(self):
        self.configure_sms(iys=True)
        self.env['sms.system.contact'].create({'mobile': '5321234567', 'iys_status': 'rejected'})
        msg = self.Message.send_sms('05321234567', 'Siparişiniz hazır')
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(self.net.sent_numbers, ['5321234567'])
        self.assertEqual(self.net.smartadm_calls, [])

    def test_kk_a26_kara_listedeki_numaraya_da_bilgilendirme_tekli_gider(self):
        self.env['sms.system.contact'].create({'mobile': '5321234567', 'opt_out': True})
        msg = self.Message.send_sms('05321234567', 'Siparişiniz hazır')
        self.assertEqual(msg.state, 'sent')

    # ── KK-A27 (K2): test modu ──
    def test_kk_a27_test_modunda_tekli_kayit_test_ve_cagri_yok(self):
        for value in (None, '', 'True', '0', 'false'):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                msg = self.Message.send_sms('05321234567', 'Merhaba')
                self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    def test_kk_a27_test_modunda_yeniden_deneme_cron_cagri_yapmaz(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'error')
        calls = len(self.net.calls)
        for value in ('True', None, '0', 'false', ''):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                self.Message._cron_retry_failed()
                msg.action_retry()
                method = getattr(self.Message, '_cron_send_queued', None)
                if method:
                    method()
                self.assertEqual(len(self.net.calls), calls, 'Test modunda sağlayıcıya gidildi')

    def test_kk_a27_test_modunda_yeniden_deneme_kaydi_test_olur(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.set_param('test_mode', '0')
        self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'test')

    def test_kk_a27_test_modunda_kuyruk_cron_cagri_yapmaz(self):
        msg = self.send_queued()
        self.set_param('test_mode', 'true')   # tam 'False' değil: açık sayılır
        self.cron_send_queued()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    def test_kk_a27_test_modu_kapali_ise_gercekten_gonderir(self):
        self.set_param('test_mode', 'False')
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(len(self.net.turatel_calls), 1)

"""A5 ek testleri: kuyruk tetiği, cron kaydı, kayıt başına 'sending', süre sınırı, SerializationFailure."""
from unittest.mock import patch

from psycopg2 import errors as pg_errors

from odoo.tests.common import tagged

from .common import SmsTestCase

CRON_XMLID = 'sms_system.cron_sms_send_queued'


@tagged('post_install', '-at_install')
class TestQueueTrigger(SmsTestCase):

    def _trigger_count(self):
        cron = self.env.ref(CRON_XMLID)
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', cron.id)])

    def test_cron_kaydi_5_dakikada_bir_ve_aktif(self):
        cron = self.env.ref(CRON_XMLID)
        self.assertEqual((cron.interval_number, cron.interval_type), (5, 'minutes'))
        self.assertTrue(cron.active)
        self.assertEqual(cron.code.strip(), 'model._cron_send_queued()')
        self.assertEqual(cron.model_id.model, 'sms.system.message')

    def test_queue_true_kuyruk_cronunu_hemen_tetikler(self):
        before = self._trigger_count()
        msg = self.Message.send_sms('05321234567', 'Merhaba', queue=True)
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(self._trigger_count(), before + 1, 'Terzi/vendor SMS 5 dk beklememeli: tetik yok')
        self.assertEqual(self.net.calls, [])

    def test_queue_true_normal_kullanici_da_tetikler(self):
        before = self._trigger_count()
        msg = self.Message.with_user(self.plain_user).send_sms('05321234567', 'Merhaba', queue=True)
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(self._trigger_count(), before + 1)

    def test_queue_true_test_modunda_tetik_yok(self):
        self.set_param('test_mode', 'True')
        before = self._trigger_count()
        msg = self.Message.send_sms('05321234567', 'Merhaba', queue=True)
        self.assertEqual(msg.state, 'test')
        self.assertEqual(self._trigger_count(), before)

    def test_queue_true_baslik_yoksa_tetik_yok(self):
        self.set_param('turatel_originator', '')
        before = self._trigger_count()
        msg = self.Message.send_sms('05321234567', 'Merhaba', queue=True)
        self.assertEqual(msg.state, 'error')
        self.assertEqual(self._trigger_count(), before)

    def test_cron_kaydi_yoksa_tetik_atlanir_retry_cron_gonderir(self):
        self.env.ref(CRON_XMLID).sudo().unlink()   # redeploy ile -u arası
        msg = self.Message.send_sms('05321234567', 'Merhaba', queue=True)
        self.assertEqual(msg.state, 'queued')
        self.Message._cron_retry_failed()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(len(self.net.turatel_calls), 1)

    def test_action_retry_tetikler_ve_bildirim_doner(self):
        msg = self.make_message(state='error', retry_count=1)
        before = self._trigger_count()
        action = msg.action_retry()
        self.assertEqual(self._trigger_count(), before + 1)
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('kuyruğa alındı', action['params']['message'])
        self.assertEqual(self.net.calls, [])

    def test_action_retry_kuyruga_alinacak_yoksa_uyari_ve_tetik_yok(self):
        msg = self.make_message(state='uncertain', retry_count=3)
        before = self._trigger_count()
        action = msg.action_retry()
        self.assertEqual(self._trigger_count(), before)
        self.assertEqual(action['params']['type'], 'warning')
        self.assertIn('atlandı', action['params']['message'])


@tagged('post_install', '-at_install')
class TestQueueOrdering(SmsTestCase):

    def test_sending_kayit_basina_yazilir(self):
        """Sağlayıcı ilk kaydı gönderirken ikinci kayıt hâlâ 'queued' olmalı (toplu 'sending' yok)."""
        first = self.Message.send_sms('05321111111', 'Bir', queue=True)
        second = self.Message.send_sms('05322222222', 'İki', queue=True)
        seen = []

        def hook(call):
            seen.append((call['numbers'], self.db_state(first, flush=False), self.db_state(second, flush=False)))

        self.net.turatel_hook = hook
        self.Message._cron_send_queued()
        self.assertEqual(seen, [(['5321111111'], 'sending', 'queued'), (['5322222222'], 'sent', 'sending')])

    def test_sure_bitince_kalanlar_queued_kalir(self):
        records = self.Message.send_sms(['05321111111', '05322222222', '05323333333'], 'Merhaba', queue=True)
        events = self.events

        def short_progress(cron, processed=0, *, remaining=None, deactivate=False):
            cron.env.flush_all()
            events.append(('commit', processed, remaining))
            return 5.0 if processed else 1000.0   # ilk kayıttan sonra süre bitti

        with patch.object(self.env.registry['ir.cron'], '_commit_progress', short_progress):
            self.Message._cron_send_queued()
        records.invalidate_recordset()
        self.assertEqual(records.mapped('state'), ['sent', 'queued', 'queued'])
        self.assertEqual(len(self.net.turatel_calls), 1)

    def test_tek_calismada_50_den_fazla_kayit_gonderilir(self):
        numbers = ['0532%07d' % i for i in range(1, 53)]
        records = self.Message.send_sms(numbers, 'Merhaba', queue=True)
        self.Message._cron_send_queued()
        records.invalidate_recordset()
        self.assertEqual(set(records.mapped('state')), {'sent'})
        self.assertEqual(len(self.net.turatel_calls), 52)

    def test_kilit_altinda_serialization_failure_kaydi_atlar(self):
        """REPEATABLE READ: kayıt başka işlemde değiştiyse kilit sorgusu hata verir; kayıt atlanır."""
        msg = self.make_message(state='error', retry_count=1)
        cr = self.env.cr
        real_execute = cr.execute

        def execute(query, params=None, log_exceptions=True):
            if 'SKIP LOCKED' in str(query):
                raise pg_errors.SerializationFailure('could not serialize access due to concurrent update')
            return real_execute(query, params, log_exceptions)

        with patch.object(cr, 'execute', execute):
            locked = self.Message._lock_for_send(msg.ids, ('error',))
            msg.action_retry()
        self.assertFalse(locked)
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'error')
        # işlem kullanılabilir kalmalı (savepoint geri alındı)
        self.assertEqual(self.db_state(msg), 'error')
        self.assertEqual(self.net.calls, [])

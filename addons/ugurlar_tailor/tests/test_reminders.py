"""Terzi 'hazır' hatırlatma cron'u: SMS kuyruğa alınır (istek/cron sağlayıcıyı beklemez), kayıt başına commit."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import tagged

from odoo.addons.sms_system.tests.common import SmsTestCase

from ..models import tailor_order as tailor_order_module


@tagged('post_install', '-at_install')
class TestTailorReminders(SmsTestCase):

    def setUp(self):
        super().setUp()
        self.Order = self.env['ugurlar.tailor.order'].sudo()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('ugurlar_tailor.sms_reminder_enabled', 'True')
        icp.set_param('ugurlar_tailor.sms_reminder_days', '3')
        icp.set_param('ugurlar_tailor.sms_reminder_max', '2')

    def make_order(self, mobile='05321234567', days_ago=5):
        return self.Order.create({
            'product_barcode': '8690000000001', 'customer_name': 'Ayşe Yılmaz', 'customer_mobile': mobile,
            'state': 'completed', 'completed_at': fields.Datetime.now() - timedelta(days=days_ago)})

    def order_sms(self, order):
        return self.env['sms.system.message'].sudo().search(
            [('res_model', '=', order._name), ('res_id', '=', order.id)])

    def test_cron_kuyruga_alir_saglayici_cagrilmaz(self):
        order = self.make_order()
        self.Order._cron_ready_reminders()
        self.assertEqual(self.order_sms(order).mapped('state'), ['queued'])
        self.assertEqual(self.net.turatel_calls, [], 'Hatırlatma cron\'u sağlayıcıyı doğrudan çağırmamalı')
        self.assertEqual(self.net.json_calls, [])
        order.invalidate_recordset()
        self.assertEqual(order.reminder_count, 1)
        self.assertTrue(order.last_reminder_at)

    def test_ayni_gun_ikinci_hatirlatma_yok(self):
        order = self.make_order()
        self.Order._cron_ready_reminders()
        self.Order._cron_ready_reminders()
        order.invalidate_recordset()
        self.assertEqual(order.reminder_count, 1)
        self.assertEqual(len(self.order_sms(order)), 1)

    def test_gecersiz_numarada_da_sayac_artar_ve_not_duser(self):
        order = self.make_order(mobile='123')
        self.Order._cron_ready_reminders()
        order.invalidate_recordset()
        self.assertEqual(order.reminder_count, 1, 'Her gün yeniden denenmesin')
        self.assertFalse(self.order_sms(order))
        self.assertTrue(any('Hatırlatma SMS gönderilemedi' in (m.body or '') for m in order.message_ids))

    def test_kayit_basina_commit_kesintide_islenenler_kalici(self):
        orders = [self.make_order('0532123450%d' % i) for i in range(4)]
        ids = tuple(o.id for o in orders)
        snapshots = []
        env = self.env

        def fake_commit(cron, processed=0, *, remaining=None, deactivate=False):
            cron.env.flush_all()
            env.cr.execute('SELECT id, COALESCE(reminder_count, 0) FROM ugurlar_tailor_order WHERE id IN %s', (ids,))
            snapshots.append((processed, sum(count for _id, count in env.cr.fetchall())))
            if len(snapshots) == 3:
                raise RuntimeError('kesinti')
            return 1000.0

        with patch.object(self.env.registry['ir.cron'], '_commit_progress', fake_commit):
            with self.assertRaisesRegex(RuntimeError, 'kesinti'):
                self.Order._cron_ready_reminders()
        self.assertEqual(snapshots, [(1, 1), (1, 2), (1, 3)], 'Her siparişten sonra sayaçla birlikte commit')

    def test_sure_azsa_durur_kalan_sonraki_calismada(self):
        orders = [self.make_order('0532123460%d' % i) for i in range(3)]
        low = tailor_order_module.MIN_TIME_LEFT - 1
        with patch.object(self.env.registry['ir.cron'], '_commit_progress', lambda *a, **k: low):
            self.Order._cron_ready_reminders()
        self.assertEqual(sum(len(self.order_sms(o)) for o in orders), 1, 'Süre azsa ilk siparişten sonra durur')
        self.Order._cron_ready_reminders()
        self.assertEqual([len(self.order_sms(o)) for o in orders], [1, 1, 1])

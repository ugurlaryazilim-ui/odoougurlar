# -*- coding: utf-8 -*-
"""K3: ürün kuyruğu cron'u 10 dakikada bir; kuyruğa iş eklenince _trigger ile hemen işlenir."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestQueueCronInterval(TransactionCase):

    def setUp(self):
        super().setUp()
        self.cron = self.env.ref('odoougurlar.cron_process_product_queue')

    def _triggers(self):
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', self.cron.id)])

    def test_xml_default_is_ten_minutes_and_active(self):
        # NEDEN: kayıt cron_data.xml'de noupdate="0" bloğunda; her -u XML'deki değeri yazar, bu yüzden
        # prod kaydı için ayrıca migration gerekmez. Test, XML varsayılanının 10 dk olduğunu sabitler.
        self.assertEqual((self.cron.interval_number, self.cron.interval_type), (10, 'minutes'))
        self.assertTrue(self.cron.active)

    def test_retry_still_triggers_cron_immediately(self):
        # DIKKAT: aralık 10 dk olsa da kuyruğa iş eklenince işlem beklememeli (ir.cron.trigger kaydı)
        item = self.env['odoougurlar.product.queue'].create({'item_code': 'K3-TEST', 'state': 'error'})
        before = self._triggers()
        item.action_retry()
        self.assertEqual(item.state, 'pending')
        self.assertEqual(self._triggers(), before + 1, 'iş kuyruğa alınınca cron anında tetiklenmeli')

    def test_retry_without_failed_items_does_not_trigger(self):
        item = self.env['odoougurlar.product.queue'].create({'item_code': 'K3-TEST2', 'state': 'done'})
        before = self._triggers()
        item.action_retry()
        self.assertEqual(self._triggers(), before)

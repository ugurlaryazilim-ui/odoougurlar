# -*- coding: utf-8 -*-
"""K6: ai.content.log saklama temizliği (süre ayarı, partileme, kapsam)."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

LOG_MOD = 'odoo.addons.ai_title_description.models.ai_content_log'
ICP_KEY = 'ai_title_description.log_retention_days'


@tagged('post_install', '-at_install', 'ai_title_description')
class TestAiContentLogRetention(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Log = self.env['ai.content.log']
        self.product = self.env['product.template'].create({'name': 'GC Ürün'})
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, '180')

    def _log(self, age_days):
        rec = self.Log.create({'product_tmpl_id': self.product.id})
        self.env.cr.execute(
            "UPDATE ai_content_log SET create_date = %s WHERE id = %s",
            (fields.Datetime.subtract(fields.Datetime.now(), days=age_days), rec.id))
        rec.invalidate_recordset()
        return rec

    def test_boundary_one_day_inside_kept_one_day_outside_deleted(self):
        inside, outside = self._log(179), self._log(181)
        self.Log._cron_gc_old_logs()
        self.assertTrue(inside.exists())
        self.assertFalse(outside.exists())

    def test_retention_param_is_used(self):
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, '10')
        young, old = self._log(9), self._log(11)
        self.Log._cron_gc_old_logs()
        self.assertTrue(young.exists())
        self.assertFalse(old.exists())

    def test_zero_or_invalid_param_deletes_nothing(self):
        old = self._log(1000)
        # '' denenmez: Odoo get_param boş değeri tanımsız sayıp varsayılana düşer
        for bad in ('0', '-5', 'abc', '99999999999'):
            self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, bad)
            self.assertEqual(self.Log._cron_gc_old_logs(), 0, bad)
            self.assertTrue(old.exists(), bad)

    def test_batch_limit_outside_cron_deletes_single_batch(self):
        recs = self.Log
        for _i in range(5):
            recs |= self._log(400)
        with patch(LOG_MOD + '._GC_BATCH', 2):
            self.assertEqual(self.Log._cron_gc_old_logs(), 2)
        self.assertEqual(len(recs.exists()), 3)

    def test_cron_context_loops_batches_and_commits_each(self):
        recs = self.Log
        for _i in range(5):
            recs |= self._log(400)
        cron_model = type(self.env['ir.cron'])
        with patch(LOG_MOD + '._GC_BATCH', 2), \
                patch.object(cron_model, '_commit_progress', return_value=100.0) as commit:
            self.assertEqual(self.Log.with_context(cron_id=1)._cron_gc_old_logs(), 5)
        self.assertFalse(recs.exists())
        self.assertEqual(commit.call_count, 2)  # son (kısa) partiden sonra commit yok

    def test_cron_walks_id_order_skips_young_and_never_rescans(self):
        # A5 diğer Ö-2: genç satırlar araya karışsa da tüm eskiler silinir; partiler kaldığı id'den sürer
        old, young = self.Log, self.Log
        for i in range(6):
            old |= self._log(400)
            if i % 2:
                young |= self._log(5)
        seen = []
        real = self.env.cr.execute

        def spy(query, params=None, *a, **kw):
            seen.append(str(query))
            return real(query, params, *a, **kw)
        cron_model = type(self.env['ir.cron'])
        with patch(LOG_MOD + '._GC_BATCH', 2),                 patch.object(cron_model, '_commit_progress', return_value=100.0),                 patch.object(self.env.cr, 'execute', spy):
            self.Log.with_context(cron_id=1)._cron_gc_old_logs()
        self.assertFalse(old.exists())
        self.assertEqual(young.exists(), young)
        self.assertFalse([q for q in seen if 'IN (SELECT' in q], 'alt sorgulu tam tarama kaldı')
        self.assertTrue([q for q in seen if 'id >' in q and 'ORDER BY id' in q])

    def test_time_budget_stops_the_loop(self):
        recs = self.Log
        for _i in range(5):
            recs |= self._log(400)
        cron_model = type(self.env['ir.cron'])
        with patch(LOG_MOD + '._GC_BATCH', 2), patch(LOG_MOD + '._GC_TIME_BUDGET', -1), \
                patch.object(cron_model, '_commit_progress', return_value=100.0):
            self.assertEqual(self.Log.with_context(cron_id=1)._cron_gc_old_logs(), 2)
        self.assertEqual(len(recs.exists()), 3)

    def test_other_models_untouched(self):
        queue = self.env['ai.content.queue'].create({'product_tmpl_id': self.product.id})
        self.env.cr.execute(
            "UPDATE ai_content_queue SET create_date = %s WHERE id = %s",
            (fields.Datetime.subtract(fields.Datetime.now(), days=1000), queue.id))
        queue.invalidate_recordset()
        self._log(1000)
        self.Log._cron_gc_old_logs()
        self.assertTrue(queue.exists())

    def test_cron_is_active_and_calls_gc(self):
        cron = self.env.ref('ai_title_description.ir_cron_ai_content_log_gc')
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_type, 'days')
        self.assertEqual(cron.model_id.model, 'ai.content.log')
        self.assertIn('_cron_gc_old_logs', cron.code)

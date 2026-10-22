# -*- coding: utf-8 -*-
"""K6: ugurlar.image.sync.log saklama temizliği (süre ayarı, partileme, kapsam)."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

LOG_MOD = 'odoo.addons.ugurlar_images.models.image_sync_log'
ICP_KEY = 'ugurlar_images.log_retention_days'


@tagged('post_install', '-at_install', 'ugurlar_images')
class TestImageSyncLogRetention(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Log = self.env['ugurlar.image.sync.log']
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, '180')

    def _vals(self):
        return {'name': 'GC test'}

    def _age(self, table, rec, age_days):
        self.env.cr.execute(
            "UPDATE " + table + " SET create_date = %s WHERE id = %s",
            (fields.Datetime.subtract(fields.Datetime.now(), days=age_days), rec.id))
        rec.invalidate_recordset()
        return rec

    def _log(self, age_days):
        return self._age('ugurlar_image_sync_log', self.Log.create(self._vals()), age_days)

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
        with patch(LOG_MOD + '._GC_BATCH', 2), \
                patch.object(cron_model, '_commit_progress', return_value=100.0), \
                patch.object(self.env.cr, 'execute', spy):
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

    def test_sync_file_never_deleted(self):
        # DIKKAT: ugurlar.image.sync.file mükerrer işlem engelleme kaydıdır; silinirse tüm dosyalar yeniden işlenir
        f = self.env['ugurlar.image.sync.file'].create({'filename': 'gc_test_1.jpg'})
        self._age('ugurlar_image_sync_file', f, 1000)
        self._log(1000)
        self.Log._cron_gc_old_logs()
        self.assertTrue(f.exists())

    def test_cron_is_active_and_calls_gc(self):
        cron = self.env.ref('ugurlar_images.ir_cron_image_sync_log_gc')
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_type, 'days')
        self.assertEqual(cron.model_id.model, 'ugurlar.image.sync.log')
        self.assertIn('_cron_gc_old_logs', cron.code)

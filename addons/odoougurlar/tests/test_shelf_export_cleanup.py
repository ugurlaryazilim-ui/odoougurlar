# -*- coding: utf-8 -*-
"""K6: raf export eklerinin saklama temizliği; başka ekler asla seçilmemeli."""
import base64
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

CLEAN_MOD = 'odoo.addons.odoougurlar.models.shelf_export_cleanup'
ICP_KEY = 'odoougurlar.shelf_export_retention_days'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@tagged('post_install', '-at_install')
class TestShelfExportCleanup(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Att = self.env['ir.attachment']
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, '30')

    def _att(self, age_days, **kw):
        # Değerler stock.py action_export_shelf_detail'deki create() ile aynı (ad kalıbı, mimetype, bağsız).
        # NEDEN: gerçek export çağrılamıyor; metot Odoo 19'da kaldırılmış `posx` alanını okuyup düşüyor.
        vals = {'name': 'raf_detay_listesi_2020-01-01_10-00.xlsx', 'type': 'binary',
                'datas': base64.b64encode(b'x'), 'mimetype': XLSX}
        vals.update(kw)
        rec = self.Att.create(vals)
        self.env.cr.execute(
            "UPDATE ir_attachment SET create_date = %s WHERE id = %s",
            (fields.Datetime.subtract(fields.Datetime.now(), days=age_days), rec.id))
        rec.invalidate_recordset()
        return rec

    def test_boundary_one_day_inside_kept_one_day_outside_deleted(self):
        inside, outside = self._att(29), self._att(31)
        self.Att._cron_gc_shelf_exports()
        self.assertTrue(inside.exists())
        self.assertFalse(outside.exists())

    def test_other_attachments_never_selected(self):
        partner = self.env['res.partner'].create({'name': 'Ek Sahibi'})
        others = [
            # aynı ad ama bir kayda bağlı (kullanıcı yüklemesi)
            self._att(1000, res_model='res.partner', res_id=partner.id),
            # aynı ad, farklı mimetype
            self._att(1000, mimetype='text/plain'),
            # benzer ad; "_" joker gibi davranmamalı
            self._att(1000, name='rafXdetayXlistesiX2020.xlsx'),
            self._att(1000, name='baska_dosya.xlsx'),
            self._att(1000, name='raf_detay_listesi_2020.pdf'),
            # URL tipi (varlık/asset) ek
            self._att(1000, type='url', url='/web/assets/x.css', datas=False, mimetype='text/css'),
            # alan eki
            self._att(1000, res_model='res.partner', res_id=partner.id, res_field='image_1920'),
        ]
        self.Att._cron_gc_shelf_exports()
        for rec in others:
            self.assertTrue(rec.exists(), rec.name)

    def test_zero_or_invalid_param_deletes_nothing(self):
        old = self._att(1000)
        # '' denenmez: Odoo get_param boş değeri tanımsız sayıp varsayılana düşer
        for bad in ('0', '-5', 'abc', '99999999999'):
            self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, bad)
            self.assertEqual(self.Att._cron_gc_shelf_exports(), 0, bad)
            self.assertTrue(old.exists(), bad)

    def test_retention_param_is_used(self):
        self.env['ir.config_parameter'].sudo().set_param(ICP_KEY, '5')
        young, old = self._att(4), self._att(6)
        self.Att._cron_gc_shelf_exports()
        self.assertTrue(young.exists())
        self.assertFalse(old.exists())

    def test_batch_limit_and_cron_loop(self):
        recs = self.Att
        for _i in range(5):
            recs |= self._att(100)
        with patch(CLEAN_MOD + '._GC_BATCH', 2):
            self.assertEqual(self.Att._cron_gc_shelf_exports(), 2)  # cron dışı: tek parti
            self.assertEqual(len(recs.exists()), 3)
            cron_model = type(self.env['ir.cron'])
            with patch.object(cron_model, '_commit_progress', return_value=100.0) as commit:
                self.assertEqual(self.Att.with_context(cron_id=1)._cron_gc_shelf_exports(), 3)
            self.assertEqual(commit.call_count, 1)  # son (kısa) partiden sonra commit yok
        self.assertFalse(recs.exists())

    def test_time_budget_stops_the_loop(self):
        recs = self.Att
        for _i in range(5):
            recs |= self._att(100)
        cron_model = type(self.env['ir.cron'])
        with patch(CLEAN_MOD + '._GC_BATCH', 2), patch(CLEAN_MOD + '._GC_TIME_BUDGET', -1), \
                patch.object(cron_model, '_commit_progress', return_value=100.0):
            self.assertEqual(self.Att.with_context(cron_id=1)._cron_gc_shelf_exports(), 2)
        self.assertEqual(len(recs.exists()), 3)

    def test_cron_is_active_and_calls_gc(self):
        cron = self.env.ref('odoougurlar.cron_shelf_export_gc')
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_type, 'days')
        self.assertEqual(cron.model_id.model, 'ir.attachment')
        self.assertIn('_cron_gc_shelf_exports', cron.code)

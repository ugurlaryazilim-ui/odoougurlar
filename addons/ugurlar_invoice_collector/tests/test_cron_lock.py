# -*- coding: utf-8 -*-
import itertools
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

WIZ = 'odoo.addons.ugurlar_invoice_collector.wizard.invoice_collector_wizard'


@tagged('post_install', '-at_install', 'ugurlar_invoice_collector')
class TestInvoiceCollectorCronLock(TransactionCase):
    """J6 / TODO-31: arka plan cron'u ile JS otomatik tıklama aynı işi çift indirmesin."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['ugurlar.invoice.collector']
        self.job = self.Job.create({'state': 'downloading', 'batch_size': 1, 'line_ids': [
            (0, 0, {'document_number': 'A1'}), (0, 0, {'document_number': 'A2'})]})
        # TransactionCase'te commit yapılamaz
        self.startPatcher(patch.object(self.env.registry['ir.cron'], '_commit_progress',
                                       lambda cron, *a, **k: 1000.0))
        self.processed = []

        def fake_batch(job, lines):
            self.processed.extend(lines.ids)
            lines.write({'download_status': 'success', 'pdf_file': False})

        self.startPatcher(patch.object(self.Job.__class__, '_process_batch_lines', fake_batch))

    def test_cron_skips_job_locked_by_interactive_step(self):
        with patch.object(self.Job.__class__, '_try_lock_job', return_value=False):
            self.Job._cron_process_download_jobs()
        self.assertFalse(self.processed)

    def test_interactive_step_yields_to_cron(self):
        with patch.object(self.Job.__class__, '_try_lock_job', return_value=False):
            action = self.job.action_download_zip()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_id'], self.job.id)
        self.assertFalse(self.processed)

    def test_lock_is_reentrant_for_own_transaction(self):
        self.assertTrue(self.job._try_lock_job())
        self.assertTrue(self.job._try_lock_job())

    def test_cron_retriggers_itself_when_lines_remain(self):
        cron = self.env.ref('ugurlar_invoice_collector.cron_process_invoice_collector_jobs')
        triggers = self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)])
        ticks = itertools.chain([0, 1], itertools.repeat(100))   # 25 sn dilim bir pakette dolar
        with patch(WIZ + '.time', SimpleNamespace(time=lambda: next(ticks))):
            self.Job._cron_process_download_jobs()
        self.assertEqual(len(self.processed), 1)
        self.assertEqual(self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)]), triggers + 1)

    def test_cron_does_not_retrigger_when_nothing_remains(self):
        cron = self.env.ref('ugurlar_invoice_collector.cron_process_invoice_collector_jobs')
        triggers = self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)])
        with patch.object(self.Job.__class__, '_finalize_zip', return_value=None):
            self.Job._cron_process_download_jobs()
        self.assertEqual(len(self.processed), 2)
        self.assertEqual(self.env['ir.cron.trigger'].search_count([('cron_id', '=', cron.id)]), triggers)

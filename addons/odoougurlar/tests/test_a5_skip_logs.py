# -*- coding: utf-8 -*-
"""A5 Ö-5: takılı kuyruk / uzun süre bırakılmayan stok kilidi günlükte görünür."""
import logging
from types import SimpleNamespace
from unittest.mock import patch

from odoo import sql_db
from odoo.tests import TransactionCase, tagged

from odoo.addons.odoougurlar.services import nebim_service

QUEUE_LOGGER = 'odoo.addons.odoougurlar.models.nebim_product_queue'
SERVICE_LOGGER = 'odoo.addons.odoougurlar.services.nebim_service'


@tagged('post_install', '-at_install')
class TestA5SkipLogs(TransactionCase):

    def test_auto_sync_skip_is_info(self):
        Queue = self.env['odoougurlar.product.queue']
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('odoougurlar.nebim_auto_sync', 'True')
        ICP.set_param('odoougurlar.nebim_sync_mode', 'daily')
        Queue.sudo().create({'item_code': 'A5-SKIP', 'state': 'pending'})
        with patch.object(type(Queue), 'enqueue_products', side_effect=AssertionError('çekmemeli')), \
                self.assertLogs(QUEUE_LOGGER, logging.INFO) as cm:
            Queue.auto_sync_cron()
        self.assertTrue(any('hâlâ işleniyor' in r.getMessage() and r.levelno == logging.INFO for r in cm.records))

    def test_stock_skip_debug_then_warning_after_30_min_and_reset_on_lock(self):
        # başka worker kilidi tutar
        cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        self.addCleanup(cr.close)
        cr.execute('SELECT pg_advisory_lock(%s)', [nebim_service.NEBIM_STOCK_SYNC_LOCK])
        self.addCleanup(cr.execute, 'SELECT pg_advisory_unlock(%s)', [nebim_service.NEBIM_STOCK_SYNC_LOCK])
        self.patch(nebim_service, '_STOCK_SKIP_SINCE', {})
        service = self.env['odoougurlar.nebim.service']
        clock = [1000.0]
        with patch.object(nebim_service, 'time', SimpleNamespace(monotonic=lambda: clock[0])):
            with self.assertNoLogs(SERVICE_LOGGER, logging.WARNING):
                service.sync_stock_prices()       # ilk atlama: DEBUG
            clock[0] += nebim_service.STOCK_SKIP_WARN_SECONDS + 1
            with self.assertLogs(SERVICE_LOGGER, logging.WARNING) as cm:
                service.sync_stock_prices()
            self.assertIn('30 dk', cm.records[0].getMessage())
            # kilit bırakılınca sayaç sıfırlanır
            cr.execute('SELECT pg_advisory_unlock(%s)', [nebim_service.NEBIM_STOCK_SYNC_LOCK])
            with patch.object(type(service), '_sync_stock_prices_locked', return_value=None):
                service.sync_stock_prices()
            self.assertNotIn(self.env.cr.dbname, nebim_service._STOCK_SKIP_SINCE)

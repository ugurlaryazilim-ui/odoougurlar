from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'idefix_integration')
class TestIdefixSyncWrites(TransactionCase):
    """TODO-22: değişmeyen sevkiyat için last_checked yazılmaz; cron penceresi 3 güne iner."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = cls.env['idefix.store'].create({
            'name': 'Idefix W', 'client_id': 'x', 'client_secret': 'y', 'vendor_id': '1',
            'order_day_range': 7, 'auto_sync': True,
        })
        cls.Order = cls.env['idefix.order']

    def _sync(self, order_json):
        # NEDEN: dış çağrı/SO üretimi bu testin konusu değil; yalnız last_checked yazımı ölçülür.
        M = type(self.Order)
        with patch.object(M, '_apply_order_json', return_value=False), \
                patch.object(M, '_reconcile_sale_order'), patch.object(M, '_auto_picking'), \
                patch.object(M, '_upsert_settlement'):
            return self.Order._sync_order_json(self.store, order_json)

    def test_unchanged_order_is_not_written(self):
        self.assertEqual(self._sync({'id': 'W1', 'orderNumber': 'W1'}), 'created')
        rec = self.Order.search([('order_id', '=', 'W1')])
        self.assertTrue(rec.last_checked)
        with patch.object(type(rec), 'write', autospec=True) as w:
            self.assertEqual(self._sync({'id': 'W1', 'orderNumber': 'W1'}), 'unchanged')
        w.assert_not_called()

    def test_stale_last_checked_is_refreshed(self):
        self._sync({'id': 'W2', 'orderNumber': 'W2'})
        rec = self.Order.search([('order_id', '=', 'W2')])
        old = fields.Datetime.now() - timedelta(hours=1)
        rec.last_checked = old
        self._sync({'id': 'W2', 'orderNumber': 'W2'})
        self.assertGreater(rec.last_checked, old)

    def test_cron_window_capped_manual_not(self):
        calls = []

        def fake_fetch(api_client, start_date=None, end_date=None, **kw):
            calls.append((end_date - start_date).days)
            return [], False

        M = type(self.Order)
        with patch.object(M, '_fetch_orders', side_effect=fake_fetch), \
                patch.object(M, '_refresh_stale_orders'), patch.object(M, '_cancel_pending_orders'), \
                patch.object(M, '_send_pending_invoices'), \
                patch.object(type(self.env['idefix.refund']), '_sync_refunds_if_due'), \
                patch.object(type(self.store), 'get_api'):
            self.Order.sync_orders_for_store(self.store, max_days=3)
            self.Order.sync_orders_for_store(self.store)
        self.assertEqual(calls, [3, 7])

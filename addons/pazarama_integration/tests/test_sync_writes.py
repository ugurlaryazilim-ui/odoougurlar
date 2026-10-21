from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pazarama_integration')
class TestPazaramaSyncWrites(TransactionCase):
    """TODO-22: değişmeyen sipariş için last_checked yazılmaz; cron penceresi 3 güne iner."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = cls.env['pazarama.store'].create({
            'name': 'Pazarama W', 'client_id': 'x', 'client_secret': 'y', 'order_day_range': 14,
        })
        cls.Order = cls.env['pazarama.order']

    def _sync(self, order_json):
        # NEDEN: dış çağrı/SO üretimi bu testin konusu değil; yalnız last_checked yazımı ölçülür.
        M = type(self.Order)
        with patch.object(M, '_apply_order_json', return_value=False), \
                patch.object(M, '_reconcile_sale_order'), patch.object(M, '_auto_accept'):
            return self.Order._sync_order_json(self.store, order_json)

    def test_unchanged_order_is_not_written(self):
        self.assertEqual(self._sync({'orderId': 'W1', 'orderNumber': 'W1'}), 'created')
        rec = self.Order.search([('order_id', '=', 'W1')])
        self.assertTrue(rec.last_checked)
        with patch.object(type(rec), 'write', autospec=True) as w:
            self.assertEqual(self._sync({'orderId': 'W1', 'orderNumber': 'W1'}), 'unchanged')
        w.assert_not_called()

    def test_stale_last_checked_is_refreshed(self):
        self._sync({'orderId': 'W2', 'orderNumber': 'W2'})
        rec = self.Order.search([('order_id', '=', 'W2')])
        old = fields.Datetime.now() - timedelta(hours=7)
        rec.last_checked = old
        self._sync({'orderId': 'W2', 'orderNumber': 'W2'})
        self.assertGreater(rec.last_checked, old)

    def test_cron_uses_store_window(self):
        # A4 K1: cron mağaza penceresini (14 gün) kullanır, 3 güne daraltmaz.
        calls = []

        def fake_fetch(api_client, start_date, end_date, *a, **kw):
            calls.append((end_date - start_date).days)
            return [], False

        M = type(self.Order)
        with patch.object(M, '_fetch_orders', side_effect=fake_fetch), \
                patch.object(M, '_refresh_stale_orders'), patch.object(M, '_cancel_pending_orders'), \
                patch.object(type(self.store), 'get_api'):
            self.Order.sync_orders_for_store(self.store)
            self.Order.sync_orders_for_store(self.store, max_days=3)
        self.assertEqual(calls, [14, 3])

    def test_cron_entry_passes_no_max_days(self):
        seen = []
        M = type(self.Order)
        with patch.object(M, 'sync_orders_for_store', side_effect=lambda store, **kw: seen.append(kw)):
            self.Order.sync_orders_from_pazarama()
        self.assertTrue(all(not kw for kw in seen))

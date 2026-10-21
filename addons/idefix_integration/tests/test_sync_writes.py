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

    def test_cron_uses_store_window_and_old_shipment_taken(self):
        # A4 K1/Ö1: cron mağaza penceresini (7 gün) kullanır; 5 günlük yeni sevkiyat cron'da alınır.
        calls, synced = [], []
        old = (fields.Datetime.now() - timedelta(days=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        older = (fields.Datetime.now() - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%SZ')

        def fake_fetch(api_client, start_date=None, end_date=None, **kw):
            calls.append((end_date - start_date).days)
            return [{'id': 'OLD5', 'orderDate': old}, {'id': 'OLD10', 'orderDate': older}], False

        M = type(self.Order)
        with patch.object(M, '_fetch_orders', side_effect=fake_fetch), \
                patch.object(M, '_safe_sync', side_effect=lambda *a, **k: synced.append(a[2]['id'])), \
                patch.object(M, '_refresh_stale_orders'), patch.object(M, '_cancel_pending_orders'), \
                patch.object(M, '_send_pending_invoices'), \
                patch.object(type(self.env['idefix.refund']), '_sync_refunds_if_due'), \
                patch.object(type(self.store), 'get_api'):
            self.Order.sync_orders_for_store(self.store)
        self.assertEqual(calls, [7])
        # pencere içindeki yeni sevkiyat alınır, pencereden eski YENİ sevkiyat açılmaz
        self.assertEqual(synced, ['OLD5'])

    def test_cron_entry_passes_no_max_days(self):
        seen = []
        M = type(self.Order)
        with patch.object(M, 'sync_orders_for_store', side_effect=lambda store, **kw: seen.append(kw)):
            self.Order.sync_orders_from_idefix()
        self.assertTrue(all(not kw for kw in seen))

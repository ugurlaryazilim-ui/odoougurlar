from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'n11_integration')
class TestN11SyncWrites(TransactionCase):
    """TODO-22: değişmeyen sipariş için last_checked yazılmaz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = cls.env['n11.store'].create({'name': 'N11 W', 'n11_app_key': 'x', 'n11_app_secret': 'y'})
        cls.Order = cls.env['n11.order']
        cls.pkg = {'id': 'P1', 'orderNumber': 'NW1'}

    def _sync(self):
        # NEDEN: dış çağrı/SO üretimi bu testin konusu değil; yalnız last_checked yazımı ölçülür.
        M = type(self.Order)
        rec = self.Order.search([('order_number', '=', 'NW1')])
        if not rec:
            rec = self.Order.create({'store_id': self.store.id, 'order_id': 'NW1', 'order_number': 'NW1'})
        with patch.object(M, '_apply_packages', return_value=False), \
                patch.object(M, '_reconcile_sale_order'), patch.object(M, '_auto_accept'):
            return self.Order._sync_order_packages(self.store, None, 'NW1', [self.pkg], refetch=False)

    def test_unchanged_order_is_not_written(self):
        self._sync()  # last_checked ilk kez yazılır
        rec = self.Order.search([('order_number', '=', 'NW1')])
        self.assertTrue(rec.last_checked)
        with patch.object(type(rec), 'write', autospec=True) as w:
            self.assertEqual(self._sync(), 'unchanged')
        w.assert_not_called()

    def test_stale_last_checked_is_refreshed(self):
        self._sync()
        rec = self.Order.search([('order_number', '=', 'NW1')])
        old = fields.Datetime.now() - timedelta(hours=7)
        rec.last_checked = old
        self._sync()
        self.assertGreater(rec.last_checked, old)

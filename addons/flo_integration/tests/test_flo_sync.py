from datetime import datetime, timezone
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

API = 'odoo.addons.flo_integration.models.flo_api.FloAPIClient.get_orders'


def _flo_order(number, status='Cancelled', ts=None, **kw):
    # 'Cancelled' FLO_VALID_ORDER_STATUSES dışında → Sale Order oluşturulmaz (ürün verisi gerekmez)
    vals = {'orderNumber': number, 'id': number, 'shipmentPackageStatus': status,
            'orderDate': ts or int(datetime.now(timezone.utc).timestamp()), 'lines': []}
    vals.update(kw)
    return vals


@tagged('post_install', '-at_install')
class TestFloSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Store = cls.env['flo.store']
        cls.store = Store.create({'name': 'A', 'flo_username': 'u', 'flo_password': 'p', 'auto_sync': False})
        cls.store2 = Store.create({'name': 'B', 'flo_username': 'u', 'flo_password': 'p', 'auto_sync': False})
        cls.Order = cls.env['flo.order']

    def _sync(self, content, store=None):
        with patch(API, return_value={'success': True, 'data': {'totalPages': 1, 'content': content}}) as m:
            res = self.Order.sync_orders_for_store(store or self.store)
        return res, m

    def test_cron_loads_on_odoo19(self):
        cron = self.env.ref('flo_integration.ir_cron_flo_sync_orders')
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 5)

    def test_client_filter_window(self):
        # pencere 1 gün; 23 saat önceki sipariş içeride, 25 saat önceki dışarıda
        now = int(datetime.now(timezone.utc).timestamp())
        res, _m = self._sync([_flo_order('F1', ts=now - 23 * 3600), _flo_order('F2', ts=now - 25 * 3600)])
        self.assertEqual(res['created'], 1)
        self.assertTrue(self.Order.search([('order_number', '=', 'F1')]))
        self.assertFalse(self.Order.search([('order_number', '=', 'F2')]))

    def test_unchanged_order_is_not_written(self):
        self._sync([_flo_order('F10')])
        rec = self.Order.search([('order_number', '=', 'F10')])
        with patch.object(type(rec), 'write', autospec=True) as w:
            res, _m = self._sync([_flo_order('F10')])
        w.assert_not_called()
        self.assertEqual((res['created'], res['updated'], res['errors']), (0, 0, 0))

    def test_changed_status_counts_as_updated(self):
        self._sync([_flo_order('F11')])
        res, _m = self._sync([_flo_order('F11', status='Shipped', cargoTrackingNumber='T1')])
        self.assertEqual(res['updated'], 1)
        rec = self.Order.search([('order_number', '=', 'F11')])
        self.assertEqual((rec.order_status, rec.cargo_tracking_number), ('Shipped', 'T1'))

    def test_lookup_is_scoped_by_store(self):
        self._sync([_flo_order('F12')], self.store)
        res, _m = self._sync([_flo_order('F12')], self.store2)
        self.assertEqual(res['created'], 1)  # aynı numara başka mağazada → yeni kayıt, diğerine yazılmaz
        self.assertEqual(len(self.Order.search([('order_number', '=', 'F12')])), 2)

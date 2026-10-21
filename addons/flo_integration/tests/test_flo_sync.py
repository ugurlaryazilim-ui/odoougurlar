from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.flo_integration.models.flo_api import FloAPIClient, _epoch

API = 'odoo.addons.flo_integration.models.flo_api.FloAPIClient.get_orders'


def _flo_order(number, status='Cancelled', ts=None, **kw):
    # 'Cancelled' FLO_VALID_ORDER_STATUSES dışında → Sale Order oluşturulmaz (ürün verisi gerekmez)
    vals = {'orderNumber': number, 'id': number, 'shipmentPackageStatus': status,
            'orderDate': ts or int(datetime.now(timezone.utc).timestamp()), 'lines': []}
    vals.update(kw)
    return vals


@tagged('post_install', '-at_install')
class TestFloApiTime(TransactionCase):

    def test_epoch_naive_is_utc_regardless_of_server_tz(self):
        # 2026-01-01 00:00 UTC
        self.assertEqual(_epoch(datetime(2026, 1, 1)), 1767225600)
        # aynı an, TR saatiyle (UTC+3)
        tr = datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(_epoch(tr), 1767225600)
        self.assertEqual(_epoch(1767225600), 1767225600)

    def test_get_orders_sends_epoch_params(self):
        store = SimpleNamespace(flo_username='u', flo_password='p', flo_seller_id='1')
        client = FloAPIClient(store)
        client._request = MagicMock(return_value={'success': True, 'data': {}})
        client.get_orders(start_date=datetime(2026, 1, 1), end_date=datetime(2026, 1, 2), page=2, size=50)
        params = client._request.call_args.kwargs['params']
        self.assertEqual(params, {'page': 2, 'size': 50, 'startDate': 1767225600, 'endDate': 1767225600 + 86400})


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

    def test_window_is_utc(self):
        _res, m = self._sync([])
        start, end = m.call_args.kwargs['start_date'], m.call_args.kwargs['end_date']
        now = fields.Datetime.now()
        self.assertLess(abs((end - timedelta(minutes=5)) - now), timedelta(seconds=30))
        self.assertEqual(end - start, timedelta(days=self.store.order_day_range or 1, minutes=5))

    def test_client_filter_uses_utc(self):
        # penceresi 1 gün; 23 saat önceki sipariş (TR-UTC farkı 3 sa) içeride kalmalı, 25 saat önceki dışarıda
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

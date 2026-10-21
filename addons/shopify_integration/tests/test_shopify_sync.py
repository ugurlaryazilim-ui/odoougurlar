from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.shopify_integration.models import shopify_api
from odoo.addons.shopify_integration.models.shopify_api import ShopifyAPIClient

API = 'odoo.addons.shopify_integration.models.shopify_api.ShopifyAPIClient.get_orders'


def _resp(orders, link='', status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {'orders': orders}
    r.headers = {'Link': link} if link else {}
    r.text = 'err'
    return r


def _next(token):
    return f'<https://x.myshopify.com/admin/api/2024-04/orders.json?limit=250&page_info={token}>; rel="next"'


def _order(oid, **kw):
    vals = {'id': oid, 'name': f'#{oid}', 'financial_status': 'paid', 'fulfillment_status': None,
            'created_at': fields.Datetime.now().strftime('%Y-%m-%dT%H:%M:%S+00:00'), 'line_items': []}
    vals.update(kw)
    return vals


@tagged('post_install', '-at_install')
class TestShopifyApiPaging(TransactionCase):

    def _client(self, responses):
        store = SimpleNamespace(shop_url='x.myshopify.com', access_token='t', api_version='2024-04')
        client = ShopifyAPIClient(store)
        client._session = MagicMock()
        client._session.request.side_effect = responses
        return client

    def test_follows_link_header_until_last_page(self):
        client = self._client([
            _resp([{'id': 1}], _next('AAA')),
            _resp([{'id': 2}], _next('BBB')),
            _resp([{'id': 3}]),
        ])
        res = client.get_orders(created_at_min='2026-01-01T00:00:00+00:00')
        self.assertEqual([o['id'] for o in res['data']], [1, 2, 3])
        calls = client._session.request.call_args_list
        self.assertEqual(len(calls), 3)
        # Shopify: page_info ile yalnız limit gönderilebilir (diğer filtreler 400 verir)
        self.assertEqual(calls[1].kwargs['params'], {'limit': 250, 'page_info': 'AAA'})
        self.assertEqual(calls[2].kwargs['params'], {'limit': 250, 'page_info': 'BBB'})
        self.assertIn('created_at_min', calls[0].kwargs['params'])

    def test_previous_and_next_rels_picks_next(self):
        link = '<https://x/o.json?page_info=PREV>; rel="previous", ' + _next('NEXT')
        client = self._client([_resp([{'id': 1}], link), _resp([{'id': 2}])])
        client.get_orders()
        self.assertEqual(client._session.request.call_args_list[1].kwargs['params']['page_info'], 'NEXT')

    def test_page_cap(self):
        client = self._client([_resp([{'id': i}], _next('X')) for i in range(10)])
        with patch.object(shopify_api, 'MAX_PAGES', 3):
            res = client.get_orders()
        self.assertEqual(len(res['data']), 3)
        self.assertEqual(client._session.request.call_count, 3)

    def test_first_page_error_is_returned(self):
        client = self._client([_resp([], status=500)])
        self.assertFalse(client.get_orders()['success'])

    def test_later_page_error_returns_partial(self):
        client = self._client([_resp([{'id': 1}], _next('A')), _resp([], status=500)])
        res = client.get_orders()
        self.assertTrue(res['success'])
        self.assertEqual([o['id'] for o in res['data']], [1])


@tagged('post_install', '-at_install')
class TestShopifySync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = cls.env['shopify.store'].create({
            'name': 'T', 'shop_url': 'x.myshopify.com', 'access_token': 't', 'auto_sync': False})
        cls.Order = cls.env['shopify.order']

    def _sync(self, orders, so_mock=None):
        # SO oluşturma ürün/vergi verisine bağlı; burada sınanan sayfalama sonrası işleme mantığı.
        so_mock = so_mock or MagicMock(return_value=False)
        with patch(API, return_value={'success': True, 'data': orders}), \
                patch.object(type(self.Order), '_create_odoo_sale_order', so_mock):
            return self.Order.sync_orders_for_store(self.store)

    def _age(self, rec, create_ago, write_ago):
        now = fields.Datetime.now()
        self.env.cr.execute('UPDATE shopify_order SET create_date=%s, write_date=%s WHERE id=%s',
                            (now - create_ago, now - write_ago, rec.id))
        rec.invalidate_recordset()

    def test_db_error_in_one_order_does_not_roll_back_others(self):
        real = type(self.Order)._process_order_json

        def fake(this, order_json, store):
            if order_json['id'] == 2:
                this.env.cr.execute('SELECT 1/0')  # transaction'ı abort eden gerçek DB hatası
            return real(this, order_json, store)

        with patch.object(type(self.Order), '_process_order_json', fake):
            res = self._sync([_order(1), _order(2), _order(3)])
        self.assertEqual(res['created'], 2)
        self.assertEqual(res['errors'], 1)
        got = self.Order.search([('store_id', '=', self.store.id)]).mapped('order_id')
        self.assertEqual(sorted(got), ['1', '3'])

    def test_unchanged_order_is_not_written(self):
        self._sync([_order(10)])
        rec = self.Order.search([('order_id', '=', '10')])
        with patch.object(type(rec), 'write', autospec=True) as w:
            res = self._sync([_order(10)])
        w.assert_not_called()
        self.assertEqual((res['created'], res['updated'], res['errors']), (0, 0, 0))

    def test_changed_order_counts_as_updated(self):
        self._sync([_order(11)])
        res = self._sync([_order(11, fulfillment_status='fulfilled')])
        self.assertEqual(res['updated'], 1)
        self.assertEqual(self.Order.search([('order_id', '=', '11')]).fulfillment_status, 'fulfilled')

    def test_sale_order_retry_backoff(self):
        so_mock = MagicMock(return_value=False)
        self._sync([_order(20)], so_mock)
        self.assertEqual(so_mock.call_count, 1)  # yeni sipariş: bir deneme
        rec = self.Order.search([('order_id', '=', '20')])

        self._sync([_order(20)], so_mock)  # hemen sonraki tur: bekleme süresi dolmadı
        self.assertEqual(so_mock.call_count, 1)

        # 2 saatlik kayıt → bekleme 1 saat; son işlem 10 dk önce → hâlâ erken
        self._age(rec, timedelta(hours=2), timedelta(minutes=10))
        self._sync([_order(20)], so_mock)
        self.assertEqual(so_mock.call_count, 1)

        # son işlem 2 saat önce → deneme zamanı; başarısız deneme sayacı (write_date) sıfırlar
        self._age(rec, timedelta(hours=2), timedelta(hours=2))
        self._sync([_order(20)], so_mock)
        self.assertEqual(so_mock.call_count, 2)
        self._sync([_order(20)], so_mock)
        self.assertEqual(so_mock.call_count, 2)

    def test_failed_retry_does_not_break_sync(self):
        so_mock = MagicMock(side_effect=ValueError('boom'))
        self._sync([_order(30)], so_mock)
        rec = self.Order.search([('order_id', '=', '30')])
        self.assertTrue(rec)  # SO hatası shopify.order kaydını düşürmez
        self._age(rec, timedelta(hours=2), timedelta(hours=2))
        res = self._sync([_order(30)], so_mock)
        self.assertEqual(res['errors'], 0)
        self.assertEqual(so_mock.call_count, 2)

import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.hepsiburada_integration.models.hepsiburada_order_sync import _tr_now


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data
        self.text = ''

    def json(self):
        return self._data


class FakeSession:
    """requests.Session yerine: routes(url) -> (status, data); çağrıları kaydeder."""

    def __init__(self, routes=None):
        self.routes = routes or (lambda url: None)
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        res = self.routes(url)
        if res is None:
            # Açık paket listesi boş, diğer uçlar kayıt yok
            return FakeResponse(200, []) if url.endswith('/packages/merchantid/x') else FakeResponse(404)
        return FakeResponse(*res)

    def count(self, part):
        return sum(1 for u in self.urls if part in u)


@tagged('post_install', '-at_install', 'hepsiburada_integration')
class TestHepsiburadaSyncLoad(TransactionCase):
    """Dakikalık cron yükü: ağır taramalar 15 dk'da bir, eksik sipariş backoff'u, yalnız iş varsa log."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # NEDEN: onay/iptal kancaları Nebim'e dış çağrı yapmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['hepsiburada.store'].create(
            {'name': 'HB Load', 'merchant_id': 'x', 'api_user': 'y', 'api_password': 'z'})
        cls.Sync = cls.env['hepsiburada.order.sync']
        cls.Log = cls.env['hepsiburada.sync.log']
        cls.ICP = ICP

    def _run(self, routes=None, force=False):
        session = FakeSession(routes)
        with patch.object(type(self.store), '_get_session', return_value=(session, 'x')):
            self.Sync._sync_store_orders(self.store, force=force)
        return session

    def _logs(self):
        return self.Log.search_count([('store_id', '=', self.store.id)])

    def _age_heavy_stamp(self, minutes):
        key = f'hepsiburada_integration.heavy_sync.{self.store.id}'
        self.ICP.set_param(key, fields.Datetime.to_string(fields.Datetime.subtract(
            fields.Datetime.now(), minutes=minutes)))

    # ── ağır tarama sıklığı ──

    def test_heavy_scans_run_at_most_every_15_minutes(self):
        first = self._run()
        self.assertTrue(first.count('/cancelled'))
        self.assertTrue(first.count('/shipped'))
        second = self._run()
        # Yeni sipariş gecikmesi artmasın: açık paketler + unpacked her dakika
        self.assertTrue(second.count('/packages/merchantid/x'))
        self.assertTrue(second.count('/status/unpacked'))
        self.assertEqual(second.count('/cancelled'), 0)
        self.assertEqual(second.count('/shipped'), 0)
        self.assertEqual(second.count('/delivered'), 0)
        self.assertEqual(second.count('/undelivered'), 0)
        self.assertLessEqual(len(second.urls), 3)
        self._age_heavy_stamp(16)
        third = self._run()
        self.assertTrue(third.count('/cancelled'))

    def test_manual_sync_forces_heavy_scan_and_log(self):
        self._run()
        forced = self._run(force=True)
        self.assertTrue(forced.count('/cancelled'))
        self.assertGreaterEqual(self._logs(), 1)

    # ── log yalnız iş yapıldıysa ──

    def test_idle_run_opens_no_log(self):
        self._run()
        self._run()
        self.assertEqual(self._logs(), 0)

    def test_new_order_opens_log(self):
        def fake_create(order_no, group, store, split=False, multi=False):
            return self.env['hepsiburada.order'].create(
                {'store_id': store.id, 'hb_order_number': order_no})

        pkg = {'packageNumber': 'P1', 'items': [{'orderNumber': 'LOG-1', 'packageNumber': 'P1'}]}
        with patch.object(type(self.Sync), '_create_or_update_order', side_effect=fake_create):
            self._run(lambda url: (200, [pkg]) if url.endswith('/packages/merchantid/x') else None)
        self.assertEqual(self._logs(), 1)

    def test_error_opens_log(self):
        pkg = {'packageNumber': 'P2', 'items': [{'orderNumber': 'LOG-2', 'packageNumber': 'P2'}]}
        with patch.object(type(self.Sync), '_create_or_update_order', side_effect=ValueError('boom')):
            self._run(lambda url: (200, [pkg]) if url.endswith('/packages/merchantid/x') else None)
        log = self.Log.search([('store_id', '=', self.store.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.state, 'error')

    def test_open_packages_failure_opens_error_log(self):
        self._run(lambda url: (500, None) if url.endswith('/packages/merchantid/x') else None)
        self.assertEqual(self.Log.search([('store_id', '=', self.store.id)]).state, 'error')

    # ── eksik sipariş detayı ──

    def _shipped_route(self, order_no, detail):
        shipped = [{'OrderNumbers': [order_no], 'PackageNumber': 'PK-1',
                    'ShippedDate': fields.Datetime.to_string(_tr_now()).replace(' ', 'T')}]

        def routes(url):
            if url.endswith('/shipped'):
                return 200, shipped
            if f'/orderNumber/{order_no}' in url:
                return 200, detail
            return None
        return routes

    def _history(self, routes):
        session = FakeSession(routes)
        with patch.object(type(self.Sync), '_process_orders', return_value=(1, 0, 1, ['hata'])) as proc:
            self.Sync._fetch_historical_statuses(self.store, session, 'x')
        return session, proc

    def test_missing_order_detail_is_not_refetched_within_30_minutes(self):
        routes = self._shipped_route('MISS-1', {'orderNumber': 'MISS-1', 'orderDate': _tr_now().strftime('%Y-%m-%dT%H:%M:%S')})
        s1, _p = self._history(routes)
        self.assertEqual(s1.count('/orderNumber/MISS-1'), 1)
        s2, _p = self._history(routes)
        self.assertEqual(s2.count('/orderNumber/MISS-1'), 0)
        # 31 dk sonra yeniden denenir
        key = f'hepsiburada_integration.detail_retry.{self.store.id}'
        past = fields.Datetime.to_string(fields.Datetime.subtract(fields.Datetime.now(), minutes=1))
        self.ICP.set_param(key, json.dumps({'MISS-1': past}))
        s3, _p = self._history(routes)
        self.assertEqual(s3.count('/orderNumber/MISS-1'), 1)

    def test_order_older_than_window_is_fetched_once_and_never_processed(self):
        old = (_tr_now() - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%S')
        routes = self._shipped_route('OLD-1', {'orderNumber': 'OLD-1', 'orderDate': old})
        s1, proc = self._history(routes)
        self.assertEqual(s1.count('/orderNumber/OLD-1'), 1)
        proc.assert_not_called()
        # Pencere (3 gün) bitene dek bekler: 30 dk değil gün mertebesinde
        retry = json.loads(self.ICP.get_param(f'hepsiburada_integration.detail_retry.{self.store.id}'))
        wait = fields.Datetime.to_datetime(retry['OLD-1']) - fields.Datetime.now()
        self.assertGreater(wait, timedelta(days=2))

    def test_old_order_date_in_history_item_skips_detail_fetch(self):
        old = (_tr_now() - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M:%S')
        shipped = [{'OrderNumbers': ['OLD-2'], 'PackageNumber': 'PK-2', 'orderDate': old,
                    'ShippedDate': fields.Datetime.to_string(_tr_now()).replace(' ', 'T')}]
        s1, proc = self._history(lambda url: (200, shipped) if url.endswith('/shipped') else None)
        self.assertEqual(s1.count('/orderNumber/'), 0)
        proc.assert_not_called()

    # ── N+1 ──

    def test_history_looks_up_orders_with_one_query(self):
        HbOrder = self.env['hepsiburada.order']
        nos = [f'BATCH-{i}' for i in range(6)]
        for no in nos:
            HbOrder.create({'store_id': self.store.id, 'hb_order_number': no, 'status': 'Open'})
        stamp = fields.Datetime.to_string(_tr_now()).replace(' ', 'T')
        shipped = [{'OrderNumbers': [no], 'PackageNumber': f'PK-{no}', 'ShippedDate': stamp} for no in nos]
        original = type(HbOrder).search
        with patch.object(type(HbOrder), 'search', autospec=True, side_effect=original) as search:
            self.Sync._fetch_historical_statuses(
                self.store, FakeSession(lambda url: (200, shipped) if url.endswith('/shipped') else None), 'x')
        by_number = [c for c in search.call_args_list
                     if any(isinstance(t, (tuple, list)) and t and t[0] == 'hb_order_number' for t in c.args[1])]
        self.assertEqual(len(by_number), 1)
        self.assertEqual(set(HbOrder.search([('hb_order_number', 'in', nos)]).mapped('status')), {'Shipped'})

    def test_cancellations_use_batched_lookup_and_still_cancel(self):
        product = self.env['product.product'].create(
            {'name': 'HB Load Ürün', 'default_code': 'HB-LOAD-1', 'type': 'consu', 'list_price': 100})
        so = self.env['sale.order'].create({
            'partner_id': self.env['res.partner'].create({'name': 'HB Load Müşteri'}).id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        so.action_confirm()
        hb = self.env['hepsiburada.order'].create({
            'store_id': self.store.id, 'hb_order_number': 'CNL-1', 'status': 'Open', 'sale_order_id': so.id,
            'line_ids': [(0, 0, {'line_item_id': 'L1', 'quantity': 1, 'price': 100})],
        })
        cancelled = [{'orderNumber': 'CNL-1', 'lineItemId': 'L1', 'quantity': 1, 'cancelDate': '2026-10-01'}]
        session = FakeSession(lambda url: (200, cancelled) if url.endswith('/cancelled') else None)
        self.assertEqual(self.Sync._sync_cancellations(self.store, session, 'x'), 1)
        self.assertEqual(hb.status, 'Cancelled')
        self.assertEqual(so.state, 'cancel')


@tagged('post_install', '-at_install', 'hepsiburada_integration')
class TestHepsiburadaLogGc(TransactionCase):

    def test_logs_older_than_30_days_are_deleted(self):
        store = self.env['hepsiburada.store'].create(
            {'name': 'HB GC', 'merchant_id': 'x', 'api_user': 'y', 'api_password': 'z'})
        Log = self.env['hepsiburada.sync.log']
        old, new = (Log.create({'store_id': store.id, 'name': n}) for n in ('eski', 'yeni'))
        self.env.cr.execute("UPDATE hepsiburada_sync_log SET create_date = %s WHERE id = %s",
                            (fields.Datetime.subtract(fields.Datetime.now(), days=31), old.id))
        Log._gc_old_logs()
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

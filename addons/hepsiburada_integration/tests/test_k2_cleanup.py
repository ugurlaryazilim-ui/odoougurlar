"""K2 (P3 temizlik): HB mağaza adı toplu arama, 429 sonrası log seli yok."""
import logging
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.hepsiburada_integration.models.hepsiburada_order_sync import _tr_now

from .test_sync_load import FakeSession

SYNC_LOGGER = 'odoo.addons.hepsiburada_integration.models.hepsiburada_order_sync'


@tagged('post_install', '-at_install', 'hepsiburada_integration')
class TestK2Cleanup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        Store = cls.env['hepsiburada.store']
        cls.store = Store.create({'name': 'HB K2', 'merchant_id': 'k2-m1', 'api_user': 'y', 'api_password': 'z'})
        cls.store2 = Store.create({'name': 'HB K2b', 'merchant_id': 'k2-m2', 'api_user': 'y', 'api_password': 'z'})
        cls.Sync = cls.env['hepsiburada.order.sync']

    # ── KK1: satış listesinde HB mağaza adı toplu ──

    def _hb_orders(self, merchants):
        partner = self.env['res.partner'].create({'name': 'K2 Müşteri'})
        return self.env['sale.order'].create([
            {'partner_id': partner.id, 'client_order_ref': 'K2-%d' % i, 'hb_store_id': m}
            for i, m in enumerate(merchants)
        ])

    def test_store_name_lookup_is_batched(self):
        orders = self._hb_orders(['k2-m1', 'k2-m2', 'k2-m1', 'k2-m2', 'k2-yok'])
        orders.invalidate_recordset()
        calls = []
        orig = type(self.env['hepsiburada.store']).search

        def spy(model, *args, **kwargs):
            calls.append(args)
            return orig(model, *args, **kwargs)

        with patch.object(type(self.env['hepsiburada.store']), 'search', spy):
            orders._compute_marketplace_info()
        self.assertEqual(len(calls), 1, "kayıt başına değil, kayıt kümesi için tek arama")
        self.assertEqual(orders.mapped('marketplace_store_name'),
                         ['HB K2', 'HB K2b', 'HB K2', 'HB K2b', 'k2-yok'])  # eşleşmeyen: merchant ID
        self.assertEqual(orders[0].marketplace_seller_id, 'k2-m1')
        self.assertFalse(orders[4].marketplace_seller_id)

    # ── KK3: 429 sonrası log seli ──

    def _history_with_missing(self, order_nos, status=429):
        shipped = [{'OrderNumbers': list(order_nos), 'PackageNumber': 'PK-K2',
                    'ShippedDate': fields.Datetime.to_string(_tr_now()).replace(' ', 'T')}]

        def routes(url):
            if url.endswith('/shipped'):
                return 200, shipped
            if '/orderNumber/' in url:
                return status, None
            if url.endswith('/packages/merchantid/k2-m1'):
                return 200, []  # açık paket yok (FakeSession varsayılanı yalnız merchant 'x' için)
            return None

        return FakeSession(routes)

    def test_429_does_not_log_error_per_missing_order(self):
        session = self._history_with_missing(['K2-A', 'K2-B', 'K2-C'])
        with self.assertNoLogs(SYNC_LOGGER, logging.ERROR):
            self.Sync._fetch_historical_statuses(self.store, session, 'k2-m1')
        self.assertEqual(session.count('/orderNumber/'), 1, "429'dan sonra kalan siparişler için istek atılmaz")
        # Kalanlar sonraki tura kalır: 30 dk damgası vurulmaz
        key = f'hepsiburada_integration.detail_retry.{self.store.id}'
        self.assertNotIn('K2-B', self.env['ir.config_parameter'].sudo().get_param(key) or '')

    def test_429_round_has_single_warning(self):
        session = self._history_with_missing(['K2-A', 'K2-B', 'K2-C'])
        with patch.object(type(self.store), '_get_session', return_value=(session, 'k2-m1')), \
                self.assertLogs(SYNC_LOGGER, logging.WARNING) as logs:
            self.Sync._sync_store_orders(self.store, force=True)
        self.assertFalse([r for r in logs.records if r.levelno >= logging.ERROR])
        warnings = [r for r in logs.records if r.levelno == logging.WARNING and '429' in r.getMessage()]
        self.assertEqual(len(warnings), 1, "tur başına tek 429 uyarısı")

    def test_other_detail_errors_still_logged_as_error(self):
        class Boom(FakeSession):
            def get(self, url, params=None, timeout=None):
                raise RuntimeError('bağlantı koptu')

        with self.assertLogs(SYNC_LOGGER, logging.ERROR):
            self.assertIsNone(self.Sync._fetch_full_order_detail('K2-X', self.store, Boom(), 'k2-m1'))

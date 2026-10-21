from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .test_sync_load import FakeResponse, FakeSession


class RateLimitedResponse(FakeResponse):
    def __init__(self, retry_after='120'):
        super().__init__(429, None)
        self.headers = {'Retry-After': retry_after}


class BadJsonResponse(FakeResponse):
    def __init__(self):
        super().__init__(200, None)
        self.text = '<html>bakim</html>'

    def json(self):
        raise ValueError('Expecting value')


@tagged('post_install', '-at_install', 'hepsiburada_integration')
class TestHepsiburadaResilience(TransactionCase):
    """TODO-32: mağaza başına izolasyon, bozuk JSON, 429 geri çekilme, last_sync yalnız değişince."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        Store = cls.env['hepsiburada.store']
        cls.store = Store.create({'name': 'HB R1', 'merchant_id': 'x', 'api_user': 'y', 'api_password': 'z'})
        cls.store2 = Store.create({'name': 'HB R2', 'merchant_id': 'x2', 'api_user': 'y', 'api_password': 'z'})
        cls.Sync = cls.env['hepsiburada.order.sync']
        cls.ICP = ICP

    def _run(self, session, force=False):
        with patch.object(type(self.store), '_get_session', return_value=(session, 'x')):
            self.Sync._sync_store_orders(self.store, force=force)
        return session

    def test_store_error_does_not_stop_other_stores(self):
        seen = []

        def fake(model, store, force=False):
            seen.append(store.id)
            if store == self.store:
                raise RuntimeError('mağaza 1 patladı')

        with patch.object(type(self.Sync), '_sync_store_orders', autospec=True, side_effect=fake):
            self.Sync.sync_orders()
        self.assertIn(self.store.id, seen)
        self.assertIn(self.store2.id, seen, "ilk mağazanın hatası ikinciyi durdurmamalı")

    def test_bad_json_is_logged_not_raised(self):
        class Bad(FakeSession):
            def get(self, url, params=None, timeout=None):
                self.urls.append(url)
                return BadJsonResponse()

        items, error = self.Sync._fetch_open_packages(self.store, Bad(), 'x')
        self.assertIsNone(items)
        self.assertIn('JSON', error)
        self.assertIsNone(self.Sync._fetch_paged(Bad(), 'https://h/shipped', 50))
        self.assertIsNone(self.Sync._fetch_full_order_detail('N1', self.store, Bad(), 'x'))
        self._run(Bad(), force=True)  # tur çökmemeli

    def test_429_stops_requests_and_backs_off(self):
        class Limited(FakeSession):
            def get(self, url, params=None, timeout=None):
                self.urls.append(url)
                return RateLimitedResponse('120')

        session = self._run(Limited(), force=True)
        self.assertEqual(len(session.urls), 1, "429'dan sonra aynı turda başka istek gitmemeli")
        until = fields.Datetime.to_datetime(self.ICP.get_param(f'hepsiburada_integration.backoff.{self.store.id}'))
        remaining = (until - fields.Datetime.now()).total_seconds()
        self.assertTrue(100 < remaining <= 120, remaining)
        # Süre dolana dek cron turu mağazayı hiç yormaz; elle senkron (force) çalışır
        self.assertEqual(len(self._run(FakeSession()).urls), 0)
        self.assertTrue(len(self._run(FakeSession(), force=True).urls) > 0)

    def test_retry_after_parsing_is_clamped(self):
        from odoo.addons.hepsiburada_integration.models.hepsiburada_order_sync import _retry_after_seconds
        self.assertEqual(_retry_after_seconds(RateLimitedResponse('30')), 30)
        self.assertEqual(_retry_after_seconds(RateLimitedResponse('99999')), 900)
        self.assertEqual(_retry_after_seconds(RateLimitedResponse('abc')), 60)
        self.assertEqual(_retry_after_seconds(FakeResponse(429)), 60)

    def test_last_sync_written_only_when_stale_or_work(self):
        self._run(FakeSession(), force=True)
        first = self.store.last_sync
        self.assertTrue(first)
        self.store.last_sync = fields.Datetime.now() - timedelta(minutes=1)
        recent = self.store.last_sync
        with patch.object(type(self.store), 'write', autospec=True) as write:
            self._run(FakeSession())
        write.assert_not_called()
        self.assertEqual(self.store.last_sync, recent)
        self.store.last_sync = fields.Datetime.now() - timedelta(minutes=20)
        stale = self.store.last_sync
        self._run(FakeSession())
        self.assertGreater(self.store.last_sync, stale)

"""Nebim çağrı süreleri: etkileşimli okuma uçları kısa timeout + yeniden deneme yok;
paketleme zinciri 60 sn context'i taşır; packing_complete'te Nebim süre bütçesi (20261021-performans H3)."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.odoougurlar.services import nebim_connector as nc
from odoo.addons.ugurlar_barcode.controllers import batch_api, discount_api, packing_api, product_api
from odoo.addons.ugurlar_barcode.tests.common import PackingCase


@tagged('post_install', '-at_install')
class TestNebimTimeouts(PackingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Nebim Süre Ürünü', 'NTO-1')

    def setUp(self):
        super().setUp()
        self._patch_request(discount_api, product_api, batch_api)
        self.conn_cls = type(self.env['odoougurlar.nebim.connector'])

    def _capture_run_proc(self):
        calls = []

        def fake(conn, proc_name, params=None, **kw):
            calls.append(kw)
            return []
        p = patch.object(self.conn_cls, 'run_proc', fake)
        p.start()
        self.addCleanup(p.stop)
        return calls

    # ─── etkileşimli okuma uçları ──────────────────────
    def test_discount_endpoints_pass_short_timeout_and_no_retry(self):
        calls = self._capture_run_proc()
        discount_api.DiscountApiController().calculate_discounts(
            basket=[{'barcode': 'NTO-1', 'quantity': 1}])
        discount_api.DiscountApiController().search_customer(query='abc')
        self.assertEqual(len(calls), 2)
        for kw in calls:
            self.assertEqual(kw, {'timeout': nc.INTERACTIVE_TIMEOUT, 'retries': 0})
        self.assertLessEqual(nc.INTERACTIVE_TIMEOUT, 20)

    def test_inventory_matrix_passes_short_timeout_and_no_retry(self):
        calls = self._capture_run_proc()
        product_api.ProductApiController().inventory_matrix(barcode='NTO-1')
        self.assertEqual(calls, [{'timeout': nc.INTERACTIVE_TIMEOUT, 'retries': 0}])

    # ─── paketleme zinciri ─────────────────────────────
    def _route_ready(self):
        sale, picking = self._sale(self.prod, 1)
        batch = self._route(picking)
        picking.move_ids.write({'wave_collected_qty': 1, 'wave_skipped': False})
        res = batch_api.BatchApiController().batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        return picking, batch

    def test_packing_chain_carries_write_timeout_context(self):
        """Fatura POST'u connector'a 60 sn context'iyle ulaşır (cron yolunda context yok -> 300)."""
        rec = self._nebim_real()
        seen = []
        real_post = self.conn_cls.post_data

        def spy(conn, endpoint, payload):
            seen.append(conn.env.context.get('nebim_timeout'))
            return real_post(conn, endpoint, payload)
        # _nebim_real zaten post_data'yı taklit etti; onun üstüne gözlemci
        with patch.object(self.conn_cls, 'post_data', spy):
            picking, batch = self._route_ready()
            res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(rec['posts'], 1)
        self.assertEqual(seen, [nc.WRITE_CHAIN_TIMEOUT])
        self.assertEqual(nc.WRITE_CHAIN_TIMEOUT, 60)

    def test_packing_complete_defers_nebim_when_budget_exhausted(self):
        rec = self._nebim_real()
        picking, batch = self._route_ready()
        with patch.object(packing_api, 'NEBIM_COMPLETE_BUDGET', -1):
            res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual(picking.state, 'done', 'doğrulama bütçeden etkilenmez')
        self.assertEqual(rec['posts'], 0, 'bütçe dolunca Nebim çağrılmaz')
        self.assertFalse(res['success'])
        self.assertTrue(any('ertelendi' in e and picking.name in e for e in res['errors']), res)
        # Tekrar Tamamla: bütçe yeterliyse takılı kalan sipariş aktarılır
        res2 = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res2.get('success'), res2)
        self.assertEqual(rec['posts'], 1)

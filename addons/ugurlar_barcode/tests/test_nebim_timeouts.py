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
            seen.append((conn.env.context.get('nebim_timeout'), conn.env.context.get('nebim_retries')))
            return real_post(conn, endpoint, payload)
        # _nebim_real zaten post_data'yı taklit etti; onun üstüne gözlemci
        with patch.object(self.conn_cls, 'post_data', spy):
            picking, batch = self._route_ready()
            res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(rec['posts'], 1)
        self.assertEqual(seen, [(nc.WRITE_CHAIN_TIMEOUT, 0)])
        self.assertEqual(nc.WRITE_CHAIN_TIMEOUT, 60)
        # NEDEN: istemci RPC süresi ~90 sn; bütçe onun altında kalmalı
        self.assertLess(packing_api.NEBIM_COMPLETE_BUDGET, 90)

    def test_packing_complete_writes_early_orders_defers_rest_when_write_window_closes(self):
        """A4 düzeltme #1 (K-1) davranışı: yazma penceresi (bütçe - WRITE_CHAIN_TIMEOUT) içinde başlayan
        sipariş Nebim'e yazılır; kalan süre WRITE_CHAIN_TIMEOUT'tan azsa sonraki sipariş HİÇ gönderilmez,
        ertelenenler listesinde adıyla çıkar; ikinci Tamamla kalanı aktarır (mükerrer yok)."""
        rec = self._nebim_real()
        prod2 = self._new_product('Nebim Süre Ürünü 2', 'NTO-2')
        sale1, picking1 = self._sale(self.prod, 1)
        sale2, picking2 = self._sale(prod2, 1)
        batch = self._route(picking1 | picking2)
        (picking1 | picking2).move_ids.write({'wave_collected_qty': 1, 'wave_skipped': False})
        res = batch_api.BatchApiController().batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)

        real_sync = type(self.pack_ctl)._trigger_nebim_sync

        def slow_sync(ctl, picking, *args, **kwargs):
            # Birinci sipariş yazma penceresi içinde başlar ve 0,8 sn sürer; kalan 1,5 - 0,8 < 1,0
            import time
            time.sleep(0.8)
            return real_sync(ctl, picking, *args, **kwargs)

        with patch.object(packing_api, 'NEBIM_COMPLETE_BUDGET', 1.5), \
                patch.object(packing_api, 'WRITE_CHAIN_TIMEOUT', 1.0), \
                patch.object(type(self.pack_ctl), '_trigger_nebim_sync', slow_sync):
            res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual((picking1 | picking2).mapped('state'), ['done', 'done'], 'doğrulama bütçeden etkilenmez')
        self.assertEqual(rec['posts'], 1, 'yalnız ilk sipariş yazıldı, ikincisi ağa çıkmadı')
        deferred_msgs = [e for e in res['errors'] if 'ertelendi' in e]
        self.assertEqual(len(deferred_msgs), 1, res)
        names = (picking1 | picking2).mapped('name')
        in_msg = [n for n in names if n in deferred_msgs[0]]
        self.assertEqual(len(in_msg), 1, 'yalnız ertelenen sipariş adı geçmeli: %s' % deferred_msgs)
        self.assertFalse(res['success'])
        # Tekrar Tamamla: ertelenen aktarılır, ilk sipariş mükerrer gönderilmez
        res2 = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res2.get('success'), res2)
        self.assertEqual(rec['posts'], 2, 'toplam 2 fatura: mükerrer yok')

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

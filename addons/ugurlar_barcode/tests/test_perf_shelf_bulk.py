"""TODO-28: toplu raf işlemleri (Rafı Taşı / Rafı Boşalt / toplu raflama / sayım) ürün başına
ayrı hareket turu yerine tek turda çalışır; stok sonucu eski sıralı davranışla aynıdır."""
import logging
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import (
    base_api, counting_api, operations_api, shelf_api)
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestPerfShelfBulk(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.src = cls._new_shelf('PB-KAYNAK', 'PB-RAF-S')
        cls.dst = cls._new_shelf('PB-HEDEF', 'PB-RAF-D')
        cls.prods = [cls._new_product('Toplu Raf %02d' % i, 'PB-%02d' % i) for i in range(24)]

    def setUp(self):
        super().setUp()
        self._patch_request(shelf_api, operations_api, counting_api)
        self.shelf_ctl = shelf_api.ShelfApiController()
        self.ops_ctl = operations_api.OperationsApiController()
        self.count_ctl = counting_api.CountingApiController()

    # ─── yardımcılar ───────────────────────────────────
    def _stock(self, products, location, base=2):
        for i, p in enumerate(products):
            self._add_stock(p, location, base + i)

    def _measure(self, func, *args, **kwargs):
        """(sonuç, sorgu sayısı, _action_done çağrı sayısı)"""
        done_calls = []
        move_cls = type(self.env['stock.move'])
        original = move_cls._action_done

        def spy(rec, *a, **k):
            done_calls.append(len(rec))
            return original(rec, *a, **k)

        before = self.env.cr.sql_log_count
        with patch.object(move_cls, '_action_done', spy):
            res = func(*args, **kwargs)
        return res, self.env.cr.sql_log_count - before, done_calls

    def _done_moves(self, products, **domain):
        dom = [('product_id', 'in', [p.id for p in products]), ('state', '=', 'done')]
        dom += [(k, '=', v.id) for k, v in domain.items()]
        return self.env['stock.move'].search(dom)

    # ─── Rafı Taşı ─────────────────────────────────────
    def test_move_all_same_stock_result_and_single_move_round(self):
        prods = self.prods[:6]
        self._stock(prods, self.src)
        res, _q, done = self._measure(
            self.shelf_ctl.shelf_move_all, source_barcode='PB-RAF-S', target_barcode='PB-RAF-D')

        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['moved_count'], 6)
        self.assertEqual(res['total_quantity'], sum(2 + i for i in range(6)))
        self.assertEqual(done, [6], 'tüm hareketler tek _action_done turunda')
        for i, p in enumerate(prods):
            self.assertEqual(self._qty(p, self.src), 0)
            self.assertEqual(self._qty(p, self.dst), 2 + i)
            move = self._done_moves([p], location_id=self.src, location_dest_id=self.dst)
            self.assertEqual(len(move), 1, 'ürün başına tam bir iç hareket')
            self.assertEqual(move.quantity, 2 + i)
            self.assertEqual(move.origin, 'Mobil: Tüm Rafı Taşı')
        ops = self.env['ugurlar.barcode.operation'].search([
            ('operation_type', '=', 'shelf_transfer'), ('location_id', '=', self.dst.id)])
        self.assertEqual(len(ops), 6)

    def test_move_all_query_growth_is_sublinear(self):
        """Ürün sayısı 4 -> 16: ürün başına sorgu eski döngünün (>100/ürün) çok altında kalır."""
        self._stock(self.prods[:4], self.src)
        _r, q4, _d = self._measure(
            self.shelf_ctl.shelf_move_all, source_barcode='PB-RAF-S', target_barcode='PB-RAF-D')
        self._stock(self.prods[4:20], self.src)
        _r, q16, done = self._measure(
            self.shelf_ctl.shelf_move_all, source_barcode='PB-RAF-S', target_barcode='PB-RAF-D')
        per_product = (q16 - q4) / 12.0
        _logger.info('PERF raf_tasi: 4 ürün=%d sorgu, 16 ürün=%d sorgu, ürün başına=%.1f',
                     q4, q16, per_product)
        self.assertEqual(done, [16])
        self.assertLess(per_product, 45, 'ürün başına sorgu hâlâ eski döngü düzeyinde')

    def test_move_all_reserved_product_still_skipped(self):
        prods = self.prods[:3]
        self._stock(prods, self.src, base=5)
        picking = self._picking(prods[0], 2)
        self.assertEqual(picking.move_ids.quantity, 2)
        res = self.shelf_ctl.shelf_move_all(source_barcode='PB-RAF-S', target_barcode='PB-RAF-D')
        self.assertEqual(res['moved_count'], 2)
        self.assertEqual(res['skipped_count'], 1)
        self.assertEqual(self._qty(prods[0], self.src), 5)
        self.assertEqual(self._qty(prods[1], self.dst), 6)

    # ─── Rafı Boşalt ───────────────────────────────────
    def test_clear_all_same_stock_result_and_single_move_round(self):
        prods = self.prods[:5]
        self._stock(prods, self.src)
        res, _q, done = self._measure(self.shelf_ctl.shelf_clear_all, shelf_barcode='PB-RAF-S')

        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['cleared_count'], 5)
        self.assertEqual(done, [5])
        for i, p in enumerate(prods):
            self.assertEqual(self._qty(p, self.src), 0)
            move = self._done_moves([p], location_id=self.src)
            self.assertEqual(len(move), 1)
            self.assertEqual(move.quantity, 2 + i)
            self.assertTrue(move.is_inventory)
            self.assertEqual(move.location_dest_id.usage, 'inventory')
        self.assertEqual(self.env['ugurlar.barcode.operation'].search_count([
            ('operation_type', '=', 'remove'), ('location_id', '=', self.src.id)]), 5)

    # ─── Toplu raflama ─────────────────────────────────
    def test_bulk_putaway_same_stock_result_order_and_single_round(self):
        prods = self.prods[:4]
        items = [{'barcode': p.barcode, 'quantity': 3} for p in prods]
        items.insert(2, {'barcode': 'YOK-BARKOD', 'quantity': 1})
        items.append({'barcode': prods[0].barcode, 'quantity': 2})  # aynı ürün tekrar
        res, _q, done = self._measure(
            self.ops_ctl.bulk_scan, items=items, operation='putaway', shelf_barcode='PB-RAF-D')

        self.assertEqual([r['barcode'] for r in res['results']], [i['barcode'] for i in items],
                         'yanıt sırası kalem sırası')
        self.assertEqual(res['results'][2]['status'], 'not_found')
        self.assertEqual(res['success_count'], 5)
        self.assertEqual(done, [5])
        self.assertEqual(self._qty(prods[0], self.dst), 5)
        for p in prods[1:]:
            self.assertEqual(self._qty(p, self.dst), 3)
        self.assertEqual(self.env['ugurlar.barcode.operation'].search_count([
            ('operation_type', '=', 'putaway'), ('location_id', '=', self.dst.id)]), 5)

    def test_bulk_items_upper_bound(self):
        too_many = [{'barcode': 'X', 'quantity': 1}] * (base_api.MAX_BULK_ITEMS + 1)
        for res in (
                self.ops_ctl.bulk_scan(items=too_many, operation='putaway', shelf_barcode='PB-RAF-D'),
                self.count_ctl.count_save(shelf_barcode='PB-RAF-S', items=too_many)):
            self.assertIn('en fazla %d' % base_api.MAX_BULK_ITEMS, res.get('error', ''))

    # ─── Sayım ─────────────────────────────────────────
    def test_count_save_same_result_single_round_and_duplicate_semantics(self):
        prods = self.prods[:4]
        self._add_stock(prods[0], self.src, 5)   # sayım: 5 -> 2 (çıkış)
        self._add_stock(prods[1], self.src, 1)   # 1 -> 4 (giriş)
        self._add_stock(prods[2], self.src, 3)   # 3 -> 3 (hareket yok)
        # prods[3] rafta yok: 0 -> 2
        items = [
            {'barcode': prods[0].barcode, 'quantity': 2},
            {'barcode': prods[1].barcode, 'quantity': 4},
            {'barcode': prods[2].barcode, 'quantity': 3},
            {'barcode': prods[3].barcode, 'quantity': 9},
            {'barcode': prods[3].barcode, 'quantity': 2},   # tekrar: önceki sonuç "eski" sayılır
        ]
        res, _q, done = self._measure(
            self.count_ctl.count_save, shelf_barcode='PB-RAF-S', items=items)

        self.assertTrue(res.get('success'), res)
        self.assertEqual([r['status'] for r in res['results']], ['updated'] * 5)
        self.assertEqual([r['old_qty'] for r in res['results']], [5, 1, 3, 0, 9])
        self.assertEqual(done, [4], 'dört farklı hareket (çıkış, giriş, giriş, tekrar farkı) tek turda')
        for p, expected in zip(prods, (2, 4, 3, 2)):
            self.assertEqual(self._qty(p, self.src), expected)
        self.assertEqual(self.env['ugurlar.barcode.operation'].search_count([
            ('operation_type', '=', 'counting'), ('location_id', '=', self.src.id)]), 5)

    def test_count_save_queries_do_not_grow_per_item_with_locks_and_reads(self):
        self._add_stock(self.prods[0], self.src, 1)
        _r, q1, _d = self._measure(self.count_ctl.count_save, shelf_barcode='PB-RAF-S', items=[
            {'barcode': self.prods[0].barcode, 'quantity': 3}])
        items = [{'barcode': p.barcode, 'quantity': 3} for p in self.prods[1:13]]
        _r, q12, done = self._measure(
            self.count_ctl.count_save, shelf_barcode='PB-RAF-S', items=items)
        _logger.info('PERF sayim: 1 ürün=%d sorgu, 12 ürün=%d sorgu, ürün başına=%.1f',
                     q1, q12, (q12 - q1) / 11.0)
        self.assertEqual(done, [12])
        self.assertLess((q12 - q1) / 11.0, 45)

    def test_count_save_batch_failure_falls_back_per_item(self):
        """Parti bozulursa kalem kalem denenir: bozuk kalem 'error', diğerleri sayılır."""
        p_ok, p_bad = self.prods[0], self.prods[1]
        real = base_api.BarcodeApiBase._mobile_stock_moves

        def flaky(ctl, entries, *a, **k):
            # çok kalemli parti her zaman bozulur; tek kalemde yalnız p_bad bozulur
            if len(entries) > 1 or entries[0][0] == p_bad:
                raise UserError('hareket hatası')
            return real(ctl, entries, *a, **k)

        with patch.object(base_api.BarcodeApiBase, '_mobile_stock_moves', flaky):
            res = self.count_ctl.count_save(shelf_barcode='PB-RAF-S', items=[
                {'barcode': p_ok.barcode, 'quantity': 2},
                {'barcode': p_bad.barcode, 'quantity': 2}])
        statuses = {r['barcode']: r['status'] for r in res['results']}
        self.assertEqual(statuses[p_bad.barcode], 'error')
        self.assertEqual(statuses[p_ok.barcode], 'updated')

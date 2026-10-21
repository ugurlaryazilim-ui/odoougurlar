# -*- coding: utf-8 -*-
"""Nebim stok sync: raflı (alt lokasyonlu) üründe mevcut miktar doğru okunmalı."""
from unittest import mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.stock.models.stock_quant import StockQuant


@tagged('post_install', '-at_install')
class TestStockProcessorShelf(TransactionCase):

    def setUp(self):
        super().setUp()
        self.proc = self.env['odoougurlar.stock.processor']
        self.wh = self.env['stock.warehouse'].create({
            'name': 'G7 Test Depo', 'code': 'ZG7', 'nebim_warehouse_code': 'ZG7',
        })
        self.root = self.wh.lot_stock_id
        self.product = self.env['product.product'].create({
            'name': 'G7 Ürün', 'is_storable': True, 'barcode': '8690000007001',
        })
        self.Quant = self.env['stock.quant'].sudo()
        # NEDEN: sync chunk sonrası cr.commit() yapar; TransactionCase içinde commit taklit edilir.
        patcher = mock.patch.object(self.env.cr, 'commit', lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _shelf(self, code):
        return self.env['stock.location'].create({
            'name': code, 'location_id': self.root.id, 'usage': 'internal',
        })

    def _put(self, location, qty):
        self.Quant._update_available_quantity(self.product, location, qty)

    def _qty(self, location):
        quants = self.Quant.search([('product_id', '=', self.product.id),
                                    ('location_id', '=', location.id)])
        return sum(quants.mapped('quantity'))

    def _sync(self, qty, wh_code='ZG7'):
        """Süreci çalıştırır; (istatistik, stock.quant.write çağrı sayısı) döndürür."""
        data = [{'Barcode1': self.product.barcode, 'WarehouseCode': wh_code, 'Inventory': qty}]
        with mock.patch.object(StockQuant, 'write', autospec=True, side_effect=StockQuant.write) as w:
            stats = self.proc.process_stock_prices(data)
        return stats, w.call_count

    def test_single_root_location_unchanged(self):
        self._put(self.root, 5)
        stats, writes = self._sync(5)
        self.assertEqual(writes, 0)
        self.assertEqual(stats['skipped'], 1)
        stats, _writes = self._sync(8)
        self.assertEqual(self._qty(self.root), 8)
        self.assertEqual(stats['updated'], 1)

    def test_single_root_location_created_when_missing(self):
        stats, _writes = self._sync(4)
        self.assertEqual(self._qty(self.root), 4)
        self.assertEqual(stats['updated'], 1)

    def test_shelf_same_qty_no_write(self):
        shelf = self._shelf('R1')
        self._put(shelf, 7)
        stats, writes = self._sync(7)
        self.assertEqual(writes, 0)
        self.assertEqual(stats['updated'], 0)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(self._qty(shelf), 7)

    def test_shelf_different_qty_updates_shelf_only(self):
        shelf = self._shelf('R1')
        self._put(shelf, 7)
        stats, _writes = self._sync(3)
        self.assertEqual(stats['updated'], 1)
        self.assertEqual(self._qty(shelf), 3)
        self.assertEqual(self._qty(self.root), 0)

    def test_root_and_shelf_total_compared(self):
        shelf = self._shelf('R1')
        self._put(self.root, 2)
        self._put(shelf, 5)
        _stats, writes = self._sync(7)  # toplam zaten 7
        self.assertEqual(writes, 0)
        self._sync(10)  # fark rafa yazılır, kök korunur
        self.assertEqual(self._qty(self.root), 2)
        self.assertEqual(self._qty(shelf), 8)

    def test_multiple_shelf_quants_same_total_no_write(self):
        s1, s2 = self._shelf('R1'), self._shelf('R2')
        self._put(s1, 3)
        self._put(s2, 4)
        _stats, writes = self._sync(7)
        self.assertEqual(writes, 0)

    def test_multiple_shelf_quants_different_total_not_overwritten(self):
        s1, s2 = self._shelf('R1'), self._shelf('R2')
        self._put(s1, 3)
        self._put(s2, 4)
        with self.assertLogs('odoo.addons.odoougurlar.processors.stock_processor', 'WARNING') as logs:
            stats, writes = self._sync(10)
        self.assertEqual(writes, 0)
        self.assertEqual(stats['updated'], 0)
        self.assertEqual((self._qty(s1), self._qty(s2)), (3, 4))
        self.assertTrue(any('birden çok raf' in line for line in logs.output))

    def test_skip_warehouse_002_still_skipped(self):
        self.wh.code = '002'
        shelf = self._shelf('R1')
        self._put(shelf, 7)
        stats, writes = self._sync(1, wh_code='002')
        self.assertEqual(writes, 0)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(self._qty(shelf), 7)

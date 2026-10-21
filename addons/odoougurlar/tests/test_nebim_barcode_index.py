# -*- coding: utf-8 -*-
"""nebim_barcode indeksleri, toplu pazaryeri barkod eşleştirme, stok cron'u erken çıkış / parmak izi,
maliyet sync sorgusu (denetim H1)."""
from unittest import mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.odoougurlar.processors import stock_processor


@tagged('post_install', '-at_install')
class TestNebimBarcodeIndex(TransactionCase):

    def test_indexes_exist(self):
        self.env.cr.execute("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = 'product_product' AND indexdef ILIKE '%nebim_barcode%'
        """)
        defs = ' '.join(row[1] for row in self.env.cr.fetchall())
        self.assertIn('gin (string_to_array(replace((nebim_barcode)::text', defs.lower().replace('"', ''))
        self.assertIn('btree (nebim_barcode)', defs)

    def test_list_lookup_uses_expression_index(self):
        """Çok küçük tabloda planner seq scan seçebilir; seqscan kapatılarak ifadenin indeksle
        eşleştiği (indeksin kullanılabildiği) gösterilir. Sorgu metni yardımcının gerçek sorgusundan alınır."""
        Product = self.env['product.product']
        captured = []
        real_execute = self.env.cr.execute

        def spy(query, params=None, *a, **kw):
            captured.append((query, params))
            return real_execute(query, params, *a, **kw)

        with mock.patch.object(self.env.cr, 'execute', spy):
            Product._search_nebim_barcodes(['8690000000011'])
        query, params = next(c for c in captured if 'nebim_barcode' in c[0])
        self.env.cr.execute('SET LOCAL enable_seqscan = off')
        self.env.cr.execute('EXPLAIN ' + query, params)
        plan = '\n'.join(row[0] for row in self.env.cr.fetchall())
        self.assertIn('nebim_barcode_list_idx', plan, plan)


@tagged('post_install', '-at_install')
class TestMarketplaceBarcodeBatch(TransactionCase):

    def setUp(self):
        super().setUp()
        self.P = self.env['product.product']

    def test_priority_barcode_then_nebim_then_default_code(self):
        by_barcode = self.P.create({'name': 'B', 'barcode': 'H1-X1'})
        by_nebim = self.P.create({'name': 'N', 'nebim_barcode': 'H1-X1, H1-X2 ,H1-X3'})
        by_code = self.P.create({'name': 'C', 'default_code': 'H1-X4'})
        res = self.P.batch_find_by_marketplace_barcodes(['H1-X1', 'H1-X2', 'H1-X3', 'H1-X4', 'H1-YOK'])
        self.assertEqual(res['H1-X1'], by_barcode)  # barcode, nebim_barcode'dan önce
        self.assertEqual(res['H1-X2'], by_nebim)
        self.assertEqual(res['H1-X3'], by_nebim)  # boşluklu liste elemanı
        self.assertEqual(res['H1-X4'], by_code)
        self.assertFalse(res['H1-YOK'])

    def test_nebim_substring_never_matches(self):
        self.P.create({'name': 'N', 'nebim_barcode': 'H1-AB123,H1-ZZ'})
        self.assertFalse(self.P.find_by_marketplace_barcode('H1-AB12'))

    def test_normalized_match_and_single_equals_batch(self):
        target = self.P.create({'name': 'T', 'default_code': 'H1T2-0003-0006-34/30'})
        code = 'h1t2-0003000634-30'
        self.assertEqual(self.P.find_by_marketplace_barcode(code), target)
        self.assertEqual(self.P.batch_find_by_marketplace_barcodes([code])[code], target)

    def test_substitute_returned_and_batch_uses_few_queries(self):
        real = self.P.create({'name': 'Gerçek', 'barcode': 'H1-REAL'})
        pack = self.P.create({'name': 'Paket', 'barcode': 'H1-PACK', 'substitute_product_id': real.id})
        codes = ['H1-PACK'] + ['H1-NONE%d' % i for i in range(30)]
        with self.assertQueryCount(__system__=18):
            res = self.P.batch_find_by_marketplace_barcodes(codes)
        self.assertEqual(res['H1-PACK'], real)
        self.assertNotEqual(res['H1-PACK'], pack)

    def test_empty_code(self):
        self.assertFalse(self.P.find_by_marketplace_barcode(''))
        self.assertEqual(self.P.batch_find_by_marketplace_barcodes(['', None]), {})


@tagged('post_install', '-at_install')
class TestStockCronEarlyExit(TransactionCase):

    def setUp(self):
        super().setUp()
        self.proc = self.env['odoougurlar.stock.processor']
        wh = self.env['stock.warehouse'].create({'name': 'H1 Depo', 'code': 'ZH1', 'nebim_warehouse_code': 'ZH1'})
        self.skip_wh = self.env['stock.warehouse'].create({'name': 'H1 İnternet', 'code': '002'})
        self.product = self.env['product.product'].create(
            {'name': 'H1 Ürün', 'is_storable': True, 'barcode': '8690000001001'})
        self.row = {'Barcode1': self.product.barcode, 'WarehouseCode': wh.code, 'Inventory': 3}
        self.row_002 = dict(self.row, WarehouseCode='002')
        # NEDEN: işlemci chunk sonrası cr.commit() yapar; TransactionCase içinde taklit edilir.
        patcher = mock.patch.object(self.env.cr, 'commit', lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        stock_processor._FINGERPRINTS.clear()
        self.addCleanup(stock_processor._FINGERPRINTS.clear)

    def test_only_skip_warehouse_rows_exit_before_cache(self):
        with mock.patch.object(type(self.proc), '_init_stock_cache') as init:
            stats = self.proc.process_stock_prices([self.row_002] * 50)
        init.assert_not_called()
        self.assertEqual((stats['skipped_warehouse'], stats['skipped_same'], stats['skipped']), (50, 0, 50))
        self.assertEqual(stats['processed'], 50)

    def test_skip_rows_removed_before_cache_load(self):
        with mock.patch.object(type(self.proc), '_init_stock_cache', autospec=True,
                               side_effect=type(self.proc)._init_stock_cache) as init:
            stats = self.proc.process_stock_prices([self.row, self.row_002])
        passed = init.call_args.kwargs['stock_data']
        self.assertEqual([r['WarehouseCode'] for r in passed], ['ZH1'])
        self.assertEqual((stats['updated'], stats['skipped_warehouse']), (1, 1))

    def test_same_counter_separate_from_warehouse(self):
        self.proc.process_stock_prices([self.row])
        stats = self.proc.process_stock_prices([self.row, self.row_002])
        self.assertEqual((stats['skipped_same'], stats['skipped_warehouse'], stats['updated']), (1, 1, 0))

    def test_fingerprint_skips_identical_result_until_expiry(self):
        key = 'stock_sp_test'
        first = self.proc.process_stock_prices([self.row, self.row_002], fingerprint_key=key)
        self.assertEqual(first['updated'], 1)
        with mock.patch.object(type(self.proc), '_init_stock_cache') as init:
            second = self.proc.process_stock_prices([self.row_002, self.row], fingerprint_key=key)  # sıra önemsiz
        init.assert_not_called()
        self.assertTrue(second['fingerprint_hit'])
        self.assertEqual(second['skipped_same'], 1)
        # Değişen veri işlenir
        changed = self.proc.process_stock_prices([dict(self.row, Inventory=9)], fingerprint_key=key)
        self.assertEqual(changed['updated'], 1)
        # Süre dolunca aynı veri yine işlenir (Odoo tarafı sapmasını düzeltmek için)
        db_key = (self.env.cr.dbname, key)
        digest, stamp = stock_processor._FINGERPRINTS[db_key]
        stock_processor._FINGERPRINTS[db_key] = (digest, stamp - stock_processor.FINGERPRINT_MAX_AGE - 1)
        with mock.patch.object(type(self.proc), '_init_stock_cache',
                               autospec=True, side_effect=type(self.proc)._init_stock_cache) as init:
            again = self.proc.process_stock_prices([dict(self.row, Inventory=9)], fingerprint_key=key)
        init.assert_called_once()
        self.assertFalse(again.get('fingerprint_hit'))

    def test_fingerprint_not_stored_after_failure(self):
        key = 'stock_sp_fail'
        self.proc.process_stock_prices([self.row])  # quant oluşur; sonraki çalışma güncelleme yazar
        with mock.patch.object(type(self.env['stock.quant']), 'write', side_effect=RuntimeError('x')):
            self.proc.process_stock_prices([dict(self.row, Inventory=8)], fingerprint_key=key)
        self.assertNotIn((self.env.cr.dbname, key), stock_processor._FINGERPRINTS)


@tagged('post_install', '-at_install')
class TestCostSyncLookup(TransactionCase):

    def test_costs_matched_by_barcode_sku_and_nebim_list(self):
        P = self.env['product.product']
        a = P.create({'name': 'A', 'barcode': 'H1-C1'})
        b = P.create({'name': 'B', 'default_code': 'H1-SKU'})
        c = P.create({'name': 'C', 'nebim_barcode': 'H1-N1, H1-N2'})
        rows = [
            {'Barcode1': 'H1-C1', 'Price2': '10'},
            {'ItemSku': 'H1-SKU', 'Price2': '20'},
            {'Barcode1': 'H1-N2', 'Price2': '30'},
        ]
        self.env['ir.config_parameter'].sudo().set_param('odoougurlar.nebim_sync_cost_enabled', 'True')
        connector = type(self.env['odoougurlar.nebim.connector'])
        with mock.patch.object(connector, 'run_proc', return_value=rows), \
                mock.patch.object(connector, '_get_sp_name', return_value='sp'), \
                mock.patch.object(self.env.cr, 'commit', lambda: None):
            self.env['odoougurlar.nebim.service'].sync_product_costs()
        self.assertEqual((a.standard_price, b.standard_price, c.standard_price), (10, 20, 30))

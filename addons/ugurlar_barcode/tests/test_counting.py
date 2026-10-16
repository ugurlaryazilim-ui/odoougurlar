"""G2 / KK-A2.1, A2.2, A3.1, RG-5: sayım (count_save)."""
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import counting_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestCounting(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Sayım Ürünü', 'CN-1')
        cls.prod_other = cls._new_product('Sayım Başka Ürün', 'CN-2')
        cls.shelf = cls._new_shelf('CN-RAF', 'CN-RAF-1')
        cls.shelf_neg = cls._new_shelf('CN-RAF-NEG', 'CN-RAF-2')
        # Nebim deposu (sayılmayan depo)
        cls.nebim_wh = cls._new_warehouse('Sayim Nebim Depo', 'SNB')

    def setUp(self):
        super().setUp()
        self._patch_request(counting_api)
        self.ctl = counting_api.CountingApiController()

    def _count(self, qty, product=None):
        product = product or self.prod
        return self.ctl.count_save(
            shelf_barcode='CN-RAF-1', items=[{'barcode': product.barcode, 'quantity': qty}])

    def _moves_into(self, product, location):
        return self.env['stock.move'].search([
            ('product_id', '=', product.id), ('state', '=', 'done'),
            ('location_dest_id', '=', location.id)])

    def _moves_from(self, product, location):
        return self.env['stock.move'].search([
            ('product_id', '=', product.id), ('state', '=', 'done'),
            ('location_id', '=', location.id)])

    # ─── KK-A2.1 ───────────────────────────────────────
    def test_a21_negative_in_counted_warehouse_corrected_by_stock_move(self):
        """Sayılan depodaki negatifler stock.move ile sıfırlanır; Nebim deposuna dokunulmaz."""
        nebim_stock = self.nebim_wh.lot_stock_id
        self._add_stock(self.prod, self.shelf_neg, -3)      # sayılan depo, başka raf
        self._add_stock(self.prod, self.stock, -2)          # sayılan depo, kök stok lokasyonu
        self._add_stock(self.prod, nebim_stock, -4)         # Nebim deposu
        self._add_stock(self.prod_other, self.shelf_neg, -1)  # sayılmayan ürün
        self.assertEqual(self._qty(self.prod, self.shelf_neg), -3)

        res = self._count(5)
        self.assertTrue(res.get('success'), res)

        self.assertEqual(self._qty(self.prod, self.shelf), 5, 'sayılan raf')
        self.assertEqual(self._qty(self.prod, self.shelf_neg), 0, 'negatif raf sıfırlanmalı')
        self.assertEqual(self._qty(self.prod, self.stock), 0, 'kök stok negatifi sıfırlanmalı')

        # izlenebilirlik: düzeltme tamamlanmış stock.move olarak kayıtlı (silinen quant değil)
        fix_shelf = self._moves_into(self.prod, self.shelf_neg)
        fix_root = self._moves_into(self.prod, self.stock)
        self.assertEqual(len(fix_shelf), 1, 'negatif raf için tek düzeltme hareketi')
        self.assertEqual(fix_shelf.quantity, 3)
        self.assertEqual(len(fix_root), 1, 'kök stok için tek düzeltme hareketi')
        self.assertEqual(fix_root.quantity, 2)
        self.assertIn('Sayım', fix_shelf.origin or '')

        # Nebim deposu ve sayılmayan ürün dokunulmaz
        self.assertEqual(self._qty(self.prod, nebim_stock, child=True), -4)
        self.assertFalse(self._moves_into(self.prod, nebim_stock))
        self.assertEqual(self._qty(self.prod_other, self.shelf_neg), -1)

    def test_a21_adjustment_operation_record_kept(self):
        """Düzeltme için count_adjustment operasyon kaydı yazılmaya devam eder."""
        self._add_stock(self.prod, self.shelf_neg, -3)
        res = self._count(5)
        self.assertTrue(res.get('success'), res)
        ops = self.env['ugurlar.barcode.operation'].search([
            ('operation_type', '=', 'count_adjustment'),
            ('product_id', '=', self.prod.id),
            ('location_id', '=', self.shelf_neg.id)])
        self.assertEqual(len(ops), 1)
        self.assertGreaterEqual(res.get('adjustments', 0), 1)

    # ─── KK-A2.2 / RG-5 ────────────────────────────────
    def test_a22_no_negative_no_extra_move(self):
        """Negatif quant yoksa yalnız sayım hareketi oluşur, düzeltme hareketi oluşmaz."""
        res = self._count(5)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf), 5)
        moves = self.env['stock.move'].search([('product_id', '=', self.prod.id), ('state', '=', 'done')])
        self.assertEqual(len(moves), 1, 'yalnız sayım farkı hareketi')
        self.assertEqual(moves.location_dest_id, self.shelf)
        self.assertEqual(res.get('adjustments'), 0)

    def test_rg5_normal_count_result_and_move_count(self):
        """RG-5: negatifsiz normal sayım; artış, azalış ve değişmeme sonuçları."""
        self._add_stock(self.prod, self.shelf, 4)
        # aynı sayı: hareket yok
        res = self._count(4)
        self.assertTrue(res.get('success'), res)
        self.assertFalse(self.env['stock.move'].search([
            ('product_id', '=', self.prod.id), ('state', '=', 'done'),
            ('origin', 'ilike', 'Sayım')]))
        self.assertEqual(self._qty(self.prod, self.shelf), 4)
        # fazla say: tek +3 hareketi
        self._count(7)
        self.assertEqual(self._qty(self.prod, self.shelf), 7)
        plus = self._moves_into(self.prod, self.shelf).filtered(lambda m: m.origin and 'Sayım' in m.origin)
        self.assertEqual(plus.mapped('quantity'), [3])
        # eksik say: tek -5 hareketi
        self._count(2)
        self.assertEqual(self._qty(self.prod, self.shelf), 2)
        minus = self._moves_from(self.prod, self.shelf).filtered(lambda m: m.origin and 'Sayım' in m.origin)
        self.assertEqual(minus.mapped('quantity'), [5])
        # sayım oturumu ve operasyon kayıtları
        ops = self.env['ugurlar.barcode.operation'].search([
            ('operation_type', '=', 'counting'), ('product_id', '=', self.prod.id)])
        self.assertEqual(len(ops), 3)

    def test_count_zero_clears_shelf(self):
        """Koruma: 0 sayılırsa raf boşalır."""
        self._add_stock(self.prod, self.shelf, 3)
        res = self._count(0)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf), 0)

    # ─── KK-A3.1 ───────────────────────────────────────
    def _duplicate_quants(self, a=3, b=2):
        quants = self.env['stock.quant'].sudo().create([
            {'product_id': self.prod.id, 'location_id': self.shelf.id, 'quantity': a},
            {'product_id': self.prod.id, 'location_id': self.shelf.id, 'quantity': b},
        ])
        found = self.env['stock.quant'].search([
            ('product_id', '=', self.prod.id), ('location_id', '=', self.shelf.id)])
        self.assertEqual(len(found), 2, 'ön koşul: aynı raf/üründe iki quant')
        self.assertEqual(sum(found.mapped('quantity')), a + b)
        return quants

    def test_a31_duplicate_quants_count_equal_makes_no_move(self):
        """Raf iki quant (3+2); 5 sayılırsa miktar 5 kalır, fark hareketi oluşmaz."""
        self._duplicate_quants()
        res = self._count(5)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf), 5)
        self.assertFalse(self.env['stock.move'].search([
            ('product_id', '=', self.prod.id), ('state', '=', 'done')]),
            'fark hareketi oluşmamalı')

    def test_a31_duplicate_quants_count_lower_one_minus_move(self):
        """Raf iki quant (3+2); 4 sayılırsa raf 4 olur ve tek -1 hareketi oluşur."""
        self._duplicate_quants()
        res = self._count(4)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf), 4)
        moves = self.env['stock.move'].search([
            ('product_id', '=', self.prod.id), ('state', '=', 'done')])
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.quantity, 1)
        self.assertEqual(moves.location_id, self.shelf)

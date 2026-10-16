"""G3 / KK-A4.1 - A4.4, RG-4: toplu raf işlemleri (Rafı Boşalt / Rafı Taşı / tekli taşıma)."""
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import shelf_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestShelfBulk(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod_x = cls._new_product('Raf Ürünü X', 'SB-X')
        cls.prod_y = cls._new_product('Raf Ürünü Y', 'SB-Y')
        cls.src = cls._new_shelf('SB-KAYNAK', 'SB-RAF-S')
        cls.dst = cls._new_shelf('SB-HEDEF', 'SB-RAF-D')
        # Aynı lokasyona iki farklı yazımla ulaşılır: barkod 'SB-RAF-AL', ad 'SB-ALIAS-ADI'
        cls.alias = cls._new_shelf('SB-ALIAS-ADI', 'SB-RAF-AL')

    def setUp(self):
        super().setUp()
        self._patch_request(shelf_api)
        self.ctl = shelf_api.ShelfApiController()

    # ─── yardımcılar ───────────────────────────────────
    def _reserve_x(self, qty=2, in_route=True):
        """Açık rotadaki bir sipariş X'ten `qty` adedi kaynak raftan rezerve eder."""
        picking = self._picking(self.prod_x, qty)
        self.assertEqual(picking.move_ids.quantity, qty, 'ön koşul: rezerv tam')
        if in_route:
            self._route(picking)
        return picking

    def _x_y_on_source(self):
        self._add_stock(self.prod_x, self.src, 5)
        self._add_stock(self.prod_y, self.src, 3)

    def _move_count(self, *products):
        return self.env['stock.move'].search_count([('product_id', 'in', [p.id for p in products])])

    def _ops(self, op_type, location):
        return self.env['ugurlar.barcode.operation'].search([
            ('operation_type', '=', op_type), ('location_id', '=', location.id)])

    # ─── KK-A4.1 ───────────────────────────────────────
    def test_a41_clear_all_skips_reserved_product(self):
        self._x_y_on_source()
        picking = self._reserve_x(2)

        res = self.ctl.shelf_clear_all(shelf_barcode='SB-RAF-S')

        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod_x, self.src), 5, 'X tamamen atlanmalı (kısmi çıkarma yok)')
        self.assertEqual(self._qty(self.prod_y, self.src), 0, 'Y raftan çıkmalı')
        self.assertEqual(res.get('skipped_count'), 1, res)
        skipped = res.get('skipped') or []
        self.assertEqual(len(skipped), 1, res)
        self.assertEqual(skipped[0].get('product_name'), self.prod_x.name)
        self.assertEqual(skipped[0].get('barcode'), 'SB-X')
        reason = skipped[0].get('reason') or ''
        self.assertIn('rezerv', reason.lower())
        self.assertIn('2', reason)
        # operasyon kaydı yalnız Y için
        self.assertEqual(self._ops('remove', self.src).mapped('product_id'), self.prod_y)
        # siparişin rezervi değişmez
        picking.move_ids.invalidate_recordset()
        self.assertEqual(picking.move_ids.quantity, 2)
        self.assertEqual(picking.state, 'assigned')

    def test_a41_clear_all_without_reservation_clears_everything(self):
        """RG-4: rezervsiz rafta Rafı Boşalt her şeyi çıkarır, sonuç alanları değişmez."""
        self._x_y_on_source()
        res = self.ctl.shelf_clear_all(shelf_barcode='SB-RAF-S')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res.get('cleared_count'), 2)
        self.assertEqual(res.get('total_quantity'), 8)
        self.assertEqual(self._qty(self.prod_x, self.src), 0)
        self.assertEqual(self._qty(self.prod_y, self.src), 0)
        self.assertEqual(len(self._ops('remove', self.src)), 2)
        # atlanan yok (alan eklendiyse 0)
        self.assertFalse(res.get('skipped'))
        self.assertFalse(res.get('skipped_count'))

    # ─── KK-A4.2 ───────────────────────────────────────
    def test_a42_move_all_reports_skipped(self):
        self._x_y_on_source()
        self._reserve_x(2)

        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-S', target_barcode='SB-RAF-D')

        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod_y, self.dst), 3)
        self.assertEqual(self._qty(self.prod_y, self.src), 0)
        self.assertGreaterEqual(res.get('skipped_count', 0), 1, res)
        skipped = res.get('skipped') or []
        self.assertEqual([s.get('barcode') for s in skipped], ['SB-X'], res)
        self.assertEqual(skipped[0].get('product_name'), self.prod_x.name)
        self.assertTrue(skipped[0].get('reason'), 'neden metni dolu olmalı')
        self.assertEqual(res.get('moved_count'), 1)

    def test_b2_move_all_skip_reason_names_reservation(self):
        """Test raporu B2: atlama nedeni rezervi söyler, 'Yetersiz stok / İstenen' demez."""
        self._x_y_on_source()
        self._reserve_x(2)
        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-S', target_barcode='SB-RAF-D')
        reason = (res.get('skipped') or [{}])[0].get('reason', '')
        self.assertIn('2 adet rezerve', reason, res)
        self.assertIn('taşınmadı', reason, res)
        self.assertNotIn('İstenen', reason, res)
        self.assertNotIn('Yetersiz', reason, res)
        self.assertIn('rezerve', res.get('message', ''), res)

    def test_rg4_move_all_without_reservation_moves_everything(self):
        """RG-4: rezervsiz rafta Rafı Taşı her şeyi taşır."""
        self._x_y_on_source()
        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-S', target_barcode='SB-RAF-D')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res.get('moved_count'), 2)
        self.assertEqual(res.get('total_quantity'), 8)
        self.assertEqual((self._qty(self.prod_x, self.src), self._qty(self.prod_x, self.dst)), (0, 5))
        self.assertEqual((self._qty(self.prod_y, self.src), self._qty(self.prod_y, self.dst)), (0, 3))
        self.assertFalse(res.get('skipped'))
        self.assertFalse(res.get('skipped_count'))

    # ─── KK-A4.3 ───────────────────────────────────────
    def test_a43_two_barcodes_same_location_rejected(self):
        """Farklı iki yazım aynı lokasyona çözülüyor: tekli ve toplu taşıma hata verir, hareket yok."""
        self._add_stock(self.prod_x, self.alias, 4)
        self.assertEqual(self.api._find_location('SB-RAF-AL'), self.alias)   # barkod
        self.assertEqual(self.api._find_location('SB-ALIAS-ADI'), self.alias)  # ad
        before = self._move_count(self.prod_x)

        res = self.ctl.shelf_transfer(
            product_barcode='SB-X', source_shelf_barcode='SB-RAF-AL',
            target_shelf_barcode='SB-ALIAS-ADI', quantity=1)
        self.assertIn('error', res, res)

        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-AL', target_barcode='SB-ALIAS-ADI')
        self.assertIn('error', res, res)

        self.assertEqual(self._move_count(self.prod_x), before, 'hiç stock.move oluşmamalı')
        self.assertEqual(self._qty(self.prod_x, self.alias), 4)

    def test_a43_same_barcode_twice_rejected(self):
        """Aynı barkod iki kez okutuldu: hata, hareket yok (koruma)."""
        self._add_stock(self.prod_x, self.src, 4)
        before = self._move_count(self.prod_x)
        res = self.ctl.shelf_transfer(
            product_barcode='SB-X', source_shelf_barcode='SB-RAF-S',
            target_shelf_barcode='SB-RAF-S', quantity=1)
        self.assertIn('error', res, res)
        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-S', target_barcode='SB-RAF-S')
        self.assertIn('error', res, res)
        self.assertEqual(self._move_count(self.prod_x), before)

    # ─── KK-A4.4 ───────────────────────────────────────
    def test_a44_single_ops_limited_to_free_quantity(self):
        """Rafta 5, rotada 2 rezerve: tekli taşıma / kaldırma 3'e kadar serbest, 4 hata."""
        self._add_stock(self.prod_x, self.src, 5)
        picking = self._reserve_x(2)
        before = self._move_count(self.prod_x)

        res = self.ctl.shelf_transfer(
            product_barcode='SB-X', source_shelf_barcode='SB-RAF-S',
            target_shelf_barcode='SB-RAF-D', quantity=4)
        self.assertIn('error', res, res)
        res = self.ctl.remove_from_shelf(product_barcode='SB-X', shelf_barcode='SB-RAF-S', quantity=4)
        self.assertIn('error', res, res)
        self.assertEqual(self._move_count(self.prod_x), before, 'hata sonrası hareket oluşmamalı')

        res = self.ctl.shelf_transfer(
            product_barcode='SB-X', source_shelf_barcode='SB-RAF-S',
            target_shelf_barcode='SB-RAF-D', quantity=3)
        self.assertTrue(res.get('success'), res)
        self.assertEqual((self._qty(self.prod_x, self.src), self._qty(self.prod_x, self.dst)), (2, 3))

        # kalan 2 adet tamamen rezerve: ne taşınır ne kaldırılır
        res = self.ctl.remove_from_shelf(product_barcode='SB-X', shelf_barcode='SB-RAF-S', quantity=1)
        self.assertIn('error', res, res)
        picking.move_ids.invalidate_recordset()
        self.assertEqual(picking.move_ids.quantity, 2, 'siparişin rezervi değişmemeli')
        self.assertEqual(picking.state, 'assigned')

    def test_a44_remove_free_part_allowed(self):
        self._add_stock(self.prod_x, self.src, 5)
        self._reserve_x(2)
        res = self.ctl.remove_from_shelf(product_barcode='SB-X', shelf_barcode='SB-RAF-S', quantity=3)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod_x, self.src), 2)

    def test_a44_move_all_never_moves_reserved_quantity(self):
        """Rafı Taşı: rezerve 2 adet hedefe geçmez; ürün tam taşınamadıysa skipped'te yer alır."""
        self._add_stock(self.prod_x, self.src, 5)
        picking = self._reserve_x(2)

        res = self.ctl.shelf_move_all(source_barcode='SB-RAF-S', target_barcode='SB-RAF-D')

        self.assertGreaterEqual(self._qty(self.prod_x, self.src), 2, 'rezerve 2 adet kaynakta kalmalı')
        self.assertLessEqual(self._qty(self.prod_x, self.dst), 3)
        self.assertIn('SB-X', [s.get('barcode') for s in (res.get('skipped') or [])], res)
        picking.move_ids.invalidate_recordset()
        self.assertEqual(picking.move_ids.quantity, 2)
        self.assertEqual(picking.state, 'assigned')

    def test_a44_clear_all_skips_reserved_product_completely(self):
        self._add_stock(self.prod_x, self.src, 5)
        picking = self._reserve_x(2)
        res = self.ctl.shelf_clear_all(shelf_barcode='SB-RAF-S')
        self.assertEqual(self._qty(self.prod_x, self.src), 5)
        self.assertIn('SB-X', [s.get('barcode') for s in (res.get('skipped') or [])], res)
        picking.move_ids.invalidate_recordset()
        self.assertEqual(picking.move_ids.quantity, 2)

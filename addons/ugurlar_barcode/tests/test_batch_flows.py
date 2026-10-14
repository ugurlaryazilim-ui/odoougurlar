"""Rota toplama / paketleme doğrulama akışları (gerçek stok hareketleriyle)."""
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.ugurlar_barcode.controllers import base_api
from odoo.addons.ugurlar_barcode.controllers.base_api import BarcodeApiBase


@tagged('post_install', '-at_install')
class TestBatchFlows(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock = cls.wh.lot_stock_id
        Loc = cls.env['stock.location']
        cls.shelf_a = Loc.create({'name': 'T-A', 'location_id': cls.stock.id, 'usage': 'internal'})
        cls.shelf_b = Loc.create({'name': 'T-B', 'location_id': cls.stock.id, 'usage': 'internal'})
        cls.product = cls.env['product.product'].create({
            'name': 'Test Gömlek', 'type': 'consu', 'is_storable': True, 'barcode': 'TST-1'})
        cls.out_type = cls.wh.out_type_id
        cls.customer = cls.env['res.partner'].create({'name': 'Test Müşteri'})
        cls.api = BarcodeApiBase()

    def setUp(self):
        super().setUp()
        patcher = patch.object(base_api, 'request', SimpleNamespace(env=self.env))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stock(self, location, qty):
        self.env['stock.quant']._update_available_quantity(self.product, location, qty)

    def _picking(self, demand):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'partner_id': self.customer.id,
            'location_id': self.stock.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'move_ids': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': demand,
                'product_uom': self.product.uom_id.id,
                'location_id': self.stock.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        # Rota oluşturma (FAZ 5) gibi: personel okutarak dolduracak
        for move in picking.move_ids:
            move.quantity = 0
        return picking

    def _done_qty(self, picking):
        return sum(picking.move_ids.filtered(lambda m: m.state == 'done').mapped('quantity'))

    def test_partial_with_skip_creates_backorder(self):
        """3'ten 1 toplandı + Eksik → 1 sevk, 2 için bekleyen sevkiyat."""
        self._stock(self.stock, 10)
        picking = self._picking(3)
        move = picking.move_ids
        move.write({'wave_collected_qty': 1, 'wave_skipped': True})

        self.assertFalse(self.api._missing_moves(picking))
        _total, partial = self.api._apply_collected_quantities(picking)
        self.assertTrue(partial)
        self.assertTrue(self.api._safe_validate_picking(picking, backorder=True))

        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._done_qty(picking), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(len(backorder), 1, 'kalan için bekleyen sevkiyat açılmalı')
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)
        # copy=False: backorder hareketi toplama / eksik durumunu devralmaz
        self.assertEqual(backorder.move_ids.wave_collected_qty, 0)
        self.assertFalse(backorder.move_ids.wave_skipped)

    def test_missing_without_skip_blocks(self):
        """Eksik işaretlenmemiş eksik ürün → tamamlama listesi döner."""
        self._stock(self.stock, 10)
        picking = self._picking(3)
        picking.move_ids.wave_collected_qty = 1
        missing = self.api._missing_moves(picking)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['collected_qty'], 1)
        self.assertIn('missing', self.api._missing_error(missing))

    def test_two_shelves_not_doubled(self):
        """İki rafa bölünmüş ürün: önceden her move line'a tüm talep yazılıp 2 katı sevk ediliyordu."""
        self._stock(self.shelf_a, 1)
        self._stock(self.shelf_b, 1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'location_id': self.stock.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'move_ids': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2, 'product_uom': self.product.uom_id.id,
                'location_id': self.stock.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(len(picking.move_line_ids), 2)
        picking.move_ids.wave_collected_qty = 2

        _total, partial = self.api._apply_collected_quantities(picking)
        self.assertFalse(partial)
        self.assertTrue(self.api._safe_validate_picking(picking))
        self.assertEqual(self._done_qty(picking), 2)
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', picking.id)]))

    def test_full_collect_no_backorder(self):
        self._stock(self.stock, 5)
        picking = self._picking(2)
        picking.move_ids.wave_collected_qty = 2
        _total, partial = self.api._apply_collected_quantities(picking)
        self.assertTrue(self.api._safe_validate_picking(picking, backorder=partial))
        self.assertEqual(self._done_qty(picking), 2)
        self.assertEqual(self.product.qty_available, 3)

    def test_copy_does_not_carry_flags(self):
        self._stock(self.stock, 5)
        picking = self._picking(1)
        picking.write({'packing_done': True, 'invoice_done': True, 'label_printed': True})
        picking.move_ids.write({'wave_collected_qty': 1, 'packing_scanned_qty': 1})
        copy = picking.copy()
        self.assertFalse(copy.packing_done or copy.invoice_done or copy.label_printed)
        self.assertEqual(copy.move_ids.wave_collected_qty, 0)
        self.assertEqual(copy.move_ids.packing_scanned_qty, 0)

    def test_batch_membership_and_cleanup(self):
        """Rota değişince kalıcı liste eşitlenir; biten / boş rota temizlikte kapanır."""
        self._stock(self.stock, 5)
        picking = self._picking(1)
        Batch = self.env['stock.picking.batch']
        b1 = Batch.create({'picking_type_id': self.out_type.id})
        b2 = Batch.create({'picking_type_id': self.out_type.id})
        picking.batch_id = b1
        self.assertIn(picking, b1.all_picking_ids)
        picking.batch_id = b2
        self.assertNotIn(picking, b1.all_picking_ids, 'eski rotadan çıkmalı')
        self.assertIn(picking, b2.all_picking_ids)

        # b1 artık boş → iptal; b2 açık siparişli → dokunulmaz
        old = '2026-01-01 00:00:00'
        (b1 | b2).write({'schedule_time': old, 'state': 'in_progress'})
        Batch._cron_cleanup_route_batches()
        self.assertEqual(b1.state, 'cancel')
        self.assertEqual(b2.state, 'in_progress')

        # b2'nin siparişi sevk edilince → tamamlandı
        picking.move_ids.quantity = 1
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        b2.write({'state': 'in_progress'})
        Batch._cron_cleanup_route_batches()
        self.assertEqual(b2.state, 'done')


@tagged('post_install', '-at_install')
class TestShelfStockMoves(TransactionCase):
    """Raf işlemleri: doğrudan quant yazımı yerine tamamlanmış stok hareketi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        Loc = cls.env['stock.location']
        cls.shelf_a = Loc.create({'name': 'S-A', 'location_id': cls.wh.lot_stock_id.id, 'usage': 'internal'})
        cls.shelf_b = Loc.create({'name': 'S-B', 'location_id': cls.wh.lot_stock_id.id, 'usage': 'internal'})
        cls.product = cls.env['product.product'].create({
            'name': 'Raf Ürünü', 'type': 'consu', 'is_storable': True, 'barcode': 'RAF-1'})
        cls.api = BarcodeApiBase()

    def setUp(self):
        super().setUp()
        patcher = patch.object(base_api, 'request', SimpleNamespace(env=self.env))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _qty(self, location):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', location.id)]).mapped('quantity'))

    def _moves(self, origin):
        return self.env['stock.move'].search([
            ('product_id', '=', self.product.id), ('origin', '=', origin), ('state', '=', 'done')])

    def test_putaway_and_remove_create_moves(self):
        self.assertEqual(self.api._safe_update_quant(self.product, self.shelf_a, 3, 'Mobil: Raflama'), 3)
        self.assertEqual(self._qty(self.shelf_a), 3)
        move = self._moves('Mobil: Raflama')
        self.assertEqual(len(move), 1)
        self.assertTrue(move.is_inventory)
        self.assertEqual(move.location_dest_id, self.shelf_a)

        self.assertEqual(self.api._safe_update_quant(self.product, self.shelf_a, -2, 'Mobil: Raftan Kaldırma'), 1)
        self.assertEqual(self._qty(self.shelf_a), 1)
        self.assertEqual(self._moves('Mobil: Raftan Kaldırma').location_id, self.shelf_a)

    def test_remove_more_than_shelf_clamps_to_zero(self):
        self.api._safe_update_quant(self.product, self.shelf_a, 2)
        self.assertEqual(self.api._safe_update_quant(self.product, self.shelf_a, -5), 0)
        self.assertEqual(self._qty(self.shelf_a), 0)

    def test_transfer_between_shelves(self):
        self.api._safe_update_quant(self.product, self.shelf_a, 4)
        ok, err = self.api._safe_move_quant(self.product, self.shelf_a, self.shelf_b, 3, 'Mobil: Raf Transferi')
        self.assertTrue(ok, err)
        self.assertEqual(self._qty(self.shelf_a), 1)
        self.assertEqual(self._qty(self.shelf_b), 3)
        move = self._moves('Mobil: Raf Transferi')
        self.assertFalse(move.is_inventory)
        self.assertEqual((move.location_id, move.location_dest_id), (self.shelf_a, self.shelf_b))
        # depo toplamı değişmez
        self.assertEqual(self.product.with_context(warehouse_id=self.wh.id).qty_available, 4)

    def test_transfer_insufficient_and_reserved(self):
        self.api._safe_update_quant(self.product, self.shelf_a, 2)
        ok, err = self.api._safe_move_quant(self.product, self.shelf_a, self.shelf_b, 5)
        self.assertFalse(ok)
        self.assertIn('Yetersiz', err)
        # 1 adedi siparişe ayrılmış: yalnız 1 taşınabilir
        out = self.env['stock.picking'].create({
            'picking_type_id': self.wh.out_type_id.id,
            'location_id': self.shelf_a.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'move_ids': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 1,
                'product_uom': self.product.uom_id.id, 'location_id': self.shelf_a.id,
                'location_dest_id': self.env.ref('stock.stock_location_customers').id})],
        })
        out.action_confirm()
        out.action_assign()
        ok, err = self.api._safe_move_quant(self.product, self.shelf_a, self.shelf_b, 2)
        self.assertFalse(ok)
        self.assertIn('siparişe ayrılmış', err)
        ok, _err = self.api._safe_move_quant(self.product, self.shelf_a, self.shelf_b, 1)
        self.assertTrue(ok)
        self.assertEqual(self._qty(self.shelf_a), 1)

    def test_missing_source_shelf(self):
        ok, err = self.api._safe_move_quant(self.product, self.shelf_a, self.shelf_b, 1)
        self.assertFalse(ok)
        self.assertIn('bulunamadı', err)


@tagged('post_install', '-at_install')
class TestShelfEndpoints(TransactionCase):
    """Mobil raf uç noktaları (istek katmanı dahil)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        Loc = cls.env['stock.location']
        cls.shelf_a = Loc.create({'name': 'E-A', 'barcode': 'RAF-EA', 'location_id': wh.lot_stock_id.id,
                                  'usage': 'internal'})
        cls.shelf_b = Loc.create({'name': 'E-B', 'barcode': 'RAF-EB', 'location_id': wh.lot_stock_id.id,
                                  'usage': 'internal'})
        cls.product = cls.env['product.product'].create({
            'name': 'Uç Ürün', 'type': 'consu', 'is_storable': True, 'barcode': 'UC-1'})

    def setUp(self):
        super().setUp()
        from odoo.addons.ugurlar_barcode.controllers import shelf_api
        fake = SimpleNamespace(env=self.env)
        for mod in (base_api, shelf_api):
            p = patch.object(mod, 'request', fake)
            p.start()
            self.addCleanup(p.stop)
        self.ctl = shelf_api.ShelfApiController()

    def _qty(self, location):
        return sum(self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', location.id)]).mapped('quantity'))

    def test_putaway_remove_transfer(self):
        res = self.ctl.putaway(product_barcode='UC-1', shelf_barcode='RAF-EA', quantity=5)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.shelf_a), 5)

        res = self.ctl.remove_from_shelf(product_barcode='UC-1', shelf_barcode='RAF-EA', quantity=9)
        self.assertIn('yeterli stok', res.get('error', ''))
        res = self.ctl.remove_from_shelf(product_barcode='UC-1', shelf_barcode='RAF-EA', quantity=1)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.shelf_a), 4)

        res = self.ctl.shelf_transfer(product_barcode='UC-1', source_shelf_barcode='RAF-EA',
                                      target_shelf_barcode='RAF-EB', quantity=3)
        self.assertTrue(res.get('success'), res)
        self.assertEqual((self._qty(self.shelf_a), self._qty(self.shelf_b)), (1, 3))

        res = self.ctl.putaway(product_barcode='UC-1', shelf_barcode='RAF-EA', quantity=-2)
        self.assertEqual(res.get('error'), 'Geçersiz miktar')
        moves = self.env['stock.move'].search([('product_id', '=', self.product.id), ('state', '=', 'done')])
        self.assertEqual(sorted(moves.mapped('origin')),
                         ['Mobil: Raf Transferi', 'Mobil: Raflama', 'Mobil: Raftan Kaldırma'])

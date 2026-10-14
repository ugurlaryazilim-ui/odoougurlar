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

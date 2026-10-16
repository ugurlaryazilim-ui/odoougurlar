"""G1 / KK-A1.2 - A1.5: gizli "Sipariş Toplama" uç noktalarının güvenliği.

Dışarıdan gözlenen davranış: yanıttaki `error` / `success` / `state` ve kayıtların durumu.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import picking_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestPickingApi(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('PA Ürün', 'PA-1')
        cls.prod_a = cls._new_product('PA Stoksuz A', 'PA-2')   # stok yok: rezerv 0
        cls.prod_b = cls._new_product('PA Stoksuz B', 'PA-3')
        cls.shelf = cls._new_shelf('PA-RAF', 'PA-RAF-1')

    def setUp(self):
        super().setUp()
        self._patch_request(picking_api)
        self.ctl = picking_api.PickingApiController()

    # ─── yardımcılar ───────────────────────────────────
    def _snapshot(self, picking):
        picking.invalidate_recordset()
        picking.move_ids.invalidate_recordset()
        return (
            picking.state,
            tuple(picking.move_ids.mapped('state')),
            tuple(picking.move_ids.mapped('quantity')),
            tuple(picking.move_ids.mapped('picked')),
            len(picking.move_line_ids),
            len(picking.backorder_ids),
        )

    def _incoming(self):
        return self._picking(
            self.prod, 2, picking_type=self.wh.in_type_id,
            src=self.loc_suppliers, dest=self.stock)

    def _internal(self):
        self._add_stock(self.prod, self.stock, 10)
        return self._picking(
            self.prod, 2, picking_type=self.wh.int_type_id,
            src=self.stock, dest=self.shelf)

    # ─── KK-A1.2 ───────────────────────────────────────
    def test_a12_non_outgoing_pickings_rejected(self):
        """Giriş / iç transfer id'si ile üç uç nokta da hata döner, kayıt değişmez."""
        calls = {
            'picking_scan': lambda p: self.ctl.picking_scan(
                picking_id=p.id, barcode='PA-1', quantity=1),
            'picking_detail': lambda p: self.ctl.picking_detail(picking_id=p.id),
            'picking_validate': lambda p: self.ctl.picking_validate(picking_id=p.id),
        }
        for kind, maker in (('incoming', self._incoming), ('internal', self._internal)):
            for name, call in calls.items():
                with self.subTest(kind=kind, endpoint=name):
                    picking = maker()
                    self.assertNotEqual(picking.picking_type_code, 'outgoing')
                    before = self._snapshot(picking)
                    res = call(picking)
                    self.assertIn('error', res, f'{kind}/{name} hata dönmeli: {res}')
                    self.assertEqual(self._snapshot(picking), before,
                                     f'{kind}/{name} kaydı değiştirmemeli')

    def test_a12_unknown_id_still_error(self):
        """Mevcut davranış: olmayan id hata döner (koruma)."""
        for name, res in (
            ('scan', self.ctl.picking_scan(picking_id=999999999, barcode='PA-1')),
            ('detail', self.ctl.picking_detail(picking_id=999999999)),
            ('validate', self.ctl.picking_validate(picking_id=999999999)),
        ):
            self.assertIn('error', res, name)

    # ─── KK-A1.3 ───────────────────────────────────────
    def test_a13_scan_cannot_exceed_demand(self):
        """Talep 2, rezerv 2: 5 okutma sonunda quantity <= 2; aşımda hata."""
        self._add_stock(self.prod, self.stock, 10)
        picking = self._picking(self.prod, 2)
        move = picking.move_ids
        self.assertEqual(move.quantity, 2, 'ön koşul: rezerv tam')

        responses = [self.ctl.picking_scan(picking_id=picking.id, barcode='PA-1', quantity=1)
                     for _i in range(5)]
        move.invalidate_recordset()
        self.assertLessEqual(move.quantity, 2, 'quantity talebi aşmamalı')
        self.assertIn('error', responses[-1], f'aşan okutma hata dönmeli: {responses[-1]}')

    def test_a13_scan_quantity_param_cannot_exceed_demand(self):
        """Tek okutmada büyük miktar gönderilse de talep aşılmaz."""
        self._add_stock(self.prod, self.stock, 10)
        picking = self._picking(self.prod, 2)
        res = self.ctl.picking_scan(picking_id=picking.id, barcode='PA-1', quantity=50)
        picking.move_ids.invalidate_recordset()
        self.assertLessEqual(picking.move_ids.quantity, 2)
        self.assertIn('error', res)

    # ─── KK-A1.4 ───────────────────────────────────────
    def _two_moves_picking(self, prod_a, prod_b):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'partner_id': self.customer.id,
            'location_id': self.stock.id,
            'location_dest_id': self.loc_customers.id,
            'move_ids': [(0, 0, {
                'product_id': p.id, 'product_uom_qty': 2,
                'product_uom': p.uom_id.id,
                'location_id': self.stock.id,
                'location_dest_id': self.loc_customers.id,
            }) for p in (prod_a, prod_b)],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def test_a14_only_open_move_is_updated(self):
        """Aynı üründe biri iptal, biri açık iki move: yalnız açık olan güncellenir."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'partner_id': self.customer.id,
            'location_id': self.stock.id,
            'location_dest_id': self.loc_customers.id,
            # description_picking farklı: confirm sırasında iki move birleştirilmesin
            'move_ids': [(0, 0, {
                'product_id': self.prod_a.id, 'product_uom_qty': 1,
                'product_uom': self.prod_a.uom_id.id,
                'description_picking': f'satir-{i}',
                'location_id': self.stock.id,
                'location_dest_id': self.loc_customers.id,
            }) for i in range(2)],
        })
        picking.action_confirm()
        cancelled, open_move = picking.move_ids.sorted('id')
        cancelled._action_cancel()
        self.assertEqual((cancelled.state, open_move.state), ('cancel', 'confirmed'))

        try:
            res = self.ctl.picking_scan(picking_id=picking.id, barcode='PA-2', quantity=1)
        except UserError as exc:
            self.fail(f'iptal move yazılmaya çalışıldı: {exc}')
        cancelled.invalidate_recordset()
        open_move.invalidate_recordset()
        self.assertEqual(cancelled.quantity, 0, 'iptal move yazılmamalı')
        self.assertEqual(open_move.quantity, 1, f'açık move güncellenmeli: {res}')
        self.assertTrue(res.get('success'), res)

    def test_a14_no_open_move_for_product_is_error(self):
        """Ürünün tek move'u iptalse hata döner ve miktar yazılmaz."""
        picking = self._two_moves_picking(self.prod_a, self.prod_b)
        cancelled = picking.move_ids.filtered(lambda m: m.product_id == self.prod_b)
        cancelled._action_cancel()
        self.assertEqual(cancelled.state, 'cancel')
        self.assertNotEqual(picking.state, 'cancel')

        try:
            res = self.ctl.picking_scan(picking_id=picking.id, barcode='PA-3', quantity=1)
        except UserError as exc:
            self.fail(f'iptal move yazılmaya çalışıldı (temiz hata yerine istisna): {exc}')
        cancelled.invalidate_recordset()
        self.assertIn('error', res, res)
        self.assertEqual(cancelled.quantity, 0)

    def test_scan_valid_outgoing_still_works(self):
        """Koruma: geçerli giden sevkiyatta, rezervi olmayan move'a okutma çalışır."""
        picking = self._two_moves_picking(self.prod_a, self.prod_b)
        move = picking.move_ids.filtered(lambda m: m.product_id == self.prod_a)
        res = self.ctl.picking_scan(picking_id=picking.id, barcode='PA-2', quantity=1)
        move.invalidate_recordset()
        self.assertTrue(res.get('success'), res)
        self.assertEqual(move.quantity, 1)
        self.assertEqual(res.get('done_qty'), 1)

    # ─── KK-A1.5 ───────────────────────────────────────
    def test_a15a_partial_picking_rejected(self):
        """(a) Kısmi (quantity < talep) giden picking: hata, done olmaz, backorder yok."""
        self._add_stock(self.prod, self.stock, 1)
        picking = self._picking(self.prod, 3)
        self.assertLess(picking.move_ids.quantity, picking.move_ids.product_uom_qty)

        res = self.ctl.picking_validate(picking_id=picking.id)
        picking.invalidate_recordset()
        self.assertIn('error', res, res)
        self.assertNotEqual(picking.state, 'done')
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', picking.id)]))

    def test_a15b_route_picking_rejected(self):
        """(b) Rotadaki (batch_id dolu) picking, rezervi tam olsa da bu uçtan doğrulanmaz."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)
        self.assertEqual(picking.move_ids.quantity, 2, 'ön koşul: rezerv tam')
        self._route(picking)

        res = self.ctl.picking_validate(picking_id=picking.id)
        picking.invalidate_recordset()
        self.assertIn('error', res, res)
        self.assertIn('Rota', res['error'])
        self.assertNotEqual(picking.state, 'done')

    def test_a15c_full_unrouted_picking_validates_with_state(self):
        """(c) Rotasız ve miktarı tam picking: doğrulanır, yanıt gerçek durumu taşır."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)

        res = self.ctl.picking_validate(picking_id=picking.id)
        picking.invalidate_recordset()
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res.get('state'), 'done', res)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 2)

    def test_a15c_not_done_does_not_claim_validated(self):
        """(c) Doğrulama done olmazsa success False ve 'doğrulandı' metni dönmez."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)

        with patch.object(picking_api.PickingApiController, '_safe_validate_picking',
                          return_value=False) as validate:
            res = self.ctl.picking_validate(picking_id=picking.id)
        self.assertTrue(validate.called, '_safe_validate_picking kullanılmalı')
        self.assertFalse(res.get('success'), res)
        self.assertNotIn('doğrulandı', str(res))
        self.assertEqual(res.get('state'), 'assigned', res)

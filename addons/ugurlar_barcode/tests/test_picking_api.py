"""G1 / KK-A1.2 - A1.5: gizli "Sipariş Toplama" uç noktalarının güvenliği.

Düzeltme turu 1 (güvenlik K1): picking_scan / picking_validate koşulsuz kapalı;
KK-A1.5(c) iptal edildi. picking_list / picking_detail salt okuma.

Dışarıdan gözlenen davranış: yanıttaki `error` / `success` / `state` ve kayıtların durumu.
"""
from unittest.mock import patch

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

    # ─── KK-A1.3 - A1.5: yazma uçları kapalı (güvenlik K1, KK-A1.5(c) iptal) ───
    def _assert_closed(self, res, picking, before):
        self.assertEqual(res, {'error': picking_api.PickingApiController.CLOSED_ERROR}, res)
        self.assertEqual(self._snapshot(picking), before, 'kapalı uç kaydı değiştirmemeli')

    def _op_count(self):
        return self.env['ugurlar.barcode.operation'].search_count([('operation_type', '=', 'picking')])

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

    # KK-A1.3 (eski: talep aşılmaz) -> okutma hiç yazmaz
    def test_a13_scan_closed_on_reserved_picking(self):
        """Rezervi tam giden sevkiyatta okutma: hata, quantity ve kayıt aynı, işlem kaydı yok."""
        self._add_stock(self.prod, self.stock, 10)
        picking = self._picking(self.prod, 2)
        self.assertEqual(picking.move_ids.quantity, 2, 'ön koşul: rezerv tam')
        ops = self._op_count()
        before = self._snapshot(picking)
        self._assert_closed(
            self.ctl.picking_scan(picking_id=picking.id, barcode='PA-1', quantity=1), picking, before)
        self.assertEqual(self._op_count(), ops, 'işlem kaydı oluşmamalı')

    def test_a13_scan_closed_with_quantity_param(self):
        """Büyük miktar parametresi de hata döner, yazım yok."""
        self._add_stock(self.prod, self.stock, 10)
        picking = self._picking(self.prod, 2)
        before = self._snapshot(picking)
        self._assert_closed(
            self.ctl.picking_scan(picking_id=picking.id, barcode='PA-1', quantity=50), picking, before)

    # KK-A1.4 (eski: yalnız açık move güncellenir) -> hiçbir move güncellenmez
    def test_a14_scan_closed_with_cancelled_and_open_move(self):
        """Aynı üründe iptal + açık move: ikisi de yazılmaz, istisna yok."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'partner_id': self.customer.id,
            'location_id': self.stock.id,
            'location_dest_id': self.loc_customers.id,
            'move_ids': [(0, 0, {
                'product_id': self.prod_a.id, 'product_uom_qty': 1,
                'product_uom': self.prod_a.uom_id.id,
                'description_picking': f'satir-{i}',
                'location_id': self.stock.id,
                'location_dest_id': self.loc_customers.id,
            }) for i in range(2)],
        })
        picking.action_confirm()
        cancelled, _open_move = picking.move_ids.sorted('id')
        cancelled._action_cancel()
        before = self._snapshot(picking)
        self._assert_closed(
            self.ctl.picking_scan(picking_id=picking.id, barcode='PA-2', quantity=1), picking, before)

    def test_a14_scan_closed_when_product_move_cancelled(self):
        picking = self._two_moves_picking(self.prod_a, self.prod_b)
        picking.move_ids.filtered(lambda m: m.product_id == self.prod_b)._action_cancel()
        before = self._snapshot(picking)
        self._assert_closed(
            self.ctl.picking_scan(picking_id=picking.id, barcode='PA-3', quantity=1), picking, before)

    def test_scan_closed_on_unreserved_move(self):
        """Eski koruma tersine döndü: rezervsiz move'a okutma artık yazmaz (kökte satır açılmaz)."""
        picking = self._two_moves_picking(self.prod_a, self.prod_b)
        self.assertEqual(picking.move_ids.mapped('quantity'), [0, 0], 'ön koşul: rezerv yok')
        before = self._snapshot(picking)
        self._assert_closed(
            self.ctl.picking_scan(picking_id=picking.id, barcode='PA-2', quantity=1), picking, before)
        self.assertFalse(picking.move_line_ids, 'move line açılmamalı')

    # KK-A1.5 (a)(b) korunur, (c) iptal: doğrulama ucu hiçbir siparişi sevk etmez
    def test_a15a_validate_closed_on_partial_picking(self):
        self._add_stock(self.prod, self.stock, 1)
        picking = self._picking(self.prod, 3)
        before = self._snapshot(picking)
        self._assert_closed(self.ctl.picking_validate(picking_id=picking.id), picking, before)
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', picking.id)]))

    def test_a15b_validate_closed_on_route_picking(self):
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)
        self._route(picking)
        before = self._snapshot(picking)
        self._assert_closed(self.ctl.picking_validate(picking_id=picking.id), picking, before)

    def test_a15c_validate_closed_on_full_unrouted_picking(self):
        """Rotasız, rezervi tam, hiç okutulmamış sipariş bu uçtan sevk edilemez (K1 senaryosu)."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)
        before = self._snapshot(picking)
        self._assert_closed(self.ctl.picking_validate(picking_id=picking.id), picking, before)
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(self._shipped_qty(picking), 0)
        self.assertEqual(self._qty(self.prod, self.stock, child=True), 5, 'stok düşmemeli')

    def test_a15c_validate_never_calls_core_validation(self):
        """Doğrulama yardımcısı hiç çağrılmaz; yanıtta 'doğrulandı' / success yok."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)
        with patch.object(picking_api.PickingApiController, '_safe_validate_picking') as validate:
            res = self.ctl.picking_validate(picking_id=picking.id)
        validate.assert_not_called()
        self.assertNotIn('success', res)
        self.assertNotIn('doğrulandı', str(res))

    def test_detail_still_reads_outgoing_picking(self):
        """Salt okuma ucu sürer: giden sevkiyat detayı döner, kayıt değişmez."""
        self._add_stock(self.prod, self.stock, 5)
        picking = self._picking(self.prod, 2)
        before = self._snapshot(picking)
        res = self.ctl.picking_detail(picking_id=picking.id)
        self.assertNotIn('error', res, res)
        self.assertEqual(res['picking']['id'], picking.id)
        self.assertEqual([line['product_barcode'] for line in res['lines']], ['PA-1'])
        self.assertEqual(self._snapshot(picking), before)

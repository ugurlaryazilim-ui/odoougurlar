"""Rota Toplama Tamamla sevkiyatı doğrulamaz; OUT'u paketleme doğrular (20261020-rota-dogrulama).

Kök neden: 769f1e1 ile Rota Tamamla OUT'u done yapmaya başladı; qty_delivered oluşunca
sale_stock satırın miktarı teslim edilenin altına düşürülemedi (S06508). Doğrulama
paketlemeye taşındı: paketlemeye kadar sipariş satırı değiştirilebilir.

K1-K8 ve rota silme koruması. Gerçek ORM, `request` yamalı; Nebim connector / commit taklit.
"""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import batch_api
from odoo.addons.ugurlar_barcode.tests.common import PackingCase


@tagged('post_install', '-at_install')
class TestRouteValidateAtPacking(PackingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Rota Doğrulama Ürünü', 'RVP-1')
        cls.prod2 = cls._new_product('Rota Doğrulama Yeni Ürün', 'RVP-2')

    def setUp(self):
        super().setUp()
        self._patch_request(batch_api)
        self.batch_ctl = batch_api.BatchApiController()
        self.nebim = self._nebim_real()

    # ─── yardımcılar ───────────────────────────────────
    def _collected_route(self, qty, wave=None, skipped=False):
        """Onaylı satış + rota; toplama okutması (wave) yazılmış, Tamamla çalıştırılmış.
        Returns (sale, picking, batch, collect_complete yanıtı)."""
        sale, picking = self._sale(self.prod, qty)
        batch = self._route(picking)
        picking.move_ids.write({
            'wave_collected_qty': qty if wave is None else wave, 'wave_skipped': skipped})
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        return sale, picking, batch, res

    def _scan(self, batch, times, barcode='RVP-1'):
        res = None
        for _i in range(times):
            res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode=barcode)
            self.assertTrue(res.get('success'), res)
        return res

    def _delivered(self, sale, product=None):
        product = product or self.prod
        line = sale.order_line.filtered(lambda line: line.product_id == product)
        line.invalidate_recordset(['qty_delivered'])
        return line.qty_delivered

    # ─── K1 ────────────────────────────────────────────
    def test_k1_collect_complete_does_not_validate(self):
        sale, picking, batch, res = self._collected_route(2)
        self.assertTrue(res.get('collect_done'))
        self.assertFalse(res.get('batch_done'))
        self.assertEqual(res.get('failed_pickings'), [])
        self.assertEqual(res.get('backorder_pickings'), [])
        self.assertIn('paketlemede doğrulanır', res['message'])
        self.assertEqual(picking.state, 'assigned', 'sevkiyat açık kalmalı')
        self.assertFalse(any(picking.move_ids.mapped('picked')), 'picked yazılmamalı')
        self.assertEqual(picking.move_ids.quantity, 2, 'rezerv korunur, üzerine yazılmaz')
        self.assertEqual(picking.move_ids.wave_collected_qty, 2)
        self.assertEqual(picking.batch_id, batch, 'toplanan sipariş rotada kalır')
        self.assertNotEqual(batch.state, 'done')
        self.assertEqual(self._delivered(sale), 0)
        self.assertEqual(self.nebim['posts'], 0, 'Tamamla fatura / Nebim tetiklememeli')

    def test_k1_second_complete_call_is_harmless(self):
        _sale, picking, batch, _res = self._collected_route(1)
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res.get('collect_done'))
        self.assertEqual(picking.state, 'assigned')

    # ─── K2: kullanıcı akışı (S06508) ──────────────────
    def test_k2_order_line_can_be_changed_after_collect(self):
        """Tamamla sonrası satır 0'a düşürülüp yeni ürün eklenebilir; yeni teslimat açılır."""
        sale, picking, _batch, _res = self._collected_route(1)
        line = sale.order_line
        self._add_stock(self.prod2, self.stock, 5)

        line.product_uom_qty = 0  # önceden: "teslim edilen miktarın altına düşürülemez"
        sale.write({'order_line': [(0, 0, {
            'product_id': self.prod2.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})

        old_move = picking.move_ids.filtered(lambda m: m.product_id == self.prod)
        self.assertEqual(old_move.state, 'cancel', 'eski ürünün hareketi iptal olmalı')
        sale.invalidate_recordset(['picking_ids'])
        new_moves = sale.picking_ids.move_ids.filtered(
            lambda m: m.product_id == self.prod2 and m.state != 'cancel')
        self.assertEqual(len(new_moves), 1, 'yeni ürün için teslimat hareketi açılmalı')
        self.assertNotEqual(new_moves.picking_id.state, 'done')
        self.assertEqual(new_moves.picking_id.picking_type_code, 'outgoing')
        self.assertEqual(self._delivered(sale), 0)

    # ─── K3 ────────────────────────────────────────────
    def test_k3_untouched_picking_leaves_route(self):
        _s1, p1 = self._sale(self.prod, 1)
        _s2, p2 = self._sale(self.prod, 1)
        batch = self._route(p1 | p2)
        p1.move_ids.wave_collected_qty = 1
        p2.move_ids.wave_skipped = True  # hiç toplanamadı, "Eksik"

        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['skipped_pickings'], [p2.name])
        self.assertFalse(p2.batch_id)
        self.assertNotIn(p2, batch.all_picking_ids)
        self.assertEqual(p2.state, 'assigned', 'çıkarılan sipariş açık kalır (sonraki rota)')
        self.assertEqual(p1.batch_id, batch)
        self.assertEqual(p1.state, 'assigned')
        self.assertIn('sonraki rotaya', res['message'])

    # ─── K4 ────────────────────────────────────────────
    def test_k4_missing_item_blocks_complete(self):
        _sale, picking = self._sale(self.prod, 2)
        batch = self._route(picking)
        picking.move_ids.wave_collected_qty = 1  # eksik, "Eksik" işaretlenmedi
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertIn('error', res, res)
        self.assertTrue(res.get('missing'))
        self.assertFalse(res.get('collect_done'))
        self.assertEqual(picking.state, 'assigned')

    # ─── K5 + K8 ───────────────────────────────────────
    def test_k5_k8_last_packing_scan_validates_and_invoices_once(self):
        sale, picking, batch, _res = self._collected_route(2)

        first = self._scan(batch, 1)
        self.assertFalse(first['picking_completed'])
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(self.nebim['posts'], 0)

        last = self._scan(batch, 1)
        self.assertTrue(last['picking_completed'])
        self.assertTrue(last['all_matched'])
        self.assertNotIn('validate_error', last)
        self.assertEqual(picking.state, 'done')
        self.assertTrue(picking.packing_done)
        self.assertEqual(self._delivered(sale), 2)
        self.assertEqual(batch.state, 'done', 'tüm picking done: rota paketlemede kapanır')
        # K8: done picking Nebim'e gider, fatura tek
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.assertEqual(self.nebim['posts'], 1)
        self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual(len(self._out_invoices(sale)), 1, 'ikinci fatura oluşmamalı')
        self.assertEqual(self.nebim['posts'], 1)

    # ─── K6 ────────────────────────────────────────────
    def test_k6_partial_skip_completes_with_collected_scans(self):
        sale, picking, batch, _res = self._collected_route(3, wave=1, skipped=True)
        self.assertEqual(picking.state, 'assigned')

        detail = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        self.assertEqual(detail['matched'], 0)

        res = self._scan(batch, 1)
        self.assertTrue(res['complete'])
        self.assertTrue(res['picking_completed'])
        self.assertEqual(res['remaining_items'], [])
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1)
        self.assertEqual(self._delivered(sale), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)
        self.assertNotEqual(backorder.state, 'done')

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RVP-1')
        self.assertFalse(res.get('success'), 'toplanandan fazlası okutulamaz')

    def test_k6_skipped_line_counts_as_matched_in_detail(self):
        _sale, picking, batch, _res = self._collected_route(3, wave=1, skipped=True)
        picking.move_ids.packing_scanned_qty = 1
        detail = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        self.assertTrue(detail['items'][0]['matched'])
        self.assertTrue(detail['all_matched'])

    # ─── K7 ────────────────────────────────────────────
    def test_k7_packing_backorder_ships_scanned_on_open_picking(self):
        sale, picking, batch, _res = self._collected_route(3)
        self._scan(batch, 1)
        self.assertEqual(picking.state, 'assigned')
        res = self.pack_ctl.packing_backorder(picking_id=picking.id, batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1)
        self.assertEqual(self._delivered(sale), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)

    def test_k7_packing_complete_ships_collected_on_open_picking(self):
        sale, picking, batch, _res = self._collected_route(2)
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['validated'], 1)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._delivered(sale), 2)
        self.assertEqual(batch.state, 'done')
        self.assertEqual(self.nebim['posts'], 1)
        self.assertEqual(self.sp_depth[0], 0)

    def test_k7_packing_complete_partial_skip_creates_backorder(self):
        sale, picking, batch, _res = self._collected_route(3, wave=1, skipped=True)
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._shipped_qty(picking), 1)
        self.assertEqual(self._delivered(sale), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)

    # ─── Rota silme koruması ───────────────────────────
    def _delete(self, batch):
        with patch.object(batch_api.BatchApiController, '_is_stock_manager', return_value=True):
            return self.batch_ctl.batch_delete(batch_id=batch.id)

    def test_delete_blocked_when_collected_not_packed(self):
        _sale, picking, batch, _res = self._collected_route(1)
        res = self._delete(batch)
        self.assertIn('error', res, res)
        self.assertIn('toplanmış ama paketlenmemiş', res['error'])
        self.assertIn('(1 sipariş)', res['error'])
        self.assertTrue(batch.exists())
        self.assertEqual(picking.batch_id, batch)

    def test_delete_allowed_when_nothing_collected(self):
        _sale, picking = self._sale(self.prod, 1)
        batch = self._route(picking)
        res = self._delete(batch)
        self.assertTrue(res.get('success'), res)
        self.assertFalse(batch.exists())
        self.assertFalse(picking.batch_id)

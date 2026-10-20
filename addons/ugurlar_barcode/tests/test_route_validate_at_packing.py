"""Rota Toplama Tamamla sevkiyatı doğrulamaz; OUT'u paketleme doğrular (20261020-rota-dogrulama).

Kök neden: 769f1e1 ile Rota Tamamla OUT'u done yapmaya başladı; qty_delivered oluşunca
sale_stock satırın miktarı teslim edilenin altına düşürülemedi (S06508). Doğrulama
paketlemeye taşındı: paketlemeye kadar sipariş satırı değiştirilebilir.

K1-K8 ve rota silme koruması. Gerçek ORM, `request` yamalı; Nebim connector / commit taklit.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
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
        cls.prod3 = cls._new_product('Rota Doğrulama Sonradan Eklenen', 'RVP-3')

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
        # Bekleyen sevkiyat bu rotada kalmaz (sonraki rotaya girer); rota kapanır
        self.assertFalse(backorder.batch_id)
        self.assertNotIn(backorder, batch.all_picking_ids)
        self.assertEqual(batch.state, 'done')

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RVP-1')
        self.assertFalse(res.get('success'), 'toplanandan fazlası okutulamaz')

    def test_k6_skipped_line_counts_as_matched_in_detail(self):
        _sale, picking, batch, _res = self._collected_route(3, wave=1, skipped=True)
        picking.move_ids.packing_scanned_qty = 1
        detail = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        self.assertTrue(detail['items'][0]['matched'])
        self.assertTrue(detail['all_matched'])
        # İstemci aktif sipariş kutularını hedefle çizer (talep 3, hedef toplanan 1)
        self.assertEqual(detail['items'][0]['target_qty'], 1)
        self.assertEqual(detail['items'][0]['demand_qty'], 3)

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

    # ─── İnceleme 1: satırı değişen siparişin iptal picking'i rotayı kilitlemez ───
    def _two_orders_one_changed(self):
        """Rotada A ve B (1'er adet, toplandı, Tamamla). A'nın satırı 0'a düşürülüp yeni ürün
        eklenir: A'nın OUT'u iptal olur ama rotanın kalıcı listesinde kalır."""
        sale_a, pa = self._sale(self.prod, 1)
        _sale_b, pb = self._sale(self.prod, 1)
        batch = self._route(pa | pb)
        (pa | pb).move_ids.write({'wave_collected_qty': 1})
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self._add_stock(self.prod2, self.stock, 5)
        sale_a.order_line.product_uom_qty = 0
        sale_a.write({'order_line': [(0, 0, {
            'product_id': self.prod2.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})
        self.assertEqual(pa.state, 'cancel', 'ön koşul: A iptal')
        self.assertIn(pa, batch.all_picking_ids, 'ön koşul: iptal picking kalıcı listede')
        return pa, pb, batch

    def test_k2_changed_order_packing_complete_closes_route(self):
        _pa, pb, batch = self._two_orders_one_changed()
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res['errors'], [])
        self.assertEqual(pb.state, 'done')
        self.assertEqual(batch.state, 'done', 'iptal + done picking: rota kapanmalı')

    def test_k2_changed_order_last_scan_closes_route(self):
        _pa, pb, batch = self._two_orders_one_changed()
        res = self._scan(batch, 1)
        self.assertEqual(res['picking_id'], pb.id)
        self.assertEqual(pb.state, 'done')
        self.assertEqual(batch.state, 'done')

    def test_route_finished_rule(self):
        """Tek kural: hepsi done/cancel ve en az biri done."""
        _sale_a, pa = self._sale(self.prod, 1)
        _sale_b, pb = self._sale(self.prod, 1)
        finished = self.pack_ctl._route_finished
        self.assertFalse(finished(pa.browse()))
        self.assertFalse(finished(pa | pb))
        pa.action_cancel()
        self.assertFalse(finished(pa), 'yalnız iptal: kapanmaz (cron iptal eder)')
        self.assertFalse(finished(pa | pb))
        pb.move_ids.write({'quantity': 1, 'picked': True})
        pb.button_validate()
        self.assertTrue(finished(pa | pb))

    # ─── İnceleme 2: aynı siparişin kardeş picking'leri tek faturada ───
    def _sale_two_pickings(self):
        """2 satırlı sipariş, satırlar ayrı OUT'larda (farklı depodan toplama gibi)."""
        for product in (self.prod, self.prod2):
            product.product_tmpl_id.invoice_policy = 'delivery'
            self._add_stock(product, self.stock, 5)
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': 1, 'price_unit': 10.0})
                           for p in (self.prod, self.prod2)],
        })
        sale.action_confirm()
        p1 = sale.picking_ids
        self.assertEqual(len(p1), 1, 'ön koşul')
        move2 = p1.move_ids.filtered(lambda m: m.product_id == self.prod2)
        p2 = self.env['stock.picking'].create({
            'picking_type_id': p1.picking_type_id.id, 'partner_id': p1.partner_id.id,
            'location_id': p1.location_id.id, 'location_dest_id': p1.location_dest_id.id,
            'origin': p1.origin})
        move2.picking_id = p2
        (p1 | p2).action_assign()
        batch = self._route(p1 | p2)
        (p1 | p2).move_ids.write({'wave_collected_qty': 1})
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        return sale, p1, p2, batch

    def _invoiced_products(self, sale):
        return self._out_invoices(sale).invoice_line_ids.product_id

    def test_siblings_scanned_invoice_once_with_both_products(self):
        sale, p1, p2, batch = self._sale_two_pickings()
        first = self._scan(batch, 1, barcode='RVP-1')
        self.assertEqual(p1.state, 'done')
        self.assertFalse(first['picking_completed'], 'sipariş tamam değil: etiket yok')
        self.assertEqual(len(self._out_invoices(sale)), 0, 'kardeş açıkken fatura kesilmemeli')
        self.assertEqual(self.nebim['posts'], 0)

        last = self._scan(batch, 1, barcode='RVP-2')
        self.assertTrue(last['picking_completed'])
        self.assertEqual(p2.state, 'done')
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.assertEqual(self._invoiced_products(sale), self.prod | self.prod2)
        self.assertEqual(self.nebim['posts'], 1)

    def test_siblings_packing_complete_invoice_once_with_both_products(self):
        sale, p1, p2, batch = self._sale_two_pickings()
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual((p1 | p2).mapped('state'), ['done', 'done'])
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.assertEqual(self._invoiced_products(sale), self.prod | self.prod2)
        self.assertEqual(self.nebim['posts'], 1)

    # ─── İnceleme 3: iki satırlı siparişte satır değişimi ───
    def test_line_change_on_two_line_order_does_not_lock_packing(self):
        """Tamamla sonrası bir satır 0'a düşürülüp yeni ürün eklenir: yeni (toplanmamış) hareket
        rotadaki toplanmış picking'e girmez, paketleme kilitlenmez."""
        for product in (self.prod, self.prod2, self.prod3):
            product.product_tmpl_id.invoice_policy = 'delivery'
            self._add_stock(product, self.stock, 5)
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': 1, 'price_unit': 10.0})
                           for p in (self.prod, self.prod2)],
        })
        sale.action_confirm()
        picking = sale.picking_ids
        picking.action_assign()
        batch = self._route(picking)
        picking.move_ids.write({'wave_collected_qty': 1})
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)

        sale.order_line.filtered(lambda line: line.product_id == self.prod).product_uom_qty = 0
        sale.write({'order_line': [(0, 0, {
            'product_id': self.prod3.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})

        new_move = self.env['stock.move'].search([
            ('product_id', '=', self.prod3.id), ('sale_line_id.order_id', '=', sale.id)])
        self.assertEqual(len(new_move), 1)
        self.assertNotEqual(new_move.picking_id, picking, 'toplanmış picking e yeni hareket girmemeli')
        self.assertNotIn(new_move.picking_id, batch.all_picking_ids)

        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1)
        self.assertEqual(self._delivered(sale, self.prod2), 1)
        self.assertNotEqual(new_move.picking_id.state, 'done')
        self.assertEqual(batch.state, 'done')

    def test_line_added_before_collection_still_joins_routed_picking(self):
        """Toplama başlamadan eklenen satır eskisi gibi aynı picking'e girer (rota listesinde)."""
        self.prod3.product_tmpl_id.invoice_policy = 'delivery'
        self._add_stock(self.prod3, self.stock, 5)
        sale, picking = self._sale(self.prod, 1)
        self._route(picking)
        sale.write({'order_line': [(0, 0, {
            'product_id': self.prod3.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})
        self.assertIn(self.prod3, picking.move_ids.product_id)

    def test_line_swap_in_single_write_cancels_old_and_opens_new_picking(self):
        """Azaltma ve yeni satır tek kayıtta: azaltma toplanmış picking'deki hareketi iptal
        eder (iade hareketine dönmez), yeni ürün ayrı sevkiyata gider."""
        self.prod3.product_tmpl_id.invoice_policy = 'delivery'
        self._add_stock(self.prod3, self.stock, 5)
        sale, picking, _batch, _res = self._collected_route(1)
        sale.write({'order_line': [
            (1, sale.order_line.id, {'product_uom_qty': 0}),
            (0, 0, {'product_id': self.prod3.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})
        self.assertEqual(picking.move_ids.filtered(
            lambda m: m.product_id == self.prod).state, 'cancel')
        self.assertEqual(picking.state, 'cancel')
        moves = self.env['stock.move'].search([('sale_line_id.order_id', '=', sale.id),
                                               ('state', '!=', 'cancel')])
        self.assertEqual(moves.product_id, self.prod3, 'iade / negatif hareket kalmamalı')
        self.assertNotEqual(moves.picking_id, picking)
        self.assertEqual(moves.picking_id.picking_type_code, 'outgoing')

    def test_fully_skipped_picking_removed_from_route_accepts_new_lines(self):
        """Tamamen "Eksik" olup rotadan çıkarılan picking'in wave_skipped işareti kalır; yeni
        satır yine bu picking'e girer (gereksiz ayrı OUT açılmaz)."""
        self.prod3.product_tmpl_id.invoice_policy = 'delivery'
        self._add_stock(self.prod3, self.stock, 5)
        _s1, p1 = self._sale(self.prod, 1)
        sale2, p2 = self._sale(self.prod, 1)
        batch = self._route(p1 | p2)
        p1.move_ids.wave_collected_qty = 1
        p2.move_ids.wave_skipped = True
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertFalse(p2.batch_id, 'ön koşul: rotadan çıkarıldı')
        sale2.write({'order_line': [(0, 0, {
            'product_id': self.prod3.id, 'product_uom_qty': 1, 'price_unit': 10.0})]})
        self.assertIn(self.prod3, p2.move_ids.product_id)
        self.assertEqual(len(sale2.picking_ids), 1)

    # ─── İnceleme 4: model katmanında silme koruması ───
    def test_model_unlink_blocked_when_collected_not_packed(self):
        _sale, _picking, batch, _res = self._collected_route(1)
        with self.assertRaises(UserError):
            batch.unlink()
        self.assertTrue(batch.exists())

    def test_model_unlink_not_blocked_by_picking_moved_to_other_route(self):
        _sale, picking, batch, _res = self._collected_route(1)
        other = self.env['stock.picking.batch'].create(
            {'picking_type_id': picking.picking_type_id.id})
        picking.batch_id = other
        batch.unlink()
        self.assertFalse(batch.exists())

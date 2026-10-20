"""G4 / KK-A5.1, A5.2, A6, A7.1 - A7.5, RG-1: rota motoru ve rezervasyon.

İki bölüm:
- TestScheduleReservation: gerçek `_create_batch_for_window` akışı (FAZ 1-5), her test
  kendi izole depolarını (ana / yedek / iade) kullanır.
- TestReservedRouteScreens: rezervi tam rota picking'inde ekranların "toplanan" / "okutulan"
  değerini rezervden değil kendi sayaçlarından okuması (KK-A7.3 - A7.5, RG-1).
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytz

from odoo import fields
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import batch_api, packing_api, shelf_api
from odoo.addons.ugurlar_barcode.controllers.base_api import BarcodeApiBase
from odoo.addons.ugurlar_barcode.models import picking_schedule
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestScheduleReservation(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pri = cls._new_warehouse('Faz Ana Depo', 'FZA')
        cls.fbk = cls._new_warehouse('Faz Yedek Depo', 'FZB')
        cls.ret = cls._new_warehouse('Faz Iade Depo', 'FZR')
        # Odoo'nun otomatik tek-sipariş rotası (in_progress, sorumlu atanmış) bu testlerde
        # pencere seçimini etkilemesin; rota motoru kendi rotasını kurar
        cls.pri.out_type_id.auto_batch = False
        cls.pri_shelf = cls._new_shelf('FZ-RAF-A', 'FZ-RAF-A', parent=cls.pri.lot_stock_id)
        cls.fbk_shelf = cls._new_shelf('FZ-RAF-B', 'FZ-RAF-B', parent=cls.fbk.lot_stock_id)
        cls.prod = cls._new_product('Faz Ürünü 1', 'FZ-P1')
        cls.prod2 = cls._new_product('Faz Ürünü 2', 'FZ-P2')
        cls.schedule = cls.env['ugurlar.picking.schedule'].create({
            'name': 'Faz Test Planı',
            'warehouse_id': cls.pri.id,
            'fallback_warehouse_id': cls.fbk.id,
            'return_warehouse_id': cls.ret.id,
            'schedule_line_ids': [(0, 0, {'hour': 23, 'minute': 59})],
        })
        cls.line = cls.schedule.schedule_line_ids

    def setUp(self):
        super().setUp()
        self._patch_request(shelf_api)
        self.shelf_ctl = shelf_api.ShelfApiController()

    # ─── yardımcılar ───────────────────────────────────
    def _pri_picking(self, product, demand, **kw):
        """Ana depo çıkışı: confirm'lü, henüz rezerve edilmemiş (FAZ 1 rezerve edecek)."""
        kw.setdefault('assign', False)
        return self._picking(product, demand, picking_type=self.pri.out_type_id, **kw)

    def _run_window(self, pickings):
        """Pickings'i pencere içine alıp FAZ 1-5'i çalıştırır. create_date ORM ile yazılamaz."""
        start, _end, _label = self.schedule._get_time_window(self.line)
        create = pytz.timezone('Europe/Istanbul').localize(start + timedelta(hours=1)) \
            .astimezone(pytz.UTC).replace(tzinfo=None)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_picking SET create_date=%s WHERE id IN %s", (create, tuple(pickings.ids)))
        pickings.invalidate_recordset(['create_date'])
        now = datetime.now(pytz.UTC).astimezone(picking_schedule.IST)
        batch = self.schedule._create_batch_for_window(self.line, now.date(), now)
        pickings.invalidate_recordset()
        pickings.move_ids.invalidate_recordset()
        self.assertTrue(batch, 'ön koşul: pencere rotası oluşmalı')
        return batch

    def _open_auto_transfers(self):
        return self.env['stock.picking'].search([
            ('origin', 'ilike', 'Toplama Otomatik Transfer'),
            ('state', 'not in', ('done', 'cancel'))])

    def _negative_quants(self, product):
        return self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('quantity', '<', 0),
            ('location_id.usage', '=', 'internal')])

    # ─── KK-A7.1 ───────────────────────────────────────
    def test_a71_reservation_kept_after_phase5(self):
        """Rezervi tam rota siparişi: move.quantity ve move line'lar FAZ 5'ten sonra korunur."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod, 2)

        batch = self._run_window(picking)

        self.assertTrue(batch, 'rota oluşmalı')
        self.assertEqual(picking.batch_id, batch)
        move = picking.move_ids
        self.assertEqual(move.state, 'assigned')
        self.assertEqual(move.quantity, 2, 'rezerv sıfırlanmamalı')
        self.assertEqual(sum(move.move_line_ids.mapped('quantity')), 2)
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(move.source_warehouse_id, self.pri)

    def test_a71_other_order_cannot_take_reserved_stock(self):
        """Aynı stok için başka sipariş action_assign çalıştırınca rezerve edemez."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod, 2)
        self._run_window(picking)

        other = self._pri_picking(self.prod, 1, assign=True)
        other.move_ids.invalidate_recordset()
        self.assertEqual(other.move_ids.quantity, 0, 'stok rotadaki siparişe ayrılı')
        self.assertNotEqual(other.state, 'assigned')

    def test_a71_reserved_stock_blocked_for_shelf_ops(self):
        """BD-1: rotadaki siparişin rezerve ettiği adet raftan kaldırılamaz / taşınamaz."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod, 2)
        self._run_window(picking)

        res = self.shelf_ctl.remove_from_shelf(
            product_barcode='FZ-P1', shelf_barcode='FZ-RAF-A', quantity=1)
        self.assertIn('error', res, res)
        self.assertEqual(self._qty(self.prod, self.pri_shelf), 2)

    # ─── KK-A7.2 ───────────────────────────────────────
    def test_a72_partial_collected_ships_collected_only(self):
        """wave_collected_qty=1, talep 2: doğrulama sonrası teslim 1, kalan için bekleyen sevkiyat."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod, 2)
        self._run_window(picking)
        move = picking.move_ids
        move.write({'wave_collected_qty': 1, 'wave_skipped': True})

        _total, partial = self.api._apply_collected_quantities(picking)
        self.assertTrue(partial)
        with patch.object(BarcodeApiBase, '_safe_validate_picking', autospec=True,
                          side_effect=BarcodeApiBase._safe_validate_picking):
            self._patch_request()
            self.assertTrue(self.api._safe_validate_picking(picking, backorder=True))

        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1, 'talep 2 sevk edilmemeli')
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2 - 1)
        self.assertEqual(self._qty(self.prod, self.pri_shelf), 1, 'kalan adet rafta')

    # ─── KK-A5.1 ───────────────────────────────────────
    def test_a51_partial_fallback_stock_validates_only_reserved(self):
        """Yedek depoda talebin yalnız kısmı var: yalnız rezerve edilen taşınır, negatif oluşmaz."""
        self._add_stock(self.prod, self.fbk_shelf, 1)
        transfer = self.schedule._create_auto_internal_transfer(
            {self.prod.id: 3}, self.fbk, self.pri, 'Yedek Depo')

        self.assertFalse(self._negative_quants(self.prod), 'yedek depo negatife düşmemeli')
        self.assertEqual(self._qty(self.prod, self.fbk.lot_stock_id, child=True), 0)
        self.assertEqual(self._qty(self.prod, self.pri.lot_stock_id, child=True), 1,
                         'yalnız rezerve edilen 1 adet ana depoya geçmeli')
        self.assertFalse(self._open_auto_transfers(), 'yarım kalan transfer bırakılmamalı')
        if transfer:
            self.assertEqual(transfer.state, 'done')

    def test_a51_no_reservation_cancels_transfer(self):
        """Yedek depoda hiç stok yoksa transfer iptal edilir (None), stok oluşmaz."""
        transfer = self.schedule._create_auto_internal_transfer(
            {self.prod.id: 3}, self.fbk, self.pri, 'Yedek Depo')

        self.assertFalse(transfer)
        self.assertFalse(self._negative_quants(self.prod))
        self.assertEqual(self._qty(self.prod, self.pri.lot_stock_id, child=True), 0)
        self.assertFalse(self._open_auto_transfers())
        self.assertFalse(self.env['stock.move'].search([
            ('product_id', '=', self.prod.id), ('state', '=', 'done')]))

    def test_a51_full_fallback_stock_still_transfers(self):
        """Koruma: yedek depoda yeterli stok varsa tam miktar ana depoya taşınır."""
        self._add_stock(self.prod, self.fbk_shelf, 3)
        transfer = self.schedule._create_auto_internal_transfer(
            {self.prod.id: 3}, self.fbk, self.pri, 'Yedek Depo')
        self.assertTrue(transfer)
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(self._qty(self.prod, self.fbk.lot_stock_id, child=True), 0)
        self.assertEqual(self._qty(self.prod, self.pri.lot_stock_id, child=True), 3)

    # ─── KK-A5.2 ───────────────────────────────────────
    def test_a52_dozen_demand_sufficient_with_12_units(self):
        """1 düzine talep, yedek depoda 12 adet: yeterli sayılır ve 12 adet taşınır."""
        dozen = self.env.ref('uom.product_uom_dozen')
        self._add_stock(self.prod, self.fbk_shelf, 12)
        picking = self._pri_picking(self.prod, 1, uom=dozen)

        batch = self._run_window(picking)

        self.assertTrue(batch)
        move = picking.move_ids
        self.assertEqual(self._qty(self.prod, self.fbk.lot_stock_id, child=True), 0,
                         '12 adedin tamamı ana depoya taşınmalı')
        self.assertEqual(move.state, 'assigned', 'düzine talebi tam karşılanmalı')
        self.assertEqual(move.product_qty, 12)

    def test_a52_dozen_demand_insufficient_with_11_units(self):
        """1 düzine talep, yedek depoda 11 adet: yetersiz, hiçbir şey taşınmaz."""
        dozen = self.env.ref('uom.product_uom_dozen')
        self._add_stock(self.prod, self.fbk_shelf, 11)
        picking = self._pri_picking(self.prod, 1, uom=dozen)

        self._run_window(picking)

        self.assertEqual(self._qty(self.prod, self.fbk.lot_stock_id, child=True), 11)
        self.assertEqual(self._qty(self.prod, self.pri.lot_stock_id, child=True), 0)
        self.assertNotEqual(picking.move_ids.source_warehouse_id, self.fbk)

    # ─── İnceleme Ö-2: stok durumu kendi rezervini serbest sayar, ürün UoM'u ile ───
    def _status(self, picking):
        return picking._check_availability_status(self.pri, self.fbk, self.ret)

    def test_review_o2_own_reservation_counts_as_available(self):
        """Rezervi tam rota siparişi (stok 2, talep 2, rezerv 2) 'stokta' görünür."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        picking = self._pri_picking(self.prod, 2, assign=True)
        self.assertEqual(picking.move_ids.quantity, 2, 'ön koşul: rezerv tam')
        self._route(picking, self.pri.out_type_id)
        self.assertEqual(self._status(picking), 'available')
        self.assertEqual(picking.availability_status, 'available')

    def test_review_o2_other_order_reservation_still_blocks(self):
        """Başka siparişin rezervi serbest sayılmaz: stok 2'nin tamamı A'da, B stoksuz."""
        self._add_stock(self.prod, self.pri_shelf, 2)
        self._pri_picking(self.prod, 2, assign=True)
        other = self._pri_picking(self.prod, 2, assign=True)
        self.assertEqual(other.move_ids.quantity, 0, 'ön koşul: B rezervsiz')
        self.assertEqual(self._status(other), 'unavailable')

    def test_review_o2_dozen_demand_uses_product_uom(self):
        """1 düzine talep: ana depoda 12 adet yeterli, 11 adet yetersiz (move birimi değil ürün birimi)."""
        dozen = self.env.ref('uom.product_uom_dozen')
        self._add_stock(self.prod, self.pri_shelf, 11)
        picking = self._pri_picking(self.prod, 1, uom=dozen)
        self.assertNotEqual(self._status(picking), 'available', '11 adet 1 düzineyi karşılamaz')
        self._add_stock(self.prod, self.pri_shelf, 1)
        self.assertEqual(self._status(picking), 'available')
        picking.action_assign()
        self.assertEqual(picking.move_ids.quantity, 1, 'ön koşul: 1 düzine rezerve')
        self.assertEqual(self._status(picking), 'available', 'kendi düzine rezervi 12 adet sayılmalı')

    # ─── KK-A6 ─────────────────────────────────────────
    def test_a6_failed_fallback_transfer_does_not_label_fallback(self):
        """Yedek depo transferi None dönerse move'lar yedek depo etiketi almaz."""
        self._add_stock(self.prod, self.fbk_shelf, 2)
        picking = self._pri_picking(self.prod, 2)

        with patch.object(type(self.schedule), '_create_auto_internal_transfer', return_value=None):
            batch = self._run_window(picking)

        self.assertTrue(batch)
        self.assertNotEqual(picking.move_ids.source_warehouse_id, self.fbk,
                            'transfer olmadı: etiket yedek depo olmamalı')

    def test_a6_successful_fallback_transfer_labels_fallback(self):
        """Koruma: transfer başarılıysa move'lar yedek depo etiketi alır."""
        self._add_stock(self.prod, self.fbk_shelf, 2)
        picking = self._pri_picking(self.prod, 2)

        self._run_window(picking)

        self.assertEqual(picking.move_ids.source_warehouse_id, self.fbk)
        self.assertEqual(self._qty(self.prod, self.pri.lot_stock_id, child=True), 2,
                         'yedekten ana depoya 2 adet geçmeli')

    def test_a71_fallback_transferred_stock_stays_reserved(self):
        """Yedekten taşınan stok FAZ 5'ten sonra da siparişe rezerve kalır."""
        self._add_stock(self.prod, self.fbk_shelf, 2)
        picking = self._pri_picking(self.prod, 2)

        self._run_window(picking)

        move = picking.move_ids
        self.assertEqual(move.state, 'assigned')
        self.assertEqual(move.quantity, 2)


@tagged('post_install', '-at_install')
class TestReservedRouteScreens(BarcodeCase):
    """A7 sonrası rota picking'leri rezervi tam halde durur; ekranlar kendi sayaçlarını okur."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Rota Ürünü', 'RR-1')
        cls.prod_x = cls._new_product('Rota Ürünü X', 'RR-X')
        cls.shelf = cls._new_shelf('RR-RAF', 'RR-RAF-1')

    def setUp(self):
        super().setUp()
        self._patch_request(batch_api, packing_api)
        self.batch_ctl = batch_api.BatchApiController()
        self.pack_ctl = packing_api.PackingApiController()
        nebim = patch.object(packing_api.PackingApiController, '_trigger_nebim_sync')
        self.nebim = nebim.start()
        self.addCleanup(nebim.stop)

    # ─── yardımcılar ───────────────────────────────────
    def _reserved_route(self, demand=2, wave=0, product=None, origin=None):
        """Rezervi TAM (quantity = talep) bir rota picking'i. Returns (picking, batch)."""
        product = product or self.prod
        self._add_stock(product, self.shelf, demand + 3)
        picking = self._picking(product, demand, origin=origin)
        move = picking.move_ids
        self.assertEqual(move.quantity, demand, 'ön koşul: rezerv tam')
        if wave:
            move.wave_collected_qty = wave
        return picking, self._route(picking)

    def _validate_picking(self, picking, qty_field='wave_collected_qty'):
        self.api._apply_collected_quantities(picking, qty_field)
        self.assertTrue(self.api._safe_validate_picking(picking))

    def _detail_item(self, batch, picking=None):
        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        items = res['items']
        if picking:
            items = [i for i in items if i['picking_id'] == picking.id]
        self.assertEqual(len(items), 1, items)
        return items[0]

    # ─── KK-A7.3: Rota Toplama ─────────────────────────
    def test_a73_route_items_and_collect_scan_use_wave_counter(self):
        picking, batch = self._reserved_route()
        res = self.batch_ctl.batch_route_items(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        self.assertEqual(res['items'][0]['collected_qty'], 0, 'rezerv toplanmış sayılmamalı')
        self.assertFalse(res['all_collected'])

        for expected in (1, 2):
            scan = self.batch_ctl.batch_collect_scan(batch_id=batch.id, barcode='RR-1')
            self.assertTrue(scan.get('success'), scan)
            self.assertEqual(scan['collected_qty'], expected)
        self.assertTrue(scan['item_complete'])
        self.assertEqual(picking.move_ids.wave_collected_qty, 2)

        res = self.batch_ctl.batch_route_items(batch_id=batch.id)
        self.assertEqual(res['items'][0]['collected_qty'], 2)
        self.assertTrue(res['all_collected'])

    def test_a73_collect_complete_blocks_untouched_reserved_picking(self):
        """Hiç toplanmamış (ama rezervli) sipariş 'toplandı' sayılıp sevk edilmez."""
        picking, batch = self._reserved_route()
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        picking.invalidate_recordset()
        self.assertIn('error', res, res)
        self.assertNotEqual(picking.state, 'done')

    def test_a73_collect_complete_leaves_shipping_to_packing(self):
        """Rota Tamamla sevkiyatı doğrulamaz; toplanan miktarı paketleme sevk eder."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res.get('collect_done'))
        self.assertFalse(res.get('batch_done'))
        self.assertNotEqual(picking.state, 'done')
        self.assertFalse(any(picking.move_ids.mapped('picked')))

        for _i in range(2):
            scan = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-1')
            self.assertTrue(scan.get('success'), scan)
        self.assertTrue(scan['picking_completed'])
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 2)
        self.assertEqual(batch.state, 'done')

    def test_a73_batch_detail_uses_wave_counter(self):
        """batch_detail: done_qty / collected_qty rezervden değil wave_collected_qty'den."""
        picking, batch = self._reserved_route(demand=2, wave=0)
        res = self.batch_ctl.batch_detail(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        self.assertEqual(res['pickings'][0]['lines'][0]['done_qty'], 0)
        self.assertEqual(res['route_products'][0]['collected_qty'], 0)

        picking.move_ids.wave_collected_qty = 1
        res = self.batch_ctl.batch_detail(batch_id=batch.id)
        self.assertEqual(res['pickings'][0]['lines'][0]['done_qty'], 1)
        self.assertEqual(res['route_products'][0]['collected_qty'], 1)

    # ─── KK-A7.3 / A7.4: Paketleme listesi ─────────────
    def test_a74_unscanned_line_has_zero_done_qty(self):
        """Rezervi tam, doğrulanmamış rota picking'i; okutma 0 -> done_qty 0 (geri al butonu çıkmaz)."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        item = self._detail_item(batch)
        self.assertEqual(item['demand_qty'], 2)
        self.assertEqual(item['scanned_qty'], 0)
        self.assertEqual(item['done_qty'], 0)
        self.assertFalse(item['matched'])

    def test_a74_done_qty_follows_scanned_counter(self):
        """Bir okutmadan sonra done_qty = 1."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        scan = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-1')
        self.assertTrue(scan.get('success'), scan)
        self.assertEqual(scan['done_qty'], 1)
        item = self._detail_item(batch)
        self.assertEqual(item['scanned_qty'], 1)
        self.assertEqual(item['done_qty'], 1)

    def test_a74_done_picking_shows_shipped_quantity(self):
        """Doğrulanmış picking'de gösterilen değer sevk edilen miktardır (move.quantity)."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        self._validate_picking(picking)
        self.assertEqual(picking.state, 'done')
        item = self._detail_item(batch)
        self.assertEqual(item['done_qty'], 2)

    def _orig_with_cancelled_x(self, origin):
        """Rotadaki sipariş: RR-1 (rezervi tam, 2) + iptal edilmiş RR-X satırı. Returns (picking, batch)."""
        self._add_stock(self.prod, self.shelf, 5)
        self._add_stock(self.prod_x, self.shelf, 5)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id,
            'partner_id': self.customer.id,
            'location_id': self.stock.id,
            'location_dest_id': self.loc_customers.id,
            'origin': origin,
            'move_ids': [(0, 0, {
                'product_id': p.id, 'product_uom_qty': q, 'product_uom': p.uom_id.id,
                'location_id': self.stock.id, 'location_dest_id': self.loc_customers.id,
            }) for p, q in ((self.prod, 2), (self.prod_x, 1))],
        })
        picking.action_confirm()
        picking.action_assign()
        move_x = picking.move_ids.filtered(lambda m: m.product_id == self.prod_x)
        move_x._action_cancel()
        move_main = picking.move_ids - move_x
        self.assertEqual((move_x.state, move_main.quantity), ('cancel', 2), 'ön koşul')
        move_main.wave_collected_qty = 2
        return picking, self._route(picking)

    def _replacement_x(self, origin, done=False):
        """Aynı siparişin rotaya girmemiş yedek (replacement) picking'i: RR-X, rezervi tam."""
        repl = self._picking(self.prod_x, 1, origin=origin)
        self.assertEqual(repl.move_ids.quantity, 1, 'ön koşul: replacement rezervi tam')
        if done:
            repl.move_ids.picked = True
            repl.button_validate()
            self.assertEqual(repl.state, 'done')
        return repl

    def test_a73_replacement_row_done_qty_follows_scanned_counter(self):
        """Replacement satırı için de aynı kural: bitmemiş move'da okutulan, rezerv değil."""
        orig, batch = self._orig_with_cancelled_x('SO-REP')
        repl = self._replacement_x('SO-REP')

        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        rows = [i for i in res['items'] if i['picking_id'] == repl.id]
        self.assertEqual(len(rows), 1, 'replacement satırı beklenir')
        self.assertEqual(rows[0]['done_qty'], 0, 'okutulmamış replacement 0 görünmeli')

        repl.move_ids.packing_scanned_qty = 1
        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        rows = [i for i in res['items'] if i['picking_id'] == repl.id]
        self.assertEqual(rows[0]['done_qty'], 1)

    # ─── KK-A7.3: all_matched ──────────────────────────
    def test_a73_soft_match_all_matched_uses_scanned_counter(self):
        """Replacement yokken iptal satırı soft-match edilir; rezervli ama okutulmamış
        diğer satır varken tüm rota 'eşleşti' sayılmamalı."""
        _orig, batch = self._orig_with_cancelled_x('SO-SOFT')
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertTrue(res.get('soft_match'), res)
        self.assertFalse(res['all_matched'], 'okutulmamış satır varken tümü eşleşmiş sayılmamalı')

    def test_a73_replacement_match_all_matched_uses_scanned_counter(self):
        _orig, batch = self._orig_with_cancelled_x('SO-RDONE')
        self._replacement_x('SO-RDONE', done=True)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertTrue(res.get('replacement_match'), res)
        self.assertFalse(res['all_matched'])

    # ─── İnceleme Ö-1: rotadaki replacement soft match'e düşmez ───
    def _routed_replacement_x(self, origin, wave=0):
        """Replacement başka bir rotada (R2), rezervi tam (A7: FAZ 5 sıfırlamaz)."""
        repl = self._replacement_x(origin)
        repl.move_ids.wave_collected_qty = wave
        other_batch = self._route(repl)
        repl.batch_schedule_time = fields.Datetime.now()
        return repl, other_batch

    def test_review_o1_replacement_in_other_route_not_soft_matched(self):
        """R2 henüz toplamadı: R1 paketlemesi 'eşleşti' demez, 'rota toplanmamış' hatası verir."""
        _orig, batch = self._orig_with_cancelled_x('SO-O1A')
        repl, _r2 = self._routed_replacement_x('SO-O1A')
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertFalse(res.get('soft_match'), res)
        self.assertFalse(res.get('success'), res)
        self.assertTrue(res.get('not_collected'), res)
        self.assertEqual(repl.move_ids.packing_scanned_qty, 0)
        self.nebim.assert_not_called()
        self.assertNotIn(repl, batch.all_picking_ids, 'hata dönüşünde rotaya eklenmemeli')

    def test_review_o1_replacement_removed_from_route_not_soft_matched(self):
        """Rotada hiç toplanamayıp çıkarılan (batch_id boş, rotadan geçmiş) replacement da aynı."""
        _orig, batch = self._orig_with_cancelled_x('SO-O1B')
        repl, _r2 = self._routed_replacement_x('SO-O1B')
        repl.batch_id = False
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertFalse(res.get('soft_match'), res)
        self.assertTrue(res.get('not_collected'), res)
        self.assertNotIn(repl, batch.all_picking_ids, 'hata dönüşünde rotaya eklenmemeli')

    def test_review_o1_collected_routed_replacement_counts_scan(self):
        """R2 toplandı (wave 1): okutma replacement sayacına yazılır, soft match değil."""
        _orig, batch = self._orig_with_cancelled_x('SO-O1C')
        repl, _r2 = self._routed_replacement_x('SO-O1C', wave=1)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertTrue(res.get('success'), res)
        self.assertFalse(res.get('soft_match'), res)
        self.assertEqual(res.get('picking_id'), repl.id)
        self.assertEqual(repl.move_ids.packing_scanned_qty, 1)
        self.assertIn(repl, batch.all_picking_ids, 'başarılı okutmada rotaya eklenir')

    def test_review_o1_unrouted_reserved_replacement_keeps_soft_match(self):
        """Koruma (eski davranış): rotaya hiç girmemiş, Odoo'nun rezerve ettiği replacement soft match."""
        _orig, batch = self._orig_with_cancelled_x('SO-O1D')
        repl = self._replacement_x('SO-O1D')
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-X')
        self.assertTrue(res.get('soft_match'), res)
        self.assertEqual(repl.move_ids.packing_scanned_qty, 0)

    # ─── KK-A7.5 ───────────────────────────────────────
    def test_a75_packing_completion_validates_via_scanned_counter(self):
        """Son okutmada doğrulama _apply_collected_quantities(picking, 'packing_scanned_qty') ile."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        original = BarcodeApiBase._apply_collected_quantities
        with patch.object(BarcodeApiBase, '_apply_collected_quantities', autospec=True,
                          side_effect=original) as spy:
            first = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-1')
            self.assertTrue(first.get('success'), first)
            self.assertNotEqual(picking.state, 'done')
            last = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-1')
            self.assertTrue(last.get('success'), last)

        fields_used = [
            (c.args[2] if len(c.args) > 2 else c.kwargs.get('qty_field', 'wave_collected_qty'))
            for c in spy.call_args_list]
        self.assertIn('packing_scanned_qty', fields_used,
                      'paketleme doğrulaması okutulan sayaçtan yazılmalı')
        picking.invalidate_recordset()
        self.assertEqual(picking.state, 'done')
        self.assertTrue(picking.packing_done)
        self.assertEqual(self._shipped_qty(picking), 2)
        self.assertEqual(self._qty(self.prod, self.shelf), 3, 'depodan yalnız 2 adet düşmeli')

    def test_a75_scanned_counter_one_ships_one(self):
        """packing_scanned_qty=1 ile aynı doğrulama yolu: 1 sevk edilir, rezerve 2 değil."""
        picking, _batch = self._reserved_route(demand=2, wave=2)
        picking.move_ids.packing_scanned_qty = 1
        _total, partial = self.api._apply_collected_quantities(picking, 'packing_scanned_qty')
        self.assertTrue(partial)
        self.assertTrue(self.api._safe_validate_picking(picking, backorder=True))
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1)

    # ─── RG-1 ──────────────────────────────────────────
    def test_rg1_old_style_zero_quantity_route_completes(self):
        """Deploy öncesi açılmış rota (quantity = 0): toplama kapanır, paketleme toplanan
        kadar sevk eder."""
        picking, batch = self._reserved_route(demand=2, wave=2)
        picking.move_ids.quantity = 0
        self.assertEqual(picking.move_ids.quantity, 0)

        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertNotEqual(picking.state, 'done')

        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 2)
        self.assertEqual(batch.state, 'done')

    def test_rg1_partial_with_skip_creates_backorder(self):
        """Eksik işaretleme: 3'ten 1 toplandı -> Tamamla doğrulamaz; paketlemede 1 okutma
        siparişi tamamlar: 1 sevk, 2 için bekleyen sevkiyat."""
        picking, batch = self._reserved_route(demand=3, wave=0)
        picking.move_ids.write({'wave_collected_qty': 1, 'wave_skipped': True})

        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertNotEqual(picking.state, 'done')
        self.assertEqual(res.get('backorder_pickings'), [])

        scan = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='RR-1')
        self.assertTrue(scan.get('success'), scan)
        self.assertTrue(scan['complete'], 'Eksik satır toplanan kadar okutulunca tamam')
        self.assertTrue(scan['picking_completed'])
        self.assertTrue(scan['all_matched'])
        self.assertEqual(picking.state, 'done')
        self.assertEqual(self._shipped_qty(picking), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)

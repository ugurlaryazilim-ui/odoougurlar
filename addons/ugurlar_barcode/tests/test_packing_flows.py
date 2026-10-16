"""G6 + G7 / KK-B2, B3.1, B3.3, B4.1, B4.2, B5, B6, RG-2: paketleme akışları.

`_trigger_nebim_sync` taklit edilir (çağrı sayısı ve savepoint derinliği izlenir);
`button_validate` seçili picking için hata verecek şekilde yamalanır.
"""
import base64
import re
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import packing_api
from odoo.addons.ugurlar_barcode.tests.common import PackingCase

ERR = 'Test doğrulama hatası'
# 1x1 PNG
PNG = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f'
    b'\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00'
    b'\x00\x00\x00IEND\xaeB`\x82')


class PackingFlowCase(PackingCase):
    """Ortak kurulum: iki ürün, raf, Nebim taklidi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod_a = cls._new_product('Paket Ürünü A', 'PK-A')
        cls.prod_b = cls._new_product('Paket Ürünü B', 'PK-B')
        cls.shelf = cls._new_shelf('PK-RAF', 'PK-RAF-1')

    def setUp(self):
        super().setUp()
        nebim = patch.object(packing_api.PackingApiController, '_trigger_nebim_sync')
        self.nebim = nebim.start()
        self.addCleanup(nebim.stop)
        self.nebim_depths = []
        self.nebim.side_effect = lambda *a, **k: self.nebim_depths.append(self.sp_depth[0])

    def _routed(self, product, demand, wave, origin=None, skipped=False, scanned=0):
        """Rezervi tam (quantity = talep), toplanan = wave olan giden picking."""
        self._add_stock(product, self.shelf, demand + 3)
        picking = self._picking(product, demand, origin=origin)
        picking.move_ids.write({
            'wave_collected_qty': wave, 'wave_skipped': skipped, 'packing_scanned_qty': scanned})
        return picking

    def _with_cancelled(self, cancelled_product, demand=1, origin=None):
        """Picking: `cancelled_product` iptal edilmiş move + aktif ürün B (rotaya girebilsin
        diye picking tümden iptal olmaz). Returns (picking, iptal move)."""
        self._add_stock(self.prod_b, self.shelf, 5)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.out_type.id, 'partner_id': self.customer.id,
            'location_id': self.stock.id, 'location_dest_id': self.loc_customers.id,
            'origin': origin or False,
            'move_ids': [(0, 0, {
                'product_id': prod.id, 'product_uom_qty': qty, 'product_uom': prod.uom_id.id,
                'location_id': self.stock.id, 'location_dest_id': self.loc_customers.id,
            }) for prod, qty in ((cancelled_product, demand), (self.prod_b, 1))],
        })
        picking.action_confirm()
        picking.action_assign()
        cancelled = picking.move_ids.filtered(lambda m: m.product_id == cancelled_product)
        cancelled._action_cancel()
        (picking.move_ids - cancelled).write({'wave_collected_qty': 1})
        self.assertEqual(cancelled.state, 'cancel')
        return picking, cancelled

    def _nebim_pickings(self):
        return [c.args[0] for c in self.nebim.call_args_list]

    def _snapshot(self, picking):
        picking.invalidate_recordset()
        picking.move_ids.invalidate_recordset()
        return {
            'state': picking.state, 'packing_done': picking.packing_done,
            'label_printed': picking.label_printed,
            'moves': [(m.id, m.state, m.quantity, m.picked, m.packing_scanned_qty)
                      for m in picking.move_ids],
        }


@tagged('post_install', '-at_install')
class TestPackingSelection(PackingFlowCase):
    """KK-B2: okutma, toplanan miktarı dolmamış siparişe işlenir."""

    def _assert_caps(self, pickings):
        for move in pickings.move_ids:
            move.invalidate_recordset()
            cap = min(move.product_uom_qty, move.wave_collected_qty)
            self.assertLessEqual(move.packing_scanned_qty, cap,
                                 'okutulan, min(talep, toplanan) değerini aşmamalı')

    def test_b2_scan_goes_to_collected_order_when_first_is_missing(self):
        s1 = self._routed(self.prod_a, 1, wave=0, origin='SO-B2-1', skipped=True)
        s2 = self._routed(self.prod_a, 1, wave=1, origin='SO-B2-2')
        batch = self._route(s1 | s2)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(s2.move_ids.packing_scanned_qty, 1, "okutma S2'ye işlenmeli")
        self.assertEqual(s1.move_ids.packing_scanned_qty, 0)
        self.assertEqual(res['picking_id'], s2.id)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertFalse(res.get('success'), 'sınır dolunca okutma başarılı sayılmamalı')
        self.assertTrue(res.get('error') or res.get('warning'), res)
        self.assertEqual(s1.move_ids.packing_scanned_qty, 0)
        self._assert_caps(s1 | s2)

    def test_b2_partial_first_order_cap_overflows_to_next_order(self):
        s1 = self._routed(self.prod_a, 2, wave=1, origin='SO-B2-3', skipped=True)
        s2 = self._routed(self.prod_a, 2, wave=2, origin='SO-B2-4')
        batch = self._route(s1 | s2)

        for expected in (1, 2, 3):
            res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
            self.assertTrue(res.get('success'), '%s. okutma başarılı olmalı: %s' % (expected, res))
            self._assert_caps(s1 | s2)
        self.assertEqual(s1.move_ids.packing_scanned_qty, 1)
        self.assertEqual(s2.move_ids.packing_scanned_qty, 2)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertFalse(res.get('success'), res)
        self.assertTrue(res.get('error') or res.get('warning'), res)
        self._assert_caps(s1 | s2)
        self.assertEqual(s1.move_ids.packing_scanned_qty, 1)
        self.assertEqual(s2.move_ids.packing_scanned_qty, 2)

    def test_b2_uncollected_only_still_reports_not_collected(self):
        """Hiçbir sipariş toplanmadıysa mevcut 'henüz toplanmamış' hatası korunur."""
        s1 = self._routed(self.prod_a, 1, wave=0, origin='SO-B2-5', skipped=True)
        batch = self._route(s1)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('error'), res)
        self.assertEqual(s1.move_ids.packing_scanned_qty, 0)

    def test_b2_soft_match_not_used_when_active_move_exists(self):
        """Ürünün aktif move'u (kapasitesi dolu) varken iptal move'u soft match sayılmaz."""
        full = self._routed(self.prod_a, 1, wave=1, origin='SO-B2-6', scanned=1)
        other, cancelled = self._with_cancelled(self.prod_a, origin='SO-B2-7')
        batch = self._route(full | other)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertFalse(res.get('soft_match'), res)
        self.assertFalse(res.get('success'), res)
        self.assertEqual(cancelled.packing_scanned_qty, 0)
        self.nebim.assert_not_called()


@tagged('post_install', '-at_install')
class TestPackingValidateSavepoint(PackingFlowCase):
    """KK-B3.1, B3.2, B3.3: doğrulama hatası picking başına izole edilir."""

    def _bad_good(self):
        """P1: talep 2, toplanan 1 (Eksik) -> doğrulaması hata verir. P2: tam, sağlam."""
        p1 = self._routed(self.prod_a, 2, wave=1, skipped=True, origin='SO-B3-1')
        p2 = self._routed(self.prod_b, 1, wave=1, origin='SO-B3-2')
        batch = self._route(p1 | p2)
        return p1, p2, batch

    # ─── packing_complete ──────────────────────────────
    def test_b31_complete_rolls_back_failed_picking_and_finishes_other(self):
        p1, p2, batch = self._bad_good()
        before = self._snapshot(p1)
        self.assertEqual(before['moves'][0][2], 2, 'ön koşul: rezerv 2')
        self.assertFalse(before['moves'][0][3], 'ön koşul: picked False')
        broken = self._break_validate(p1, ERR)

        res = self.pack_ctl.packing_complete(batch_id=batch.id)

        self.assertGreaterEqual(broken['calls'], 1, 'ön koşul: P1 doğrulaması denendi')
        self.assertEqual(self._snapshot(p1), before,
                         'hatalı picking: quantity/picked/packing_done/etiket çağrı öncesine dönmeli')
        self.assertNotEqual(p1.state, 'done')
        self.assertEqual(p2.state, 'done', 'diğer picking tamamlanmalı')
        self.assertEqual(res['validated'], 1)
        self.assertFalse(res['success'])
        self.assertEqual(len(res['errors']), 1, res)
        self.assertIn(p1.name, res['errors'][0])
        self.assertIn(ERR, res['errors'][0])

    def test_b31_complete_nebim_runs_only_for_done_picking_outside_savepoint(self):
        p1, p2, batch = self._bad_good()
        self._break_validate(p1, ERR)
        self.pack_ctl.packing_complete(batch_id=batch.id)
        called = self._nebim_pickings()
        self.assertNotIn(p1, called, 'başarısız picking için Nebim çalışmamalı')
        self.assertEqual(called, [p2])
        self.assertEqual(self.nebim_depths, [0], '_trigger_nebim_sync savepoint içinde çağrılmamalı')

    def test_b31_failed_picking_can_be_completed_after_fix(self):
        p1, p2, batch = self._bad_good()
        broken = self._break_validate(p1, ERR)
        self.pack_ctl.packing_complete(batch_id=batch.id)
        broken['ids'].clear()
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual(p1.state, 'done')
        self.assertEqual(res['errors'], [])
        self.assertIn(p1, self._nebim_pickings())

    # ─── packing_backorder ─────────────────────────────
    def test_b31_backorder_failure_rolls_back_and_reports_error_text(self):
        p = self._routed(self.prod_a, 3, wave=3, origin='SO-B3-3', scanned=1)
        self._route(p)
        before = self._snapshot(p)
        self._break_validate(p, ERR)

        res = self.pack_ctl.packing_backorder(picking_id=p.id)

        self.assertIn(ERR, res.get('error', ''), res)
        self.assertEqual(self._snapshot(p), before, 'doğrulama yazımları geri alınmalı')
        self.assertNotEqual(p.state, 'done')
        self.assertFalse(self.env['stock.picking'].search([('backorder_id', '=', p.id)]))
        self.nebim.assert_not_called()

    def test_rg2_backorder_ships_scanned_quantity_and_opens_backorder(self):
        p = self._routed(self.prod_a, 3, wave=3, origin='SO-B3-4', scanned=1)
        self._route(p)
        res = self.pack_ctl.packing_backorder(picking_id=p.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(p.state, 'done')
        self.assertEqual(self._shipped_qty(p), 1)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', p.id)])
        self.assertEqual(sum(backorder.move_ids.mapped('product_uom_qty')), 2)

    # ─── packing_scan (KK-B3.3) ────────────────────────
    def test_b33_scan_validate_failure_keeps_counter_rolls_back_validation(self):
        p = self._routed(self.prod_a, 2, wave=2, origin='SO-B3-5', scanned=1)
        batch = self._route(p)
        before = self._snapshot(p)
        self._break_validate(p, ERR)

        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')

        self.assertTrue(res.get('success'), 'okutma sayılmalı: %s' % res)
        self.assertIn(ERR, res.get('validate_error', ''), res)
        after = self._snapshot(p)
        self.assertEqual(p.move_ids.packing_scanned_qty, 2, 'sayaç okutma öncesinden 1 fazla')
        self.assertEqual(after['state'], before['state'])
        self.assertNotEqual(p.state, 'done')
        self.assertFalse(after['packing_done'], 'packing_done geri alınmalı')
        self.assertFalse(after['label_printed'], 'etiket bayrağı yazılmamalı')
        self.assertEqual([m[3] for m in after['moves']], [False], 'picked geri alınmalı')
        self.assertEqual([m[2] for m in after['moves']], [2], 'quantity geri alınmalı')
        self.nebim.assert_not_called()

    def test_b33_scan_failure_then_complete_validates_picking(self):
        p = self._routed(self.prod_a, 2, wave=2, origin='SO-B3-6', scanned=1)
        batch = self._route(p)
        broken = self._break_validate(p, ERR)
        self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        broken['ids'].clear()

        res = self.pack_ctl.packing_complete(batch_id=batch.id)

        self.assertEqual(p.state, 'done', res)
        self.assertEqual(res['errors'], [])
        self.assertEqual(self._nebim_pickings(), [p])

    def test_b33_scan_without_failure_has_no_validate_error(self):
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-B3-7')
        batch = self._route(p)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertFalse(res.get('validate_error'))

    def test_b32_scan_nebim_outside_savepoint(self):
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-B3-8')
        batch = self._route(p)
        self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertEqual(self.nebim_depths, [0], '_trigger_nebim_sync savepoint içinde çağrılmamalı')

    # ─── RG-2 ──────────────────────────────────────────
    def test_rg2_single_scan_flow_validates_labels_and_sends_once(self):
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-RG2-1')
        batch = self._route(p)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res['picking_completed'])
        self.assertEqual(p.state, 'done')
        self.assertEqual(self._shipped_qty(p), 1)
        self.assertTrue(p.packing_done)
        self.assertTrue(p.label_printed)
        self.assertEqual(self._nebim_pickings(), [p], 'Nebim bir kez çağrılmalı')

    def test_rg2_complete_happy_path_two_pickings(self):
        p1 = self._routed(self.prod_a, 1, wave=1, origin='SO-RG2-2')
        p2 = self._routed(self.prod_b, 2, wave=2, origin='SO-RG2-3')
        batch = self._route(p1 | p2)
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertTrue(res['success'], res)
        self.assertEqual((res['validated'], res['errors']), (2, []))
        self.assertEqual((p1.state, p2.state), ('done', 'done'))
        self.assertEqual(sorted(p.id for p in self._nebim_pickings()), sorted([p1.id, p2.id]))

    def test_rg2_undo_decrements_counter_and_clears_label_flag(self):
        p = self._routed(self.prod_a, 2, wave=2, origin='SO-RG2-4', scanned=1)
        p.label_printed = True
        res = self.pack_ctl.packing_undo(picking_id=p.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(p.move_ids.packing_scanned_qty, 0)
        self.assertFalse(p.label_printed)
        res = self.pack_ctl.packing_undo(picking_id=p.id, barcode='PK-A')
        self.assertTrue(res.get('error'), 'okutulmuş miktar yokken geri alma hata vermeli')


@tagged('post_install', '-at_install')
class TestPackingDetailReadOnly(PackingFlowCase):
    """KK-B4.1, B4.2: packing_batch_detail yazmaz ve toplu sorgu kullanır."""

    def _cancelled_order_batch(self):
        """Rota: sağlam sipariş (P) + iptal edilmiş satış siparişinin picking'i (C)."""
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.prod_b.id, 'product_uom_qty': 1, 'price_unit': 5.0})],
        })
        sale.write({'state': 'cancel'})
        c = self._routed(self.prod_b, 1, wave=1, origin=sale.name)
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-B4-OK')
        return p, c, self._route(p | c)

    def test_b41_detail_does_not_change_any_state(self):
        p, c, batch = self._cancelled_order_batch()
        # ayrıca iptal move'lu + yedek (replacement) picking'li sipariş
        orig, _cancelled = self._with_cancelled(self.prod_a, origin='SO-B4-REP')
        repl = self._routed(self.prod_a, 1, wave=0, origin='SO-B4-REP')
        batch.all_picking_ids = [(4, orig.id)]
        pickings = p | c | orig | repl
        before = {x.id: self._snapshot(x) for x in pickings}

        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)

        self.assertNotIn('error', res, res)
        self.assertEqual({x.id: self._snapshot(x) for x in pickings}, before,
                         'packing_batch_detail hiçbir picking/move durumunu değiştirmemeli')
        self.assertNotEqual(c.state, 'cancel')
        self.assertNotIn(c.id, [i['picking_id'] for i in res['items']],
                         "iptal siparişin picking'i listeden çıkmalı")
        self.assertIn(p.id, [i['picking_id'] for i in res['items']])

    def test_b41_scan_ignores_cancelled_order_picking(self):
        """Sözleşme G7 eki: detay artık iptal etmediği için açık kalan iptal-sipariş
        picking'i okutulup doğrulanmamalı (mal sevk edilirdi)."""
        p, c, batch = self._cancelled_order_batch()
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-B')
        self.assertFalse(res.get('success'), res)
        self.assertTrue(res.get('error'), res)
        self.assertEqual(c.move_ids.packing_scanned_qty, 0)
        self.assertNotEqual(c.state, 'done')
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res.get('all_matched'), 'iptal siparişin picking\'i all_matched\'i bozmamalı')
        self.assertNotEqual(batch.state, 'done', "iptal siparişin açık picking'i varken rota kapanmaz")

    def test_b41_cancellation_still_happens_in_complete(self):
        p, c, batch = self._cancelled_order_batch()
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        self.assertEqual(c.state, 'cancel', "iptal siparişin picking'i packing_complete'te iptal olur")
        self.assertEqual(p.state, 'done')
        self.assertEqual(res['validated'], 1)

    def test_b42_no_picking_search_per_cancelled_move(self):
        """İptal move'ların yedek araması döngüde değil, en çok tek sorguyla yapılır."""
        pickings = self.env['stock.picking']
        for i in range(4):
            orig, _cancelled = self._with_cancelled(self.prod_a, origin='SO-B42-%s' % i)
            pickings |= orig
        batch = self._route(pickings)
        picking_cls = type(self.env['stock.picking'])
        original = picking_cls.search
        calls = []

        def counting(rec, *args, **kwargs):
            calls.append(args)
            return original(rec, *args, **kwargs)

        with patch.object(picking_cls, 'search', counting):
            res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        self.assertLessEqual(
            len(calls), 1,
            'stock.picking.search çağrısı iptal move sayısıyla artmamalı (%s çağrı)' % len(calls))

    def test_b42_has_image_flag_still_correct(self):
        self.prod_a.image_1920 = PNG
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-B42-IMG1')
        q = self._routed(self.prod_b, 1, wave=1, origin='SO-B42-IMG2')
        batch = self._route(p | q)
        res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
        flags = {i['product_id']: i['has_image'] for i in res['items']}
        self.assertTrue(flags[self.prod_a.id])
        self.assertFalse(flags[self.prod_b.id])


@tagged('post_install', '-at_install')
class TestPackingLabelNote(PackingFlowCase):
    """KK-B5: etiket verisi yazmaz; yazdırma bildirilince picking'e tek not düşer."""

    NOTE = re.compile(r'Kargo Etiketi Yazd[ıi]r[ıi]ld[ıi]')

    def _product_notes(self, product):
        return self.env['mail.message'].search_count([
            ('model', '=', 'product.product'), ('res_id', '=', product.id),
            ('body', 'ilike', 'Kargo Etiketi')])

    def _picking_notes(self, picking):
        msgs = self.env['mail.message'].search([
            ('model', '=', 'stock.picking'), ('res_id', '=', picking.id)])
        return [m for m in msgs if self.NOTE.search(m.body or '')]

    def test_b5_label_data_only_reads(self):
        p = self._routed(self.prod_a, 2, wave=2, origin='SO-B5-1')
        res = self.pack_ctl.packing_label_data(picking_id=p.id, trigger_sync=False)
        self.assertEqual(res['picking_name'], p.name, 'etiket verisi korunmalı')
        self.assertEqual(res['total_qty'], 2)
        self.assertEqual(len(res['items']), 1)
        self.assertEqual(self._product_notes(self.prod_a), 0, "ürün chatter'ına yazılmamalı")
        self.assertEqual(self._picking_notes(p), [], 'log_print yokken picking notu da yazılmamalı')

    def test_b5_log_print_writes_single_picking_note(self):
        p = self._routed(self.prod_a, 2, wave=2, origin='SO-B5-2')
        self.pack_ctl.packing_label_data(picking_id=p.id, trigger_sync=False, log_print=True)
        self.assertEqual(len(self._picking_notes(p)), 1,
                         'picking\'e tek "Kargo Etiketi Yazdırıldı" notu düşmeli')
        self.assertEqual(self._product_notes(self.prod_a), 0)

    def test_b5_multi_line_picking_still_single_note(self):
        p = self._routed(self.prod_a, 1, wave=1, origin='SO-B5-3')
        self._add_stock(self.prod_b, self.shelf, 5)
        self.env['stock.move'].create({
            'product_id': self.prod_b.id, 'product_uom_qty': 1,
            'product_uom': self.prod_b.uom_id.id,
            'picking_id': p.id, 'location_id': p.location_id.id,
            'location_dest_id': p.location_dest_id.id})
        self.pack_ctl.packing_label_data(picking_id=p.id, trigger_sync=False, log_print=True)
        self.assertEqual(len(self._picking_notes(p)), 1)
        self.assertEqual(self._product_notes(self.prod_a) + self._product_notes(self.prod_b), 0)


@tagged('post_install', '-at_install')
class TestPackingSoftMatchLimit(PackingFlowCase):
    """KK-B6: iptal move'lu yumuşak eşleşme move miktarıyla sınırlı."""

    def _cancelled_only(self, demand=1, origin='SO-B6-1'):
        """Rota: ürün A yalnız iptal move'unda (yedeği yok) + aktif ürün B."""
        picking, move_a = self._with_cancelled(self.prod_a, demand=demand, origin=origin)
        return picking, move_a, self._route(picking)

    def test_b6_soft_match_limited_to_cancelled_move_quantity(self):
        _picking, move_a, batch = self._cancelled_only(demand=1)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res.get('soft_match'), res)
        for _ in range(2):
            res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
            self.assertFalse(res.get('success'), 'sonraki okutmalar hata vermeli: %s' % res)
            self.assertTrue(res.get('error') or res.get('warning'), res)
        move_a.invalidate_recordset()
        self.assertEqual(move_a.packing_scanned_qty, 1)

    def test_b6_soft_match_allows_up_to_demand(self):
        _picking, move_a, batch = self._cancelled_only(demand=2, origin='SO-B6-2')
        for n in (1, 2):
            res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
            self.assertTrue(res.get('success') and res.get('soft_match'), '%s. okutma: %s' % (n, res))
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        self.assertFalse(res.get('success'), res)
        move_a.invalidate_recordset()
        self.assertEqual(move_a.packing_scanned_qty, 2)

    def test_b6_list_row_follows_cancelled_move_counter(self):
        """Tasarım G7: iptal move'u satırının scanned_qty / matched değeri sayaçtan gelir."""
        _picking, move_a, batch = self._cancelled_only(demand=1, origin='SO-B6-3')

        def row():
            res = self.pack_ctl.packing_batch_detail(batch_id=batch.id)
            rows = [i for i in res['items'] if i['move_id'] == move_a.id]
            self.assertEqual(len(rows), 1, res['items'])
            return rows[0]

        first = row()
        self.assertEqual((first['scanned_qty'], first['matched']), (0, False))
        self.pack_ctl.packing_scan(batch_id=batch.id, barcode='PK-A')
        second = row()
        self.assertEqual((second['scanned_qty'], second['matched']), (1, True))

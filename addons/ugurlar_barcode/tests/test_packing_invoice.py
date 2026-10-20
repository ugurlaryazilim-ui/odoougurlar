"""G5 / KK-B1.1 - B1.3, RG-3: paketlemede fatura koşulu ve Nebim gönderimi.

Gerçek `_trigger_nebim_sync` çalışır; Nebim connector, fatura yükü ve `cr.commit` taklit edilir.
Toggle'lar `ir.config_parameter` ile açılır. Faturalar gerçek `sale.order._create_invoices`
ile kesilir (taklit yok).
"""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import packing_api
from odoo.addons.ugurlar_barcode.tests.common import PackingCase


@tagged('post_install', '-at_install')
class TestPackingInvoice(PackingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Fatura Ürünü', 'INV-1')

    def setUp(self):
        super().setUp()
        self.nebim = self._nebim_real()

    # ─── yardımcılar ───────────────────────────────────
    def _complete(self, picking, wave, skipped=False):
        """Picking'i kendi rotasında `packing_complete` ile tamamla."""
        picking.move_ids.write({'wave_collected_qty': wave, 'wave_skipped': skipped})
        batch = self._route(picking)
        res = self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertNotIn('error', res, res)
        return res

    def _first_shipment_then_backorder(self):
        """Sipariş 2 adet: ilk sevk 1 adet (Eksik) tamamlanır; backorder açıkken fatura
        kesilmez (kullanıcı kararı B, 2026-10-20). Returns (sale, backorder picking)."""
        sale, p1 = self._sale(self.prod, 2)
        self._complete(p1, wave=1, skipped=True)
        self.assertEqual(p1.state, 'done', 'ön koşul: ilk sevk tamam')
        self.assertEqual(len(self._out_invoices(sale)), 0, 'backorder açıkken fatura yok')
        self.assertEqual(self.nebim['posts'], 0)
        backorder = (sale.picking_ids - p1).filtered(lambda p: p.state not in ('done', 'cancel'))
        self.assertEqual(len(backorder), 1, 'ön koşul: backorder sevki var')
        backorder.action_assign()
        self.assertEqual(backorder.move_ids.product_uom_qty, 1)
        return sale, backorder

    # ─── KK-B1.1 (kullanıcı kararı B ile değişti: önceden ilk sevk faturalanıyor, backorder
    # faturası elle kesiliyordu; artık tek fatura backorder kapanınca) ───
    def test_b11_single_invoice_after_backorder_shipped(self):
        sale, backorder = self._first_shipment_then_backorder()
        self._complete(backorder, wave=1)
        self.assertEqual(backorder.state, 'done')
        sale.invalidate_recordset(['invoice_status'])
        self.assertEqual(sale.invoice_status, 'invoiced')
        invoices = self._out_invoices(sale)
        self.assertEqual(len(invoices), 1, 'sipariş başına tek fatura')
        self.assertEqual(sum(invoices.invoice_line_ids.mapped('quantity')), 2)
        self.assertEqual(self.nebim['posts'], 1)

    # ─── KK-B1.2 ───────────────────────────────────────
    def test_b12_second_complete_call_creates_no_extra_invoice(self):
        sale, backorder = self._first_shipment_then_backorder()
        batch = self._route(backorder)
        backorder.move_ids.wave_collected_qty = 1
        self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual(backorder.state, 'done')
        self.assertEqual(len(self._out_invoices(sale)), 1)
        posts = self.nebim['posts']
        # aynı tamamlama tekrar: picking done, Nebim yeniden denenir ama fatura oluşmaz
        self.pack_ctl.packing_complete(batch_id=batch.id)
        self.pack_ctl.packing_complete(batch_id=batch.id)
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.assertEqual(self.nebim['posts'], posts, 'gönderilmiş fatura tekrar gönderilmemeli')

    def test_b12_fully_invoiced_order_gets_no_new_invoice(self):
        sale, picking = self._sale(self.prod, 2)
        self._complete(picking, wave=2)
        sale.invalidate_recordset(['invoice_status'])
        self.assertEqual(sale.invoice_status, 'invoiced')
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.pack_ctl._trigger_nebim_sync(picking)
        self.pack_ctl._trigger_nebim_sync(picking)
        self.assertEqual(len(self._out_invoices(sale)), 1)
        self.assertEqual(self.nebim['posts'], 1)

    def test_b12_nothing_to_invoice_creates_no_invoice(self):
        """invoice_status == 'no': teslim edilmemiş, teslimata göre faturalanan sipariş."""
        sale, picking = self._sale(self.prod, 2)
        sale.invalidate_recordset(['invoice_status'])
        self.assertEqual(sale.invoice_status, 'no', 'ön koşul')
        self.pack_ctl._trigger_nebim_sync(picking)
        self.assertEqual(len(self._out_invoices(sale)), 0)
        self.assertEqual(self.nebim['posts'], 0)

    def test_b12_existing_draft_invoice_is_posted_not_duplicated(self):
        """Taslak fatura varken ikinci fatura kesilmez; taslak onaylanıp gönderilir (R5)."""
        sale, picking = self._sale(self.prod, 2)
        picking.move_ids.write({'wave_collected_qty': 2})
        self.pack_ctl._apply_collected_quantities(picking)
        self.assertTrue(self.pack_ctl._safe_validate_picking(picking))
        draft = sale._create_invoices()
        self.assertEqual(draft.state, 'draft')
        self.pack_ctl._trigger_nebim_sync(picking)
        invoices = self._out_invoices(sale)
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices.state, 'posted')
        self.assertTrue(invoices.nebim_sent)

    # ─── KK-B1.3 ───────────────────────────────────────
    def test_b13_refund_is_never_sent_to_nebim(self):
        sale, picking = self._sale(self.prod, 2)
        self._complete(picking, wave=2)
        refund = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.customer.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.prod.id, 'quantity': 1, 'price_unit': 10.0,
                'sale_line_ids': [(6, 0, sale.order_line.ids)]})],
        })
        refund.action_post()
        sale.invalidate_recordset(['invoice_ids'])
        self.assertIn(refund, sale.invoice_ids, 'ön koşul: iade siparişin faturaları arasında')
        self.assertEqual(refund.state, 'posted')
        self.assertFalse(refund.nebim_sent)

        self.pack_ctl._trigger_nebim_sync(picking)

        self.assertNotIn(refund.id, [inv.id for inv in self.nebim['sent']],
                         'out_refund için Nebim yükü hazırlanmamalı / gönderilmemeli')
        self.assertTrue(all(inv.move_type == 'out_invoice' for inv in self.nebim['sent']))
        refund.invalidate_recordset(['nebim_sent'])
        self.assertFalse(refund.nebim_sent, 'iade faturası nebim_sent olmamalı')

    def test_b13_draft_refund_is_not_auto_posted(self):
        """Sözleşme G5 S3: taslak iade paketlemede onaylanmaz (muhasebenin kararı)."""
        sale, picking = self._sale(self.prod, 2)
        self._complete(picking, wave=2)
        refund = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.customer.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.prod.id, 'quantity': 1, 'price_unit': 10.0,
                'sale_line_ids': [(6, 0, sale.order_line.ids)]})],
        })
        self.assertEqual(refund.state, 'draft', 'ön koşul')
        posts = self.nebim['posts']

        self.pack_ctl._trigger_nebim_sync(picking)

        refund.invalidate_recordset(['state', 'nebim_sent'])
        self.assertEqual(refund.state, 'draft', 'taslak iade otomatik onaylanmamalı')
        self.assertFalse(refund.nebim_sent)
        self.assertEqual(self.nebim['posts'], posts)

    # ─── RG-3 ──────────────────────────────────────────
    def test_rg3_commit_after_nebim_acceptance_and_outside_savepoint(self):
        sale, picking = self._sale(self.prod, 2)
        self._complete(picking, wave=2)
        invoice = self._out_invoices(sale)
        self.assertEqual(len(invoice), 1)
        self.assertTrue(self.nebim['commits'], 'Nebim kabulünden sonra commit yapılmalı')
        first = self.nebim['commits'][0]
        self.assertGreaterEqual(first['posts'], 1, "commit Nebim POST'undan sonra olmalı")
        self.assertIn(invoice.id, first['sent_ids'], 'commit anında fatura nebim_sent olmalı')
        for entry in self.nebim['commits']:
            self.assertEqual(entry['depth'], 0, 'cr.commit hiçbir savepoint bloğunda olmamalı')

    def test_rg3_sent_invoice_not_resent(self):
        sale, picking = self._sale(self.prod, 1)
        self._complete(picking, wave=1)
        self.assertEqual(self.nebim['posts'], 1)
        self.pack_ctl._trigger_nebim_sync(picking)
        self.pack_ctl._trigger_nebim_sync(picking)
        self.assertEqual(self.nebim['posts'], 1)

    def test_rg3_invoice_lock_busy_skips_sending(self):
        """Fatura başka işlemde gönderiliyor (`_nebim_try_lock` False): Nebim'e gitmez."""
        sale, picking = self._sale(self.prod, 1)
        picking.move_ids.write({'wave_collected_qty': 1})
        self.pack_ctl._apply_collected_quantities(picking)
        self.assertTrue(self.pack_ctl._safe_validate_picking(picking))
        with patch.object(type(self.env['account.move']), '_nebim_try_lock', return_value=False):
            self.pack_ctl._trigger_nebim_sync(picking)
        self.assertEqual(self.nebim['posts'], 0)
        invoices = self._out_invoices(sale)
        self.assertFalse(any(invoices.mapped('nebim_sent')))

    def test_rg3_sale_order_lock_busy_skips_invoicing(self):
        """sale_order `FOR UPDATE NOWAIT` alınamazsa faturalama diğer işleme bırakılır."""
        sale, picking = self._sale(self.prod, 1)
        picking.move_ids.write({'wave_collected_qty': 1})
        self.pack_ctl._apply_collected_quantities(picking)
        self.assertTrue(self.pack_ctl._safe_validate_picking(picking))
        cr = self.env.cr
        real_execute = cr.execute

        def busy(query, *args, **kwargs):
            if 'FOR UPDATE NOWAIT' in str(query) and 'sale_order' in str(query):
                raise Exception('could not obtain lock on row in relation "sale_order"')
            return real_execute(query, *args, **kwargs)

        with patch.object(cr, 'execute', busy):
            self.pack_ctl._trigger_nebim_sync(picking)
        self.assertEqual(len(self._out_invoices(sale)), 0)
        self.assertEqual(self.nebim['posts'], 0)

    def test_rg3_invoice_toggle_off_creates_nothing(self):
        self._nebim_real(invoice=False)
        sale, picking = self._sale(self.prod, 1)
        self._complete(picking, wave=1)
        self.assertEqual(len(self._out_invoices(sale)), 0)


# ── Dal B düzeltme R1 (Ö-B1) ──────────────────────────────
@tagged('post_install', '-at_install')
class TestPackingNebimGuard(PackingCase):
    """Ö-B1: etiket ucu doğrulanmamış picking için Nebim'i tetiklemez; senkron iptal
    siparişte hiçbir şey yapmaz."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('Koruma Ürünü', 'GRD-1')

    def setUp(self):
        super().setUp()
        self.nebim = self._nebim_real()

    def _order_policy_sale(self):
        """Siparişe göre faturalanan onaylı sipariş: sevk olmadan da 'to invoice'."""
        self.prod.product_tmpl_id.invoice_policy = 'order'
        self._add_stock(self.prod, self.stock, 5)
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.prod.id, 'product_uom_qty': 1, 'price_unit': 10.0})],
        })
        sale.action_confirm()
        picking = sale.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing')
        picking.action_assign()
        self.assertEqual(picking.state, 'assigned', 'ön koşul: picking doğrulanmamış')
        self.assertEqual(sale.invoice_status, 'to invoice', 'ön koşul: sipariş faturalanabilir')
        return sale, picking

    def test_rb1_label_data_does_not_sync_undone_picking(self):
        sale, picking = self._order_policy_sale()
        res = self.pack_ctl.packing_label_data(picking_id=picking.id)
        self.assertNotIn('error', res, res)
        self.assertEqual(picking.state, 'assigned')
        self.assertFalse(self._out_invoices(sale), 'doğrulanmamış picking için fatura kesilmemeli')
        self.assertEqual(self.nebim['posts'], 0, "Nebim'e gönderim olmamalı")

    def test_rb1_sync_skips_cancelled_order(self):
        sale, picking = self._order_policy_sale()
        sale.write({'state': 'cancel'})  # picking packing_complete'e kadar açık kalır (G7)
        with patch.object(packing_api, '_extract_marketplace_info',
                          wraps=packing_api._extract_marketplace_info) as mp:
            self.pack_ctl._trigger_nebim_sync(picking)
        mp.assert_not_called()
        self.assertFalse(self._out_invoices(sale))
        self.assertEqual(self.nebim['posts'], 0)

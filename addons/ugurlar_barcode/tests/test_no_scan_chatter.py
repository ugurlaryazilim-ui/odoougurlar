"""H4: okutma/raf/sayım/operasyon uçları ürün chatter'ına mesaj yazmaz; iz
`ugurlar.barcode.operation` kaydında kalır. Rota Tamamla rota üzerinde tek özet not yazar."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import (
    batch_api, counting_api, operations_api, packing_api, shelf_api)
from odoo.addons.ugurlar_barcode.tests.common import PackingCase


@tagged('post_install', '-at_install')
class TestNoScanChatter(PackingCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod_a = cls._new_product('Chatter Ürünü A', 'CH-A')
        cls.prod_b = cls._new_product('Chatter Ürünü B', 'CH-B')
        cls.shelf = cls._new_shelf('CH-RAF', 'CH-RAF-1')
        cls.shelf2 = cls._new_shelf('CH-RAF2', 'CH-RAF-2')

    def setUp(self):
        super().setUp()
        self._patch_request(batch_api, shelf_api, counting_api, operations_api)
        self.batch_ctl = batch_api.BatchApiController()
        self.shelf_ctl = shelf_api.ShelfApiController()
        self.count_ctl = counting_api.CountingApiController()
        self.ops_ctl = operations_api.OperationsApiController()
        # Nebim çağrısı bu testlerin konusu değil
        p = patch.object(packing_api.PackingApiController, '_trigger_nebim_sync')
        p.start()
        self.addCleanup(p.stop)

    # ─── yardımcılar ───────────────────────────────────
    def _msgs(self, record):
        return self.env['mail.message'].search_count([
            ('model', '=', record._name), ('res_id', '=', record.id)])

    def _ops(self, product, op_type):
        return self.env['ugurlar.barcode.operation'].search([
            ('product_id', '=', product.id), ('operation_type', '=', op_type)])

    def _routed(self, product, demand, wave):
        self._add_stock(product, self.shelf, demand + 3)
        picking = self._picking(product, demand)
        picking.move_ids.write({'wave_collected_qty': wave})
        return picking

    # ─── rota / paketleme okutma ───────────────────────
    def test_packing_scan_no_product_message_but_operation(self):
        p = self._routed(self.prod_a, 2, wave=2)
        batch = self._route(p)
        before = self._msgs(self.prod_a)
        res = self.pack_ctl.packing_scan(batch_id=batch.id, barcode='CH-A')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(self._msgs(self.prod_a), before, 'okutma ürün chatter mesajı yazmamalı')
        self.assertEqual(len(self._ops(self.prod_a, 'picking')), 1, 'iz operation kaydında')

    def test_batch_collect_scan_no_product_message_but_operation(self):
        p = self._routed(self.prod_a, 2, wave=0)
        batch = self._route(p)
        before = self._msgs(self.prod_a)
        res = self.batch_ctl.batch_collect_scan(batch_id=batch.id, barcode='CH-A')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._msgs(self.prod_a), before)
        self.assertEqual(len(self._ops(self.prod_a, 'picking')), 1)

    def test_batch_undo_no_product_message_but_operation(self):
        p = self._routed(self.prod_a, 2, wave=1)
        self._route(p)
        before = self._msgs(self.prod_a)
        res = self.batch_ctl.batch_undo(move_id=p.move_ids.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._msgs(self.prod_a), before)
        ops = self._ops(self.prod_a, 'picking')
        self.assertEqual(ops.mapped('quantity'), [-1], 'geri alma eksi miktarlı operasyon kaydı')

    def test_collect_complete_writes_single_batch_note(self):
        p = self._routed(self.prod_a, 2, wave=2)
        q = self._routed(self.prod_b, 1, wave=1)
        batch = self._route(p | q)
        before_a, before_b = self._msgs(self.prod_a), self._msgs(self.prod_b)
        before_batch = self._msgs(batch)
        res = self.batch_ctl.batch_collect_complete(batch_id=batch.id)
        self.assertTrue(res.get('success'), res)
        self.assertEqual((self._msgs(self.prod_a), self._msgs(self.prod_b)), (before_a, before_b),
                         'toplanan move başına ürün mesajı yazılmamalı')
        notes = self.env['mail.message'].search([
            ('model', '=', 'stock.picking.batch'), ('res_id', '=', batch.id),
            ('body', 'ilike', 'Toplama Tamamlandı')])
        self.assertEqual(len(notes), 1, 'rota üzerinde tek özet not')
        self.assertEqual(self._msgs(batch), before_batch + 1)
        for picking in (p, q):
            self.assertIn(picking.name, notes.body)

    # ─── raf ───────────────────────────────────────────
    def test_shelf_ops_no_product_message_but_operations(self):
        prod = self.prod_a
        before = self._msgs(prod)
        self.assertTrue(self.shelf_ctl.putaway(
            product_barcode='CH-A', shelf_barcode='CH-RAF-1', quantity=5).get('success'))
        self.assertTrue(self.shelf_ctl.remove_from_shelf(
            product_barcode='CH-A', shelf_barcode='CH-RAF-1', quantity=1).get('success'))
        self.assertTrue(self.shelf_ctl.shelf_transfer(
            product_barcode='CH-A', source_shelf_barcode='CH-RAF-1',
            target_shelf_barcode='CH-RAF-2', quantity=2, reason='damage').get('success'))
        self.assertTrue(self.shelf_ctl.shelf_move_all(
            source_barcode='CH-RAF-2', target_barcode='CH-RAF-1', reason='season').get('success'))
        self.assertTrue(self.shelf_ctl.shelf_clear_all(shelf_barcode='CH-RAF-1').get('success'))
        self.assertEqual(self._msgs(prod), before, 'raf uçları ürün chatter mesajı yazmamalı')
        types = self.env['ugurlar.barcode.operation'].search(
            [('product_id', '=', prod.id)]).mapped('operation_type')
        self.assertEqual(sorted(types),
                         sorted(['putaway', 'remove', 'shelf_transfer', 'shelf_transfer', 'remove']))
        # Neden/kaynak bilgisi chatter yerine operasyon notunda
        transfer = self._ops(prod, 'shelf_transfer').filtered(
            lambda o: 'Hasar' in (o.notes or ''))
        self.assertEqual(len(transfer), 1)

    def test_bulk_putaway_no_product_message(self):
        before = self._msgs(self.prod_b)
        res = self.ops_ctl.bulk_scan(
            items=[{'barcode': 'CH-B', 'quantity': 3}], operation='putaway',
            shelf_barcode='CH-RAF-1')
        self.assertEqual(res['success_count'], 1, res)
        self.assertEqual(self._msgs(self.prod_b), before)
        self.assertEqual(len(self._ops(self.prod_b, 'putaway')), 1)

    # ─── sayım ─────────────────────────────────────────
    def test_count_save_no_product_message_but_operations(self):
        self._add_stock(self.prod_a, self.shelf, 4)
        # başka konumda negatif bakiye: düzeltme yolu da sınanır
        self._add_stock(self.prod_a, self.shelf2, -2)
        before = self._msgs(self.prod_a)
        res = self.count_ctl.count_save(
            shelf_barcode='CH-RAF-1', items=[{'barcode': 'CH-A', 'quantity': 6}])
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._msgs(self.prod_a), before, 'sayım ürün chatter mesajı yazmamalı')
        self.assertEqual(len(self._ops(self.prod_a, 'counting')), 1)
        self.assertEqual(len(self._ops(self.prod_a, 'count_adjustment')), 1)

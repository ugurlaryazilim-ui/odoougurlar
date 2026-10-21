from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'n11_integration')
class TestN11CancelScan(TransactionCase):
    """İptal taraması: sevk/fatura koruması, doğru sayaç, engelli kaydı her turda yeniden denememe."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # NEDEN: onay/iptal kancaları Nebim'e dış çağrı yapmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['n11.store'].create({'name': 'N11 Test', 'n11_app_key': 'x', 'n11_app_secret': 'y'})
        cls.product = cls.env['product.product'].create({
            'name': 'N11 Test Ürün', 'default_code': 'N11-CANCEL-1', 'type': 'consu', 'list_price': 100,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'N11 Test Müşteri'})
        cls.Sync = cls.env['n11.order']

    def _order(self, ref):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        so.action_confirm()
        pz = self.env['n11.order'].create({
            'store_id': self.store.id, 'order_id': ref, 'order_number': ref,
            'order_status': 'Cancelled', 'sale_order_id': so.id,
        })
        return pz, so

    def _ship(self, so):
        # NEDEN: gerçek sevk için stok/rezerv kurmak yerine picking durumunu doğrudan 'done' yapıyoruz
        self.assertTrue(so.picking_ids)
        self.env.cr.execute("UPDATE stock_picking SET state='done' WHERE id IN %s", (tuple(so.picking_ids.ids),))
        so.picking_ids.invalidate_recordset(['state'])

    def _age(self, pz, hours):
        self.env.cr.execute("UPDATE n11_order SET write_date = %s WHERE id = %s",
                            (fields.Datetime.subtract(fields.Datetime.now(), hours=hours), pz.id))
        pz.invalidate_recordset(['write_date'])

    def test_unshipped_order_is_cancelled_and_counted(self):
        pz, so = self._order('N11-C-1')
        self.assertEqual(self.Sync._cancel_pending_orders(self.store), 1)
        self.assertEqual(so.state, 'cancel')

    def test_shipped_order_is_not_cancelled_and_not_counted(self):
        pz, so = self._order('N11-C-2')
        self._ship(so)
        self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
        self.assertEqual(so.state, 'sale')
        self.assertIn('sevk edildiği', pz.error_message)
        self.assertTrue(pz.error_message.startswith('Otomatik iptal edilmedi'))

    def test_posted_invoice_blocks_cancel(self):
        pz, so = self._order('N11-C-3')
        invoice = so._create_invoices()
        invoice.action_post()
        self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
        self.assertEqual(so.state, 'sale')
        self.assertIn('faturası kesildiği', pz.error_message)

    def test_blocked_order_is_skipped_on_next_scan_and_warned_once(self):
        pz, so = self._order('N11-C-4')
        self._ship(so)
        self.Sync._cancel_pending_orders(self.store)
        msgs = len(so.message_ids)
        with patch.object(type(self.Sync), '_cancel_blocker', autospec=True) as blocker:
            self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
            blocker.assert_not_called()
        self.assertEqual(len(so.message_ids), msgs)

    def test_failed_cancel_is_marked_not_counted_and_retried_only_after_backoff(self):
        pz, so = self._order('N11-C-5')
        SO = type(self.env['sale.order'])
        with patch.object(SO, '_action_cancel', side_effect=UserError('boom')):
            self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
        self.assertIn('iptal hatası', pz.error_message)
        self.assertEqual(so.state, 'sale')
        with patch.object(SO, '_action_cancel') as action_cancel:
            self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
            action_cancel.assert_not_called()
        self._age(pz, 25)
        self.assertEqual(self.Sync._cancel_pending_orders(self.store), 1)
        self.assertEqual(so.state, 'cancel')
        self.assertFalse(pz.error_message)

    def test_auto_cancel_off_does_nothing(self):
        pz, so = self._order('N11-C-6')
        self.store.auto_cancel = False
        self.assertEqual(self.Sync._cancel_pending_orders(self.store), 0)
        self.assertEqual(so.state, 'sale')

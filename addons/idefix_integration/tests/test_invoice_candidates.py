from unittest.mock import MagicMock, patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'idefix_integration')
class TestIdefixInvoiceCandidates(TransactionCase):
    """Fatura adayı seçimi (açlık yok) ve _send_picking (SO yok / mesaj tekrarı)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # Fatura onayında Nebim'e gönderim yapılmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['idefix.store'].create({
            'name': 'Idefix Test', 'client_id': 'x', 'client_secret': 'y', 'vendor_id': '1',
            'auto_send_invoice': True,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Fatura Test Müşteri'})
        cls.product = cls.env['product.product'].create({'name': 'Fatura Test Ürün', 'list_price': 100})

    def _sale_order(self, invoice_state=None):
        """state='sale' SO; invoice_state verilirse tek satırlık müşteri faturası ('draft' ya da 'posted')."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        so.state = 'sale'
        if invoice_state:
            move = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.partner.id,
                'invoice_line_ids': [Command.create({
                    'product_id': self.product.id, 'quantity': 1, 'price_unit': 100,
                    'sale_line_ids': [Command.link(so.order_line.id)],
                })],
            })
            if invoice_state == 'posted':
                move.action_post()
        return so

    def _order_vals(self, so, number, status='shipment_ready'):
        return {
            'store_id': self.store.id, 'order_id': number, 'order_number': number,
            'sale_order_id': so.id if so else False, 'order_status': status, 'order_date': fields.Datetime.now(),
        }

    def _orders(self, so, count, prefix):
        return self.env['idefix.order'].create([self._order_vals(so, f'{prefix}{i}') for i in range(count)])

    def _run_pending(self):
        Order = self.env['idefix.order']
        with patch.object(type(Order), '_send_invoice_to_idefix', autospec=True, return_value=True) as sender:
            Order._send_pending_invoices(self.store, object())
        return [c.args[0] for c in sender.call_args_list]

    # ─── Aday seçimi ─────────────────────────────────────────

    def test_invoiced_order_selected_despite_many_uninvoiced(self):
        """200'den fazla faturasız kayıt varken faturalı yeni kayıt yine seçilir (eskiden aç kalırdı)."""
        self._orders(self._sale_order(), 205, 'NOINV')
        invoiced = self.env['idefix.order'].create(self._order_vals(self._sale_order('posted'), 'INV1'))
        self.assertEqual(self._run_pending(), [invoiced])

    def test_draft_invoice_not_selected(self):
        self.env['idefix.order'].create(self._order_vals(self._sale_order('draft'), 'DRAFT1'))
        self.assertEqual(self._run_pending(), [])

    def test_batch_limit_and_recent_attempt_skipped(self):
        """Başarılı yol: parti sınırı (10) korunur, yakın zamanda denenmiş kayıt atlanır."""
        orders = self._orders(self._sale_order('posted'), 12, 'BATCH')
        orders[0].invoice_attempt_date = fields.Datetime.now()
        sent = self._run_pending()
        self.assertEqual(len(sent), 10)
        self.assertNotIn(orders[0], sent)

    # ─── _send_picking ───────────────────────────────────────

    def _chatter_count(self, so, needle):
        return len(self.env['mail.message'].search([
            ('model', '=', 'sale.order'), ('res_id', '=', so.id), ('body', 'ilike', needle)]))

    def test_send_picking_without_sale_order_skips_api(self):
        order = self.env['idefix.order'].create(self._order_vals(None, 'NOSO1'))
        api = MagicMock()
        self.assertFalse(order._send_picking(api_client=api))
        api.update_shipment_status.assert_not_called()
        self.assertFalse(order.picking_sent)

    def test_action_send_picking_without_sale_order_raises(self):
        order = self.env['idefix.order'].create(self._order_vals(None, 'NOSO2'))
        with patch.object(type(self.store), 'get_api') as get_api, self.assertRaises(UserError):
            order.action_send_picking()
        get_api.assert_not_called()

    def test_send_picking_success(self):
        so = self._sale_order()
        order = self.env['idefix.order'].create(self._order_vals(so, 'OK1'))
        api = MagicMock()
        api.update_shipment_status.return_value = {'success': True}
        self.assertTrue(order._send_picking(api_client=api))
        api.update_shipment_status.assert_called_once_with('OK1', 'picking')
        self.assertTrue(order.picking_sent)
        self.assertEqual(order.order_status, 'shipment_picking')
        self.assertEqual(self._chatter_count(so, 'OK1'), 1)

    def test_send_picking_failure_message_only_when_error_changes(self):
        so = self._sale_order()
        order = self.env['idefix.order'].create(self._order_vals(so, 'FAIL1'))
        api = MagicMock()
        api.update_shipment_status.return_value = {'success': False, 'error': 'Hata A'}
        self.assertFalse(order._send_picking(api_client=api))
        self.assertFalse(order._send_picking(api_client=api))
        self.assertEqual(self._chatter_count(so, 'FAIL1'), 1)
        api.update_shipment_status.return_value = {'success': False, 'error': 'Hata B'}
        self.assertFalse(order._send_picking(api_client=api))
        self.assertEqual(self._chatter_count(so, 'FAIL1'), 2)
        # Hata A'ya dönüş de yeni bilgidir (son mesaj Hata B)
        api.update_shipment_status.return_value = {'success': False, 'error': 'Hata A'}
        order._send_picking(api_client=api)
        self.assertEqual(self._chatter_count(so, 'FAIL1'), 3)

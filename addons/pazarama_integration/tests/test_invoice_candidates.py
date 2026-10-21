from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'pazarama_integration')
class TestPazaramaInvoiceCandidates(TransactionCase):
    """Fatura gönderim adayları: 'onaylı fatura var' koşulu limit'ten önce uygulanmalı (açlık yok)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # Fatura onayında Nebim'e gönderim yapılmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['pazarama.store'].create({
            'name': 'Pazarama Test', 'client_id': 'x', 'client_secret': 'y', 'auto_send_invoice': True,
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

    def _order_vals(self, so, number):
        return {
            'store_id': self.store.id, 'order_id': number, 'order_number': number,
            'sale_order_id': so.id, 'order_status': 1, 'order_date': fields.Datetime.now(),
        }

    def _orders(self, so, count, prefix):
        return self.env['pazarama.order'].create([self._order_vals(so, f'{prefix}{i}') for i in range(count)])

    def _run_pending(self):
        Order = self.env['pazarama.order']
        with patch.object(type(Order), '_send_invoice_to_pazarama', autospec=True, return_value=True) as sender:
            Order._send_pending_invoices(self.store, object())
        return [c.args[0] for c in sender.call_args_list]

    def test_invoiced_order_selected_despite_many_uninvoiced(self):
        """200'den fazla faturasız kayıt varken faturalı yeni kayıt yine seçilir (eskiden aç kalırdı)."""
        self._orders(self._sale_order(), 205, 'NOINV')
        invoiced = self.env['pazarama.order'].create(self._order_vals(self._sale_order('posted'), 'INV1'))
        self.assertEqual(self._run_pending(), [invoiced])

    def test_draft_invoice_not_selected(self):
        self.env['pazarama.order'].create(self._order_vals(self._sale_order('draft'), 'DRAFT1'))
        self.assertEqual(self._run_pending(), [])

    def test_batch_limit_and_recent_attempt_skipped(self):
        """Başarılı yol: parti sınırı (10) korunur, yakın zamanda denenmiş kayıt atlanır."""
        orders = self._orders(self._sale_order('posted'), 12, 'BATCH')
        orders[0].invoice_attempt_date = fields.Datetime.now()
        sent = self._run_pending()
        self.assertEqual(len(sent), 10)
        self.assertNotIn(orders[0], sent)

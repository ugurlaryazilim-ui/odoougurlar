from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'trendyol_integration')
class TestTrendyolCancelGuard(TransactionCase):
    """Trendyol iptali: sevk/fatura koruması, savepoint, chatter'ın tek sefer düşmesi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # NEDEN: onay/iptal kancaları Nebim'e dış çağrı yapmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['trendyol.store'].create({
            'name': 'TY İptal Test', 'api_key': 'k', 'api_secret': 's', 'seller_id': '996',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'TY İptal Ürün', 'default_code': 'TY-CANCEL-1', 'type': 'consu', 'list_price': 100,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'TY İptal Müşteri'})
        cls.TO = cls.env['trendyol.order']

    def _order(self, ref, status='cancelled'):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        so.action_confirm()
        ty = self.TO.create({
            'store_id': self.store.id, 'trendyol_order_number': ref, 'shipment_package_id': ref + '-P',
            'trendyol_status': status, 'sale_order_id': so.id,
        })
        return ty, so

    def _ship(self, so):
        # NEDEN: gerçek sevk için stok/rezerv kurmak yerine picking durumunu doğrudan 'done' yapıyoruz
        self.assertTrue(so.picking_ids)
        self.env.cr.execute("UPDATE stock_picking SET state='done' WHERE id IN %s", (tuple(so.picking_ids.ids),))
        so.picking_ids.invalidate_recordset(['state'])

    def test_unshipped_order_is_cancelled(self):
        ty, so = self._order('TY-C-1')
        self.assertTrue(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'cancel')
        self.assertFalse(ty.error_message)

    def test_shipped_order_is_not_cancelled_and_warns_once(self):
        ty, so = self._order('TY-C-2')
        self._ship(so)
        self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'sale')
        self.assertIn('sevk edildiği', ty.error_message)
        msgs = len(so.message_ids)
        # her senkron turunda yeniden denenir ama chatter dolmaz
        self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(len(so.message_ids), msgs)
        self.assertEqual(so.state, 'sale')

    def test_posted_invoice_blocks_cancel(self):
        ty, so = self._order('TY-C-3')
        invoice = so._create_invoices()
        invoice.action_post()
        self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'sale')
        self.assertIn('faturası kesildiği', ty.error_message)

    def test_blocked_order_is_retried_and_cancelled_once_unblocked(self):
        ty, so = self._order('TY-C-4')
        with patch.object(type(self.TO), '_cancel_blocker', return_value='sevk edildiği'):
            self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertTrue(ty.error_message)
        self.assertTrue(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'cancel')
        self.assertFalse(ty.error_message)  # eski uyarı temizlenir

    def test_cancel_failure_is_contained_and_logged(self):
        ty, so = self._order('TY-C-5')
        SO = type(self.env['sale.order'])
        with patch.object(SO, '_action_cancel', side_effect=UserError('boom')):
            self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'sale')
        self.assertIn('iptal hatası', ty.error_message)
        self.assertTrue(self.TO._cancel_odoo_order(ty, self.store))
        self.assertEqual(so.state, 'cancel')

    def test_auto_cancel_off_does_nothing(self):
        ty, so = self._order('TY-C-6')
        self.store.auto_cancel = False
        self.assertFalse(self.TO._cancel_odoo_order(ty, self.store))
        self.assertFalse(self.TO._cancel_odoo_order(ty))  # mağaza verilmezse kayıttakinden
        self.assertEqual(so.state, 'sale')

    def test_sync_path_does_not_cancel_shipped_order(self):
        """Gerçek akış: iptal paketi gelince _process_package aynı korumadan geçer."""
        ty, so = self._order('TY-C-7', status='created')
        self._ship(so)
        package = {'id': 'TY-C-7-P', 'orderNumber': 'TY-C-7', 'status': 'Cancelled'}
        for _ in range(2):
            self.TO._process_package(package, self.store)
        self.assertEqual(ty.trendyol_status, 'cancelled')
        self.assertEqual(so.state, 'sale')
        self.assertIn('sevk edildiği', ty.error_message)
        self.assertEqual(len(so.message_ids.filtered(lambda m: 'iptal edilmedi' in (m.body or ''))), 1)

    def test_sync_path_cancels_unshipped_order(self):
        ty, so = self._order('TY-C-8', status='created')
        self.TO._process_package({'id': 'TY-C-8-P', 'orderNumber': 'TY-C-8', 'status': 'Cancelled'}, self.store)
        self.assertEqual(so.state, 'cancel')

    def test_split_rebuild_uses_same_blocker(self):
        """trendyol_order.py yeniden kurulum yolu faturalı siparişi de iptal etmez."""
        ty, so = self._order('TY-C-9', status='created')
        invoice = so._create_invoices()
        invoice.action_post()
        api = MagicMock()
        api.get_orders.return_value = {'success': True, 'data': {'content': [
            {'id': 'TY-C-9-P', 'orderNumber': 'TY-C-9', 'status': 'Created', 'lines': []}]}}
        with patch.object(type(self.store), 'get_api', return_value=api):
            self.assertTrue(self.TO._rebuild_split_order(ty, self.store, 'Test'))
            self.assertTrue(self.TO._rebuild_split_order(ty, self.store, 'Test'))
        self.assertEqual(so.state, 'sale')
        self.assertEqual(ty.sale_order_id, so)
        self.assertIn('faturası kesildiği', ty.error_message)
        self.assertEqual(len(so.message_ids.filtered(lambda m: 'otomatik güncellenmedi' in (m.body or ''))), 1)

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'n11_integration')
class TestN11RebuildBlockers(TransactionCase):
    """Kısmi iptal / yeniden kurma yolu: sevk ve posted fatura SO'yu iptalden korur."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # NEDEN: onay/iptal kancaları Nebim'e dış çağrı yapmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['n11.store'].create({'name': 'N11 Test', 'n11_app_key': 'x', 'n11_app_secret': 'y'})
        cls.product = cls.env['product.product'].create({
            'name': 'N11 Rebuild Ürün', 'default_code': 'N11-REBUILD-1', 'type': 'consu', 'list_price': 100,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'N11 Rebuild Müşteri'})

    def _sale_order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })

    def _order(self, ref):
        so = self._sale_order()
        so.action_confirm()
        n11 = self.env['n11.order'].create({
            'store_id': self.store.id, 'order_id': ref, 'order_number': ref, 'sale_order_id': so.id,
        })
        return n11, so

    def _rebuild(self, n11):
        # NEDEN: yeni SO kurulumu bu testin konusu değil; taslak bir SO döndürmek yeterli
        new = self._sale_order()
        with patch.object(type(n11), '_create_odoo_sale_order', return_value=new) as create:
            n11._rebuild_sale_order(self.store, 'Kısmi iptal')
        return create

    def test_unshipped_unbilled_order_is_cancelled_and_rebuilt(self):
        n11, so = self._order('N11-R-1')
        create = self._rebuild(n11)
        self.assertEqual(so.state, 'cancel')
        create.assert_called_once()
        self.assertNotEqual(n11.sale_order_id, so)

    def test_shipped_order_is_not_cancelled(self):
        n11, so = self._order('N11-R-2')
        # NEDEN: gerçek sevk için stok kurmak yerine picking durumunu doğrudan 'done' yapıyoruz
        self.env.cr.execute("UPDATE stock_picking SET state='done' WHERE id IN %s", (tuple(so.picking_ids.ids),))
        so.picking_ids.invalidate_recordset(['state'])
        create = self._rebuild(n11)
        self.assertEqual(so.state, 'sale')
        create.assert_not_called()
        self.assertIn('sevk edildiği için otomatik güncellenmedi', n11.error_message)

    def test_posted_invoice_blocks_rebuild(self):
        n11, so = self._order('N11-R-3')
        so._create_invoices().action_post()
        create = self._rebuild(n11)
        self.assertEqual(so.state, 'sale')
        create.assert_not_called()
        self.assertIn('faturası kesildiği için otomatik güncellenmedi', n11.error_message)

    def test_draft_invoice_does_not_block_rebuild(self):
        n11, so = self._order('N11-R-4')
        so._create_invoices()  # taslak fatura: engel değil, davranış eskisi gibi
        create = self._rebuild(n11)
        self.assertEqual(so.state, 'cancel')
        create.assert_called_once()

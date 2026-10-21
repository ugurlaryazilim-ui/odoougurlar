from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'hepsiburada_integration')
class TestHepsiburadaRebuildBlockers(TransactionCase):
    """Kısmi iptal / yeni kalem yeniden kurma yolu: sevk ve posted fatura SO'yu iptalden korur."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        # NEDEN: onay/iptal kancaları Nebim'e dış çağrı yapmasın
        ICP.set_param('odoougurlar.nebim_sync_customer_enabled', 'False')
        ICP.set_param('odoougurlar.nebim_sync_order_enabled', 'False')
        cls.store = cls.env['hepsiburada.store'].create({'name': 'HB Test', 'merchant_id': 'x', 'api_user': 'y', 'api_password': 'z'})
        cls.product = cls.env['product.product'].create({
            'name': 'HB Rebuild Ürün', 'default_code': 'HB-REBUILD-1', 'type': 'consu', 'list_price': 100,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'HB Rebuild Müşteri'})
        cls.Sync = cls.env['hepsiburada.order.sync']

    def _order(self, ref):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': 100})],
        })
        so.action_confirm()
        pz = self.env['hepsiburada.order'].create({
            'store_id': self.store.id, 'hb_order_number': ref, 'sale_order_id': so.id,
        })
        return pz, so

    def _rebuild(self, pz):
        # NEDEN: yeni SO kurulumu bu testin konusu değil; boş recordset döndürmek yeterli
        with patch.object(type(self.Sync), '_create_sale_order',
                          return_value=self.env['sale.order']) as create:
            self.Sync._rebuild_sale_order(pz, self.store, 'Kısmi iptal')
        return create

    def test_unshipped_unbilled_order_is_cancelled_and_rebuilt(self):
        pz, so = self._order('HB-R-1')
        create = self._rebuild(pz)
        self.assertEqual(so.state, 'cancel')
        create.assert_called_once()

    def test_shipped_order_is_not_cancelled(self):
        pz, so = self._order('HB-R-2')
        # NEDEN: gerçek sevk için stok kurmak yerine picking durumunu doğrudan 'done' yapıyoruz
        self.env.cr.execute("UPDATE stock_picking SET state='done' WHERE id IN %s", (tuple(so.picking_ids.ids),))
        so.picking_ids.invalidate_recordset(['state'])
        create = self._rebuild(pz)
        self.assertEqual(so.state, 'sale')
        create.assert_not_called()
        self.assertIn('sevk edildiği için otomatik güncellenmedi', pz.warning_message)

    def test_posted_invoice_blocks_rebuild(self):
        pz, so = self._order('HB-R-3')
        so._create_invoices().action_post()
        create = self._rebuild(pz)
        self.assertEqual(so.state, 'sale')
        create.assert_not_called()
        self.assertIn('faturası kesildiği için otomatik güncellenmedi', pz.warning_message)

    def test_draft_invoice_does_not_block_rebuild(self):
        pz, so = self._order('HB-R-4')
        so._create_invoices()  # taslak fatura: engel değil, davranış eskisi gibi
        create = self._rebuild(pz)
        self.assertEqual(so.state, 'cancel')
        create.assert_called_once()

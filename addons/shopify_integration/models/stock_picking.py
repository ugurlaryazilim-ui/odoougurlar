import logging
from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        """Picking tamamlandığında Shopify'a kargo bilgisi gönder."""
        res = super()._action_done()

        for picking in self:
            if picking.picking_type_code != 'outgoing':
                continue

            sale_order = picking.sale_id
            if not sale_order:
                continue

            shopify_order = self.env['shopify.order'].search([
                ('sale_order_id', '=', sale_order.id)
            ], limit=1)

            if not shopify_order or not shopify_order.store_id:
                continue

            tracking_ref = picking.carrier_tracking_ref or ''
            if not tracking_ref:
                continue

            try:
                api = shopify_order.store_id.get_api()
                result = api.create_fulfillment(
                    order_id=shopify_order.order_id,
                    tracking_number=tracking_ref,
                    tracking_company=shopify_order.cargo_provider or 'DHL',
                )
                if result.get('success'):
                    shopify_order.write({
                        'cargo_tracking_number': tracking_ref,
                        'fulfillment_status': 'fulfilled',
                    })
                    _logger.info("Shopify fulfillment gönderildi: %s → %s",
                                 shopify_order.order_number, tracking_ref)
                else:
                    _logger.warning("Shopify fulfillment gönderilemedi: %s",
                                    result.get('error'))
            except Exception as e:
                _logger.error("Shopify fulfillment hatası: %s", e)

        return res

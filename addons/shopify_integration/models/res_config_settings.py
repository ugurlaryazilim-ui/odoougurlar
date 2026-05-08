from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Depo ────────────────────────────────────────────
    shopify_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Shopify Sipariş Deposu',
        config_parameter='shopify_integration.warehouse_id',
        help='Shopify siparişlerinin düşeceği depo',
    )

    def action_shopify_sync_all(self):
        """Tüm aktif Shopify mağazalarını senkronize et."""
        self.ensure_one()
        ShopifyOrder = self.env['shopify.order']
        try:
            ShopifyOrder._cron_sync_orders()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Shopify Senkronizasyon',
                    'message': '✅ Tüm mağazalar senkronize edildi!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % str(e))

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Depo ────────────────────────────────────────────
    idefix_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='İnternet Mağaza Deposu',
        config_parameter='idefix_integration.warehouse_id',
        help='Idefix siparişlerinin düşeceği ana depo',
    )
    idefix_backup_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Yedek Depo (Heykel Mağaza)',
        config_parameter='idefix_integration.backup_warehouse_id',
        help='Ana depoda stok yoksa bu depoda aranacak',
    )

    def action_idefix_sync_all(self):
        """Tüm aktif mağazaları senkronize et."""
        self.ensure_one()
        IdefixOrder = self.env['idefix.order']
        # sync_orders_from_idefix() doesn't return count but I can fix or use try/except.
        try:
            IdefixOrder.sync_orders_from_idefix()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Idefix Senkronizasyon',
                    'message': '✅ Tüm mağazalar senkronize edildi!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % str(e))

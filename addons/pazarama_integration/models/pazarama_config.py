import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Depo ────────────────────────────────────────────
    pazarama_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='İnternet Mağaza Deposu',
        config_parameter='pazarama_integration.warehouse_id',
        help='Pazarama siparişlerinin düşeceği ana depo',
    )
    pazarama_backup_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Yedek Depo (Heykel Mağaza)',
        config_parameter='pazarama_integration.backup_warehouse_id',
        help='Ana depoda stok yoksa bu depoda aranacak',
    )

    def action_pazarama_sync_all(self):
        """Tüm aktif mağazaları senkronize et."""
        self.ensure_one()
        PazaramaOrder = self.env['pazarama.order']
        # sync_orders_from_pazarama() doesn't return count but I can fix or use try/except.
        try:
            PazaramaOrder.sync_orders_from_pazarama()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Pazarama Senkronizasyon',
                    'message': '✅ Tüm mağazalar senkronize edildi!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % str(e))

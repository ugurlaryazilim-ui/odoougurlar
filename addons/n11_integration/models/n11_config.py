import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Depo ────────────────────────────────────────────
    n11_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='İnternet Mağaza Deposu',
        config_parameter='n11_integration.warehouse_id',
        help='N11 siparişlerinin düşeceği ana depo',
    )
    n11_backup_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Yedek Depo (Heykel Mağaza)',
        config_parameter='n11_integration.backup_warehouse_id',
        help='Ana depoda stok yoksa bu depoda aranacak',
    )

    def action_n11_sync_all(self):
        """Tüm aktif mağazaları senkronize et."""
        self.ensure_one()
        N11Order = self.env['n11.order']
        # sync_orders_from_n11() doesn't return count but I can fix or use try/except.
        try:
            N11Order.sync_orders_from_n11()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'N11 Senkronizasyon',
                    'message': '✅ Tüm mağazalar senkronize edildi!',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % str(e))

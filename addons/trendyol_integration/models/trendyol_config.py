import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ─── Depo ────────────────────────────────────────────
    trendyol_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='İnternet Mağaza Deposu',
        config_parameter='trendyol_integration.warehouse_id',
        help='Trendyol siparişlerinin düşeceği ana depo',
    )
    trendyol_backup_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Yedek Depo (Heykel Mağaza)',
        config_parameter='trendyol_integration.backup_warehouse_id',
        help='Ana depoda stok yoksa bu depoda aranacak',
    )

    def action_trendyol_sync_all(self):
        """Tüm aktif mağazaları senkronize et."""
        self.ensure_one()
        TrendyolOrder = self.env['trendyol.order']
        result = TrendyolOrder.sync_orders_from_trendyol()
        if result.get('error'):
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % result['error'])

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Trendyol Senkronizasyon',
                'message': '✅ Tüm mağazalar senkronize edildi!\n'
                           f'Yeni: {result.get("created", 0)} | '
                           f'Güncellenen: {result.get("updated", 0)} | '
                           f'Hatalı: {result.get("errors", 0)}',
                'type': 'success',
                'sticky': False,
            },
        }

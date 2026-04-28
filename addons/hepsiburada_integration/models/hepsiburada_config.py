from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Depo Ayarları
    hb_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='İnternet Mağaza Deposu',
        config_parameter='hepsiburada_integration.warehouse_id',
        help='Hepsiburada siparişlerinin düşeceği ana depo'
    )
    hb_backup_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Yedek Depo (Heykel Mağaza)',
        config_parameter='hepsiburada_integration.backup_warehouse_id',
        help='Ana depoda stok yoksa aranacak depo'
    )

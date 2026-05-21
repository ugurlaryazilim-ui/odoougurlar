import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class StockWarehouseNebim(models.Model):
    """Nebim depo kodu eşleştirmesi için stock.warehouse uzantısı."""
    _inherit = 'stock.warehouse'

    nebim_warehouse_code = fields.Char(
        string='Nebim Depo Kodu',
        help='Nebim tarafındaki depo kodu (ör: "MERKEZ", "DEPO1")',
    )


class StockLocationQty(models.Model):
    """Stok konumlarında toplam ürün adedini gösteren alan."""
    _inherit = 'stock.location'

    total_quant_qty = fields.Float(
        string='Adet',
        compute='_compute_total_quant_qty',
        digits=(16, 0),
        help='Bu konumdaki toplam ürün stok adedi',
    )

    @api.depends('quant_ids', 'quant_ids.quantity')
    def _compute_total_quant_qty(self):
        for loc in self:
            loc.total_quant_qty = sum(loc.quant_ids.mapped('quantity'))

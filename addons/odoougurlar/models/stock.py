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
        help='Bu konum ve tüm alt konumlarındaki toplam ürün stok adedi',
    )

    def _compute_total_quant_qty(self):
        for loc in self:
            # parent_path ile tüm alt konumları dahil et (ör: "1/5/12/" → LIKE "1/5/12/%")
            if loc.parent_path:
                self.env.cr.execute("""
                    SELECT COALESCE(SUM(sq.quantity), 0)
                    FROM stock_quant sq
                    JOIN stock_location sl ON sl.id = sq.location_id
                    WHERE sl.parent_path LIKE %s
                """, [loc.parent_path + '%'])
                loc.total_quant_qty = self.env.cr.fetchone()[0]
            else:
                loc.total_quant_qty = sum(loc.quant_ids.mapped('quantity'))

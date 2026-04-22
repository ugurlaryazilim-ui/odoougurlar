import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class StockWarehouseNebim(models.Model):
    """Nebim depo kodu eşleştirmesi için stock.warehouse uzantısı."""
    _inherit = 'stock.warehouse'

    nebim_warehouse_code = fields.Char(
        string='Nebim Depo Kodu',
        help='Nebim tarafındaki depo kodu (ör: "MERKEZ", "DEPO1")',
    )

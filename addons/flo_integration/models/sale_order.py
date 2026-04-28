from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    flo_store_id = fields.Many2one('flo.store', string='Flo Mağazası', readonly=True)
    flo_order_id = fields.Many2one('flo.order', string='Flo Siparişi', readonly=True)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    flo_item_id = fields.Char(string='Flo Item ID', readonly=True)

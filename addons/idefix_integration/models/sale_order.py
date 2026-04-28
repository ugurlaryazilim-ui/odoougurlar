from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    idefix_store_id = fields.Many2one('idefix.store', string='Idefix Mağazası', readonly=True)
    idefix_order_id = fields.Many2one('idefix.order', string='Idefix Siparişi', readonly=True)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    idefix_item_id = fields.Char(string='Idefix Item ID', readonly=True)

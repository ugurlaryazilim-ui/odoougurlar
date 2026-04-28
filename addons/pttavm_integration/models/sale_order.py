from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pttavm_store_id = fields.Many2one('pttavm.store', string='Pttavm Mağazası', readonly=True)
    pttavm_order_id = fields.Many2one('pttavm.order', string='Pttavm Siparişi', readonly=True)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    pttavm_item_id = fields.Char(string='Pttavm Item ID', readonly=True)

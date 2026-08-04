from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    amazon_store_id = fields.Many2one('amazon.store', string='Amazon Mağazası', copy=False)
    amazon_order_id = fields.Many2one('amazon.order', string='Amazon Siparişi', copy=False, readonly=True)

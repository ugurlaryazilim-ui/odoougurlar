from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopify_order_id = fields.Many2one(
        'shopify.order', string='Shopify Siparişi',
        readonly=True, ondelete='set null')

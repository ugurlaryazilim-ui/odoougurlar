# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    n11_store_id = fields.Many2one('n11.store', string='N11 Mağazası', readonly=True)
    n11_order_id = fields.Many2one('n11.order', string='N11 Siparişi', readonly=True)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    n11_item_id = fields.Char(string='N11 Item ID', readonly=True)

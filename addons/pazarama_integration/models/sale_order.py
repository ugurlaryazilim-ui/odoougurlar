# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pazarama_store_id = fields.Many2one('pazarama.store', string='Pazarama Mağazası', readonly=True)
    pazarama_order_id = fields.Many2one('pazarama.order', string='Pazarama Siparişi', readonly=True)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    pazarama_item_id = fields.Char(string='Pazarama Item ID', readonly=True)

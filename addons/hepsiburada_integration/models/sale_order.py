# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    hb_order_id = fields.Many2one('hepsiburada.order', string='Hepsiburada Siparişi', copy=False, help="İlişkili Hepsiburada Siparişi")
    hb_store_id = fields.Char(string='Hepsiburada Mağaza ID', copy=False, help="Hangi mağaza hesabına bağlı olduğu bilgisi")

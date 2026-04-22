# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    trendyol_order_id = fields.Many2one('trendyol.order', string='Trendyol Siparişi', readonly=True, copy=False)
    is_trendyol_order = fields.Boolean(string='Trendyol Siparişi', compute='_compute_is_trendyol')
    trendyol_status = fields.Selection(related='trendyol_order_id.trendyol_status', string='Trendyol Durumu')
    trendyol_order_number = fields.Char(related='trendyol_order_id.trendyol_order_number', string='TY Sipariş No')

    # ─── Mağaza Bilgileri ─────────────────────────────────
    trendyol_store_id = fields.Many2one('trendyol.store', string='Trendyol Mağaza', readonly=True, copy=False)
    trendyol_store_name = fields.Char(string='Mağaza Adı', related='trendyol_store_id.name', store=True, readonly=True)
    trendyol_seller_id = fields.Char(string='Seller ID', related='trendyol_store_id.seller_id', store=True, readonly=True)

    @api.depends('trendyol_order_id')
    def _compute_is_trendyol(self):
        for order in self:
            order.is_trendyol_order = bool(order.trendyol_order_id)

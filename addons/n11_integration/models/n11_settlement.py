# -*- coding: utf-8 -*-
from odoo import models, fields

class N11Settlement(models.Model):
    _name = 'n11.settlement'
    _description = 'N11 Finansal Mutabakat'
    _order = 'transaction_date desc'

    store_id = fields.Many2one('n11.store', string='Mağaza', required=True, ondelete='cascade')
    order_id = fields.Char(string='Sipariş ID', index=True)
    trx_code = fields.Char(string='İşlem Kodu', index=True)
    trx_id = fields.Char(string='İşlem ID')
    
    amount = fields.Float(string='Tutar')
    installment_number = fields.Integer(string='Taksit Sayısı')
    commission_amount = fields.Float(string='Komisyon Tutarı')
    coupon_discount = fields.Float(string='Kupon İndirimi')
    allowance_amount = fields.Float(string='Platform Katkısı')
    
    status = fields.Char(string='Statü')
    transaction_date = fields.Datetime(string='İşlem Tarihi')
    transferred_date = fields.Datetime(string='Aktarım Tarihi')
    
    raw_data = fields.Text(string='Ham Veri')

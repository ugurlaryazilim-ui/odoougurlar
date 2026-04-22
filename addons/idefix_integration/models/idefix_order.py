# -*- coding: utf-8 -*-
from odoo import models, fields

class IdefixOrder(models.Model):
    _name = 'idefix.order'
    _description = 'Idefix Siparişi'
    _order = 'order_date desc'

    store_id = fields.Many2one('idefix.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')
    
    order_id = fields.Char(string='Order ID', required=True, index=True)
    order_number = fields.Char(string='Sipariş No', required=True, index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')
    
    order_status = fields.Char(string='Sipariş Statüsü')
    payment_type = fields.Integer(string='Ödeme Tipi')
    invoice_type = fields.Integer(string='Fatura Tipi', help="1: Bireysel, 2: Kurumsal")
    
    # Müşteri ve Kargo Bilgileri
    customer_id = fields.Char(string='Customer ID')
    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri Email')
    
    # Adres Bilgileri
    shipment_address = fields.Text(string='Teslimat Adresi (JSON)')
    billing_address = fields.Text(string='Fatura Adresi (JSON)')
    
    shipping_city = fields.Char(string='Teslimat İl')
    shipping_district = fields.Char(string='Teslimat İlçe')
    
    # Kargo ve Paketleme için ana takip bilgileri
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    cargo_provider = fields.Char(string='Kargo Firması')
    
    # Tutar
    total_price = fields.Float(string='Toplam Tutar')
    currency = fields.Char(string='Para Birimi', default='TL')
    
    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')
    
    line_ids = fields.One2many('idefix.order.line', 'order_id', string='Sipariş Satırları')


class IdefixOrderLine(models.Model):
    _name = 'idefix.order.line'
    _description = 'Idefix Sipariş Satırı'

    order_id = fields.Many2one('idefix.order', string='Idefix Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)
    
    product_id = fields.Char(string='Idefix Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')
    
    quantity = fields.Integer(string='Miktar')
    sale_price = fields.Float(string='Satış Fiyatı')
    
    status = fields.Char(string='Sipariş Statüsü')
    
    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

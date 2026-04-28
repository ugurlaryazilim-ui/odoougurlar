from odoo import models, fields

class PazaramaRefund(models.Model):
    _name = 'pazarama.refund'
    _description = 'Pazarama İade Talepleri'
    _order = 'refund_date desc'

    store_id = fields.Many2one('pazarama.store', string='Mağaza', required=True, ondelete='cascade')
    refund_id = fields.Char(string='Refund ID', index=True, required=True)
    order_number = fields.Char(string='Sipariş No', index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')
    refund_number = fields.Char(string='İade Numarası')
    
    refund_type = fields.Char(string='İade Sebebi')
    refund_status = fields.Integer(string='İade Statü Kodu')
    refund_status_name = fields.Char(string='İade Statü Adı')
    refund_date = fields.Datetime(string='İade Tarihi')
    
    total_amount = fields.Float(string='Sipariş Toplam Tutar')
    refund_amount = fields.Float(string='İade Tutar')
    
    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri E-Posta')
    
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün Kodu')
    
    shipment_company_name = fields.Char(string='İade Kargo Firması')
    shipment_code = fields.Char(string='İade Kargo Kodu', index=True)
    
    description = fields.Text(string='Müşteri Açıklaması')
    quantity = fields.Integer(string='Adet')
    
    raw_data = fields.Text(string='Ham Veri')

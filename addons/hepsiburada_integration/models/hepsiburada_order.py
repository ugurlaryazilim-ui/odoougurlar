from odoo import models, fields

class HepsiburadaOrder(models.Model):
    _name = 'hepsiburada.order'
    _description = 'Hepsiburada Siparişi'
    _rec_name = 'hb_order_number'

    hb_order_number = fields.Char(string='Sipariş Numarası', required=True, index=True)
    merchant_id = fields.Char(string='Merchant ID')
    order_date = fields.Datetime(string='Sipariş Tarihi')
    status = fields.Char(string='Sipariş Statüsü')
    
    # Kargo ve Paketleme Verisi
    cargo_company = fields.Char(string='Kargo Firması')
    cargo_provider = fields.Char(string='Kargo Sağlayıcı Adı')
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    package_number = fields.Char(string='Paket Numarası')

    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri Email')
    customer_phone = fields.Char(string='Müşteri Telefonu')
    tax_office = fields.Char(string='Vergi Dairesi')
    tax_number = fields.Char(string='Vergi/TC No')

    shipping_address = fields.Text(string='Teslimat Adresi')
    shipping_city = fields.Char(string='Teslimat İl')
    shipping_district = fields.Char(string='Teslimat İlçe')
    
    total_price = fields.Float(string='Toplam Tutar')
    currency = fields.Char(string='Para Birimi', default='TRY')

    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True)
    line_ids = fields.One2many('hepsiburada.order.line', 'order_id', string='Satırlar')
    raw_payload = fields.Text(string='Raw JSON', help='API üzerinden gelen orijinal JSON verisi')


class HepsiburadaOrderLine(models.Model):
    _name = 'hepsiburada.order.line'
    _description = 'Hepsiburada Sipariş Satırı'

    order_id = fields.Many2one('hepsiburada.order', string='Sipariş', ondelete='cascade')
    line_item_id = fields.Char(string='Hepsiburada Satır ID', required=True, index=True)
    sku = fields.Char(string='Hepsiburada SKU')
    merchant_sku = fields.Char(string='Satıcı Stok Kodu')
    product_name = fields.Char(string='Ürün Adı')
    quantity = fields.Integer(string='Miktar', default=1)
    
    price = fields.Float(string='Kalem Tutarı')
    merchant_unit_price = fields.Float(string='Satıcı Birim Hakediş', help='Satıcıya geçecek olan gerçek ürün meblağı')
    vat = fields.Float(string='KDV Tutarı')
    vat_rate = fields.Float(string='KDV Oranı')
    
    commission_amount = fields.Float(string='Komisyon')
    commission_rate = fields.Float(string='Komisyon Oranı')
    status = fields.Char(string='Satır Statüsü')

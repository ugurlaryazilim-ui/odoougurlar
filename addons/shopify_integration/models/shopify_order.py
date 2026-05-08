from odoo import models, fields


class ShopifyOrder(models.Model):
    _name = 'shopify.order'
    _description = 'Shopify Siparişi'
    _order = 'order_date desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('shopify.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')

    order_id = fields.Char(string='Shopify Order ID', required=True, index=True)
    order_number = fields.Char(string='Sipariş No', required=True, index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')

    # Durum
    order_status = fields.Char(string='Sipariş Durumu')
    financial_status = fields.Char(string='Ödeme Durumu')
    fulfillment_status = fields.Char(string='Karşılama Durumu')

    # Müşteri Bilgileri
    customer_shopify_id = fields.Char(string='Shopify Customer ID')
    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri Email')
    customer_phone = fields.Char(string='Müşteri Telefon')

    # Adres Bilgileri
    shipping_address = fields.Text(string='Teslimat Adresi (JSON)')
    billing_address = fields.Text(string='Fatura Adresi (JSON)')

    shipping_city = fields.Char(string='Teslimat İl')
    shipping_district = fields.Char(string='Teslimat İlçe')

    # Kargo
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    cargo_provider = fields.Char(string='Kargo Firması')

    # Tutarlar
    total_price = fields.Float(string='Toplam Tutar')
    subtotal_price = fields.Float(string='Ara Toplam')
    total_tax = fields.Float(string='Toplam KDV')
    total_discount = fields.Float(string='Toplam İndirim')
    shipping_price = fields.Float(string='Kargo Ücreti')
    currency = fields.Char(string='Para Birimi', default='TRY')

    # KDV
    taxes_included = fields.Boolean(string='KDV Dahil', default=True)

    # İndirim
    discount_codes = fields.Char(string='İndirim Kodları')

    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')

    line_ids = fields.One2many('shopify.order.line', 'order_id', string='Sipariş Satırları')


class ShopifyOrderLine(models.Model):
    _name = 'shopify.order.line'
    _description = 'Shopify Sipariş Satırı'

    order_id = fields.Many2one('shopify.order', string='Shopify Siparişi', ondelete='cascade')
    line_item_id = fields.Char(string='Line Item ID', index=True)

    product_shopify_id = fields.Char(string='Shopify Product ID')
    variant_shopify_id = fields.Char(string='Shopify Variant ID')
    sku = fields.Char(string='SKU / Barkod')
    product_name = fields.Char(string='Ürün Adı')
    variant_title = fields.Char(string='Varyant')

    quantity = fields.Integer(string='Miktar')
    price = fields.Float(string='Birim Fiyat (KDV Dahil)')
    price_tax_excluded = fields.Float(string='Birim Fiyat (KDV Hariç)')
    total_discount = fields.Float(string='Toplam İndirim')
    tax_rate = fields.Float(string='KDV Oranı (%)', default=10.0)

    fulfillment_status = fields.Char(string='Karşılama Durumu')

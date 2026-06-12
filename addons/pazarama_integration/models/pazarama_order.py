from odoo import models, fields, api

class PazaramaOrder(models.Model):
    _name = 'pazarama.order'
    _description = 'Pazarama Siparişi'
    _order = 'order_date desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('pazarama.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')
    
    order_id = fields.Char(string='Order ID', required=True, index=True)
    order_number = fields.Char(string='Sipariş No', required=True, index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')
    
    order_status = fields.Integer(string='Sipariş Statüsü')
    order_status_display = fields.Char(string='Pazarama Durumu', compute='_compute_order_status_display')
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
    
    line_ids = fields.One2many('pazarama.order.line', 'order_id', string='Sipariş Satırları')

    PAZARAMA_STATUS_MAP = {
        3: 'Sipariş Alındı',
        5: 'Kargoya Verildi',
        6: 'İptal Edildi',
        11: 'Teslim Edildi',
        12: 'Hazırlanıyor',
        13: 'Tedarik Edilemedi',
        14: 'Teslim Edilemedi',
        18: 'İptal Süreci Başlatıldı',
    }

    @api.depends('order_status')
    def _compute_order_status_display(self):
        for rec in self:
            rec.order_status_display = self.PAZARAMA_STATUS_MAP.get(
                rec.order_status, str(rec.order_status) if rec.order_status else ''
            )


class PazaramaOrderLine(models.Model):
    _name = 'pazarama.order.line'
    _description = 'Pazarama Sipariş Satırı'

    order_id = fields.Many2one('pazarama.order', string='Pazarama Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)
    
    product_id = fields.Char(string='Pazarama Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')
    
    quantity = fields.Integer(string='Miktar')
    sale_price = fields.Float(string='Satış Fiyatı')
    discount_amount = fields.Float(string='İndirim Tutarı (KDV Dahil)')
    discount_pct = fields.Float(string='İndirim %')
    discount_description = fields.Char(string='İndirim Açıklaması')
    
    status = fields.Integer(string='Sipariş Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    STATUS_MAP = {
        3: 'Sipariş Alındı',
        5: 'Kargoya Verildi',
        6: 'İptal Edildi',
        11: 'Teslim Edildi',
        12: 'Hazırlanıyor',
        13: 'Tedarik Edilemedi',
        14: 'Teslim Edilemedi',
        18: 'İptal Süreci Başlatıldı',
    }

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = self.STATUS_MAP.get(
                rec.status, str(rec.status) if rec.status else ''
            )
    
    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

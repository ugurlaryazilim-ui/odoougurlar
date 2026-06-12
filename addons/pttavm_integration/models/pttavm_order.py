from odoo import models, fields, api

class PttavmOrder(models.Model):
    _name = 'pttavm.order'
    _description = 'Pttavm Siparişi'
    _order = 'order_date desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('pttavm.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')
    
    order_id = fields.Char(string='Order ID', required=True, index=True)
    order_number = fields.Char(string='Sipariş No', required=True, index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')
    
    order_status = fields.Char(string='Sipariş Statüsü')
    order_status_display = fields.Char(string='PttAvm Durumu', compute='_compute_order_status_display')
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
    
    line_ids = fields.One2many('pttavm.order.line', 'order_id', string='Sipariş Satırları')

    PTTAVM_STATUS_MAP = {
        'kargo_yapilmasi_bekleniyor': 'Kargo Bekliyor',
        'gonderilmis': 'Gönderilmiş',
        'tamamlandi': 'Tamamlandı',
        'iptal': 'İptal',
        'iade': 'İade',
        'kargoda': 'Kargoda',
        'teslim_edildi': 'Teslim Edildi',
        'hazirlaniyor': 'Hazırlanıyor',
        'onay_bekliyor': 'Onay Bekliyor',
    }

    @api.depends('order_status')
    def _compute_order_status_display(self):
        for rec in self:
            raw = rec.order_status or ''
            rec.order_status_display = self.PTTAVM_STATUS_MAP.get(
                raw, raw.replace('_', ' ').title() if raw else ''
            )


class PttavmOrderLine(models.Model):
    _name = 'pttavm.order.line'
    _description = 'Pttavm Sipariş Satırı'

    order_id = fields.Many2one('pttavm.order', string='Pttavm Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)
    
    product_id = fields.Char(string='Pttavm Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')
    
    quantity = fields.Integer(string='Miktar')
    sale_price = fields.Float(string='Satış Fiyatı')
    vat_rate = fields.Float(string='KDV Oranı')
    
    status = fields.Char(string='Sipariş Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    STATUS_MAP = {
        'kargo_yapilmasi_bekleniyor': 'Kargo Bekliyor',
        'gonderilmis': 'Gönderilmiş',
        'tamamlandi': 'Tamamlandı',
        'iptal': 'İptal',
        'iade': 'İade',
        'kargoda': 'Kargoda',
        'teslim_edildi': 'Teslim Edildi',
        'hazirlaniyor': 'Hazırlanıyor',
        'onay_bekliyor': 'Onay Bekliyor',
    }

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            raw = rec.status or ''
            rec.status_display = self.STATUS_MAP.get(
                raw, raw.replace('_', ' ').title() if raw else ''
            )
    
    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

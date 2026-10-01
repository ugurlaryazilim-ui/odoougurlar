from odoo import models, fields, api

# n11 REST paket / kalem durumları (Canceled: SOAP→REST eşleme sayfasındaki yazım)
N11_CANCEL_STATUSES = ('Cancelled', 'CANCELLED', 'Canceled', 'UnSupplied')
N11_INACTIVE_LINE_STATUSES = N11_CANCEL_STATUSES + ('Unpacked',)
N11_STATUS_RANK = {'Created': 0, 'Picking': 1, 'Shipped': 2, 'Delivered': 3}

N11_STATUS_MAP = {
    'Created': 'Yeni',
    'Picking': 'Onaylandı',
    'Shipped': 'Kargoda',
    'Delivered': 'Teslim Edildi',
    'Cancelled': 'İptal',
    'Canceled': 'İptal',
    'CANCELLED': 'İptal',
    'UnSupplied': 'Tedarik Edilemedi',
    'Unpacked': 'Paket Bölündü',
}


class N11Order(models.Model):
    _name = 'n11.order'
    _description = 'N11 Siparişi'
    _order = 'order_date desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('n11.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')

    order_id = fields.Char(string='Paket ID', required=True, index=True)
    order_number = fields.Char(string='Sipariş No', required=True, index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')

    order_status = fields.Char(string='Sipariş Statüsü')
    order_status_display = fields.Char(string='N11 Durumu', compute='_compute_order_status_display')
    partially_cancelled = fields.Boolean(string='Kısmi İptal', readonly=True)
    payment_type = fields.Integer(string='Ödeme Tipi')
    invoice_type = fields.Integer(string='Fatura Tipi', help="1: Bireysel, 2: Kurumsal")
    tax_office = fields.Char(string='Vergi Dairesi', readonly=True)
    tax_number = fields.Char(string='Vergi No', readonly=True)

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
    cargo_tracking_link = fields.Char(string='Kargo Takip Linki')
    agreed_delivery_date = fields.Datetime(string='Son Kargolama Tarihi', index=True,
                                           help="n11'in kargoya verilmesini beklediği son tarih (agreedDeliveryDate)")
    delivery_address_type = fields.Char(string='Teslimat Noktası Tipi', help='KTN / EASYPOINT / PUP')
    is_micro = fields.Boolean(string='Mikro İhracat')
    last_modified_date = fields.Datetime(string="n11 Son Değişiklik")

    # Tutar
    total_price = fields.Float(string='Toplam Tutar')
    seller_invoice_total = fields.Float(string='Satıcı Fatura Tutarı',
                                        help='Aktif kalemlerin sellerInvoiceAmount toplamı (KDV dahil)')
    currency = fields.Char(string='Para Birimi', default='TRY')

    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')
    packages_data = fields.Text(string='Paketler (JSON)', help='Siparişin tüm n11 paketleri {paket_id: paket}')

    error_message = fields.Text(string='Uyarı / Hata', readonly=True)
    last_checked = fields.Datetime(string='Son Kontrol', readonly=True)
    accept_attempt_date = fields.Datetime(string='Son Onay Denemesi', readonly=True)

    line_ids = fields.One2many('n11.order.line', 'order_id', string='Sipariş Satırları')
    refund_ids = fields.One2many('n11.refund', 'n11_order_id', string='İade Talepleri')
    refund_count = fields.Integer(compute='_compute_refund_count', string='İade')

    N11_STATUS_MAP = N11_STATUS_MAP

    @api.depends('order_status', 'partially_cancelled')
    def _compute_order_status_display(self):
        for rec in self:
            label = N11_STATUS_MAP.get(rec.order_status, rec.order_status or '')
            if rec.partially_cancelled and rec.order_status not in N11_CANCEL_STATUSES:
                label = f"{label} (Kısmi İptal)"
            rec.order_status_display = label

    @api.depends('refund_ids')
    def _compute_refund_count(self):
        for rec in self:
            rec.refund_count = len(rec.refund_ids)

    def action_view_refunds(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'İade Talepleri',
            'res_model': 'n11.refund',
            'view_mode': 'list,form',
            'domain': [('n11_order_id', '=', self.id)],
        }


class N11OrderLine(models.Model):
    _name = 'n11.order.line'
    _description = 'N11 Sipariş Satırı'

    order_id = fields.Many2one('n11.order', string='N11 Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)
    package_id = fields.Char(string='Paket ID')

    product_id = fields.Char(string='N11 Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')

    quantity = fields.Integer(string='Miktar')
    sale_price = fields.Float(string='Satış Fiyatı (KDV Dahil)')
    vat_rate = fields.Float(string='KDV Oranı (%)')

    status = fields.Char(string='Sipariş Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    STATUS_MAP = N11_STATUS_MAP

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = N11_STATUS_MAP.get(rec.status, rec.status or '')

    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

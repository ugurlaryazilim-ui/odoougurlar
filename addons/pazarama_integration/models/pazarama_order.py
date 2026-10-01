from odoo import models, fields, api

# Pazarama sipariş / kalem durumları (OrderItemStatus) — durum kalem bazındadır
PAZARAMA_STATUS_LABELS = {
    3: 'Sipariş Alındı',
    12: 'Hazırlanıyor',
    5: 'Kargoya Verildi',
    16: 'Mağazada',
    19: 'Teslimat Noktasında',
    11: 'Teslim Edildi',
    14: 'Teslim Edilemedi',
    13: 'Tedarik Edilemedi',
    6: 'İptal Edildi',
    18: 'İptal Süreci Başlatıldı',
    7: 'İade Süreci Başlatıldı',
    8: 'İade Onaylandı',
    9: 'İade Reddedildi',
    10: 'İade Edildi',
}
# İptal sayılan durumlar — Odoo siparişi açılmaz / iptal edilir
# 6 = İptal Edildi, 13 = Tedarik Edilemedi, 14 = Teslim Edilemedi, 18 = İptal Süreci Başlatıldı
PAZARAMA_CANCEL_STATUSES = (6, 13, 14, 18)
# Sipariş başlığı için "en geride kalan" aktif kalem durumu esas alınır
PAZARAMA_STATUS_RANK = {3: 0, 12: 1, 5: 2, 16: 3, 19: 3, 11: 4, 7: 5, 9: 5, 8: 6, 10: 7}
# Artık değişmesi beklenmeyen durumlar (açık sipariş yoklamasına girmez)
PAZARAMA_FINAL_STATUSES = PAZARAMA_CANCEL_STATUSES + (11, 8, 9, 10)


def status_label(value):
    return PAZARAMA_STATUS_LABELS.get(value, str(value) if value else '')


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
    partially_cancelled = fields.Boolean(string='Kısmi İptal', help='Siparişin bazı kalemleri iptal edildi')
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

    # Fatura Bilgileri (kurumsal)
    tax_office = fields.Char(string='Vergi Dairesi')

    # Kargo ve Paketleme için ana takip bilgileri
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    cargo_provider = fields.Char(string='Kargo Firması')

    # Tutar
    total_price = fields.Float(string='Toplam Tutar')
    currency = fields.Char(string='Para Birimi', default='TL')

    # Senkron / hata takibi
    error_message = fields.Char(string='Hata', readonly=True, copy=False,
                                help='Odoo siparişi oluşturulamadıysa / güncellenemediyse nedeni')
    last_checked = fields.Datetime(string='Son Kontrol', readonly=True, copy=False)
    accept_attempt_date = fields.Datetime(string='Son Onay Denemesi', readonly=True, copy=False)
    legacy_no_sale = fields.Boolean(
        string='Eski Kayıt (Otomatik Aktarılmaz)', readonly=True, copy=False,
        help="Güncellemeden önce Odoo siparişi açılmamış kayıt. Eski siparişler Nebim'e birden gitmesin diye "
             "otomatik aktarılmaz; gerekiyorsa 'Tekrar Dene' ile elle aktarılır.")

    # Fatura linki gönderimi
    invoice_sent = fields.Boolean(string='Fatura Gönderildi', readonly=True, copy=False)
    invoice_url = fields.Char(string='Fatura Linki', readonly=True, copy=False)
    invoice_sent_date = fields.Datetime(string='Fatura Gönderim Tarihi', readonly=True, copy=False)
    invoice_error = fields.Char(string='Fatura Gönderim Hatası', readonly=True, copy=False)
    invoice_attempt_date = fields.Datetime(string='Son Fatura Denemesi', readonly=True, copy=False)

    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')

    line_ids = fields.One2many('pazarama.order.line', 'order_id', string='Sipariş Satırları')

    _store_order_uniq = models.Constraint(
        'UNIQUE(store_id, order_id)',
        'Bu mağazada aynı Pazarama siparişi zaten var.',
    )

    @api.depends('order_status', 'partially_cancelled')
    def _compute_order_status_display(self):
        for rec in self:
            label = status_label(rec.order_status)
            rec.order_status_display = f"{label} (Kısmi İptal)" if rec.partially_cancelled and label else label


class PazaramaOrderLine(models.Model):
    _name = 'pazarama.order.line'
    _description = 'Pazarama Sipariş Satırı'

    order_id = fields.Many2one('pazarama.order', string='Pazarama Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)

    product_id = fields.Char(string='Pazarama Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')

    quantity = fields.Integer(string='Miktar')
    sale_price = fields.Float(string='Satış Fiyatı', help='Birim satış fiyatı (KDV dahil)')
    vat_rate = fields.Float(string='KDV Oranı')
    # Eski indirim alanları (artık kullanılmıyor — veri korunur)
    discount_amount = fields.Float(string='İndirim Tutarı (KDV Dahil)')
    discount_pct = fields.Float(string='İndirim %')
    discount_description = fields.Char(string='İndirim Açıklaması')

    status = fields.Integer(string='Sipariş Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = status_label(rec.status)

    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')
    cargo_company_id = fields.Char(string='Kargo Firma ID')

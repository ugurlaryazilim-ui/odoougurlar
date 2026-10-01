from odoo import models, fields, api

# PttAVM satır durumları (siparisDurumu) — durum satır bazındadır
PTTAVM_STATUS_LABELS = {
    'havale_onayi_bekleniyor': 'Havale Onayı Bekleniyor',
    'onay_surecinde': 'Onay Sürecinde',
    'kargo_yapilmasi_bekleniyor': 'Kargo Bekliyor',
    'gonderilmis': 'Kargoya Verildi',
    'tamamlandi': 'Tamamlandı',
    'gondericisine_teslim_edildi': 'Göndericisine Teslim Edildi',
    'iade': 'İade',
    'iptal': 'İptal',
    'odeme_gecersiz': 'Ödeme Geçersiz',
}
# Odoo siparişi açılmayan / iptal edilen durumlar
PTTAVM_CANCEL_STATUSES = ('iptal', 'odeme_gecersiz')
# Sipariş başlığı için "en geride kalan" aktif satır durumu esas alınır
PTTAVM_STATUS_RANK = {
    'havale_onayi_bekleniyor': 0,
    'onay_surecinde': 1,
    'kargo_yapilmasi_bekleniyor': 2,
    'gonderilmis': 3,
    'tamamlandi': 4,
    'gondericisine_teslim_edildi': 5,
    'iade': 6,
}


def normalize_status(value):
    status = (value or '').strip()
    # Dokümanda "gonderilmiş" olarak da geçiyor
    return 'gonderilmis' if status == 'gonderilmiş' else status


def status_label(value):
    raw = value or ''
    return PTTAVM_STATUS_LABELS.get(raw, raw.replace('_', ' ').title() if raw else '')


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
    partially_cancelled = fields.Boolean(string='Kısmi İptal', help='Siparişin bazı satırları iptal edildi')
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

    # Fatura Bilgileri
    tax_office = fields.Char(string='Vergi Dairesi')

    # Kargo ve Paketleme için ana takip bilgileri
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    cargo_provider = fields.Char(string='Kargo Firması')

    # Kargo barkodu talebi (Shipment API — asenkron)
    cargo_barcode_tracking_id = fields.Char(string='Barkod Talep No', readonly=True, copy=False)
    cargo_barcode_state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('completed', 'Oluşturuldu'),
        ('error', 'Hata'),
    ], string='Barkod Durumu', readonly=True, copy=False)
    cargo_barcode = fields.Char(string='Kargo Barkodu', readonly=True, copy=False)
    cargo_barcode_message = fields.Char(string='Barkod Mesajı', readonly=True, copy=False)
    cargo_barcode_date = fields.Datetime(string='Barkod Talep Tarihi', readonly=True, copy=False)

    # Fatura gönderimi (PttAVM'ye fatura linki)
    invoice_sent = fields.Boolean(string='Fatura Gönderildi', readonly=True, copy=False)
    invoice_url = fields.Char(string='Fatura Linki', readonly=True, copy=False)
    invoice_sent_date = fields.Datetime(string='Fatura Gönderim Tarihi', readonly=True, copy=False)
    invoice_error = fields.Char(string='Fatura Gönderim Hatası', readonly=True, copy=False)
    invoice_attempt_date = fields.Datetime(string='Son Fatura Denemesi', readonly=True, copy=False)

    # Tutar
    total_price = fields.Float(string='Toplam Tutar')
    currency = fields.Char(string='Para Birimi', default='TRY')

    error_message = fields.Char(string='Hata', readonly=True, copy=False,
                                help='Odoo siparişi oluşturulamadıysa / güncellenemediyse nedeni')

    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')

    line_ids = fields.One2many('pttavm.order.line', 'order_id', string='Sipariş Satırları')

    _store_order_uniq = models.Constraint(
        'UNIQUE(store_id, order_number)',
        'Bu mağazada aynı PttAVM sipariş numarası zaten var.',
    )

    @api.depends('order_status', 'partially_cancelled')
    def _compute_order_status_display(self):
        for rec in self:
            label = status_label(rec.order_status)
            rec.order_status_display = f"{label} (Kısmi İptal)" if rec.partially_cancelled and label else label


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

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = status_label(rec.status)

    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

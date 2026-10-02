from odoo import models, fields, api

# Idefix sevkiyat (shipment) statüleri — developer.idefix.com "Sipariş sevkiyatlarının alınması"
IDEFIX_STATUS_LABELS = {
    'created': 'Oluşturuldu',
    'shipment_ready': 'Sevke Hazır',
    'shipment_picking': 'Hazırlanıyor',
    'shipment_invoiced': 'Faturalandı',
    'shipment_in_cargo': 'Kargoda',
    'shipment_delivered': 'Teslim Edildi',
    'shipment_undeliver': 'Teslim Edilemedi',
    'shipment_approved': 'Tamamlandı (Hakediş)',
    'shipment_cancelled': 'İptal',
    'shipment_unsupplied': 'Tedarik Edilemedi',
    'shipment_split': 'Bölündü',
}
# Sevkiyat kapandı: Odoo siparişi açılmaz / iptal edilir.
# Bölünen (split) ve tedarik edilemeyen (unsupplied) sevkiyatların kalan ürünleri aynı sipariş
# numarasında YENİ bir shipment olarak gelir — eski sevkiyatın Odoo siparişi iptal edilmelidir.
IDEFIX_CANCEL_STATUSES = ('shipment_cancelled', 'shipment_unsupplied', 'shipment_split')
# Odoo siparişi bu statülerde açılır (sonraki statülerde ilk kez görülen sevkiyat otomatik açılmaz)
IDEFIX_OPEN_STATUSES = ('created', 'shipment_ready', 'shipment_picking', 'shipment_invoiced')
# Artık değişmesi beklenmeyen statüler (açık sevkiyat yoklamasına girmez)
IDEFIX_FINAL_STATUSES = IDEFIX_CANCEL_STATUSES + ('shipment_delivered', 'shipment_approved')


def status_label(value):
    return IDEFIX_STATUS_LABELS.get(value, value or '')


def is_inactive_item_status(value):
    """Kalem statüsü (itemStatus) dokümante değil — iptal / tedarik edilemedi içerenler pasif sayılır."""
    value = (value or '').lower()
    return any(key in value for key in ('cancel', 'unsuppl', 'split'))


class IdefixOrder(models.Model):
    _name = 'idefix.order'
    _description = 'Idefix Siparişi (Sevkiyat)'
    _order = 'order_date desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('idefix.store', string='Mağaza', required=True, ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')

    order_id = fields.Char(string='Shipment ID', required=True, index=True,
                           help='Idefix sevkiyat (shipment) ID — API işlemleri bu ID ile yapılır')
    order_number = fields.Char(string='Sipariş No', required=True, index=True,
                               help='Idefix ana sipariş numarası (bölünen siparişlerde birden fazla sevkiyatta aynıdır)')
    order_date = fields.Datetime(string='Sipariş Tarihi')

    order_status = fields.Char(string='Sipariş Statüsü')
    order_status_display = fields.Char(string='İdefix Durumu', compute='_compute_order_status_display')
    status_updated_at = fields.Datetime(string='Statü Tarihi', readonly=True)
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
    cargo_tracking_url = fields.Char(string='Kargo Takip Linki')
    cargo_provider = fields.Char(string='Kargo Firması')
    cargo_profile_id = fields.Char(string='Kargo Profil ID')
    cargo_profile_name = fields.Char(string='Kargo Profili')

    # Tutar
    total_price = fields.Float(string='Toplam Tutar', help='İndirimler düşülmüş sevkiyat tutarı (discountedTotalPrice)')
    gross_price = fields.Float(string='Brüt Tutar', help='İndirimler düşülmeden önceki tutar (totalPrice)')
    platform_discount = fields.Float(string='Platform İndirimi')
    vendor_discount = fields.Float(string='Satıcı İndirimi')
    commission_amount = fields.Float(string='Komisyon', help='Kalemlerin komisyon toplamı')
    earning_amount = fields.Float(string='Hakediş', help='Kalemlerin satıcı hakediş toplamı')
    currency = fields.Char(string='Para Birimi', default='TL')

    # Senkron / hata takibi
    error_message = fields.Char(string='Hata', readonly=True, copy=False,
                                help='Odoo siparişi oluşturulamadıysa / güncellenemediyse nedeni')
    last_checked = fields.Datetime(string='Son Kontrol', readonly=True, copy=False)
    legacy_no_sale = fields.Boolean(
        string='Eski Kayıt (Otomatik Aktarılmaz)', readonly=True, copy=False,
        help="Güncellemeden önce Odoo siparişi açılmamış kayıt. Eski siparişler Nebim'e birden gitmesin diye "
             "otomatik aktarılmaz; gerekiyorsa 'Tekrar Dene' ile elle aktarılır.")

    # Idefix'e statü bildirimi (picking / invoiced)
    picking_sent = fields.Boolean(string="'Hazırlanıyor' Bildirildi", readonly=True, copy=False)
    picking_attempt_date = fields.Datetime(string='Son Hazırlanıyor Denemesi', readonly=True, copy=False)

    # Fatura gönderimi (invoiced statüsü + fatura linki)
    invoice_number = fields.Char(string='Fatura No', readonly=True, copy=False)
    invoice_sent = fields.Boolean(string='Fatura Gönderildi', readonly=True, copy=False)
    invoice_url = fields.Char(string='Fatura Linki', readonly=True, copy=False)
    invoice_sent_date = fields.Datetime(string='Fatura Gönderim Tarihi', readonly=True, copy=False)
    invoice_error = fields.Char(string='Fatura Gönderim Hatası', readonly=True, copy=False)
    invoice_attempt_date = fields.Datetime(string='Son Fatura Denemesi', readonly=True, copy=False)

    # Raw Data
    raw_data = fields.Text(string='Raw JSON Data')

    line_ids = fields.One2many('idefix.order.line', 'order_id', string='Sipariş Satırları')

    _store_order_uniq = models.Constraint(
        'UNIQUE(store_id, order_id)',
        'Bu mağazada aynı Idefix sevkiyatı zaten var.',
    )

    @api.depends('order_status')
    def _compute_order_status_display(self):
        for rec in self:
            rec.order_status_display = status_label(rec.order_status)


class IdefixOrderLine(models.Model):
    _name = 'idefix.order.line'
    _description = 'Idefix Sipariş Satırı'
    _rec_name = 'product_name'

    order_id = fields.Many2one('idefix.order', string='Idefix Siparişi', ondelete='cascade')
    item_id = fields.Char(string='Item ID', index=True)

    product_id = fields.Char(string='Idefix Product ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün/Stok Kodu')

    # Idefix list servisinde her kalem 1 adettir (aynı üründen 2 adet = 2 kalem)
    quantity = fields.Integer(string='Miktar', default=1)
    sale_price = fields.Float(string='Satış Fiyatı (KDV Hariç)')
    sale_price_tax_included = fields.Float(string='Satış Fiyatı (KDV Dahil)',
                                           help='İndirimler düşülmüş kalem tutarı (discountedTotalPrice)')
    gross_price = fields.Float(string='Liste Fiyatı', help='İndirim öncesi fiyat (price)')
    vat_rate = fields.Integer(string='KDV Oranı (%)', default=10)
    platform_discount = fields.Float(string='Platform İndirimi')
    vendor_discount = fields.Float(string='Satıcı İndirimi')
    commission_amount = fields.Float(string='Komisyon')
    earning_amount = fields.Float(string='Hakediş')
    vendor_amount = fields.Float(string='Satıcı Tutarı')

    status = fields.Char(string='Sipariş Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    cargo_tracking = fields.Char(string='Kargo Takip')
    cargo_company = fields.Char(string='Kargo Firması')

    ITEM_STATUS_LABELS = {
        'in_delivery': 'Teslimatta',
    }

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = (self.ITEM_STATUS_LABELS.get(rec.status)
                                  or IDEFIX_STATUS_LABELS.get(rec.status) or rec.status or '')

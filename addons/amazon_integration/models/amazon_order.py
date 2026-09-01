import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

AMAZON_STATUS_MAP = {
    'Pending': 'Beklemede (Pending)',
    'Unshipped': 'Kargolanacak (Unshipped)',
    'PartiallyShipped': 'Kısmen Kargolandı',
    'Shipped': 'Kargolandı (Shipped)',
    'Canceled': 'İptal Edildi (Canceled)',
    'Unfulfillable': 'Tedarik Edilemedi',
}


class AmazonOrder(models.Model):
    _name = 'amazon.order'
    _description = 'Amazon Siparişi'
    _order = 'order_date desc, id desc'
    _rec_name = 'amazon_order_number'

    name = fields.Char(string='Referans', compute='_compute_name', store=True)
    amazon_order_number = fields.Char(string='Amazon Sipariş No', required=True, index=True)
    store_id = fields.Many2one('amazon.store', string='Mağaza', index=True, ondelete='set null')
    store_name = fields.Char(string='Mağaza Adı', related='store_id.name', store=True, readonly=True)

    order_date = fields.Datetime(string='Sipariş Tarihi', index=True)
    order_status = fields.Char(string='Amazon Statüsü')
    status_display = fields.Char(string='Amazon Durumu', compute='_compute_status_display', store=True)

    fulfillment_channel = fields.Selection([
        ('MFN', 'Satıcı Tarafından (MFN)'),
        ('AFN', 'Amazon Tarafından (FBA/AFN)'),
    ], string='Teslimat Kanalı', default='MFN')

    # Müşteri ve Adres
    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='E-posta')
    customer_phone = fields.Char(string='Telefon')
    shipping_address = fields.Text(string='Teslimat Adresi')
    shipping_city = fields.Char(string='Şehir')
    shipping_district = fields.Char(string='İlçe/Bölge')
    postal_code = fields.Char(string='Posta Kodu')

    # Kargo
    cargo_provider = fields.Char(string='Kargo Firması')
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    easyship_tracking_id = fields.Char(
        string='EasyShip Takip Kodu',
        help='Amazon EasyShip API üzerinden çekilen gerçek kargo takip kodu (örn: ZA8156127)'
    )

    # Tutarlar
    total_price = fields.Float(string='Toplam Tutar', digits=(12, 2))
    currency = fields.Char(string='Para Birimi', default='TRY')

    # İlişkiler
    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='set null')
    line_ids = fields.One2many('amazon.order.line', 'order_id', string='Sipariş Satırları')
    raw_payload = fields.Text(string='Raw JSON', help='Amazon SP-API üzerinden gelen orijinal JSON verisi')

    @api.depends('amazon_order_number')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.amazon_order_number or _('Yeni Amazon Siparişi')

    @api.depends('order_status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = AMAZON_STATUS_MAP.get(rec.order_status, rec.order_status or '')

    def action_refetch_from_amazon(self):
        """Amazon'dan sipariş ve müşteri detaylarını yenile."""
        self.ensure_one()
        if not self.store_id:
            raise UserError(_("Bu siparişe bağlı bir Amazon mağazası bulunamadı."))
        self.store_id._refetch_single_amazon_order(self.amazon_order_number)
        
        msg = _('Sipariş ve müşteri bilgileri Amazon SP-API üzerinden yenilendi.')
        msg_type = 'success'
        if self.order_status == 'Pending' and not self.shipping_address:
            msg = _('Bu sipariş Amazon tarafında henüz "Pending" (Ödeme Bekliyor) durumundadır. Amazon PII politikası gereği ödeme onaylanana kadar adres ve müşteri bilgileri API üzerinden verilmeyebilir. Ödeme onaylandığında bilgiler otomatik olarak aktarılacaktır.')
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bilgi'),
                'message': msg,
                'type': msg_type,
                'sticky': False,
            }
        }


class AmazonOrderLine(models.Model):
    _name = 'amazon.order.line'
    _description = 'Amazon Sipariş Satırı'

    order_id = fields.Many2one('amazon.order', string='Amazon Siparişi', ondelete='cascade', index=True)
    order_item_id = fields.Char(string='Item ID', index=True)
    sku = fields.Char(string='Satıcı SKU', index=True)
    asin = fields.Char(string='ASIN', index=True, help='Amazon Standard Identification Number')
    product_name = fields.Char(string='Ürün Adı')
    quantity = fields.Integer(string='Miktar', default=1)
    price = fields.Float(string='Birim Fiyat', digits=(12, 2))
    item_tax = fields.Float(string='KDV / Vergi', digits=(12, 2))

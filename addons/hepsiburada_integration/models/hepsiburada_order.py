from odoo import models, fields, api

# Kalem bazında iptal sayılan HB statüleri (sipariş detay servisi)
HB_CANCEL_STATUSES = {'Cancelled', 'CancelledByCustomer', 'CancelledByMerchant', 'CancelledBySap'}


class HepsiburadaOrder(models.Model):
    _name = 'hepsiburada.order'
    _description = 'Hepsiburada Siparişi'
    _rec_name = 'hb_order_number'
    _order = 'order_date desc, id desc'

    hb_order_number = fields.Char(string='Sipariş Numarası', required=True, index=True)
    merchant_id = fields.Char(string='Merchant ID')
    store_id = fields.Many2one('hepsiburada.store', string='Mağaza', index=True, ondelete='set null')
    order_date = fields.Datetime(string='Sipariş Tarihi')
    status = fields.Char(string='Sipariş Statüsü')
    status_display = fields.Char(string='Hepsiburada Durumu', compute='_compute_status_display')
    partially_cancelled = fields.Boolean(string='Kısmi İptal', readonly=True)
    is_micro_export = fields.Boolean(string='Mikro İhracat', readonly=True)
    warning_message = fields.Text(string='Uyarı', readonly=True)
    sale_state = fields.Selection(related='sale_order_id.state', string='Odoo Sipariş Durumu')

    # Kargo ve Paketleme Verisi
    cargo_company = fields.Char(string='Kargo Firması')
    cargo_provider = fields.Char(string='Kargo Sağlayıcı Adı')
    cargo_tracking_number = fields.Char(string='Kargo Takip No')
    package_number = fields.Char(string='Paket Numarası', index=True)
    total_deci = fields.Float(string='Toplam Desi')

    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri Email')
    customer_phone = fields.Char(string='Müşteri Telefonu')
    tax_office = fields.Char(string='Vergi Dairesi')
    tax_number = fields.Char(string='Vergi/TC No')

    shipping_address = fields.Text(string='Teslimat Adresi')
    shipping_city = fields.Char(string='Teslimat İl')
    shipping_district = fields.Char(string='Teslimat İlçe')
    shipping_country_code = fields.Char(string='Ülke Kodu')

    total_price = fields.Float(string='Toplam Tutar')
    currency = fields.Char(string='Para Birimi', default='TRY')

    sale_order_id = fields.Many2one('sale.order', string='Odoo Siparişi', readonly=True, ondelete='cascade')
    line_ids = fields.One2many('hepsiburada.order.line', 'order_id', string='Satırlar')
    raw_payload = fields.Text(string='Raw JSON', help='API üzerinden gelen orijinal JSON verisi')

    # ─── Finans ───
    transaction_ids = fields.One2many('hepsiburada.transaction', 'order_id', string='Finansal Kayıtlar')
    claim_ids = fields.One2many('hepsiburada.claim', 'order_id', string='İade Talepleri')
    claim_count = fields.Integer(string='İade Talebi', compute='_compute_claim_count', store=True)
    total_commission = fields.Float(string='Komisyon (Sipariş)', compute='_compute_total_commission', store=True)
    fin_payment = fields.Float(string='Satış Tutarı', compute='_compute_financials', store=True)
    fin_return = fields.Float(string='İade Tutarı', compute='_compute_financials', store=True)
    fin_commission = fields.Float(string='Komisyon', compute='_compute_financials', store=True)
    fin_cargo = fields.Float(string='Kargo', compute='_compute_financials', store=True)
    fin_service_fee = fields.Float(string='Hizmet / İşlem Bedeli', compute='_compute_financials', store=True)
    fin_other = fields.Float(string='Diğer', compute='_compute_financials', store=True)
    fin_net = fields.Float(string='Net Hakediş', compute='_compute_financials', store=True)
    has_financials = fields.Boolean(string='Finans Verisi Var', compute='_compute_financials', store=True)
    estimated_net = fields.Float(
        string='Tahmini Net', compute='_compute_estimated_net',
        help='Finansal kayıt oluşmadan önce: tutar − komisyon − platform bedeli − desi × kargo birim fiyatı')

    HB_STATUS_MAP = {
        'Open': 'Açık',
        'Packaged': 'Paketlendi',
        'InTransit': 'Kargoda',
        'Delivered': 'Teslim Edildi',
        'Cancelled': 'İptal',
        'CancelledByCustomer': 'Müşteri İptali',
        'CancelledByMerchant': 'Satıcı İptali',
        'CancelledBySap': 'HB İptali',
        'ClaimCreated': 'Talep Açıldı',
        'UnDelivered': 'Teslim Edilemedi',
        'Returned': 'İade',
        'Shipped': 'Kargolandı',
        'Unpacked': 'Paket Bozuldu',
        'Packed': 'Paketlendi',
        'AtWarehouse': 'Depoda',
        'Processing': 'İşleniyor',
        'Completed': 'Tamamlandı',
    }

    @api.depends('status', 'partially_cancelled')
    def _compute_status_display(self):
        for rec in self:
            label = self.HB_STATUS_MAP.get(rec.status, rec.status or '')
            if rec.partially_cancelled and rec.status not in HB_CANCEL_STATUSES:
                label = f"{label} (Kısmi İptal)" if label else 'Kısmi İptal'
            rec.status_display = label

    @api.depends('claim_ids')
    def _compute_claim_count(self):
        for rec in self:
            rec.claim_count = len(rec.claim_ids)

    @api.depends('line_ids.commission_amount')
    def _compute_total_commission(self):
        for rec in self:
            rec.total_commission = sum(rec.line_ids.mapped('commission_amount'))

    @api.depends('transaction_ids.signed_amount', 'transaction_ids.category')
    def _compute_financials(self):
        for rec in self:
            sums = dict.fromkeys(('payment', 'return', 'commission', 'cargo', 'service_fee', 'other'), 0.0)
            for tx in rec.transaction_ids:
                sums[tx.category or 'other'] += tx.signed_amount
            rec.fin_payment = sums['payment']
            rec.fin_return = sums['return']
            rec.fin_commission = sums['commission']
            rec.fin_cargo = sums['cargo']
            rec.fin_service_fee = sums['service_fee']
            rec.fin_other = sums['other']
            rec.fin_net = sum(sums.values())
            rec.has_financials = bool(rec.transaction_ids)

    @api.depends('total_price', 'total_commission', 'total_deci',
                 'store_id.platform_fee_rate', 'store_id.cargo_unit_price')
    def _compute_estimated_net(self):
        for rec in self:
            store = rec.store_id
            fee = rec.total_price * (store.platform_fee_rate or 0.0) / 100.0
            cargo = (rec.total_deci or 0.0) * (store.cargo_unit_price or 0.0)
            rec.estimated_net = rec.total_price - rec.total_commission - fee - cargo


    def action_clear_warning(self):
        self.write({'warning_message': False})

    def action_view_claims(self):
        self.ensure_one()
        return {
            'name': 'İade Talepleri',
            'type': 'ir.actions.act_window',
            'res_model': 'hepsiburada.claim',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
        }


class HepsiburadaOrderLine(models.Model):
    _name = 'hepsiburada.order.line'
    _description = 'Hepsiburada Sipariş Satırı'

    order_id = fields.Many2one('hepsiburada.order', string='Sipariş', ondelete='cascade', index=True)
    line_item_id = fields.Char(string='Hepsiburada Satır ID', required=True, index=True)
    sku = fields.Char(string='Hepsiburada SKU')
    merchant_sku = fields.Char(string='Satıcı Stok Kodu')
    product_name = fields.Char(string='Ürün Adı')
    quantity = fields.Integer(string='Miktar', default=1)
    cancelled_qty = fields.Integer(string='İptal Adedi', default=0, readonly=True)
    remaining_qty = fields.Integer(string='Kalan Adet', compute='_compute_remaining_qty')
    cancel_keys = fields.Text(
        string='İşlenen İptaller', readonly=True,
        help='Aynı iptal kaydının iki kez düşülmemesi için işlenen iptal anahtarları')

    price = fields.Float(string='Kalem Tutarı')
    merchant_unit_price = fields.Float(string='Satıcı Birim Hakediş', help='Satıcıya geçecek olan gerçek ürün meblağı')
    vat = fields.Float(string='KDV Tutarı')
    vat_rate = fields.Float(string='KDV Oranı')

    commission_amount = fields.Float(string='Komisyon')
    commission_rate = fields.Float(string='Komisyon Oranı')
    status = fields.Char(string='Satır Statüsü')
    status_display = fields.Char(string='Durum', compute='_compute_status_display')

    STATUS_MAP = {
        'Open': 'Açık',
        'Packaged': 'Paketlendi',
        'InTransit': 'Kargoda',
        'Delivered': 'Teslim Edildi',
        'Cancelled': 'İptal',
        'CancelledByCustomer': 'Müşteri İptali',
        'CancelledByMerchant': 'Satıcı İptali',
        'CancelledBySap': 'HB İptali',
        'ClaimCreated': 'Talep Açıldı',
        'UnDelivered': 'Teslim Edilemedi',
        'Returned': 'İade',
        'Shipped': 'Kargolandı',
        'Unpacked': 'Paket Bozuldu',
        'Packed': 'Paketlendi',
        'Completed': 'Tamamlandı',
    }

    @api.depends('quantity', 'cancelled_qty')
    def _compute_remaining_qty(self):
        for rec in self:
            rec.remaining_qty = max((rec.quantity or 0) - (rec.cancelled_qty or 0), 0)

    @api.depends('status', 'cancelled_qty', 'quantity')
    def _compute_status_display(self):
        for rec in self:
            label = self.STATUS_MAP.get(rec.status, rec.status or '')
            if rec.cancelled_qty and rec.cancelled_qty < rec.quantity:
                label = f"Kısmi İptal ({rec.cancelled_qty}/{rec.quantity})"
            rec.status_display = label

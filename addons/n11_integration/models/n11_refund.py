import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

N11_REFUND_STATUS = [
    ('REQUESTED', 'Talep Edildi'),
    ('APPROVAL_WAITING', 'Onay Bekliyor'),
    ('PENDING', 'Askıda'),
    ('PENDED', 'Ertelendi'),
    ('APPROVED', 'Onaylandı'),
    ('DENIED', 'Reddedildi'),
    ('CANCELLED', 'İptal Edildi'),
    ('MANUAL_REFUND', 'Manuel İade'),
]


def _parse_n11_date(value):
    """SOAP tarihleri: dd/MM/yyyy (dokümanda), yyyy-MM-dd (xs:date) ya da saatli olabilir."""
    if not value or not isinstance(value, str):
        return False
    value = value.strip()
    for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return False


def _to_float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


class N11Refund(models.Model):
    _name = 'n11.refund'
    _description = 'N11 İade Talepleri'
    _order = 'refund_date desc, id desc'
    _rec_name = 'refund_id'

    store_id = fields.Many2one('n11.store', string='Mağaza', required=True, ondelete='cascade')
    n11_order_id = fields.Many2one('n11.order', string='N11 Siparişi', index=True, ondelete='set null')
    sale_order_id = fields.Many2one(related='n11_order_id.sale_order_id', string='Odoo Siparişi')
    refund_id = fields.Char(string='İade Talep No', index=True, required=True)
    order_number = fields.Char(string='Sipariş No', index=True)
    order_date = fields.Datetime(string='Ödeme Tarihi')
    refund_number = fields.Char(string='Kampanya / Kargo Kodu')

    refund_type = fields.Char(string='İade Sebebi')
    refund_status = fields.Integer(string='İade Statü Kodu')  # eski alan, kullanılmıyor
    status = fields.Selection(N11_REFUND_STATUS, string='Durum', index=True)
    refund_status_name = fields.Char(string='İade Statü Adı')
    executer = fields.Char(string='İşlemi Yapan')
    refund_date = fields.Datetime(string='Talep Tarihi')
    approved_date = fields.Datetime(string='Onay Tarihi')
    denied_date = fields.Datetime(string='Red Tarihi')
    cancelled_date = fields.Datetime(string='İptal Tarihi')
    approval_remaining_time = fields.Char(string='Kalan Onay Süresi')

    total_amount = fields.Float(string='Birim Fiyat')
    refund_amount = fields.Float(string='İade Tutar')

    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri E-Posta')

    product_id = fields.Char(string='N11 Ürün ID')
    sku_id = fields.Char(string='SKU ID')
    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Ürün Kodu')
    attribute_names = fields.Char(string='Varyant')

    shipment_company_name = fields.Char(string='İade Kargo Firması')
    shipment_code = fields.Char(string='İade Kargo Kodu', index=True)

    description = fields.Text(string='Müşteri Açıklaması')
    quantity = fields.Integer(string='Adet')

    raw_data = fields.Text(string='Ham Veri')

    _refund_store_uniq = models.Constraint(
        'unique(store_id, refund_id)', 'Bu iade talebi bu mağaza için zaten kayıtlı.')

    # ─── Senkronizasyon ─────────────────────────────────────────

    @api.model
    def cron_sync_n11_returns(self):
        stores = self.env['n11.store'].search([('active', '=', True), ('process_returns', '=', True)])
        for store in stores:
            try:
                self.sync_returns_for_store(store)
                self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception("N11 iade senkronizasyon hatası [%s]: %s", store.name, e)

    @api.model
    def sync_returns_for_store(self, store):
        """Son 'İade Gün Aralığı' içindeki iade taleplerini çeker / günceller."""
        api_client = store.get_api()
        end = fields.Date.context_today(self)
        start = end - timedelta(days=max(store.return_day_range or 3, 1))
        created = updated = 0
        page = 0
        page_count = 1
        while page < page_count and page < 50:
            res = api_client.get_claim_returns(start, end, page=page)
            if not res.get('success'):
                _logger.warning("N11 iade listesi alınamadı [%s]: %s", store.name, res.get('error'))
                break
            page_count = res.get('page_count') or 1
            for claim in res.get('data') or []:
                action = self._upsert_claim(store, claim)
                created += action == 'created'
                updated += action == 'updated'
            page += 1
        _logger.info("N11 iade senkronizasyonu [%s]: %s yeni, %s güncellenen", store.name, created, updated)
        return {'created': created, 'updated': updated}

    @api.private
    def _upsert_claim(self, store, claim):
        if not isinstance(claim, dict) or not claim.get('claimReturnId'):
            return 'skipped'
        status = claim.get('status')
        if isinstance(status, dict):  # şemada status karmaşık tip; değer çocuk etiket olarak da gelebilir
            status = next(iter(status), '')
        status = (status or '').strip().upper()
        valid = dict(N11_REFUND_STATUS)
        try:
            qty = int(float(claim.get('quantity') or 0))
        except (TypeError, ValueError):
            qty = 0
        unit_price = _to_float(claim.get('unitPrice'))
        order_number = (claim.get('orderNumber') or '').strip()
        vals = {
            'store_id': store.id,
            'refund_id': str(claim['claimReturnId']),
            'order_number': order_number,
            'status': status if status in valid else False,
            'refund_status_name': valid.get(status, status),
            'executer': claim.get('executer') if isinstance(claim.get('executer'), str) else '',
            'refund_type': claim.get('returnReasonType') or '',
            'description': claim.get('returnReasonDescription') or '',
            'refund_date': _parse_n11_date(claim.get('requestDate')),
            'approved_date': _parse_n11_date(claim.get('approvedDate')),
            'denied_date': _parse_n11_date(claim.get('deniedDate')),
            'cancelled_date': _parse_n11_date(claim.get('cancelledDate')),
            'order_date': _parse_n11_date(claim.get('paymentDate')),
            'approval_remaining_time': claim.get('approvalRemainingTime') or '',
            'product_id': claim.get('productId') or '',
            'sku_id': str(claim.get('skuId') or ''),
            'product_name': claim.get('productName') or '',
            'attribute_names': claim.get('attributesNames') or '',
            'quantity': qty,
            'total_amount': unit_price,
            'refund_amount': _to_float(claim.get('finalPrice')) or unit_price * qty,
            'customer_name': claim.get('buyerName') or '',
            'customer_email': claim.get('buyerEmail') or '',
            'shipment_company_name': claim.get('shipmentCompany') or '',
            'shipment_code': claim.get('trackingNumber') or '',
            'refund_number': claim.get('campaignNumber') or '',
            'raw_data': json.dumps(claim, ensure_ascii=False),
        }
        if order_number:
            order = self.env['n11.order'].search(
                [('store_id', '=', store.id), ('order_number', '=', order_number)], limit=1)
            if order:
                vals['n11_order_id'] = order.id
                line = order.line_ids.filtered(lambda l: l.product_id and l.product_id == vals['product_id'])[:1]
                if line:
                    vals['product_code'] = line.product_code
        existing = self.search([('store_id', '=', store.id), ('refund_id', '=', vals['refund_id'])], limit=1)
        if existing:
            if existing.raw_data == vals['raw_data'] and existing.n11_order_id.id == vals.get('n11_order_id', existing.n11_order_id.id):
                return 'unchanged'
            existing.write(vals)
            return 'updated'
        self.create(vals)
        return 'created'

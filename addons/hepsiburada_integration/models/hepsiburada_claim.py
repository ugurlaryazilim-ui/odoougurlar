import json
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

_PAGE_LIMIT = 100
_MAX_PAGES = 50


class HepsiburadaClaim(models.Model):
    _name = 'hepsiburada.claim'
    _description = 'Hepsiburada İade / Talep'
    _rec_name = 'claim_number'
    _order = 'claim_date desc, id desc'

    claim_number = fields.Char(string='Talep No', required=True, index=True)
    hb_id = fields.Char(string='HB Talep ID')
    store_id = fields.Many2one('hepsiburada.store', string='Mağaza', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one('hepsiburada.order', string='HB Siparişi', ondelete='set null', index=True)
    sale_order_id = fields.Many2one(related='order_id.sale_order_id', string='Odoo Siparişi')
    order_number = fields.Char(string='Sipariş No', index=True)
    claim_type = fields.Char(string='Talep Tipi')
    status = fields.Char(string='Durum', index=True)
    status_display = fields.Char(string='Talep Durumu', compute='_compute_status_display')
    sku = fields.Char(string='SKU')
    quantity = fields.Integer(string='Adet')
    customer_name = fields.Char(string='Müşteri')
    explanation = fields.Text(string='Müşteri Açıklaması')
    claim_date = fields.Datetime(string='Talep Tarihi')
    order_date = fields.Datetime(string='Sipariş Tarihi')
    price_amount = fields.Float(string='Birim Fiyat')
    total_price_amount = fields.Float(string='Toplam Tutar')
    refund_amount = fields.Float(string='İade Tutarı')
    refund_date = fields.Datetime(string='İade Tarihi')
    finalized_with = fields.Char(string='Sonuç', help='Refund: para iadesi, Change: değişim')
    merchant_rejection_statement = fields.Text(string='Red Açıklaması')
    raw_payload = fields.Text(string='Raw JSON')

    _claim_uniq = models.Constraint('UNIQUE(store_id, claim_number)', 'Bu iade talebi zaten mevcut.')

    STATUS_MAP = {
        'NewRequest': 'Yeni Talep',
        'AwaitingAction': 'Aksiyon Bekliyor',
        'AwaitingPreApproval': 'Ön Onay Bekliyor',
        'Accepted': 'Kabul Edildi',
        'Rejected': 'Reddedildi',
        'Cancelled': 'İptal Edildi',
        'Completed': 'Tamamlandı',
        'Dispute': 'İhtilaflı',
    }

    @api.depends('status')
    def _compute_status_display(self):
        for rec in self:
            rec.status_display = self.STATUS_MAP.get(rec.status, rec.status or '')

    # ─── Senkronizasyon ───

    @api.model
    def _parse_dt(self, value):
        return self.env['hepsiburada.transaction']._parse_dt(value)

    @api.model
    def _prepare_vals(self, item, store):
        return {
            'claim_number': str(item.get('number') or item.get('claimNumber') or ''),
            'hb_id': item.get('id') or False,
            'store_id': store.id,
            'order_number': item.get('orderNumber') or False,
            'claim_type': item.get('claimType') or item.get('type') or False,
            'status': item.get('status') or False,
            'sku': item.get('sku') or False,
            'quantity': int(item.get('quantity') or 0),
            'customer_name': item.get('customerName') or False,
            'explanation': item.get('explanation') or False,
            'claim_date': self._parse_dt(item.get('claimDate')),
            'order_date': self._parse_dt(item.get('orderDate')),
            'price_amount': float(item.get('priceAmount') or 0.0),
            'total_price_amount': float(item.get('totalPriceAmount') or 0.0),
            'refund_amount': float(item.get('refundAmount') or 0.0),
            'refund_date': self._parse_dt(item.get('refundDate')),
            'finalized_with': item.get('finalizedWith') or False,
            'merchant_rejection_statement': item.get('merchantRejectionStatement') or False,
        }

    @api.model
    def _sync_store(self, store):
        """Son N günde oluşturulan iade/değişim taleplerini çeker (yalnızca kayıt; HB'de aksiyon alınmaz)."""
        store = store.sudo()
        if not store.process_returns:
            return {'created': 0, 'updated': 0}
        merchant, _user, _pwd = store._get_clean_credentials()
        if not merchant:
            return {'created': 0, 'updated': 0}

        session, _m = store._get_session()
        url = f"https://{store._get_api_domain()}/claims/merchantId/{merchant}"
        now = datetime.utcnow() + timedelta(hours=3)
        start = now - timedelta(days=store.return_day_range or 3)

        items = []
        for page in range(_MAX_PAGES):
            params = {
                'beginDate': start.strftime('%Y-%m-%d %H:%M'),
                'endDate': now.strftime('%Y-%m-%d %H:%M'),
                'offset': page * _PAGE_LIMIT,
                'limit': _PAGE_LIMIT,
            }
            try:
                res = session.get(url, params=params, timeout=30)
            except Exception as e:
                _logger.warning("HB talep isteği başarısız (%s): %s", store.name, e)
                return {'created': 0, 'updated': 0, 'failed': True}
            if res.status_code == 404:
                break
            if res.status_code != 200:
                _logger.warning("HB talep HTTP %s: %s", res.status_code, res.text[:300])
                return {'created': 0, 'updated': 0, 'failed': True}
            data = res.json() or []
            page_items = data.get('items', []) if isinstance(data, dict) else data
            items.extend(page_items or [])
            if not page_items or len(page_items) < _PAGE_LIMIT:
                break

        created = updated = 0
        HbOrder = self.env['hepsiburada.order'].sudo()
        Transaction = self.env['hepsiburada.transaction']
        for item in items:
            vals = self._prepare_vals(item, store)
            if not vals['claim_number']:
                continue
            try:
                with self.env.cr.savepoint():
                    claim = self.sudo().search([
                        ('store_id', '=', store.id), ('claim_number', '=', vals['claim_number'])], limit=1)
                    if vals['order_number']:
                        hb_order = HbOrder.search([
                            ('hb_order_number', '=', vals['order_number']),
                            '|', ('store_id', '=', store.id), ('merchant_id', '=', store.merchant_id),
                        ], limit=1)
                        vals['order_id'] = hb_order.id or False
                    if claim:
                        changed = Transaction._changed_vals(claim, vals)
                        if changed:
                            changed['raw_payload'] = json.dumps(item, ensure_ascii=False)
                            claim.write(changed)
                            updated += 1
                    else:
                        vals['raw_payload'] = json.dumps(item, ensure_ascii=False)
                        self.sudo().create(vals)
                        created += 1
            except Exception as e:
                _logger.warning("HB talep yazılamadı (%s): %s", vals['claim_number'], e)

        if created or updated:
            _logger.info("HB iade talepleri [%s]: %s yeni, %s güncellenen", store.name, created, updated)
        return {'created': created, 'updated': updated}

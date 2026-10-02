"""Idefix iade talepleri (claim-list) — her kayıt bir iade kalemidir (claim line)."""
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_REFUND_SYNC_EVERY = timedelta(minutes=30)
_PAGE_SIZE = 50
_MAX_PAGES = 50

CLAIM_STATE_LABELS = {
    'ready': 'İade Talebi Oluştu',
    'in_cargo': 'Kargoda',
    'waiting_vendor_approve': 'Satıcı Onayı Bekliyor',
    'approved': 'Onaylandı',
    'decline': 'Reddedildi',
    'vendor_decline_request': 'Red Talebi İnceleniyor',
}


class IdefixRefund(models.Model):
    _name = 'idefix.refund'
    _description = 'Idefix İade Talepleri'
    _order = 'refund_date desc, id desc'
    _rec_name = 'refund_number'

    store_id = fields.Many2one('idefix.store', string='Mağaza', required=True, ondelete='cascade')
    refund_id = fields.Char(string='İade (Claim) ID', index=True, required=True)
    claim_line_id = fields.Char(string='İade Kalem ID', index=True)
    refund_number = fields.Char(string='İade No', compute='_compute_refund_number', store=True)
    order_number = fields.Char(string='Sipariş No', index=True)
    order_line_id = fields.Char(string='Sipariş Kalem ID', index=True)
    order_date = fields.Datetime(string='Sipariş Tarihi')
    idefix_order_id = fields.Many2one('idefix.order', string='Idefix Sevkiyatı', ondelete='set null', index=True)
    sale_order_id = fields.Many2one(related='idefix_order_id.sale_order_id', string='Odoo Siparişi')

    refund_type = fields.Char(string='İade Sebebi')
    claim_state = fields.Char(string='İade Statüsü')
    refund_status_name = fields.Char(string='İade Statü Adı')
    refund_date = fields.Datetime(string='İade Tarihi')
    state_updated_at = fields.Datetime(string='Statü Tarihi')
    auto_approve_date = fields.Datetime(string='Otomatik Onay Tarihi',
                                        help='Bu tarihe kadar işlem yapılmazsa Idefix iadeyi otomatik onaylar')
    is_controversial = fields.Boolean(string='İhtilaflı')

    total_amount = fields.Float(string='Kalem Tutarı')
    refund_amount = fields.Float(string='İade Tutarı')

    customer_name = fields.Char(string='Müşteri Adı')
    customer_email = fields.Char(string='Müşteri E-Posta')

    product_name = fields.Char(string='Ürün Adı')
    product_code = fields.Char(string='Barkod')

    shipment_company_name = fields.Char(string='İade Kargo Firması')
    shipment_code = fields.Char(string='İade Kargo Kodu', index=True)
    cargo_tracking_number = fields.Char(string='İade Kargo Takip No')

    description = fields.Text(string='Müşteri Açıklaması')
    vendor_note = fields.Text(string='Satıcı Notu')
    decline_note = fields.Text(string='Red Talebi Notu')
    quantity = fields.Integer(string='Adet', default=1)

    raw_data = fields.Text(string='Ham Veri')

    _store_claim_line_uniq = models.Constraint(
        'UNIQUE(store_id, refund_id, claim_line_id)',
        'Bu iade kalemi zaten kayıtlı.',
    )

    @api.depends('refund_id', 'claim_line_id')
    def _compute_refund_number(self):
        for rec in self:
            rec.refund_number = f"{rec.refund_id}/{rec.claim_line_id}" if rec.claim_line_id else rec.refund_id

    # ─── Senkron ─────────────────────────────────────────────

    @api.model
    def _sync_refunds_if_due(self, store, api_client=None):
        """Sipariş senkronu içinde: 'İadeleri İşle' açıksa en fazla 30 dakikada bir iadeleri çeker."""
        if not store.process_returns:
            return
        now = fields.Datetime.now()
        if store.last_refund_sync and now - store.last_refund_sync < _REFUND_SYNC_EVERY:
            return
        self._sync_refunds(store, api_client)

    @api.model
    def _sync_refunds(self, store, api_client=None):
        """Son 'İade Gün Aralığı' gündeki iade taleplerini çeker. (oluşturulan, güncellenen, hata) döner."""
        Order = self.env['idefix.order']
        api_client = api_client or store.get_api()
        end = Order._now_turkey() + timedelta(minutes=5)
        start = end - timedelta(days=max(store.return_day_range or 30, 1))
        created = updated = 0
        error = False
        for page in range(1, _MAX_PAGES + 1):
            res = api_client.get_claims(start_date=start, end_date=end, page=page, limit=_PAGE_SIZE)
            if not res.get('success'):
                error = res.get('error') or 'Bilinmeyen hata'
                break
            body = res.get('data') if isinstance(res.get('data'), dict) else {}
            claims = [c for c in body.get('items') or [] if isinstance(c, dict)]
            for claim in claims:
                try:
                    with self.env.cr.savepoint():
                        c, u = self._upsert_claim(store, claim)
                    created += c
                    updated += u
                except Exception as e:
                    self.env.invalidate_all(flush=False)
                    _logger.exception("Idefix iade işleme hatası (%s): %s", claim.get('id'), e)
            page_count = int(body.get('pageCount') or 0)
            if not claims or (page_count and page >= page_count) or (not page_count and len(claims) < _PAGE_SIZE):
                break
        if error:
            _logger.warning("Idefix iade listesi alınamadı [%s]: %s", store.name, error)
        else:
            store._write_refund_sync(fields.Datetime.now())
        return created, updated, error

    @api.model
    def _upsert_claim(self, store, claim):
        Order = self.env['idefix.order']
        claim_id = str(claim.get('id') or '')
        if not claim_id:
            return 0, 0
        order_number = str(claim.get('orderNumber') or '')
        shipments = Order.search([('store_id', '=', store.id), ('order_number', '=', order_number)]) \
            if order_number else Order
        created = updated = 0
        for item in claim.get('items') or []:
            if not isinstance(item, dict):
                continue
            line_id = str(item.get('id') or '')
            order_line_id = str(item.get('orderLineId') or '')
            shipment = shipments.filtered(lambda o: order_line_id in o.line_ids.mapped('item_id'))[:1] \
                or shipments[:1]
            reason = item.get('customerReason') or item.get('platformReason') or item.get('vendorReason') or ''
            vals = {
                'store_id': store.id,
                'refund_id': claim_id,
                'claim_line_id': line_id,
                'order_number': order_number,
                'order_line_id': order_line_id,
                'order_date': Order._parse_datetime(claim.get('orderCreatedAt')),
                'idefix_order_id': shipment.id or False,
                'refund_type': reason,
                'claim_state': item.get('state') or '',
                'refund_status_name': item.get('stateName') or CLAIM_STATE_LABELS.get(item.get('state'), ''),
                'refund_date': Order._parse_datetime(claim.get('createdAt')),
                'state_updated_at': Order._parse_datetime(item.get('stateUpdatedAt')),
                'auto_approve_date': Order._parse_datetime(item.get('autoApproveDate')),
                'is_controversial': bool(item.get('isControversial')),
                'total_amount': float(item.get('totalPrice') or 0.0),
                'refund_amount': float(item.get('discountedTotalPrice') or 0.0),
                'customer_name': claim.get('customerName') or '',
                'product_name': item.get('productName') or '',
                'product_code': item.get('barcode') or item.get('productCode') or '',
                'shipment_company_name': claim.get('cargoCompanyName') or '',
                'shipment_code': claim.get('cargoKey') or '',
                'cargo_tracking_number': claim.get('cargoTrackingNumber') or '',
                'description': item.get('customerNote') or item.get('note') or '',
                'vendor_note': item.get('vendorNote') or '',
                'decline_note': ' — '.join(filter(None, [item.get('declineRequestReasonName'),
                                                          item.get('declineRequestNote')])),
                'quantity': 1,
                'raw_data': json.dumps({'claim': {k: v for k, v in claim.items() if k != 'items'}, 'item': item},
                                       ensure_ascii=False, sort_keys=True),
            }
            rec = self.search([('store_id', '=', store.id), ('refund_id', '=', claim_id),
                               ('claim_line_id', '=', line_id)], limit=1)
            if rec:
                diff = {k: v for k, v in vals.items()
                        if (rec[k].id if isinstance(rec[k], models.BaseModel) else rec[k]) != v}
                if diff:
                    rec.write(diff)
                    updated += 1
            else:
                self.create(vals)
                created += 1
        return created, updated

    def _refetch(self):
        """İşlem sonrası ilgili iadeleri Idefix'ten tekrar çeker (claim ID ile)."""
        for store in self.mapped('store_id'):
            api_client = store.get_api()
            for claim_id in set(self.filtered(lambda r: r.store_id == store).mapped('refund_id')):
                res = api_client.get_claims(ids=[claim_id])
                body = res.get('data') if res.get('success') and isinstance(res.get('data'), dict) else {}
                for claim in body.get('items') or []:
                    if isinstance(claim, dict) and str(claim.get('id')) == claim_id:
                        self._upsert_claim(store, claim)

    # ─── İşlemler ────────────────────────────────────────────

    def _check_actionable(self):
        not_ready = self.filtered(lambda r: r.claim_state != 'waiting_vendor_approve')
        if not_ready:
            raise UserError(_("Yalnızca 'Satıcı Onayı Bekliyor' statüsündeki iadeler işlenebilir: %s",
                              ', '.join(not_ready.mapped('refund_number'))))

    def action_approve(self):
        """Seçili iade kalemlerini Idefix'te onayla (claim-approve)."""
        self._check_actionable()
        errors = []
        for (store, claim_id), lines in self._group_by_claim().items():
            res = store.get_api().approve_claim(claim_id, lines.mapped('claim_line_id'))
            if not res.get('success'):
                errors.append(f"{claim_id}: {res.get('error')}")
        self._refetch()
        if errors:
            raise UserError(_("Bazı iadeler onaylanamadı:\n%s", '\n'.join(errors)))
        return self.env['idefix.order']._notify('İade', f"{len(self)} iade kalemi onaylandı.", 'success')

    def action_open_decline_wizard(self):
        self._check_actionable()
        return {
            'type': 'ir.actions.act_window',
            'name': _('İade Red Talebi'),
            'res_model': 'idefix.claim.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_refund_ids': [(6, 0, self.ids)]},
        }

    def _group_by_claim(self):
        groups = {}
        for rec in self:
            key = (rec.store_id, rec.refund_id)
            groups[key] = groups.get(key, self.browse()) | rec
        return groups

import json

from dateutil import parser as date_parser

from odoo import models, fields, api

# Finances API v0 (listFinancialEventsByOrderId) → sipariş bazlı olay listeleri
FINANCE_EVENT_LISTS = [
    ('ShipmentEventList', 'shipment'),
    ('RefundEventList', 'refund'),
    ('GuaranteeClaimEventList', 'guarantee'),
    ('ChargebackEventList', 'chargeback'),
]


def _money(value):
    try:
        return float((value or {}).get('CurrencyAmount') or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


class AmazonFinanceEvent(models.Model):
    _name = 'amazon.finance.event'
    _description = 'Amazon Finansal İşlem'
    _order = 'posted_date desc, id desc'
    _rec_name = 'order_number'

    store_id = fields.Many2one('amazon.store', string='Mağaza', required=True, ondelete='cascade', index=True)
    order_number = fields.Char(string='Amazon Sipariş No', required=True, index=True)
    amazon_order_id = fields.Many2one('amazon.order', string='Amazon Siparişi', ondelete='set null', index=True)
    sale_order_id = fields.Many2one(related='amazon_order_id.sale_order_id', string='Odoo Siparişi')
    event_key = fields.Char(string='Olay Anahtarı', required=True, index=True)
    event_type = fields.Selection([
        ('shipment', 'Satış (Sevkiyat)'),
        ('refund', 'İade'),
        ('guarantee', 'A-z Garanti Talebi'),
        ('chargeback', 'Ters İbraz (Chargeback)'),
    ], string='İşlem Tipi', required=True)
    posted_date = fields.Datetime(string='İşlem Tarihi')

    principal = fields.Float(string='Ürün Tutarı', digits=(12, 2))
    tax = fields.Float(string='Vergi', digits=(12, 2))
    shipping = fields.Float(string='Kargo Geliri', digits=(12, 2))
    promotion = fields.Float(string='Promosyon', digits=(12, 2))
    commission = fields.Float(string='Komisyon', digits=(12, 2))
    other_fees = fields.Float(string='Diğer Kesintiler', digits=(12, 2))
    net_amount = fields.Float(string='Net Tutar', digits=(12, 2),
                              help='Olaydaki tüm tahsilat, kesinti ve promosyonların toplamı (Amazon işaretleriyle).')
    currency = fields.Char(string='Para Birimi')
    fee_breakdown = fields.Text(string='Kesinti Detayı')
    raw_data = fields.Text(string='Ham Veri')

    _event_unique = models.Constraint(
        'unique(store_id, order_number, event_key)',
        'Aynı Amazon finans olayı iki kez kaydedilemez.',
    )

    @api.model
    def _parse_event(self, event, event_type):
        """Tek bir finans olayını (ShipmentEvent / RefundEvent ...) tutarlara ayırır.

        Amazon tutarları işaretli gönderir: tahsilatlar +, kesintiler (komisyon vb.) ve promosyonlar -.
        """
        vals = dict(principal=0.0, tax=0.0, shipping=0.0, promotion=0.0,
                    commission=0.0, other_fees=0.0, net_amount=0.0)
        fees = {}
        currency = ''

        def add_charge(charge):
            nonlocal currency
            amount = _money(charge.get('ChargeAmount'))
            currency = currency or (charge.get('ChargeAmount') or {}).get('CurrencyCode') or ''
            ctype = charge.get('ChargeType') or ''
            if ctype == 'Principal':
                vals['principal'] += amount
            elif 'Tax' in ctype:
                vals['tax'] += amount
            elif ctype.startswith('Shipping'):
                vals['shipping'] += amount
            vals['net_amount'] += amount

        def add_fee(fee):
            nonlocal currency
            amount = _money(fee.get('FeeAmount'))
            currency = currency or (fee.get('FeeAmount') or {}).get('CurrencyCode') or ''
            ftype = fee.get('FeeType') or 'Diğer'
            if ftype == 'Commission':
                vals['commission'] += amount
            else:
                vals['other_fees'] += amount
            fees[ftype] = fees.get(ftype, 0.0) + amount
            vals['net_amount'] += amount

        def add_promotion(promo):
            amount = _money(promo.get('PromotionAmount'))
            vals['promotion'] += amount
            vals['net_amount'] += amount

        for key in ('OrderChargeList', 'OrderChargeAdjustmentList'):
            for charge in event.get(key) or []:
                add_charge(charge)
        for key in ('ShipmentFeeList', 'ShipmentFeeAdjustmentList', 'OrderFeeList', 'OrderFeeAdjustmentList'):
            for fee in event.get(key) or []:
                add_fee(fee)
        for key in ('ShipmentItemList', 'ShipmentItemAdjustmentList'):
            for item in event.get(key) or []:
                for ckey in ('ItemChargeList', 'ItemChargeAdjustmentList'):
                    for charge in item.get(ckey) or []:
                        add_charge(charge)
                for fkey in ('ItemFeeList', 'ItemFeeAdjustmentList'):
                    for fee in item.get(fkey) or []:
                        add_fee(fee)
                for pkey in ('PromotionList', 'PromotionAdjustmentList'):
                    for promo in item.get(pkey) or []:
                        add_promotion(promo)

        posted = False
        if event.get('PostedDate'):
            try:
                posted = date_parser.parse(event['PostedDate']).replace(tzinfo=None)
            except (ValueError, TypeError, OverflowError):
                posted = False

        vals.update({
            'event_type': event_type,
            'posted_date': posted,
            'currency': currency,
            'fee_breakdown': '\n'.join(f"{k}: {v:.2f}" for k, v in sorted(fees.items())),
            'raw_data': json.dumps(event, ensure_ascii=False),
        })
        return vals

    @api.model
    def _upsert_from_payload(self, store, amazon_order, financial_events):
        """FinancialEvents nesnesindeki olayları kaydeder. Döner: (yeni, güncellenen)."""
        created = updated = 0
        for list_name, event_type in FINANCE_EVENT_LISTS:
            for index, event in enumerate(financial_events.get(list_name) or []):
                if not isinstance(event, dict):
                    continue
                order_number = event.get('AmazonOrderId') or amazon_order.amazon_order_number
                vals = self._parse_event(event, event_type)
                vals.update({
                    'store_id': store.id,
                    'order_number': order_number,
                    'amazon_order_id': amazon_order.id,
                    # Aynı tarihte birden fazla olay olabilir → liste sırası anahtara dahil
                    'event_key': f"{event_type}|{event.get('PostedDate') or ''}|{index}",
                })
                existing = self.search([
                    ('store_id', '=', store.id),
                    ('order_number', '=', order_number),
                    ('event_key', '=', vals['event_key']),
                ], limit=1)
                if existing:
                    existing.write(vals)
                    updated += 1
                else:
                    self.create(vals)
                    created += 1
        return created, updated

import logging
from datetime import datetime, timedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# HB muhasebe kayıt tipi → özet kategorisi (bilinmeyen tipler 'other')
_CATEGORY_BY_TYPE = {
    'Payment': 'payment',
    'BnplOrder': 'payment',
    'Return': 'return',
    'BnplRefund': 'return',
    'Commission': 'commission',
    'CommissionRefund': 'commission',
    'CommissionInvoiceRefund': 'commission',
    'CommissionCorrection': 'commission',
    'CampaignDiscount': 'commission',
    'CampaignDiscountRefund': 'commission',
    'OverseasCommissionRefund': 'commission',
    'ShipmentCostSharingExpense': 'cargo',
    'ShipmentCostSharingIncome': 'cargo',
    'ReturnShipmentCostSharingExpense': 'cargo',
    'DropShipmentCostSharingExpense': 'cargo',
    'DropShipmentCostSharingIncome': 'cargo',
    'CargoMargin': 'cargo',
    'CargoCostRefund': 'cargo',
    'ProcessingFeeExpense': 'service_fee',
    'ProcessingFeeExpenseRefund': 'service_fee',
    'ReturnProcessingFeeExpense': 'service_fee',
    'DeliveryProcessingFee': 'service_fee',
    'DeliveryProcessingFeeRefund': 'service_fee',
    'ReturnDeliveryProcessingFee': 'service_fee',
    'PaymentServiceCostReflection': 'service_fee',
    'PaymentServiceCostReflectionRefund': 'service_fee',
    'BnplProcessingFee': 'service_fee',
    'BnplProcessingFeeRefund': 'service_fee',
}

_PAGE_LIMIT = 100  # HB muhasebe servisi en fazla 100
_MAX_PAGES = 200


class HepsiburadaTransaction(models.Model):
    _name = 'hepsiburada.transaction'
    _description = 'Hepsiburada Finansal Kayıt'
    _order = 'record_date desc, id desc'

    hb_id = fields.Char(string='HB Kayıt ID', required=True, index=True)
    store_id = fields.Many2one('hepsiburada.store', string='Mağaza', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one('hepsiburada.order', string='HB Siparişi', ondelete='set null', index=True)
    order_number = fields.Char(string='Sipariş No', index=True)
    package_number = fields.Char(string='Paket No')
    transaction_type = fields.Char(string='Kayıt Tipi', index=True)
    category = fields.Selection([
        ('payment', 'Satış'),
        ('return', 'İade'),
        ('commission', 'Komisyon'),
        ('cargo', 'Kargo'),
        ('service_fee', 'Hizmet / İşlem Bedeli'),
        ('other', 'Diğer'),
    ], string='Kategori', default='other', index=True)
    status = fields.Char(string='Ödeme Durumu', help='Paid: ödendi, WillBePaid: ödenecek')
    sku = fields.Char(string='SKU')
    product_name = fields.Char(string='Ürün')
    quantity = fields.Integer(string='Adet')
    invoice_number = fields.Char(string='Fatura / Belge No')
    description = fields.Char(string='Açıklama')
    is_income = fields.Boolean(string='Gelir')
    is_invoice = fields.Boolean(string='Fatura')
    amount = fields.Float(string='Tutar')
    tax_amount = fields.Float(string='KDV')
    net_amount = fields.Float(string='Net Tutar')
    signed_amount = fields.Float(
        string='Hakedişe Etkisi', help='Gelirler artı, giderler eksi (KDV dahil tutar)')
    currency_code = fields.Char(string='Para Birimi')
    record_date = fields.Datetime(string='Kayıt / Fatura Tarihi')
    order_date = fields.Datetime(string='Sipariş Tarihi')
    due_date = fields.Datetime(string='Vade Tarihi')
    payment_date = fields.Datetime(string='Ödeme Tarihi')

    _hb_id_uniq = models.Constraint('UNIQUE(store_id, hb_id)', 'Bu finansal kayıt zaten mevcut.')

    # ─── Senkronizasyon ───

    @api.model
    def _parse_dt(self, value):
        """HB ISO tarih (TR yerel) → Odoo UTC string."""
        if not value:
            return False
        try:
            dt = datetime.strptime(str(value)[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return False
        return fields.Datetime.to_string(dt - timedelta(hours=3))

    @api.model
    def _prepare_vals(self, item, store):
        def _money(key):
            obj = item.get(key) or {}
            return float(obj.get('value') or 0.0) if isinstance(obj, dict) else float(obj or 0.0)

        tx_type = item.get('transactionType') or ''
        is_income = bool(item.get('isIncome'))
        amount = _money('amount')
        currency = ((item.get('amount') or {}).get('currencyCode') or '') if isinstance(item.get('amount'), dict) else ''
        return {
            'hb_id': str(item.get('id')),
            'store_id': store.id,
            'order_number': item.get('orderNumber') or False,
            'package_number': item.get('packageNumber') or False,
            'transaction_type': tx_type,
            'category': _CATEGORY_BY_TYPE.get(tx_type, 'other'),
            'status': item.get('status') or False,
            'sku': item.get('sku') or False,
            'product_name': item.get('productName') or False,
            'quantity': int(item.get('quantity') or 0),
            'invoice_number': item.get('invoiceNumber') or False,
            'description': (item.get('invoiceExplanation') or '')[:255] or False,
            'is_income': is_income,
            'is_invoice': bool(item.get('isInvoice')),
            'amount': amount,
            'tax_amount': _money('taxAmount'),
            'net_amount': _money('netAmount'),
            'signed_amount': abs(amount) if is_income else -abs(amount),
            'currency_code': {'949': 'TRY', '840': 'USD'}.get(str(currency), currency or False),
            'record_date': self._parse_dt(item.get('invoiceDate')),
            'order_date': self._parse_dt(item.get('orderDate')),
            'due_date': self._parse_dt(item.get('dueDate')),
            'payment_date': self._parse_dt(item.get('paymentDate')),
        }

    @api.model
    def _fetch_window(self, session, url, merchant, date_key, start, end):
        """Bir tarih aralığındaki tüm kayıtları sayfalayarak çeker. Hata → None."""
        items = []
        for page in range(_MAX_PAGES):
            params = {
                'Offset': page * _PAGE_LIMIT,
                'Limit': _PAGE_LIMIT,
                f'{date_key}Start': start.strftime('%Y-%m-%dT%H:%M:%S'),
                f'{date_key}End': end.strftime('%Y-%m-%dT%H:%M:%S'),
            }
            try:
                res = session.get(url, params=params, timeout=60)
            except Exception as e:
                _logger.warning("HB finans isteği başarısız (%s): %s", merchant, e)
                return None
            if res.status_code == 404:
                break  # kayıt yok
            if res.status_code != 200:
                _logger.warning("HB finans HTTP %s: %s", res.status_code, res.text[:300])
                return None
            data = res.json() or {}
            page_items = data.get('items', []) if isinstance(data, dict) else data
            items.extend(page_items or [])
            if not page_items or len(page_items) < _PAGE_LIMIT:
                break
        return items

    @api.model
    def _sync_store(self, store):
        """Mağazanın finansal kayıtlarını çeker; yeni kayıtları ekler, değişenleri günceller.

        İki geçiş: kayıt tarihi (yeni kayıtlar) + ödeme tarihi (WillBePaid → Paid geçişleri).
        """
        store = store.sudo()
        if not store.sync_financials:
            return {'created': 0, 'updated': 0}
        merchant, _user, _pwd = store._get_clean_credentials()
        if not merchant:
            return {'created': 0, 'updated': 0}

        session, _m = store._get_session()
        url = f"https://{store._get_finance_domain()}/transactions/merchantid/{merchant}"

        now = datetime.utcnow() + timedelta(hours=3)  # HB TR saatiyle çalışır
        day_range = store.financial_day_range or 15
        start = now - timedelta(days=day_range)
        if store.last_financial_sync:
            start = max(start, store.last_financial_sync + timedelta(hours=3) - timedelta(days=1))

        items = {}
        failed = False
        for date_key in ('RecordDate', 'PaymentDate'):
            fetched = self._fetch_window(session, url, merchant, date_key, start, now)
            if fetched is None:
                failed = True
                continue
            for item in fetched:
                if item.get('id'):
                    items[str(item['id'])] = item

        created = updated = 0
        if items:
            existing = {
                tx.hb_id: tx for tx in self.sudo().search([
                    ('store_id', '=', store.id), ('hb_id', 'in', list(items))])
            }
            order_numbers = {i.get('orderNumber') for i in items.values() if i.get('orderNumber')}
            orders = {
                o.hb_order_number: o.id for o in self.env['hepsiburada.order'].sudo().search([
                    ('hb_order_number', 'in', list(order_numbers)),
                    '|', ('store_id', '=', store.id), ('merchant_id', '=', store.merchant_id),
                ])
            } if order_numbers else {}

            for hb_id, item in items.items():
                vals = self._prepare_vals(item, store)
                vals['order_id'] = orders.get(vals['order_number'] or '', False)
                try:
                    with self.env.cr.savepoint():
                        tx = existing.get(hb_id)
                        if tx:
                            changed = self._changed_vals(tx, vals)
                            if changed:
                                tx.write(changed)
                                updated += 1
                        else:
                            self.sudo().create(vals)
                            created += 1
                except Exception as e:
                    _logger.warning("HB finans kaydı yazılamadı (%s): %s", hb_id, e)

        if not failed:
            store.write({'last_financial_sync': fields.Datetime.now()})
        if created or updated:
            _logger.info("HB finans [%s]: %s yeni, %s güncellenen kayıt", store.name, created, updated)
        return {'created': created, 'updated': updated, 'failed': failed}

    @api.model
    def _changed_vals(self, tx, vals):
        """Yalnızca gerçekten değişen alanlar (gereksiz yazma → gereksiz recompute olmasın)."""
        changed = {}
        for key, new in vals.items():
            if key in ('hb_id', 'store_id'):
                continue
            field = tx._fields[key]
            old = tx[key]
            if field.type == 'many2one':
                old = old.id or False
            elif field.type == 'datetime':
                old = fields.Datetime.to_string(old) if old else False
            elif field.type == 'float':
                if abs((old or 0.0) - (new or 0.0)) < 0.005:
                    continue
            if (old or False) != (new or False):
                changed[key] = new
        return changed

    @api.model
    def _link_orphans(self, hb_orders):
        """Sipariş Odoo'ya finans kaydından sonra düştüyse eşleştir."""
        for hb_order in hb_orders:
            orphans = self.sudo().search([
                ('order_id', '=', False),
                ('order_number', '=', hb_order.hb_order_number),
                ('store_id', '=', hb_order.store_id.id),
            ])
            if orphans:
                orphans.write({'order_id': hb_order.id})

import logging
import pytz
from collections import defaultdict

from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

SETTLEMENT_TYPES = [
    ('sale', 'Satış'),
    ('return', 'İade'),
    ('discount', 'İndirim'),
    ('discount_cancel', 'İndirim İptal'),
    ('coupon', 'Kupon'),
    ('coupon_cancel', 'Kupon İptal'),
    ('provision_positive', 'Provizyon +'),
    ('provision_negative', 'Provizyon -'),
    ('platform_fee', 'Platform Hizmet Bedeli'),
    ('shipping_cargo', 'Gönderi Kargo Bedeli'),
    ('return_cargo', 'İade Kargo Bedeli'),
    ('penalty', 'Ceza'),
    ('payment', 'Ödeme / Hakediş'),
    ('commission', 'Komisyon'),
    ('other', 'Diğer'),
]


class TrendyolSettlement(models.Model):
    _name = 'trendyol.settlement'
    _description = 'Trendyol Finansal İşlem'
    _order = 'transaction_date desc, id desc'
    _rec_name = 'order_number'

    # ─── Temel ───────────────────────────────────────────
    trendyol_id = fields.Char(string='Trendyol ID', index=True, readonly=True)
    store_id = fields.Many2one('trendyol.store', string='Mağaza', index=True, readonly=True)
    order_id = fields.Many2one('trendyol.order', string='Trendyol Sipariş', readonly=True)
    transaction_date = fields.Datetime(string='İşlem Tarihi', readonly=True)
    transaction_type = fields.Selection(SETTLEMENT_TYPES, string='İşlem Türü', readonly=True)
    transaction_type_raw = fields.Char(string='Ham İşlem Türü', readonly=True)
    description = fields.Char(string='Açıklama', readonly=True)
    source = fields.Selection([
        ('settlements', 'Settlements'),
        ('otherfinancials', 'Other Financials'),
        ('cargo_invoice', 'Kargo Faturası'),
    ], string='Kaynak', readonly=True)

    # ─── Finansal ────────────────────────────────────────
    debt = fields.Float(string='Borç', digits=(12, 2), readonly=True)
    credit = fields.Float(string='Alacak', digits=(12, 2), readonly=True)
    net_amount = fields.Float(string='Net Tutar', digits=(12, 2),
                              compute='_compute_net', store=True)
    commission_rate = fields.Float(string='Komisyon Oranı (%)', readonly=True)
    commission_amount = fields.Float(string='Komisyon Tutarı', digits=(12, 2), readonly=True)
    seller_revenue = fields.Float(string='Satıcı Hakediş', digits=(12, 2), readonly=True)

    # ─── Sipariş Bilgileri ───────────────────────────────
    order_number = fields.Char(string='Sipariş No', index=True, readonly=True)
    shipment_package_id = fields.Char(string='Paket ID', index=True, readonly=True)
    barcode = fields.Char(string='Barkod', readonly=True)
    receipt_id = fields.Char(string='Dekont No', readonly=True)
    payment_order_id = fields.Char(string='Ödeme No', readonly=True)
    payment_date = fields.Datetime(string='Ödeme Tarihi', readonly=True)
    payment_period = fields.Integer(string='Vade (Gün)', readonly=True)

    _unique_tx = models.Constraint(
        'UNIQUE(trendyol_id, source, store_id)',
        'Bu finansal işlem zaten kayıtlı!',
    )

    @api.depends('debt', 'credit')
    def _compute_net(self):
        for rec in self:
            rec.net_amount = (rec.credit or 0) - (rec.debt or 0)

    # ═══════════════════════════════════════════════════════
    # SİNIFLANDIRMA
    # ═══════════════════════════════════════════════════════

    # ─── İşlem türü eşleştirme tablosu ─────────────────────
    _TX_TYPE_MAP = {
        'satis': 'sale', 'sat\u0131\u015f': 'sale', 'sale': 'sale',
        'iade': 'return', 'return': 'return',
        'indirim': 'discount', 'discount': 'discount',
        'discountcancel': 'discount_cancel',
        'kupon': 'coupon', 'coupon': 'coupon',
        'couponcancel': 'coupon_cancel',
        'odeme': 'payment', 'paymentorder': 'payment',
    }

    _TX_KEYWORD_MAP = [
        # (keyword_list, result_type) — sıra önemli, ilk eşleşen kazanır
        (['indirim', 'iptal'], 'discount_cancel'),
        (['kupon', 'iptal'], 'coupon_cancel'),
        (['kargo fatura'], 'shipping_cargo'),
        (['gonderi kargo'], 'shipping_cargo'),
        (['iade kargo'], 'return_cargo'),
        (['yurtdisi operasyon iade'], 'return_cargo'),
        (['platform hizmet'], 'platform_fee'),
        (['uluslararasi hizmet'], 'platform_fee'),
        (['komisyon'], 'commission'),
        (['komisyon fatura'], 'commission'),
        (['ceza'], 'penalty'),
        (['penalty'], 'penalty'),
        (['kusurlu urun'], 'penalty'),
        (['yanlis urun'], 'penalty'),
        (['eksik urun'], 'penalty'),
        (['provizyon', '+'], 'provision_positive'),
        (['provizyon', '-'], 'provision_negative'),
        (['kesinti'], 'platform_fee'),
        (['deduction'], 'platform_fee'),
    ]

    @api.private
    def _classify_transaction_type(self, raw_type, description=''):
        """Ham Trendyol işlem türünü sınıflandırmaya çevir."""
        raw = (raw_type or '').strip()
        desc = (description or '').strip()

        def normalize(s):
            return s.casefold().replace('\u0130', 'i').replace('\u0131', 'i').replace('i\u0307', 'i')

        raw_n = normalize(raw)
        desc_n = normalize(desc)
        combined = f"{raw_n} {desc_n}"

        # 1. Tam eşleşme
        if raw_n in self._TX_TYPE_MAP:
            # Özel durum: "iade" kelimesi kargo ile birlikte gelirse return_cargo
            if raw_n in ('iade', 'return') and 'kargo' in raw_n:
                pass  # Keyword map'e düşsün
            else:
                return self._TX_TYPE_MAP[raw_n]

        # 2. Keyword eşleştirme
        for keywords, result_type in self._TX_KEYWORD_MAP:
            if all(kw in combined for kw in keywords):
                return result_type

        return 'other'

    # ═══════════════════════════════════════════════════════
    # SİPARİŞ EŞLEŞTİRME
    # ═══════════════════════════════════════════════════════

    @api.private
    def _find_order(self, store, package_id='', order_number=''):
        """Sipariş eşleştirme: önce shipmentPackageId, sonra orderNumber."""
        TrendyolOrder = self.env['trendyol.order']
        if package_id:
            order = TrendyolOrder.search([
                ('shipment_package_id', '=', package_id),
                ('store_id', '=', store.id),
            ], limit=1)
            if order:
                return order.id
        if order_number:
            order = TrendyolOrder.search([
                ('trendyol_order_number', '=', str(order_number)),
                ('store_id', '=', store.id),
            ], limit=1)
            if order:
                return order.id
        return False

    # ═══════════════════════════════════════════════════════
    # SENKRONİZASYON
    # ═══════════════════════════════════════════════════════

    @api.model
    def sync_financials_for_store(self, store):
        """Tek bir mağazanın finansal verilerini senkronize et."""
        try:
            api = store.get_api()
        except Exception as e:
            return {'error': str(e), 'created': 0}

        day_range = min(store.financial_day_range or 15, 15)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=day_range)

        created = 0
        errors = []

        # 1) Settlements
        try:
            types_to_fetch = ['Sale', 'Return', 'Discount', 'DiscountCancel',
                              'Coupon', 'CouponCancel']
            created += self._fetch_paginated_settlements(
                api, start_date, end_date, types_to_fetch, store)
        except Exception as e:
            errors.append(f"Settlements: {e}")
            _logger.exception("Settlements sync hatası [%s]", store.name)

        # 2) OtherFinancials
        try:
            for tx_type in ['DeductionInvoices', 'PaymentOrder']:
                created += self._fetch_paginated_otherfinancials(
                    api, start_date, end_date, tx_type, store)
        except Exception as e:
            errors.append(f"OtherFinancials: {e}")
            _logger.exception("OtherFinancials sync hatası [%s]", store.name)

        # 3) Kargo Faturası Detay (cargo-invoice)
        try:
            created += self._process_cargo_invoices(api, store)
        except Exception as e:
            errors.append(f"CargoInvoice: {e}")
            _logger.exception("CargoInvoice sync hatası [%s]", store.name)

        # 4) Bağsız settlement'ları siparişlere bağla
        self._relink_unlinked_settlements(store)

        # 5) Sipariş bazlı finansal özet güncelle
        self._update_order_financial_summary(store)

        store.sudo().write({'last_financial_sync': fields.Datetime.now()})
        _logger.info("Finansal senkronizasyon [%s]: %s yeni kayıt, %s hata",
                      store.name, created, len(errors))

        return {
            'created': created,
            'errors': len(errors),
            'error_details': '\n'.join(errors),
        }

    @api.private
    def _fetch_paginated_settlements(self, api, start_date, end_date, types, store):
        """Sayfalama ile settlements verisi çek."""
        created = 0
        result = api.get_settlements(
            start_date, end_date, transaction_types=types, size=1000)
        if not result.get('success'):
            _logger.warning("Settlements API hatası: %s", result.get('error'))
            return 0

        data = result.get('data', {})
        for item in data.get('content', []):
            if self._process_settlement_item(item, store, 'settlements'):
                created += 1

        total_pages = data.get('totalPages', 1)
        for page in range(1, total_pages):
            page_result = api.get_settlements(
                start_date, end_date, transaction_types=types,
                page=page, size=1000)
            if page_result.get('success'):
                for item in page_result.get('data', {}).get('content', []):
                    if self._process_settlement_item(item, store, 'settlements'):
                        created += 1
        return created

    @api.private
    def _fetch_paginated_otherfinancials(self, api, start_date, end_date, tx_type, store):
        """Sayfalama ile otherfinancials verisi çek."""
        created = 0
        result = api.get_other_financials(
            start_date, end_date, transaction_type=tx_type, size=1000)
        if not result.get('success'):
            _logger.warning("OtherFinancials API [%s] hatası: %s",
                            tx_type, result.get('error'))
            return 0

        data = result.get('data', {})
        for item in data.get('content', []):
            if self._process_settlement_item(item, store, 'otherfinancials'):
                created += 1

        total_pages = data.get('totalPages', 1)
        for page in range(1, total_pages):
            page_result = api.get_other_financials(
                start_date, end_date, transaction_type=tx_type,
                page=page, size=1000)
            if page_result.get('success'):
                for item in page_result.get('data', {}).get('content', []):
                    if self._process_settlement_item(item, store, 'otherfinancials'):
                        created += 1
        return created

    @api.private
    def _process_cargo_invoices(self, api, store):
        """Kargo faturası seri numaralarını bul ve sipariş bazlı detay çek.

        Akış:
        1. shipping_cargo kayıtlarının trendyol_id = invoiceSerialNumber
        2. cargo-invoice API ile sipariş bazlı kargo detay çek
        3. orderNumber ile eşleştirip Gönderi/İade Kargo kayıtları oluştur
        """
        created = 0

        cargo_invoices = self.search([
            ('store_id', '=', store.id),
            ('transaction_type', '=', 'shipping_cargo'),
            ('source', '=', 'otherfinancials'),
        ])

        for invoice in cargo_invoices:
            serial_number = invoice.trendyol_id
            if not serial_number:
                continue

            try:
                result = api.get_cargo_invoice_items(serial_number)
                if not result.get('success'):
                    _logger.warning("Cargo invoice [%s] hatası: %s",
                                    serial_number, result.get('error'))
                    continue

                data = result.get('data', {})
                created += self._process_cargo_items(
                    data.get('content', []), serial_number, invoice, store)

                total_pages = data.get('totalPages', 1)
                for page in range(1, total_pages):
                    page_result = api.get_cargo_invoice_items(
                        serial_number, page=page)
                    if page_result.get('success'):
                        created += self._process_cargo_items(
                            page_result.get('data', {}).get('content', []),
                            serial_number, invoice, store)

            except Exception as e:
                _logger.warning("Cargo invoice [%s] işleme hatası: %s",
                                serial_number, e)

        return created

    @api.private
    def _process_cargo_items(self, items, serial_number, invoice, store):
        """Tek bir kargo faturasının kalemlerini işle."""
        created = 0
        for item in items:
            order_number = str(item.get('orderNumber', '') or '')
            amount = item.get('amount', 0) or 0
            pkg_type = item.get('shipmentPackageType', '')
            parcel_id = str(item.get('parcelUniqueId', '') or '')

            if 'iade' in pkg_type.lower():
                cargo_type = 'return_cargo'
            else:
                cargo_type = 'shipping_cargo'

            unique_id = f"cargo_{serial_number}_{parcel_id}"

            existing = self.search([
                ('trendyol_id', '=', unique_id),
                ('source', '=', 'cargo_invoice'),
                ('store_id', '=', store.id),
            ], limit=1)
            if existing:
                continue

            order_id = self._find_order(store, order_number=order_number)

            vals = {
                'trendyol_id': unique_id,
                'store_id': store.id,
                'order_id': order_id,
                'transaction_date': invoice.transaction_date,
                'transaction_type': cargo_type,
                'transaction_type_raw': pkg_type,
                'description': f"{pkg_type} ({order_number})",
                'source': 'cargo_invoice',
                'debt': amount,
                'credit': 0,
                'order_number': order_number,
                'receipt_id': serial_number,
            }
            try:
                self.create(vals)
                created += 1
            except Exception as e:
                _logger.warning("Cargo invoice kayıt hatası: %s — %s",
                                unique_id, e)
        return created

    @api.private
    def _relink_unlinked_settlements(self, store):
        """Sipariş bağlantısı olmayan settlement'ları orderlara bağla."""
        unlinked = self.search([
            ('store_id', '=', store.id),
            ('order_id', '=', False),
            '|',
            ('order_number', '!=', False),
            ('shipment_package_id', '!=', False),
        ])

        linked_count = 0
        for record in unlinked:
            order_id = self._find_order(
                store,
                package_id=record.shipment_package_id or '',
                order_number=record.order_number or '',
            )
            if order_id:
                record.sudo().write({'order_id': order_id})
                linked_count += 1

        if linked_count:
            _logger.info("Finansal kayıt eşleştirme [%s]: %s kayıt bağlandı",
                          store.name, linked_count)

    @api.private
    def _process_settlement_item(self, data, store, source):
        """Tek bir finansal kayıt işle. Dönüş: True=oluşturuldu, False=zaten var."""
        tid = str(data.get('id', ''))
        if not tid:
            return False

        existing = self.search([
            ('trendyol_id', '=', tid),
            ('source', '=', source),
            ('store_id', '=', store.id),
        ], limit=1)
        if existing:
            return False

        tx_ts = data.get('transactionDate', 0)
        tx_date = datetime.fromtimestamp(tx_ts / 1000, tz=timezone.utc).replace(tzinfo=None) if tx_ts else None
        pay_ts = data.get('paymentDate', 0)
        pay_date = datetime.fromtimestamp(pay_ts / 1000, tz=timezone.utc).replace(tzinfo=None) if pay_ts else None

        raw_type = data.get('transactionType', '')
        description = data.get('description', '')
        classified_type = self._classify_transaction_type(raw_type, description)

        order_number = str(data.get('orderNumber', '') or '')
        package_id = str(data.get('shipmentPackageId', '') or '')
        order_id = self._find_order(store, package_id, order_number)

        vals = {
            'trendyol_id': tid,
            'store_id': store.id,
            'order_id': order_id,
            'transaction_date': tx_date,
            'transaction_type': classified_type,
            'transaction_type_raw': raw_type,
            'description': description or raw_type,
            'source': source,
            'debt': data.get('debt', 0) or 0,
            'credit': data.get('credit', 0) or 0,
            'commission_rate': data.get('commissionRate', 0) or 0,
            'commission_amount': data.get('commissionAmount', 0) or 0,
            'seller_revenue': data.get('sellerRevenue', 0) or 0,
            'order_number': order_number,
            'shipment_package_id': package_id,
            'barcode': data.get('barcode', ''),
            'receipt_id': str(data.get('receiptId', '') or ''),
            'payment_order_id': str(data.get('paymentOrderId', '') or ''),
            'payment_date': pay_date,
            'payment_period': data.get('paymentPeriod', 0) or 0,
        }

        try:
            self.create(vals)
            return True
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                _logger.debug("Duplicate settlement atlandı: %s", tid)
                return False
            _logger.warning("Finansal kayıt oluşturma hatası [%s]: %s — %s",
                            store.name, tid, e)
            return False

    @api.private
    def _update_order_financial_summary(self, store):
        """Sipariş bazlı finansal özetleri güncelle (optimize).

        Tek sorguda tüm settlement'ları çekip Python'da gruplama yapar.
        """
        all_settlements = self.search([
            ('store_id', '=', store.id),
            ('order_id', '!=', False),
        ])

        if not all_settlements:
            return

        # Python'da order_id bazlı gruplama (N+1 yerine tek sorgu)
        order_map = defaultdict(list)
        for s in all_settlements:
            order_map[s.order_id].append(s)

        for order, settlements in order_map.items():
            platform_fee = 0.0
            shipping_cost = 0.0
            return_cargo_cost = 0.0
            penalty_amount = 0.0
            seller_revenue = 0.0
            has_platform_invoice = False
            has_cargo_invoice = False

            for s in settlements:
                if s.transaction_type == 'platform_fee':
                    platform_fee += s.debt
                    has_platform_invoice = True
                elif s.transaction_type == 'shipping_cargo':
                    shipping_cost += s.debt
                    has_cargo_invoice = True
                elif s.transaction_type == 'return_cargo':
                    return_cargo_cost += s.debt
                elif s.transaction_type == 'penalty':
                    penalty_amount += s.debt

                if s.seller_revenue:
                    if s.transaction_type in ('sale', 'coupon', 'discount_cancel',
                                              'coupon_cancel', 'provision_positive'):
                        seller_revenue += s.seller_revenue
                    elif s.transaction_type in ('discount', 'return', 'coupon',
                                                'provision_negative'):
                        seller_revenue -= abs(s.seller_revenue)

            # Fatura yoksa tahmini hesapla
            if not has_platform_invoice and store.platform_fee_rate and seller_revenue > 0:
                net_after_discount = (order.total_amount or 0) - (order.total_discount or 0)
                if net_after_discount > 0:
                    platform_fee = round(net_after_discount * store.platform_fee_rate / 100, 2)

            if not has_cargo_invoice and store.cargo_unit_price and order.trendyol_status == 'delivered':
                deci = order.cargo_deci or 1
                shipping_cost = round(deci * store.cargo_unit_price, 2)

            net_revenue = (seller_revenue - platform_fee - shipping_cost
                           - return_cargo_cost - penalty_amount)

            order.sudo().write({
                'platform_fee': platform_fee,
                'shipping_cost': shipping_cost,
                'return_cargo_cost': return_cargo_cost,
                'penalty_amount': penalty_amount,
                'seller_revenue': seller_revenue,
                'final_net_amount': net_revenue,
            })


    # ═══════════════════════════════════════════════════════
    # TOPLU İŞLEM
    # ═══════════════════════════════════════════════════════

    @api.model
    def sync_all_financials(self):
        """Tüm aktif mağazalardan finansal verileri senkronize et."""
        stores = self.env['trendyol.store'].search([
            ('active', '=', True),
            ('sync_financials', '=', True),
        ])
        total_created = 0
        for store in stores:
            try:
                result = self.sync_financials_for_store(store)
                total_created += result.get('created', 0)
            except Exception as e:
                _logger.exception("Finansal sync hatası [%s]: %s", store.name, e)
        return {'created': total_created}

    @api.model
    def cron_sync_financials(self):
        """Cron ile finansal senkronizasyon."""
        try:
            self.sync_all_financials()
        except Exception as e:
            _logger.exception("Finansal cron hatası: %s", e)

    @api.autovacuum
    def _gc_old_sync_logs(self):
        """Eski sync loglarını otomatik temizle (Odoo autovacuum)."""
        cutoff = datetime.now() - timedelta(days=90)
        SyncLog = self.env['trendyol.sync.log'].sudo()
        old_logs = SyncLog.search([('create_date', '<', cutoff)])
        count = len(old_logs)
        if old_logs:
            old_logs.unlink()
            _logger.info("Trendyol sync log temizliği: %d kayıt silindi", count)

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
    ('commission_adjustment', 'Komisyon Düzeltme'),
    ('manual_refund', 'Kısmi İade'),
    ('manual_refund_cancel', 'Kısmi İade İptal'),
    ('delivery_fee', 'Teslimat Ücreti'),
    ('delivery_fee_cancel', 'Teslimat Ücreti İptal'),
    ('ty_discount', 'Kurumsal Fatura - TY İndirim/Kupon'),
    ('ty_discount_cancel', 'Kurumsal Fatura - TY İndirim/Kupon İptal'),
    ('revenue_adjustment', 'Hakediş Düzeltme'),
    ('stoppage', 'E-Ticaret Stopajı'),
    ('other', 'Diğer'),
]

# Settlements servisinden çekilen tüm kayıt tipleri (doküman: transactionTypes virgülle)
SETTLEMENT_API_TYPES = [
    'Sale', 'Return', 'Discount', 'DiscountCancel', 'Coupon', 'CouponCancel',
    'ProvisionPositive', 'ProvisionNegative', 'ManualRefund', 'ManualRefundCancel',
    'TyDiscount', 'TyDiscountCancel', 'TyCoupon', 'TyCouponCancel',
    'SellerRevenuePositive', 'SellerRevenueNegative', 'CommissionPositive', 'CommissionNegative',
    'SellerRevenuePositiveCancel', 'SellerRevenueNegativeCancel',
    'CommissionPositiveCancel', 'CommissionNegativeCancel',
    'DeliveryFee', 'DeliveryFeeCancel', 'PayByLink',
]
OTHER_FINANCIAL_API_TYPES = ['DeductionInvoices', 'PaymentOrder', 'Stoppage']

# Hakedişe etkisi: +1 artırır, -1 azaltır (tutar mutlak değerle alınır)
_REVENUE_SIGN = {
    'manual_refund': -1, 'manual_refund_cancel': 1,
    'delivery_fee': 1, 'delivery_fee_cancel': -1,
    'ty_discount': -1, 'ty_discount_cancel': 1,
}

_TR_TRANSLATE = str.maketrans({'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u', '\u0307': None})


def normalize_tr(text):
    """Türkçe metni karşılaştırma için sadeleştir (İ/ı/ş/ç/ğ/ö/ü → ascii, küçük harf)."""
    return (text or '').strip().casefold().translate(_TR_TRANSLATE)


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
    seller_revenue = fields.Float(string='Satıcı Hakediş (Ham)', digits=(12, 2), readonly=True,
                                  help="Trendyol'un gönderdiği işaretsiz tutar")
    signed_seller_revenue = fields.Float(
        string='Hakedişe Etkisi', digits=(12, 2), compute='_compute_signed', store=True,
        help='Alacak kaydı hakedişi artırır, borç kaydı azaltır (satış +, indirim/kupon/iade −)')
    signed_commission = fields.Float(
        string='Komisyon Etkisi', digits=(12, 2), compute='_compute_signed', store=True,
        help='Satışın komisyonu +, indirim/kupon/iadede geri alınan komisyon −')

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

    def _effect_sign(self):
        """Kaydın hakediş yönü. Trendyol alacak/borç bilgisi esas alınır (satış, iade, indirim,
        kupon ve iptallerinin tamamı buna uyar); ikisi de boşsa kayıt tipine göre."""
        self.ensure_one()
        credit, debt = self.credit or 0.0, self.debt or 0.0
        if credit > 0.005 and debt <= 0.005:
            return 1
        if debt > 0.005 and credit <= 0.005:
            return -1
        if self.transaction_type in _REVENUE_SIGN:
            return _REVENUE_SIGN[self.transaction_type]
        if self.transaction_type == 'revenue_adjustment':
            raw = normalize_tr(self.transaction_type_raw)
            sign = 1 if ('pozitif' in raw or 'positive' in raw) else -1
            return -sign if ('iptal' in raw or 'cancel' in raw) else sign
        if self.transaction_type in ('discount', 'coupon', 'return', 'provision_negative'):
            return -1
        return 1

    @api.depends('debt', 'credit', 'seller_revenue', 'commission_amount',
                 'transaction_type', 'transaction_type_raw')
    def _compute_signed(self):
        for rec in self:
            sign = rec._effect_sign()
            rec.signed_seller_revenue = sign * abs(rec.seller_revenue or 0.0)
            rec.signed_commission = sign * abs(rec.commission_amount or 0.0)

    # ═══════════════════════════════════════════════════════
    # SİNIFLANDIRMA
    # ═══════════════════════════════════════════════════════

    # ─── İşlem türü eşleştirme tablosu ─────────────────────
    _TX_TYPE_MAP = {
        'satis': 'sale', 'sale': 'sale', 'paybylink': 'sale',
        'iade': 'return', 'return': 'return',
        'indirim': 'discount', 'discount': 'discount',
        'discountcancel': 'discount_cancel',
        'kupon': 'coupon', 'coupon': 'coupon',
        'couponcancel': 'coupon_cancel',
        'odeme': 'payment', 'paymentorder': 'payment',
        'provisionpositive': 'provision_positive', 'provisionnegative': 'provision_negative',
        'manualrefund': 'manual_refund', 'manuelrefund': 'manual_refund',
        'manualrefundcancel': 'manual_refund_cancel', 'manuelrefundcancel': 'manual_refund_cancel',
        'deliveryfee': 'delivery_fee', 'deliveryfeecancel': 'delivery_fee_cancel',
        'tydiscount': 'ty_discount', 'tycoupon': 'ty_discount',
        'tydiscountcancel': 'ty_discount_cancel', 'tycouponcancel': 'ty_discount_cancel',
        'stoppage': 'stoppage',
    }

    _TX_KEYWORD_MAP = [
        # (keyword_list, result_type) — sıra önemli, ilk eşleşen kazanır
        (['stopaj'], 'stoppage'),
        (['kismi iade', 'iptal'], 'manual_refund_cancel'),
        (['kismi iade'], 'manual_refund'),
        (['teslimat ucreti', 'iptal'], 'delivery_fee_cancel'),
        (['teslimat ucreti'], 'delivery_fee'),
        (['ty promosyon', 'iptal'], 'ty_discount_cancel'),
        (['ty kupon', 'iptal'], 'ty_discount_cancel'),
        (['ty promosyon'], 'ty_discount'),
        (['ty kupon'], 'ty_discount'),
        (['hakedis', 'duzeltme'], 'revenue_adjustment'),
        (['sellerrevenue'], 'revenue_adjustment'),
        (['komisyon', 'duzeltme'], 'commission_adjustment'),
        (['commissionpositive'], 'commission_adjustment'),
        (['commissionnegative'], 'commission_adjustment'),
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
        (['gecikme'], 'penalty'),
        (['tedarik edememe'], 'penalty'),
        (['provizyon', '+'], 'provision_positive'),
        (['provizyon', '-'], 'provision_negative'),
        (['kesinti'], 'platform_fee'),
        (['deduction'], 'platform_fee'),
    ]

    @api.private
    def _classify_transaction_type(self, raw_type, description=''):
        """Ham Trendyol işlem türünü sınıflandırmaya çevir."""
        raw_n = normalize_tr(raw_type)
        desc_n = normalize_tr(description)
        combined = f"{raw_n} {desc_n}"

        # 1. Tam eşleşme (boşluksuz İngilizce tip adları da: "ManualRefundCancel")
        compact = raw_n.replace(' ', '')
        if raw_n in self._TX_TYPE_MAP:
            return self._TX_TYPE_MAP[raw_n]
        if compact in self._TX_TYPE_MAP:
            return self._TX_TYPE_MAP[compact]

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
            created += self._fetch_paginated_settlements(
                api, start_date, end_date, SETTLEMENT_API_TYPES, store)
        except Exception as e:
            errors.append(f"Settlements: {e}")
            _logger.exception("Settlements sync hatası [%s]", store.name)

        # 2) OtherFinancials (Stoppage: e-ticaret stopajı)
        try:
            for tx_type in OTHER_FINANCIAL_API_TYPES:
                created += self._fetch_paginated_otherfinancials(
                    api, start_date, end_date, tx_type, store)
        except Exception as e:
            errors.append(f"OtherFinancials: {e}")
            _logger.exception("OtherFinancials sync hatası [%s]", store.name)

        # 2a) Platform hizmet bedeli (transactionSubType=PlatformServiceFee) — paket bazında
        #     gelirse siparişe bağlanır ve tahmin yerine gerçek bedel kullanılır
        try:
            created += self._fetch_platform_service_fees(api, start_date, end_date, store)
        except Exception as e:
            errors.append(f"PlatformServiceFee: {e}")
            _logger.exception("Platform hizmet bedeli sync hatası [%s]", store.name)

        # 2b) Ödeme emirleri: ödenen kayıtlara ödeme no / tarihi işlenir
        try:
            self._sync_payment_orders(api, store)
        except Exception as e:
            errors.append(f"PaymentOrder: {e}")
            _logger.exception("Ödeme emri sync hatası [%s]", store.name)

        # 3) Kargo Faturası Detay (cargo-invoice)
        try:
            created += self._process_cargo_invoices(api, store)
        except Exception as e:
            errors.append(f"CargoInvoice: {e}")
            _logger.exception("CargoInvoice sync hatası [%s]", store.name)

        # 4) Bağsız settlement'ları siparişlere bağla
        self._relink_unlinked_settlements(store)

        # 5) Sipariş bazlı finansal özet — yalnız son senkrondan beri değişen siparişler
        since = (store.last_financial_sync or start_date) - timedelta(hours=1)
        self._update_order_financial_summary(store, since=since)

        # last_financial_sync — ayrı cursor ile güncelle (serialization çakışmasını önler)
        try:
            with self.pool.cursor() as new_cr:
                new_cr.execute(
                    "UPDATE trendyol_store SET last_financial_sync = %s, write_date = %s WHERE id = %s",
                    (fields.Datetime.now(), fields.Datetime.now(), store.id)
                )
        except Exception as e:
            _logger.warning("last_financial_sync güncelleme atlandı (%s): %s", store.name, e)
        _logger.info("Finansal senkronizasyon [%s]: %s yeni kayıt, %s hata",
                      store.name, created, len(errors))

        return {
            'created': created,
            'errors': len(errors),
            'error_details': '\n'.join(errors),
        }

    @api.private
    def _sync_payment_orders(self, api, store):
        """Ödenmiş hakediş ödeme emirleri → ilgili kayıtlara ödeme no/tarihi yazılır.

        Doküman: ödeme emri oluştuktan sonra kayıtların güncellenmesi zaman alabilir, ertesi
        gün sorgulanmalı. İşlenen ödeme emirleri mağazada tutulur (tekrar sorgulanmaz).
        """
        processed = [i for i in (store.processed_payment_orders or '').split(',') if i]
        now = datetime.utcnow()
        oldest = now - timedelta(days=60)
        newly = []
        for page in range(5):
            result = api.get_payment_orders(page=page)
            if not result.get('success'):
                _logger.warning("Ödeme emri listesi alınamadı [%s]: %s", store.name, result.get('error'))
                break
            data = result.get('data') or {}
            content = data.get('content') or []
            stop = False
            for po in content:
                po_id = str(po.get('id') or '')
                payout_ts = po.get('payoutDate') or 0
                payout = datetime.fromtimestamp(payout_ts / 1000, tz=timezone.utc).replace(tzinfo=None) \
                    if payout_ts else None
                if payout and payout < oldest:
                    stop = True
                    break
                if not po_id or po_id in processed or (payout and payout > now - timedelta(days=1)):
                    continue
                self._apply_payment_order(api, store, po_id)
                newly.append(po_id)
            if stop or not content or page + 1 >= (data.get('totalPages') or 1):
                break
        if newly:
            keep = (processed + newly)[-300:]
            # Ayrı cursor: mağaza satırı ana işlemde kilitlenirse aşağıdaki last_financial_sync
            # güncellemesi (o da ayrı cursor) bu kilidi bekleyip asılı kalırdı
            try:
                with self.pool.cursor() as new_cr:
                    new_cr.execute(
                        "UPDATE trendyol_store SET processed_payment_orders = %s WHERE id = %s",
                        (','.join(keep), store.id))
            except Exception as e:
                _logger.warning("İşlenen ödeme emirleri kaydedilemedi (%s): %s", store.name, e)
            _logger.info("Trendyol ödeme emirleri [%s]: %s ödeme işlendi", store.name, len(newly))

    @api.private
    def _apply_payment_order(self, api, store, payment_order_id):
        """Bir ödeme emrinin tüm kayıtlarını çek; mevcutları günceller, eksikleri ekler."""
        for fetch, types, source in (
                (api.get_settlements, SETTLEMENT_API_TYPES, 'settlements'),
                (api.get_other_financials, OTHER_FINANCIAL_API_TYPES, 'otherfinancials')):
            page = 0
            while True:
                result = fetch(transaction_types=types, page=page, size=1000,
                               payment_order_id=payment_order_id)
                if not result.get('success'):
                    _logger.warning("Ödeme emri %s kayıtları alınamadı (%s): %s",
                                    payment_order_id, source, result.get('error'))
                    break
                data = result.get('data') or {}
                for item in data.get('content') or []:
                    self._process_settlement_item(item, store, source)
                page += 1
                if page >= (data.get('totalPages') or 1):
                    break

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
    def _fetch_platform_service_fees(self, api, start_date, end_date, store):
        """DeductionInvoices + transactionSubType=PlatformServiceFee.

        Kayıt paket/sipariş numarası taşıyorsa siparişe bağlanır. Aynı fatura ID'si birden çok
        pakete ait satırda tekrar ederse her paket ayrı saklanır (ID + paket no).
        """
        created = linked = total = 0
        page = 0
        while True:
            result = api.get_other_financials(
                start_date, end_date, transaction_type='DeductionInvoices',
                transaction_sub_type='PlatformServiceFee', page=page, size=1000)
            if not result.get('success'):
                _logger.warning("Platform hizmet bedeli API hatası [%s]: %s", store.name, result.get('error'))
                break
            data = result.get('data') or {}
            for item in data.get('content') or []:
                total += 1
                package_id = item.get('shipmentPackageId')
                if package_id or item.get('orderNumber'):
                    linked += 1
                    if package_id and item.get('id'):
                        item = dict(item, id=f"{item['id']}_{package_id}")
                if self._process_settlement_item(item, store, 'otherfinancials'):
                    created += 1
            page += 1
            if page >= (data.get('totalPages') or 1):
                break
        if total:
            _logger.info("Trendyol platform hizmet bedeli [%s]: %s kayıt, %s tanesi sipariş/paket bilgili",
                         store.name, total, linked)
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

        # Kalemleri alınmış eski faturalar her senkronda yeniden çekilmesin; son 7 gün
        # yine de kontrol edilir (fatura kalemleri geç tamamlanabilir)
        processed_serials = set(self.search([
            ('store_id', '=', store.id),
            ('source', '=', 'cargo_invoice'),
        ]).mapped('receipt_id'))
        recent = fields.Datetime.now() - timedelta(days=7)

        for invoice in cargo_invoices:
            serial_number = invoice.trendyol_id
            if not serial_number:
                continue
            if serial_number in processed_serials and (invoice.transaction_date or recent) < recent:
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

            if 'iade' in normalize_tr(pkg_type):
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
                with self.env.cr.savepoint():
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

        if existing:
            # Ödeme no / tarihi kayıt oluştuktan sonra (ödeme günü) dolar; sınıflandırma
            # düzeltmeleri de eski kayıtlara yansısın — yalnız değişen alanlar yazılır
            self._update_existing(existing, vals)
            return False

        try:
            # Savepoint: çakışma (unique) tüm finans senkronunun işlemini bozmasın
            with self.env.cr.savepoint():
                self.create(vals)
            return True
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                _logger.debug("Duplicate settlement atlandı: %s", tid)
                return False
            _logger.warning("Finansal kayıt oluşturma hatası [%s]: %s — %s",
                            store.name, tid, e)
            return False

    _UPDATABLE_FIELDS = ('transaction_type', 'debt', 'credit', 'commission_rate', 'commission_amount',
                         'seller_revenue', 'payment_order_id', 'payment_date', 'payment_period')

    @api.private
    def _update_existing(self, record, vals):
        changed = {}
        for key in self._UPDATABLE_FIELDS:
            new = vals.get(key)
            old = record[key]
            if isinstance(old, float) or isinstance(new, float):
                if abs((old or 0.0) - (new or 0.0)) > 0.005:
                    changed[key] = new or 0.0
            elif (old or False) != (new or False):
                if key == 'payment_order_id' and not new:
                    continue  # boş gelen değer dolu ödeme bilgisini silmesin
                if key == 'payment_date' and not new:
                    continue
                changed[key] = new
        if not record.order_id and vals.get('order_id'):
            changed['order_id'] = vals['order_id']
        if changed:
            record.write(changed)

    @api.private
    def _update_order_financial_summary(self, store, since=None):
        """Sipariş bazlı finansal özetleri güncelle (optimize).

        since verilirse yalnız o andan beri finans kaydı eklenen/bağlanan ya da durumu
        değişen siparişler yeniden hesaplanır (tüm geçmiş her seferinde taranmaz).
        """
        domain = [('store_id', '=', store.id), ('order_id', '!=', False)]
        if since:
            orders = self.env['trendyol.order'].search([
                ('store_id', '=', store.id),
                '|', ('write_date', '>=', since),
                ('settlement_ids.write_date', '>=', since),
            ])
            if not orders:
                return
            domain.append(('order_id', 'in', orders.ids))
        all_settlements = self.search(domain)

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
            stoppage_amount = 0.0
            seller_revenue = 0.0
            has_platform_invoice = False
            has_cargo_invoice = False
            sale_records = []

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
                elif s.transaction_type == 'stoppage':
                    stoppage_amount += (s.debt or 0) - (s.credit or 0)
                if s.transaction_type == 'sale':
                    sale_records.append(s)

                if s.source == 'settlements':
                    seller_revenue += s.signed_seller_revenue

            # Fatura yoksa tahmini hesapla
            if not has_platform_invoice and seller_revenue > 0.01:
                if store.platform_fee_fixed:
                    platform_fee = store.platform_fee_fixed
                elif store.platform_fee_rate:
                    net_after_discount = (order.total_amount or 0) - (order.total_discount or 0)
                    if net_after_discount > 0:
                        platform_fee = round(net_after_discount * store.platform_fee_rate / 100, 2)

            if not has_cargo_invoice and store.cargo_unit_price and order.trendyol_status == 'delivered':
                deci = order.cargo_deci or 1
                shipping_cost = round(deci * store.cargo_unit_price, 2)

            net_revenue = (seller_revenue - platform_fee - shipping_cost
                           - return_cargo_cost - penalty_amount - stoppage_amount)

            summary = {
                'platform_fee': platform_fee,
                'shipping_cost': shipping_cost,
                'return_cargo_cost': return_cargo_cost,
                'penalty_amount': penalty_amount,
                'stoppage_amount': stoppage_amount,
                'seller_revenue': seller_revenue,
                'final_net_amount': net_revenue,
            }
            # Yalnız değişen değerler yazılır
            changed = {k: v for k, v in summary.items() if abs((order[k] or 0.0) - v) > 0.005}
            is_paid = bool(sale_records) and all(r.payment_order_id for r in sale_records)
            paid_dates = [r.payment_date for r in sale_records if r.payment_date]
            paid_date = max(paid_dates) if paid_dates else False
            if order.is_paid != is_paid:
                changed['is_paid'] = is_paid
            if order.paid_date != paid_date:
                changed['paid_date'] = paid_date
            if changed:
                order.sudo().write(changed)


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

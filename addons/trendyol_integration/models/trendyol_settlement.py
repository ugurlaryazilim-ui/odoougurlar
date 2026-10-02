import json
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
    ('international_fee', 'Uluslararası Hizmet Bedeli'),
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

# Ödeme emri bazında toplu faturalanan, sipariş paketlerine dağıtılan hizmet bedelleri
FEE_ALLOCATION_TYPES = ('platform_fee', 'international_fee')
_FEE_ALLOCATION_LOOKBACK_DAYS = 60
_FEE_ALLOCATION_PO_LIMIT = 20  # çalışma başına ödeme emri (her biri 2 istek; finans servisi 100/dk)
_FAST_TYPE_LOOKUP_LIMIT = 100  # çalışma başına teslimat tipi için sipariş servisi sorgusu

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
        ('platform_invoice', 'Platform Faturası Detayı'),
        ('fee_allocation', 'Hizmet Bedeli Dağıtımı'),
    ], string='Kaynak', readonly=True)
    affiliate = fields.Char(string='Affiliate', readonly=True,
                            help="Trendyol satış kanalı (örn. TRENDYOLTR, TRENDYOLAZJV)")

    # ─── Toplu fatura dağıtımı (sipariş/paket bilgisi olmayan kesinti faturaları) ───
    allocation_state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('allocated', 'Dağıtıldı'),
        ('unmatched', 'Eşleşmedi'),
        ('warning', 'Uyarı'),
    ], string='Dağıtım Durumu', readonly=True, index=True, copy=False,
        help="Dağıtıldı: fatura sipariş paketlerine satır olarak dağıtıldı (kaynak faturanın hakediş "
             "etkisi 0 olur, çift sayılmaz). Uyarı: tutar paketlere tam bölünmedi, dağıtılmadı.")
    allocation_note = fields.Char(string='Dağıtım Notu', readonly=True, copy=False)
    allocation_checked_at = fields.Datetime(string='Son Dağıtım Denemesi', readonly=True, copy=False)

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
                 'transaction_type', 'transaction_type_raw', 'source', 'allocation_state')
    def _compute_signed(self):
        for rec in self:
            sign = rec._effect_sign()
            rec.signed_commission = sign * abs(rec.commission_amount or 0.0)
            if rec.source == 'settlements' or abs(rec.seller_revenue or 0.0) > 0.005:
                rec.signed_seller_revenue = sign * abs(rec.seller_revenue or 0.0)
            elif rec.transaction_type == 'payment' or rec.allocation_state == 'allocated':
                # Ödeme emri hakediş değil; dağıtılmış toplu fatura sipariş satırlarında sayılıyor
                rec.signed_seller_revenue = 0.0
            else:
                # Kesinti/fatura satırları (kargo, hizmet bedelleri, ceza, stopaj): etki = alacak − borç
                rec.signed_seller_revenue = (rec.credit or 0.0) - (rec.debt or 0.0)

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
        (['uluslararasi hizmet'], 'international_fee'),
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

        created, errors = self._sync_window(api, store, start_date, end_date)

        # 2b) Ödeme emirleri: ödenen kayıtlara ödeme no / tarihi işlenir
        try:
            self._sync_payment_orders(api, store)
        except Exception as e:
            errors.append(f"PaymentOrder: {e}")
            _logger.exception("Ödeme emri sync hatası [%s]", store.name)

        # 3) Kargo / platform faturası kalem detayları
        created += self._process_invoice_details(api, store)

        # 4) Bağsız settlement'ları siparişlere bağla
        self._relink_unlinked_settlements(store)

        # 4b) Toplu hizmet bedeli faturalarını (Uluslararası / Platform) paketlere dağıt
        try:
            alloc = self._allocate_service_fees(api, store)
            created += alloc['rows']
            errors.extend(alloc['errors'])
        except Exception as e:
            errors.append(f"Hizmet bedeli dağıtımı: {e}")
            _logger.exception("Hizmet bedeli dağıtım hatası [%s]", store.name)

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
    def _sync_window(self, api, store, start_date, end_date):
        """Bir tarih aralığındaki (en fazla 15 gün) settlements + otherfinancials kayıtları."""
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

        return created, errors

    @api.private
    def _process_invoice_details(self, api, store, recent_only=True):
        """Kargo faturası kalemleri (sipariş bazlı) + platform faturası kalem denemesi."""
        created = 0
        try:
            created += self._process_cargo_invoices(api, store, recent_only=recent_only)
        except Exception as e:
            _logger.exception("CargoInvoice sync hatası [%s]: %s", store.name, e)
        try:
            created += self._process_platform_invoices(api, store, recent_only=recent_only)
        except Exception as e:
            _logger.exception("Platform faturası detay hatası [%s]: %s", store.name, e)
        return created

    # ─── GEÇMİŞİ TAMAMLAMA (15'er günlük parçalar, arka planda) ───

    _BACKFILL_CHUNK_DAYS = 15
    _BACKFILL_CHUNKS_PER_RUN = 3
    _BACKFILL_CHUNK_PAUSE = 5  # sn — finans servisleri dakikada 100 istek

    @api.model
    def cron_financial_backfill(self):
        """Geçmiş tamamlama işi bekleyen mağazaları parça parça işler.

        İlerleme (sıradaki parça) ayrı cursor ile yazılır: ana işlem mağaza satırına hiç yazmaz,
        böylece aynı anda mağazayı güncelleyen başka bir işlemle çakışıp geri alınmaz. Bir parça
        hata verirse loglanır ve bir sonraki turda (2 dk) kaldığı yerden tekrar denenir.
        """
        store_ids = self.env['trendyol.store'].search([('backfill_next', '!=', False)]).ids
        if not store_ids:
            return
        # Önce sonraki turu planla: bu tur hata verse bile iş saatlik cron'u beklemesin
        self._schedule_backfill(120)
        for store_id in store_ids:
            try:
                self._run_backfill_store(store_id)
            except Exception as e:
                self.env.cr.rollback()
                self.env.invalidate_all()
                _logger.warning("Finans geçmişi parçası başarısız (mağaza %s), 2 dk sonra tekrar "
                                "denenecek: %s", store_id, e)

    @api.private
    def _run_backfill_store(self, store_id):
        import time
        store = self.env['trendyol.store'].browse(store_id)
        api = store.get_api()
        for i in range(self._BACKFILL_CHUNKS_PER_RUN):
            state = self._backfill_state(store_id)
            if not state or not state['next'] or state['next'] > state['to']:
                break
            if i:
                time.sleep(self._BACKFILL_CHUNK_PAUSE)
            chunk_start = state['next']
            chunk_end = min(chunk_start + timedelta(days=self._BACKFILL_CHUNK_DAYS - 1), state['to'])
            start_dt = datetime.combine(chunk_start, datetime.min.time())
            end_dt = datetime.combine(chunk_end, datetime.max.time()).replace(microsecond=0)
            created, errors = self._sync_window(api, store, start_dt, end_dt)
            self.env.cr.commit()  # parçanın kayıtları kalıcı
            self._backfill_write(
                "UPDATE trendyol_store SET backfill_next = %s, "
                "backfill_created = COALESCE(backfill_created, 0) + %s WHERE id = %s "
                "AND backfill_next IS NOT NULL",  # bu arada "Durdur" denildiyse yeniden başlatma
                (chunk_end + timedelta(days=1), created, store_id))
            _logger.info("Finans geçmişi [%s]: %s → %s, %s yeni kayıt%s", store.name,
                         chunk_start, chunk_end, created, f", hata: {'; '.join(errors)}" if errors else '')

        state = self._backfill_state(store_id)
        if state and state['next'] and state['next'] > state['to']:
            # Son adım: fatura kalemleri, eşleştirme ve tüm siparişlerin özeti
            self._process_invoice_details(api, store, recent_only=False)
            self._relink_unlinked_settlements(store)
            try:
                self._allocate_service_fees(api, store)
            except Exception as e:
                _logger.warning("Finans geçmişi — hizmet bedeli dağıtımı başarısız [%s]: %s", store.name, e)
            self._update_order_financial_summary(store)
            self.env.cr.commit()
            result = (f"{state['from']} → {state['to']}: {state['created']} yeni kayıt "
                      f"({fields.Datetime.now():%d.%m.%Y %H:%M} UTC)")
            self._backfill_write(
                "UPDATE trendyol_store SET backfill_next = NULL, backfill_last_result = %s WHERE id = %s",
                (result, store_id))
            _logger.info("Finans geçmişi tamamlandı [%s]: %s", store.name, result)

    @api.private
    def _backfill_state(self, store_id):
        """Mağazanın güncel tamamlama durumu (ayrı cursor: ana işlemin eski görüntüsünden bağımsız)."""
        with self.pool.cursor() as cr2:
            cr2.execute("SELECT backfill_from, backfill_to, backfill_next, COALESCE(backfill_created, 0) "
                        "FROM trendyol_store WHERE id = %s", (store_id,))
            row = cr2.fetchone()
        if not row:
            return None
        return {'from': row[0], 'to': row[1], 'next': row[2], 'created': row[3]}

    @api.private
    def _backfill_write(self, query, params):
        """İlerlemeyi ayrı, hemen kalıcı cursor ile yaz (çakışmada bir kez daha dener)."""
        for attempt in range(2):
            try:
                with self.pool.cursor() as cr2:
                    cr2.execute(query, params)
                return
            except Exception as e:
                if attempt:
                    raise
                _logger.info("Finans geçmişi ilerlemesi yazılamadı, tekrar deneniyor: %s", e)

    @api.private
    def _schedule_backfill(self, seconds):
        cron = self.env.ref('trendyol_integration.cron_trendyol_financial_backfill', raise_if_not_found=False)
        if not cron:
            return
        try:
            with self.pool.cursor() as cr2:
                self.env(cr=cr2)['ir.cron'].browse(cron.id)._trigger(
                    fields.Datetime.now() + timedelta(seconds=seconds))
        except Exception as e:
            _logger.warning("Finans geçmişi sonraki tur planlanamadı: %s", e)

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
    def _process_cargo_invoices(self, api, store, recent_only=True):
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
            if serial_number in processed_serials and (
                    not recent_only or (invoice.transaction_date or recent) < recent):
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

                # Kalemleri sipariş satırı olarak yazılan toplu fatura hakedişte iki kez sayılmasın
                if invoice.allocation_state != 'allocated' and self.search_count([
                        ('store_id', '=', store.id), ('source', '=', 'cargo_invoice'),
                        ('receipt_id', '=', serial_number)]):
                    invoice.write({'allocation_state': 'allocated',
                                   'allocation_note': 'Kalemleri sipariş bazında kayıtlı (kargo faturası)'})

            except Exception as e:
                _logger.warning("Cargo invoice [%s] işleme hatası: %s",
                                serial_number, e)

        return created

    @api.private
    def _process_platform_invoices(self, api, store, recent_only=True):
        """Platform hizmet bedeli faturalarının kalem (sipariş) kırılımını dene.

        Dokümanda platform faturası için kalem servisi yok; fatura seri numarasıyla çalışan
        cargo-invoice/{no}/items servisi denenir. Sipariş numaralı kalem dönerse bedel
        siparişlere dağıtılır, dönmezse faturalar toplu kalır (özet gönderi başı tahmin kullanır).
        """
        domain = [('store_id', '=', store.id), ('transaction_type', '=', 'platform_fee'),
                  ('source', '=', 'otherfinancials'), ('order_id', '=', False)]
        if recent_only:
            domain.append(('transaction_date', '>=', fields.Datetime.now() - timedelta(days=7)))
        invoices = self.search(domain)
        done = set(self.search([('store_id', '=', store.id), ('source', '=', 'platform_invoice')])
                   .mapped('receipt_id'))
        created = tried = with_items = 0
        for invoice in invoices:
            serial = (invoice.trendyol_id or '').split('_')[0]
            if not serial or serial in done:
                continue
            if tried >= 3 and not with_items:
                _logger.info("Platform faturası kalem detayı [%s]: ilk %s fatura boş döndü, kırılım yok — "
                             "faturalar toplu kalacak", store.name, tried)
                break
            tried += 1
            page = 0
            while True:
                result = api.get_cargo_invoice_items(serial, page=page)
                if not result.get('success'):
                    if tried == 1:
                        _logger.info("Platform faturası kalem detayı alınamadı [%s] (%s): %s — faturalar "
                                     "toplu kalacak", store.name, serial, result.get('error'))
                        return 0  # servis bu fatura tipini desteklemiyor: diğerlerini deneme
                    break
                data = result.get('data') or {}
                items = [i for i in (data.get('content') or []) if i.get('orderNumber')]
                if items:
                    with_items += 1
                for item in items:
                    order_number = str(item.get('orderNumber'))
                    unique_id = f"pf_{serial}_{item.get('parcelUniqueId') or order_number}"
                    if self.search_count([('trendyol_id', '=', unique_id), ('store_id', '=', store.id),
                                          ('source', '=', 'platform_invoice')]):
                        continue
                    try:
                        with self.env.cr.savepoint():
                            self.create({
                                'trendyol_id': unique_id,
                                'store_id': store.id,
                                'order_id': self._find_order(store, order_number=order_number),
                                'transaction_date': invoice.transaction_date,
                                'transaction_type': 'platform_fee',
                                'transaction_type_raw': invoice.transaction_type_raw,
                                'description': f"Platform Hizmet Bedeli ({order_number})",
                                'source': 'platform_invoice',
                                'debt': item.get('amount') or 0.0,
                                'credit': 0.0,
                                'order_number': order_number,
                                'receipt_id': serial,
                                'payment_order_id': invoice.payment_order_id,
                                'payment_date': invoice.payment_date,
                            })
                        created += 1
                    except Exception as e:
                        _logger.warning("Platform fatura kalemi yazılamadı (%s): %s", unique_id, e)
                page += 1
                if page >= (data.get('totalPages') or 1):
                    break
        if tried:
            _logger.info("Platform faturası kalem denemesi [%s]: %s fatura, %s tanesinde sipariş kalemi, "
                         "%s kayıt", store.name, tried, with_items, created)
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
            'affiliate': data.get('affiliate') or False,
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
                         'seller_revenue', 'payment_order_id', 'payment_date', 'payment_period', 'affiliate')

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
                if key in ('payment_date', 'affiliate') and not new:
                    continue
                changed[key] = new
        if not record.order_id and vals.get('order_id'):
            changed['order_id'] = vals['order_id']
        # Dağıtılmış toplu faturanın tutarı değiştiyse paylar yeniden hesaplanır
        if record.allocation_state == 'allocated' and ('debt' in changed or 'credit' in changed) \
                and record.transaction_type in FEE_ALLOCATION_TYPES:
            changed.update({'allocation_state': 'pending', 'allocation_checked_at': False})
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
            international_fee = 0.0
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
                elif s.transaction_type == 'international_fee':
                    international_fee += s.debt
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
                if order.fast_delivery_type == 'SameDayShipping' and store.platform_fee_same_day:
                    platform_fee = store.platform_fee_same_day
                elif store.platform_fee_fixed:
                    platform_fee = store.platform_fee_fixed
                elif store.platform_fee_rate:
                    net_after_discount = (order.total_amount or 0) - (order.total_discount or 0)
                    if net_after_discount > 0:
                        platform_fee = round(net_after_discount * store.platform_fee_rate / 100, 2)

            if not has_cargo_invoice and store.cargo_unit_price and order.trendyol_status == 'delivered':
                deci = order.cargo_deci or 1
                shipping_cost = round(deci * store.cargo_unit_price, 2)

            net_revenue = (seller_revenue - platform_fee - international_fee - shipping_cost
                           - return_cargo_cost - penalty_amount - stoppage_amount)

            summary = {
                'platform_fee': platform_fee,
                'international_fee': international_fee,
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
            if order.platform_fee_invoiced != has_platform_invoice:
                changed['platform_fee_invoiced'] = has_platform_invoice
            if order.is_paid != is_paid:
                changed['is_paid'] = is_paid
            if order.paid_date != paid_date:
                changed['paid_date'] = paid_date
            if changed:
                order.sudo().write(changed)


    # ═══════════════════════════════════════════════════════
    # TOPLU İŞLEM
    # ═══════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════
    # HİZMET BEDELİ DAĞITIMI (toplu fatura → paket bazlı satır)
    # ═══════════════════════════════════════════════════════

    @api.private
    def _fee_invoice_domain(self, store):
        """Sipariş/paket bilgisi olmayan (toplu) Uluslararası / Platform Hizmet Bedeli faturaları."""
        return [
            ('store_id', '=', store.id),
            ('source', '=', 'otherfinancials'),
            ('transaction_type', 'in', list(FEE_ALLOCATION_TYPES)),
            '|', ('order_number', '=', False), ('order_number', '=', ''),
            '|', ('shipment_package_id', '=', False), ('shipment_package_id', '=', ''),
        ]

    @api.private
    def _allocate_service_fees(self, api, store, force=False, payment_order_ids=None):
        """Toplu hizmet bedeli faturalarını aynı ödeme emri + affiliate'teki paketlere dağıtır.

        - Son 60 günün dağıtılmamış faturaları (her ödeme emri günde en fazla bir kez) denenir.
        - Satış kaydı görülen ama faturası henüz Odoo'da olmayan ödeme emirleri de sorgulanır
          (fatura satıştan haftalar sonra kesilir).
        Dönüş: {'payment_orders', 'allocated', 'rows', 'warnings', 'unmatched', 'errors'}
        """
        now = fields.Datetime.now()
        since = now - timedelta(days=_FEE_ALLOCATION_LOOKBACK_DAYS)
        result = {'payment_orders': 0, 'allocated': 0, 'rows': 0, 'warnings': 0, 'unmatched': 0, 'errors': []}

        domain = self._fee_invoice_domain(store) + [('allocation_state', '!=', 'allocated')]
        if payment_order_ids:
            domain.append(('payment_order_id', 'in', list(payment_order_ids)))
        else:
            domain.append(('transaction_date', '>=', since))
            if not force:
                # Uyarıdakiler (eşit bölünmeyen) tutar değişmedikçe kendiliğinden düzelmez → elle tetiklenir
                domain += [('allocation_state', '!=', 'warning'),
                           '|', ('allocation_checked_at', '=', False),
                           ('allocation_checked_at', '<', now - timedelta(days=1))]
        invoices = self.search(domain, order='transaction_date desc')

        # Ödeme no henüz yok → ödeme emri işlenince dağıtılacak
        waiting = invoices.filtered(lambda r: not r.payment_order_id and r.allocation_state != 'pending')
        if waiting:
            waiting.write({'allocation_state': 'pending', 'allocation_note': 'Ödeme no bekleniyor'})

        po_ids = []
        for po in list(payment_order_ids or []) + invoices.mapped('payment_order_id'):
            if po and po not in po_ids:
                po_ids.append(po)
        if not payment_order_ids:
            po_ids += [po for po in self._fee_scan_candidates(store, since) if po not in po_ids]
        po_ids = po_ids[:_FEE_ALLOCATION_PO_LIMIT]

        scanned = []
        for po in po_ids:
            try:
                with self.env.cr.savepoint():
                    self._allocate_payment_order(api, store, po, result)
                scanned.append(po)
            except Exception as e:
                result['errors'].append(f"Ödeme {po}: {e}")
                _logger.warning("Hizmet bedeli dağıtımı — ödeme %s [%s]: %s", po, store.name, e)
        if scanned:
            self._fee_scan_mark(store, scanned)

        if result['payment_orders']:
            _logger.info("Trendyol hizmet bedeli dağıtımı [%s]: %s ödeme, %s fatura dağıtıldı (%s satır), "
                         "%s uyarı, %s eşleşmedi, %s hata", store.name, result['payment_orders'],
                         result['allocated'], result['rows'], result['warnings'], result['unmatched'],
                         len(result['errors']))
        return result

    @api.private
    def _fee_scan_candidates(self, store, since):
        """Satışı ödenmiş ama hizmet bedeli faturası Odoo'da olmayan, bugün sorgulanmamış ödeme emirleri."""
        self.env.cr.execute("""
            SELECT DISTINCT s.payment_order_id
              FROM trendyol_settlement s
             WHERE s.store_id = %s AND s.source = 'settlements' AND s.transaction_type = 'sale'
               AND COALESCE(s.payment_order_id, '') <> '' AND s.payment_date >= %s
               AND NOT EXISTS (
                   SELECT 1 FROM trendyol_settlement f
                    WHERE f.store_id = s.store_id AND f.source = 'otherfinancials'
                      AND f.transaction_type IN %s AND f.payment_order_id = s.payment_order_id)
        """, (store.id, since, FEE_ALLOCATION_TYPES))
        candidates = [r[0] for r in self.env.cr.fetchall()]
        today = fields.Date.today().isoformat()
        checked = {p.split(':')[0] for p in (store.fee_scanned_payment_orders or '').split(',')
                   if p.endswith(':' + today)}
        return sorted((po for po in candidates if po not in checked), reverse=True)

    @api.private
    def _fee_scan_mark(self, store, po_ids):
        today = fields.Date.today().isoformat()
        entries = [p for p in (store.fee_scanned_payment_orders or '').split(',')
                   if p and p.endswith(':' + today) and p.split(':')[0] not in po_ids]
        entries += [f"{po}:{today}" for po in po_ids]
        try:
            # Ayrı cursor: mağaza satırı ana işlemde kilitlenmesin (bkz. _sync_payment_orders)
            with self.pool.cursor() as new_cr:
                new_cr.execute("UPDATE trendyol_store SET fee_scanned_payment_orders = %s WHERE id = %s",
                               (','.join(entries[-500:]), store.id))
        except Exception as e:
            _logger.warning("Hizmet bedeli tarama önbelleği yazılamadı (%s): %s", store.name, e)

    @api.private
    def _fetch_paged(self, fetch, **kwargs):
        """Sayfalı finans servisi çağrısı → (kayıtlar, hata)."""
        items, page = [], 0
        while True:
            res = fetch(page=page, size=1000, **kwargs)
            if not res.get('success'):
                return items, res.get('error') or 'API hatası'
            data = res.get('data') or {}
            items.extend(data.get('content') or [])
            page += 1
            if page >= (data.get('totalPages') or 1):
                return items, None

    @api.private
    def _allocate_payment_order(self, api, store, payment_order_id, result):
        """Tek ödeme emri: faturaları tazele, Sale/Discount paketlerini çek, gider türü bazında dağıt.

        Faturalar tek tek değil (ödeme + affiliate + tür) grubu olarak dağıtılır: TR/AZ'de grup tek
        toplu faturadır, mikro ihracatta gönderi / ülke başına kesilmiş birden çok fatura olur.
        Gruba yeni fatura gelirse (veya tutar değişirse) grup baştan hesaplanır.
        """
        # 1) Kesinti faturaları (yeni gelenler + affiliate bilgisi)
        invoices_raw, error = self._fetch_paged(
            api.get_other_financials, transaction_type='DeductionInvoices', payment_order_id=payment_order_id)
        if error:
            raise UserError(f"DeductionInvoices: {error}")
        for item in invoices_raw:
            self._process_settlement_item(item, store, 'otherfinancials')

        invoices = self.search(self._fee_invoice_domain(store) + [('payment_order_id', '=', payment_order_id)])
        if not invoices or all(inv.allocation_state == 'allocated' for inv in invoices):
            return
        result['payment_orders'] += 1

        # 2) Dağıtım tabanı: aynı ödeme emrindeki Sale + Discount kayıtları (affiliate / ülke yalnız API'de)
        rows, error = self._fetch_paged(
            api.get_settlements, transaction_types=['Sale', 'Discount'], payment_order_id=payment_order_id)
        if error:
            raise UserError(f"Settlements: {error}")
        packages = defaultdict(dict)  # affiliate → {paket: {'net', 'order_number', 'has_sale', 'country'}}
        for row in rows:
            package_id = str(row.get('shipmentPackageId') or '')
            if not package_id:
                continue
            pkg = packages[row.get('affiliate') or ''].setdefault(
                package_id, {'net': 0.0, 'order_number': str(row.get('orderNumber') or ''),
                             'has_sale': False, 'country': row.get('country') or ''})
            pkg['net'] += (row.get('credit') or 0.0) - (row.get('debt') or 0.0)
            if normalize_tr(row.get('transactionType')) in ('satis', 'sale'):
                pkg['has_sale'] = True

        # Kalemleri platform-invoice servisiyle sipariş bazında yazılmış faturalar gruba girmez
        itemized = set(self.search([('store_id', '=', store.id), ('source', '=', 'platform_invoice'),
                                    ('receipt_id', 'in', invoices.mapped('trendyol_id'))]).mapped('receipt_id'))
        groups = defaultdict(lambda: self.browse())
        for inv in invoices:
            if inv.trendyol_id in itemized:
                if inv.allocation_state != 'allocated':
                    inv.write({'allocation_state': 'allocated', 'allocation_checked_at': fields.Datetime.now(),
                               'allocation_note': 'Kalemleri sipariş bazında kayıtlı (platform faturası)'})
                continue
            groups[(self._invoice_affiliate(inv, packages), inv.transaction_type)] |= inv

        for (affiliate, tx_type), group in groups.items():
            if all(inv.allocation_state == 'allocated' for inv in group):
                continue
            pkgs = packages.get(affiliate, {}) if affiliate is not None else {}
            state = self._allocate_group(api, store, payment_order_id, affiliate, tx_type, group, pkgs, result)
            key = {'allocated': 'allocated', 'warning': 'warnings', 'unmatched': 'unmatched'}[state]
            result[key] += len(group)

    @api.model
    def _split_amount(self, amount, weights):
        """Tutarı ağırlıklara göre 2 haneli paylara böler; kuruş farkı en büyük paya eklenir.
        Payların toplamı tutara tam eşittir. weights: {anahtar: ağırlık>0}"""
        total = sum(weights.values())
        shares = {k: round(amount * w / total, 2) for k, w in weights.items()}
        diff = round(amount - sum(shares.values()), 2)
        if abs(diff) >= 0.005:
            biggest = max(shares, key=lambda k: shares[k])
            shares[biggest] = round(shares[biggest] + diff, 2)
        return shares

    @api.private
    def _invoice_affiliate(self, invoice, packages):
        """Faturanın affiliate'i. Eski kayıtta yoksa tek kanal / 'AZ-' öneki ile çıkarılır (bulunamazsa None)."""
        if invoice.affiliate:
            return invoice.affiliate
        if len(packages) == 1:
            return next(iter(packages))
        is_az = normalize_tr(invoice.transaction_type_raw).startswith('az-')
        matches = [aff for aff in packages if ('AZ' in (aff or '').upper()) == is_az]
        return matches[0] if len(matches) == 1 else None

    @api.private
    def _allocate_group(self, api, store, payment_order_id, affiliate, tx_type, invoices, all_pkgs, result):
        """Aynı ödeme + affiliate + türdeki faturaların toplamını paketlere dağıtıp satırları yazar.
        Dönüş: yeni durum (allocated / warning / unmatched)."""
        now = fields.Datetime.now()
        label = dict(SETTLEMENT_TYPES).get(tx_type)
        amounts = {inv.id: round((inv.debt or 0.0) - (inv.credit or 0.0), 2) for inv in invoices}
        total = round(sum(amounts.values()), 2)
        # İadeli/iptal paketler (net ≤ 0 veya satışı olmayan) pay almaz
        pkgs = {pid: p for pid, p in all_pkgs.items() if p['has_sale'] and p['net'] > 0.005}

        def mark(state, note):
            invoices.write({'allocation_state': state, 'allocation_note': note, 'allocation_checked_at': now})
            if state != 'allocated':
                _logger.info("Trendyol hizmet bedeli %s (%s, ödeme %s): %s",
                             ', '.join(invoices.mapped('trendyol_id')), label, payment_order_id, note)
            return state

        if total <= 0:
            return mark('unmatched', f"Tutar {total:.2f} — dağıtılacak borç yok")
        if not pkgs:
            return mark('unmatched', f"Ödeme {payment_order_id} içinde aynı kanala ait satış paketi bulunamadı")

        if tx_type == 'platform_fee':
            shares, note = self._platform_shares(api, store, total, pkgs, result)
            if shares is None:
                return mark('warning', note)
            receipts = {pid: invoices for pid in shares}
        else:
            shares, receipts, note = self._international_shares(invoices, amounts, pkgs)

        self._write_fee_rows(store, payment_order_id, affiliate, tx_type, label, shares, receipts, pkgs)
        result['rows'] += len(shares)

        skipped = len(all_pkgs) - len(pkgs)
        if skipped:
            note += f" ({skipped} iade/iptal paket pay almadı)"
        if len(invoices) > 1:
            note = f"{len(invoices)} fatura toplamı {total:.2f} TL: {note}"
        return mark('allocated', note)

    @api.private
    def _platform_shares(self, api, store, total, pkgs, result):
        """Platform bedeli: Bugün Kargoda (SameDayShipping) paketlere mağaza ayarındaki indirimli bedel,
        kalan diğer paketlere eşit. Kuruşu kuruşuna tutmazsa (None, açıklama) döner — tahmin yapılmaz."""
        cents, count = int(round(total * 100)), len(pkgs)
        types = self._package_delivery_types(api, store, pkgs, result)
        same_day = [pid for pid in pkgs if types.get(pid) == 'SameDayShipping']
        sd_cents = int(round((store.platform_fee_same_day or 0.0) * 100))
        if same_day and sd_cents:
            rest, others = cents - sd_cents * len(same_day), count - len(same_day)
            if (others == 0 and rest == 0) or (others and rest > 0 and rest % others == 0):
                std = rest // others if others else 0
                shares = {pid: (sd_cents if pid in same_day else std) / 100.0 for pid in pkgs}
                return shares, (f"{count} pakete dağıtıldı ({len(same_day)} Bugün Kargoda × "
                                f"{sd_cents / 100:.2f}, {others} × {std / 100:.2f})")
        if cents % count == 0:
            note = f"{count} pakete eşit dağıtıldı ({cents // count / 100:.2f})"
            if same_day:
                note += f" — {len(same_day)} Bugün Kargoda paketine indirim uygulanmamış"
            return {pid: cents // count / 100.0 for pid in pkgs}, note
        unknown = count - len(types)
        detail = f"{len(same_day)} Bugün Kargoda"
        if unknown:
            detail += f", {unknown} paketin teslimat tipi bilinmiyor"
        return None, f"{total:.2f} TL {count} pakete dağıtılamadı ({detail}; eşit pay {total / count:.4f})"

    @api.private
    def _package_delivery_types(self, api, store, pkgs, result):
        """Paket → fastDeliveryType. Önce Odoo siparişi (alan / ham JSON), yoksa sipariş servisi (sınırlı)."""
        Order = self.env['trendyol.order']
        types, missing = {}, []
        for pid, p in pkgs.items():
            order = Order.browse(self._find_order(store, pid, p['order_number']) or [])
            ftype = order.fast_delivery_type
            if not ftype and order.raw_data:
                try:
                    ftype = json.loads(order.raw_data).get('fastDeliveryType')
                except (ValueError, AttributeError):
                    ftype = False
                if ftype:
                    order.write({'fast_delivery_type': ftype})
            if ftype:
                types[pid] = ftype
            elif p['order_number']:
                missing.append((pid, p['order_number'], order))
        for pid, order_number, order in missing:
            if result.get('lookups', 0) >= _FAST_TYPE_LOOKUP_LIMIT:
                break
            result['lookups'] = result.get('lookups', 0) + 1
            res = api.get_orders(order_number=order_number) or {}
            content = ((res.get('data') or {}).get('content') or []) if res.get('success') else []
            match = [o for o in content if str(o.get('shipmentPackageId') or o.get('id') or '') == pid] or content
            ftype = match[0].get('fastDeliveryType') if match else False
            if ftype:
                types[pid] = ftype
                if order:
                    order.write({'fast_delivery_type': ftype})
        return types

    @api.model
    def _international_shares(self, invoices, amounts, pkgs):
        """Uluslararası bedel: net tutar oranında. Birden çok fatura varsa (mikro ihracat: ülke başına)
        her fatura tutarına uyan ülke grubuna eşlenir; eşlenemezse toplam tüm paketlere oransal bölünür.
        Dönüş: (paylar, paket → kaynak faturalar, açıklama)"""
        by_country = defaultdict(dict)
        for pid, p in pkgs.items():
            by_country[p.get('country') or ''][pid] = p['net']
        if len(invoices) > 1 and len(invoices) == len(by_country) and '' not in by_country:
            rate = sum(amounts.values()) / sum(p['net'] for p in pkgs.values())
            assign = {}
            for inv in invoices:
                cands = [c for c, nets in by_country.items() if c not in assign.values()
                         and abs(sum(nets.values()) * rate - amounts[inv.id]) <= 0.02 + 0.01 * len(nets)]
                if len(cands) != 1:
                    break
                assign[inv] = cands[0]
            if len(assign) == len(invoices):
                shares, receipts = {}, {}
                for inv, country in assign.items():
                    for pid, share in self._split_amount(amounts[inv.id], by_country[country]).items():
                        shares[pid], receipts[pid] = share, inv
                return shares, receipts, f"{len(shares)} pakete ülke bazında oransal dağıtıldı ({len(assign)} ülke)"
        total = round(sum(amounts.values()), 2)
        shares = self._split_amount(total, {pid: p['net'] for pid, p in pkgs.items()})
        return shares, {pid: invoices for pid in shares}, f"{len(shares)} pakete net tutar oranında dağıtıldı"

    @api.private
    def _write_fee_rows(self, store, payment_order_id, affiliate, tx_type, label, shares, receipts, pkgs):
        """Paket başına dağıtım satırını yazar/günceller; artık pay almayan paketin satırı silinir."""
        domain = [('store_id', '=', store.id), ('source', '=', 'fee_allocation'),
                  ('payment_order_id', '=', payment_order_id), ('transaction_type', '=', tx_type),
                  ('affiliate', '=', affiliate) if affiliate else ('affiliate', 'in', [False, ''])]
        existing = {r.trendyol_id: r for r in self.search(domain)}
        keep = set()
        for pid, share in shares.items():
            tid = f"alloc_{payment_order_id}_{tx_type}_{pid}"
            keep.add(tid)
            sources = receipts[pid]
            receipt = ', '.join(sources.mapped('trendyol_id'))
            order_number = pkgs[pid]['order_number']
            dates = [d for d in sources.mapped('transaction_date') if d]
            vals = {
                'trendyol_id': tid,
                'store_id': store.id,
                'order_id': self._find_order(store, pid, order_number),
                'transaction_date': max(dates) if dates else False,
                'transaction_type': tx_type,
                'transaction_type_raw': sources[:1].transaction_type_raw,
                'description': f"{label} (dağıtılmış, fatura {receipt})",
                'source': 'fee_allocation',
                'debt': share,
                'credit': 0.0,
                'order_number': order_number,
                'shipment_package_id': pid,
                'receipt_id': receipt,
                'payment_order_id': payment_order_id,
                'payment_date': sources[:1].payment_date,
                'affiliate': affiliate or False,
            }
            row = existing.get(tid)
            if row:
                changed = {}
                for key in ('debt', 'order_id', 'transaction_date', 'payment_date', 'description', 'receipt_id'):
                    old = row[key].id if key == 'order_id' else row[key]
                    new = vals[key]
                    if key == 'debt':
                        if abs((old or 0.0) - (new or 0.0)) > 0.005:
                            changed[key] = new
                    elif (old or False) != (new or False):
                        changed[key] = new
                if changed:
                    row.write(changed)
            else:
                self.create(vals)
        stale = [r.id for tid, r in existing.items() if tid not in keep]
        if stale:
            self.browse(stale).unlink()

    def action_allocate_fees(self):
        """Seçili toplu faturaların (uyarı / eşleşmedi dahil) dağıtımını yeniden dene."""
        stores = self.mapped('store_id')
        for store in stores:
            pos = set(self.filtered(lambda r: r.store_id == store).mapped('payment_order_id')) - {False, ''}
            if pos:
                self._allocate_service_fees(store.get_api(), store, payment_order_ids=pos)
        return True

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

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MarketplaceMapping(models.Model):
    _name = 'odoougurlar.marketplace.mapping'
    _description = 'Pazaryeri ve Ülke Bazlı Muhasebe Eşleştirmeleri'

    name = fields.Char(string='Kural Adı', required=True)
    active = fields.Boolean(default=True)

    marketplace = fields.Char(
        string='Pazaryeri Kodu / Adı',
        required=True,
        help='Örn: TRENDYOL'
    )
    country_id = fields.Many2one(
        'res.country',
        string='Hedef Ülke',
        help='Boş bırakılırsa tüm ülkelere uygulanır. TR (Yurtiçi) veya AZ, BH (İhracat) kuralı koyabilirsiniz.'
    )

    # ── MÜŞTERİ (CARİ) TANIMI ──
    nebim_customer_code = fields.Char(
        string='Müşteri Kodu (CustomerCode)',
        help='Faturada geçecek toptan/perakende cari kodu. Örn: 120.002.011'
    )

    # ── SİPARİŞ/FATURA TİPLERİ ──
    nebim_order_model_type = fields.Selection([
        ('6', 'ModelType 6 (Direkt Perakende Fatura - Hamurlabs)'),
        ('13', 'ModelType 13 (Perakende Sipariş)'),
        ('14', 'ModelType 14 (İhracat Siparişi)'),
        ('99', 'ModelType 99 (Toptan Sipariş)'),
    ], string='Nebim Sipariş Modeli', default='13', required=True)

    nebim_invoice_model_type = fields.Selection([
        ('8', 'ModelType 8 (Perakende Fatura/e-Arşiv)'),
        ('24', 'ModelType 24 (İhracat Faturası)'),
        ('7', 'ModelType 7 (Toptan Fatura/e-Fatura)'),
    ], string='Nebim Fatura Modeli', default='8', required=True)

    nebim_address_id = fields.Char(string='Nebim Varsayılan Adres ID (GUID)', help='ModelType 6 işlemleri için zorunludur.', default='adc3d09b-897b-4b74-a29f-b42600863ec3')

    # ── İHRACAT KODLARI ──
    export_type_code = fields.Char(string='ExportTypeCode', default='001', help='Örn: 001 (Mal İhracatı)')
    tax_exemption_code = fields.Char(string='TaxExemptionCode', default='301', help='Örn: 301')
    incoterm_code = fields.Char(string='IncotermCode1', default='FCA', help='Uluslararası teslimat şartı. Örn: FCA, EXW, FOB')
    payment_means_code = fields.Char(string='PaymentMeansCode', default='10', help='Ödeme yöntemi kodu. Örn: 10 (Nakit)')
    shipment_method_code = fields.Char(string='ShipmentMethodCode', default='1', help='İhracatta 1, Perakendede 2')

    # ── ÖDEME VE MUHASEBE ──
    bank_code = fields.Char(string='Banka Kodu (BankCode)', help='Örn: 102.011.012')
    credit_card_type_code = fields.Char(string='Kredi Kartı Tipi', help='Örn: AZC')
    credit_card_desc = fields.Char(string='Kredi Kartı Açıklama', help='Örn: AZERBAYCAN TRENDYOL')
    sales_advance_code = fields.Char(string='Satış Avans (Kurum/Hesap)', help='Örn: 136.004.001')
    sales_person_code = fields.Char(string='SalesPersonCode', default='TRD')

    # ── TESLİMAT VE DEPO ──
    delivery_company_code = fields.Char(
        string='Kargo Şirketi Kodu',
        default='YRT',
        help='Nebim Kargo Şirketi Kodu. Örn: YRT (Yurtiçi), MNG, PTS'
    )
    store_code = fields.Char(
        string='Mağaza Kodu',
        default='002',
        help='Nebim Mağaza Kodu. Örn: 002'
    )
    warehouse_code = fields.Char(
        string='Depo Kodu',
        default='002',
        help='Nebim Depo Kodu. Örn: 002'
    )
    payment_agent = fields.Char(
        string='Ödeme Aracı',
        default='TrendyolMp',
        help='OrdersViaInternetInfo PaymentAgent alanı. Örn: TrendyolMp, HbMp'
    )
    sales_url = fields.Char(
        string='Satış URL',
        default='www.trendyol.com',
        help='OrdersViaInternetInfo SalesURL alanı'
    )

    # Basit in-process cache (worker restart'ta temizlenir)
    _mapping_cache = {}
    
    @api.model
    def find_mapping(self, marketplace_name, country_id=False):
        """Pazaryeri ve ülkeye göre en uygun kuralı bulur (cache destekli)."""
        cache_key = (marketplace_name, country_id)
        if cache_key in self._mapping_cache:
            cached_id = self._mapping_cache[cache_key]
            if cached_id:
                cached_record = self.browse(cached_id)
                if cached_record.exists():
                    return cached_record
            elif cached_id is False:
                return False
        
        domain = [('marketplace', 'ilike', marketplace_name)]
        mappings = self.search(domain)
        
        # Ülke eşleşeni var mı?
        exact_match = None
        global_match = None
        for m in mappings:
            if m.country_id and m.country_id.id == country_id:
                exact_match = m
            if not m.country_id:
                global_match = m
                
        result = exact_match or global_match or (mappings[0] if mappings else False)
        self._mapping_cache[cache_key] = result.id if result else False
        return result

    @api.model
    def clear_mapping_cache(self):
        """Cache'i temizle — mapping değiştiğinde çağrılır."""
        self._mapping_cache.clear()

    def write(self, vals):
        """Mapping değiştiğinde cache temizle."""
        self.clear_mapping_cache()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """Yeni mapping oluşturulduğunda cache temizle."""
        self.clear_mapping_cache()
        return super().create(vals_list)

    def unlink(self):
        """Mapping silindiğinde cache temizle."""
        self.clear_mapping_cache()
        return super().unlink()

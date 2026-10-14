import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Nebim bağlantı ayarlarını Odoo Ayarlar menüsünden yönetmek için."""
    _inherit = 'res.config.settings'

    # -----------------------------------------------------------------
    #  Bağlantı Ayarları
    # -----------------------------------------------------------------
    nebim_url = fields.Char(
        string='Nebim API URL',
        config_parameter='odoougurlar.nebim_url',
        help='Nebim IntegratorService temel URL\'i (ör: http://192.168.0.225:9091/IntegratorService)',
    )
    nebim_database = fields.Char(
        string='Nebim Veritabanı',
        config_parameter='odoougurlar.nebim_database',
        default='UGURLAR',
        help='Nebim veritabanı adı',
    )
    nebim_user_group = fields.Char(
        string='Nebim Kullanıcı Grubu',
        config_parameter='odoougurlar.nebim_user_group',
        default='ADM',
    )
    nebim_username = fields.Char(
        string='Nebim Kullanıcı Adı',
        config_parameter='odoougurlar.nebim_username',
        default='INT2',
        groups='base.group_system',
    )
    nebim_password = fields.Char(
        string='Nebim Şifre',
        config_parameter='odoougurlar.nebim_password',
        groups='base.group_system',
    )
    nebim_model_type = fields.Integer(
        string='Nebim Model Type',
        config_parameter='odoougurlar.nebim_model_type',
        default=1,
        help='Nebim bağlantı için ModelType değeri',
    )

    # -----------------------------------------------------------------
    #  Stored Procedure İsimleri
    # -----------------------------------------------------------------
    nebim_sp_item_details = fields.Char(
        string='Ürün Detay SP',
        config_parameter='odoougurlar.nebim_sp_item_details',
        default='sp_GetItemDetails_Hamurlabs',
        help='Ürün detaylarını getiren stored procedure adı',
    )
    nebim_sp_inventory = fields.Char(
        string='Stok/Envanter SP',
        config_parameter='odoougurlar.nebim_sp_inventory',
        default='sp_GetInventory_Hamurlabs',
        help='Stok ve envanter bilgisini getiren stored procedure adı',
    )
    nebim_sp_item_attribute = fields.Char(
        string='Ürün Öznitelik SP',
        config_parameter='odoougurlar.nebim_sp_item_attribute',
        default='sp_GetItemAttributeType_Hamurlabs',
        help='Ürün öznitelik tiplerini getiren stored procedure adı',
    )
    nebim_sp_customer = fields.Char(
        string='Müşteri SP',
        config_parameter='odoougurlar.nebim_sp_customer',
        default='sp_GetCustomer_Hamurlabs',
        help='Müşteri bilgilerini getiren stored procedure adı',
    )
    nebim_sp_country = fields.Char(
        string='Ülke SP',
        config_parameter='odoougurlar.nebim_sp_country',
        default='sp_GetCountry_Hamurlabs',
        help='Ülke bilgilerini getiren stored procedure adı',
    )
    nebim_sp_district = fields.Char(
        string='İlçe SP',
        config_parameter='odoougurlar.nebim_sp_district',
        default='sp_GetDistrict_Hamurlabs',
        help='İlçe bilgilerini getiren stored procedure adı',
    )
    nebim_sp_vendor = fields.Char(
        string='Tedarikçi SP',
        config_parameter='odoougurlar.nebim_sp_vendor',
        default='sp_GetVendorInfo_Hamurlabs',
        help='Tedarikçi bilgilerini getiren stored procedure adı',
    )
    nebim_sp_warehouse = fields.Char(
        string='Depo SP',
        config_parameter='odoougurlar.nebim_sp_warehouse',
        default='sp_GetWarehouseInfo_Hamurlabs',
        help='Depo bilgilerini getiren stored procedure adı',
    )
    nebim_sp_basket_discount = fields.Char(
        string='Sepet İndirimleri SP',
        config_parameter='odoougurlar.nebim_sp_basket_discount',
        default='sp_Odoougurlar_GetBasketDiscounts',
        help='Fiyat ve indirimleri getiren stored procedure adı (Barkod Okutma)',
    )
    nebim_sp_search_customer = fields.Char(
        string='Müşteri Ara SP',
        config_parameter='odoougurlar.nebim_sp_search_customer',
        default='sp_Odoougurlar_SearchCustomer',
        help='Müşteri listesini getiren stored procedure adı (Barkod Okutma)',
    )
    nebim_sp_product_matrix = fields.Char(
        string='Matris Raporu SP',
        config_parameter='odoougurlar.nebim_sp_product_matrix',
        default='sp_Odoougurlar_GetProductMatrix',
        help='Renk ve beden matris raporunu getiren stored procedure adı (Barkod Okutma)',
    )
    nebim_sp_product_cost = fields.Char(
        string='Ürün Maliyet SP',
        config_parameter='odoougurlar.nebim_sp_product_cost',
        default='usp_UrunEkstresi_BirimMaliyetHesapla',
        help='Ürün maliyetlerini (Birim Maliyet) getiren stored procedure adı',
    )
    nebim_sync_cost_enabled = fields.Boolean(
        string='Maliyet Senkronizasyonu Aktif',
        config_parameter='odoougurlar.nebim_sync_cost_enabled',
        default=False,
        help='Aktif olduğunda ürünlerin maliyet fiyatları düzenli olarak Nebim\'den çekilerek güncellenir.',
    )

    # -----------------------------------------------------------------
    #  Fatura Arşivleme & e-Dönüşüm Prosedür ve Tablo Ayarları
    # -----------------------------------------------------------------
    nebim_sp_purchase_invoices = fields.Char(
        string='Toptan Alış Fatura SP',
        config_parameter='odoougurlar.nebim_sp_purchase_invoices',
        default='usp_GetPurchaseInvoices_Ugurlar',
        help='Toptan Alış faturalarını ve ürün-belge eşleşmelerini getiren prosedür',
    )
    nebim_table_wholesale_invoices = fields.Char(
        string='Toptan Alış Önbellek Tablosu',
        config_parameter='odoougurlar.nebim_table_wholesale_invoices',
        default='tbl_EntegraToptanAlisBelge',
        help='Toptan Alış belgelerini saklayan Nebim veritabanı önbellek tablosu',
    )
    nebim_sp_update_wholesale_invoices = fields.Char(
        string='Toptan Alış Önbellek Güncelleme SP',
        config_parameter='odoougurlar.nebim_sp_update_wholesale_invoices',
        default='sp_UpdateEntegraToptanAlisBelge',
        help='Toptan Alış önbellek tablosunu güncelleyen prosedür',
    )
    nebim_sp_earchive_url = fields.Char(
        string='e-Arşiv URL SP',
        config_parameter='odoougurlar.nebim_sp_earchive_url',
        default='usp_Invoice_EArchieveURL',
        help='Giden satış faturalarının e-Arşiv URL\'ini getiren prosedür',
    )
    nebim_sp_efatura_url = fields.Char(
        string='e-Fatura ETTN SP',
        config_parameter='odoougurlar.nebim_sp_efatura_url',
        default='usp_PurchaseInvoice_EFaturaURL',
        help='Gelen alış faturalarının e-Fatura ETTN (UUID) ve portal bilgisini getiren prosedür',
    )
    dogan_portal_url = fields.Char(
        string='Doğan E-Dönüşüm Portal API',
        config_parameter='odoougurlar.dogan_portal_url',
        default='https://connector.doganedonusum.com/EFaturaOIB',
        help='Doğan E-Dönüşüm SOAP entegratör PDF ve e-Fatura servis URL adresi',
    )

    # -----------------------------------------------------------------
    #  Nebim Gönderim Ayarları (Cari / Sipariş / Fatura)
    # -----------------------------------------------------------------
    nebim_sync_customer_enabled = fields.Boolean(
        string='Cari İşle',
        config_parameter='odoougurlar.nebim_sync_customer_enabled',
        default=False,
        help='Aktif olduğunda pazaryeri siparişleri için Nebim\'e cari (müşteri kartı) gönderilir.',
    )
    nebim_sync_order_enabled = fields.Boolean(
        string='Sipariş İşle',
        config_parameter='odoougurlar.nebim_sync_order_enabled',
        default=False,
        help='Aktif olduğunda pazaryeri siparişleri Nebim\'e sipariş olarak aktarılır.',
    )
    nebim_sync_invoice_enabled = fields.Boolean(
        string='Fatura İşle',
        config_parameter='odoougurlar.nebim_sync_invoice_enabled',
        default=False,
        help='Aktif olduğunda fatura oluşturulup Nebim\'e gönderilir.',
    )
    nebim_auto_delete_on_cancel = fields.Boolean(
        string='İptal Siparişi Nebim\'den Sil',
        config_parameter='odoougurlar.nebim_auto_delete_on_cancel',
        default=True,
        help='Aktif olduğunda, pazaryerinden iptal edilen siparişler '
             'Odoo\'da iptal edildiğinde Nebim\'deki siparişi de otomatik siler. '
             'Bu sayede Nebim\'in ayırdığı stok serbest kalır.',
    )
    nebim_cancel_cleanup_auto = fields.Boolean(
        string='Otomatik İptal Temizliği',
        config_parameter='odoougurlar.nebim_cancel_cleanup_auto',
        default=False,
        help='Aktif olduğunda, belirli aralıklarla Nebim\'de kalan iptal siparişler otomatik silinir.',
    )
    nebim_cancel_cleanup_interval = fields.Selection([
        ('5', '5 Dakika'),
        ('10', '10 Dakika'),
        ('15', '15 Dakika'),
        ('30', '30 Dakika'),
        ('60', '1 Saat'),
    ],
        string='İptal Temizliği Aralığı',
        config_parameter='odoougurlar.nebim_cancel_cleanup_interval',
        default='10',
        help='İptal siparişlerin Nebim\'den temizlenme sıklığı',
    )

    # -----------------------------------------------------------------
    #  Test Ayarları
    # -----------------------------------------------------------------
    nebim_test_product_count = fields.Integer(
        string='Test Ürün Sayısı',
        config_parameter='odoougurlar.nebim_test_product_count',
        default=1,
        help='Test Ürün Çek butonuyla çekilecek ürün sayısı (varsayılan: 1)',
    )
    nebim_sync_mode = fields.Selection([
        ('full', 'Tüm Ürünler (İlk Kurulum)'),
        ('hourly', 'Saatlik Güncelleme'),
        ('daily', 'Günlük Güncelleme'),
    ],
        string='Senkronizasyon Modu',
        config_parameter='odoougurlar.nebim_sync_mode',
        default='daily',
        help=(
            'Tüm Ürünler: Nebim\'deki tüm ürünleri çeker (ilk kurulumda kullanın).\n'
            'Saatlik: Son 1 saatte eklenen/değişen ürünleri otomatik çeker.\n'
            'Günlük: Son 1 günde eklenen/değişen ürünleri otomatik çeker.'
        ),
    )
    nebim_auto_sync = fields.Boolean(
        string='Otomatik Senkronizasyon',
        config_parameter='odoougurlar.nebim_auto_sync',
        default=False,
        help='Aktifleştirildiğinde, seçilen moda göre (saatlik/günlük) ürün senkronizasyonu otomatik çalışır.',
    )
    nebim_stock_auto_sync = fields.Boolean(
        string='Otomatik Stok Güncelleme',
        config_parameter='odoougurlar.nebim_stock_auto_sync',
        default=False,
        help='Aktifleştirildiğinde, belirli aralıklarla Nebim\'den stok değişimleri otomatik çekilir.',
    )
    # 30/45 sn kaldırıldı: ir.cron 'seconds' aralığını desteklemez, Ayarlar kaydı tümden çöküyordu
    nebim_stock_sync_interval = fields.Selection([
        ('60', '1 Dakika'),
        ('120', '2 Dakika'),
        ('300', '5 Dakika'),
    ],
        string='Stok Güncelleme Aralığı',
        config_parameter='odoougurlar.nebim_stock_sync_interval',
        default='60',
        help='Stok değişimlerinin Nebim\'den çekilme sıklığı',
    )
    nebim_log_auto_cleanup = fields.Boolean(
        string='Otomatik Log Temizliği',
        config_parameter='odoougurlar.nebim_log_auto_cleanup',
        default=True,
        help='Aktifleştirildiğinde, tamamlanmış loglar 1 gün, hatalı loglar 7 gün sonra otomatik silinir.',
    )

    # -----------------------------------------------------------------
    #  Ürün Güncelleme Alan Korumaları (AI / Manuel Veri Koruma)
    # -----------------------------------------------------------------
    nebim_prevent_name_update = fields.Boolean(
        string='Ürün Adı Güncellenmesin',
        config_parameter='odoougurlar.nebim_prevent_name_update',
        default=True,
        help='Açık olduğunda, mevcut ürünler Nebim senkronizasyonu ile güncellenirken Odoo\'daki ürün adı (AI başlığı) korunur ve Nebim adı ile ezilmez.',
    )
    nebim_prevent_description_update = fields.Boolean(
        string='Açıklama Güncellenmesin',
        config_parameter='odoougurlar.nebim_prevent_description_update',
        default=True,
        help='Açık olduğunda, mevcut ürünler Nebim senkronizasyonu ile güncellenirken Odoo\'daki ürün açıklaması (AI açıklaması) korunur ve Nebim notları ile ezilmez.',
    )
    nebim_prevent_price_update = fields.Boolean(
        string='Satış Fiyatı Güncellenmesin',
        config_parameter='odoougurlar.nebim_prevent_price_update',
        default=False,
        help='Açık olduğunda, mevcut ürünler Nebim senkronizasyonu ile güncellenirken Odoo\'daki satış fiyatı korunur ve Nebim fiyatı ile ezilmez.',
    )
    nebim_prevent_category_update = fields.Boolean(
        string='Kategori Güncellenmesin',
        config_parameter='odoougurlar.nebim_prevent_category_update',
        default=False,
        help='Açık olduğunda, mevcut ürünler Nebim senkronizasyonu ile güncellenirken Odoo\'daki ürün kategorisi korunur ve Nebim ürün grubu ile ezilmez.',
    )

    def _nebim_apply_cron(self, xmlid, active, interval_number, interval_type):
        """Cron'u ayara uygular; yalnız değişen alanlar yazılır.

        nextcall=now yalnız cron yeni açılıyorsa veya aralığı değiştiyse: önceden her Ayarlar
        kaydında açık tüm cron'lar hemen çalıştırılıyordu.
        """
        cron = self.env.ref(xmlid, raise_if_not_found=False)
        if not cron:
            return
        cron = cron.sudo()
        vals = {}
        if cron.active != bool(active):
            vals['active'] = bool(active)
        if cron.interval_number != interval_number:
            vals['interval_number'] = interval_number
        if cron.interval_type != interval_type:
            vals['interval_type'] = interval_type
        if active and vals:
            vals['nextcall'] = fields.Datetime.now()
        if vals:
            cron.write(vals)

    def set_values(self):
        """Ayarlar kaydedildiğinde cron'ları aktif/pasif yap ve aralığı güncelle."""
        super().set_values()
        self.nebim_apply_configured_crons()

    @api.model
    def nebim_apply_configured_crons(self):
        """Kayıtlı Nebim ayarlarını cron'lara uygular (Ayarlar kaydı ve modül upgrade'i sonrası).

        Upgrade'de XML <function> ile çağrıldığından public; yalnız yönetici / süper kullanıcı.
        """
        if not (self.env.is_superuser() or self.env.user.has_group('base.group_system')):
            return
        ICP = self.env['ir.config_parameter'].sudo()

        def flag(key, default='False'):
            return ICP.get_param(key, default) in ('True', 'true', '1')

        # Stok cron'u
        stock_on = flag('odoougurlar.nebim_stock_auto_sync')
        minutes = max(1, int(ICP.get_param('odoougurlar.nebim_stock_sync_interval', '60') or 60) // 60)
        self._nebim_apply_cron('odoougurlar.cron_stock_sync', stock_on, minutes, 'minutes')
        _logger.info("Stok cron %s, aralık: %d dk", 'aktif' if stock_on else 'pasif', minutes)

        # Ürün otomatik sync: tek cron. Eski "Günlük" cron (sync_products) aynı kuyruğu
        # silip veriyi ikinci kez çekiyordu: her zaman kapalı tutulur.
        auto_on = flag('odoougurlar.nebim_auto_sync')
        sync_mode = ICP.get_param('odoougurlar.nebim_sync_mode', 'daily') or 'daily'
        interval_type = 'hours' if sync_mode == 'hourly' else 'days'
        self._nebim_apply_cron('odoougurlar.cron_auto_product_sync', auto_on, 1, interval_type)
        self._nebim_apply_cron('odoougurlar.cron_product_sync', False, 1, 'days')
        _logger.info("Ürün sync cron %s, mod: %s", 'aktif' if auto_on else 'pasif', sync_mode)

        # İptal temizliği cron'u
        cancel_on = flag('odoougurlar.nebim_cancel_cleanup_auto')
        cancel_minutes = int(ICP.get_param('odoougurlar.nebim_cancel_cleanup_interval', '10') or 10)
        self._nebim_apply_cron('odoougurlar.cron_nebim_cancel_cleanup', cancel_on, cancel_minutes, 'minutes')
        _logger.info("İptal temizliği cron %s, aralık: %d dk", 'aktif' if cancel_on else 'pasif', cancel_minutes)

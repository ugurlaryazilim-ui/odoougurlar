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
    nebim_stock_sync_interval = fields.Selection([
        ('30', '30 Saniye'),
        ('45', '45 Saniye'),
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

    def set_values(self):
        """Ayarlar kaydedildiğinde cron'ları aktif/pasif yap ve aralığı güncelle."""
        super().set_values()

        # Stok cron'u aktifleştir/pasifleştir + aralık güncelle
        stock_cron = self.env.ref('odoougurlar.cron_stock_sync', raise_if_not_found=False)
        if stock_cron:
            interval_seconds = int(self.nebim_stock_sync_interval or '60')
            cron_vals = {'active': self.nebim_stock_auto_sync}
            if interval_seconds < 60:
                cron_vals['interval_number'] = interval_seconds
                cron_vals['interval_type'] = 'seconds'
            else:
                cron_vals['interval_number'] = interval_seconds // 60
                cron_vals['interval_type'] = 'minutes'
            if self.nebim_stock_auto_sync:
                cron_vals['nextcall'] = fields.Datetime.now()
            stock_cron.sudo().write(cron_vals)
            _logger.info(
                "Stok cron %s, aralık: %ds",
                'aktif' if self.nebim_stock_auto_sync else 'pasif',
                interval_seconds
            )

        # Ürün auto sync cron'u aktifleştir/pasifleştir
        product_cron = self.env.ref('odoougurlar.cron_auto_product_sync', raise_if_not_found=False)
        if product_cron:
            product_cron.sudo().write({'active': self.nebim_auto_sync})
            _logger.info("Ürün auto sync cron %s", 'aktif' if self.nebim_auto_sync else 'pasif')

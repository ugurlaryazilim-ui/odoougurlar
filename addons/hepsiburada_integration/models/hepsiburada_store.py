# -*- coding: utf-8 -*-
from odoo import models, fields, api
import requests
from requests.auth import HTTPBasicAuth
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class HepsiburadaStore(models.Model):
    _name = 'hepsiburada.store'
    _description = 'Hepsiburada Mağaza'

    name = fields.Char(string='Mağaza Adı', required=True, help="Odoo'daki tanımlayıcı adı")
    active = fields.Boolean(default=True, string='Aktif')

    merchant_id = fields.Char(string='Merchant ID', required=True, help="Hepsiburada Satıcı ID (GUID)")
    api_user = fields.Char(string='API Kullanıcı Adı', required=True)
    api_password = fields.Char(string='API Şifre', required=True)
    environment = fields.Selection([
        ('test', 'Test Ortamı'),
        ('prod', 'Canlı Ortam')
    ], string='Ortam', default='prod', required=True)

    auto_sync = fields.Boolean(string='Otomatik Senkronizasyon', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=15)
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)

    # ─── Sıralama ve Renk ───
    sequence = fields.Integer(string='Sıra', default=10)
    color = fields.Integer(string='Renk')

    # ─── Sipariş Ayarları ───
    auto_confirm = fields.Boolean(string='Siparişleri Otomatik Onayla', default=True)
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)
    order_day_range = fields.Integer(
        string='Sipariş Gün Aralığı',
        default=3,
        help='Son kaç güne ait siparişler çekilsin (performans için önemli)',
    )
    order_ref_type = fields.Selection([
        ('order_number', 'Hepsiburada Sipariş No'),
        ('package_id', 'Paket Numarası'),
    ], string='Sipariş Referans Tipi', default='order_number',
        help='Odoo siparişinin referans formatı',
    )

    # ─── Komisyon Ayarları ───
    process_commission = fields.Boolean(
        string='Komisyon Bilgisi İşlensin',
        default=True,
        help='Hepsiburada komisyon tutarlarını sipariş kaydına ekler',
    )

    # ─── İade Ayarları ───
    process_returns = fields.Boolean(
        string='İade İşle',
        default=False,
        help='İade edilen siparişleri de çekip işle',
    )
    return_day_range = fields.Integer(
        string='İade Gün Aralığı',
        default=3,
        help='Son kaç güne ait iadeler çekilsin',
    )

    # ─── Müşteri Ayarları ───
    customer_prefix = fields.Char(
        string='Müşteri Kodu Ön Ek',
        default='HB-',
        help='Hepsiburada müşterilerinin ref alanına eklenen ön ek',
    )
    micro_export_prefix = fields.Char(
        string='Mikro İ. Müşteri Kodu Ön Ek',
        default='MHB',
        help='Mikro ihracat siparişlerinde müşteri koduna eklenen ön ek',
    )
    skip_customer_email = fields.Boolean(
        string='Mail Adresi İşlenmesin',
        default=False,
        help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)',
    )

    # ─── Kargo Ayarları ───
    auto_send_cargo = fields.Boolean(
        string='Otomatik Kargo Kodu Gönder',
        default=True,
        help='Picking tamamlandığında kargo bilgisi Hepsiburada\'ya otomatik gönderilir',
    )
    cargo_include_order_number = fields.Boolean(
        string='Kargo Koduna Sipariş No Ekle',
        default=False,
        help='Kargo takip koduna sipariş numarasını ekler',
    )
    default_package_count = fields.Integer(
        string='Varsayılan Koli Sayısı',
        default=1,
    )
    default_desi = fields.Float(
        string='Varsayılan Desi',
        default=1.0,
        help='Hacimsel ağırlık',
    )

    # ─── Finansal İşlem Ayarları ───
    sync_financials = fields.Boolean(
        string='Finansal İşlemleri Senkronize Et',
        default=True,
        help='Finansal verileri çeker',
    )
    financial_day_range = fields.Integer(
        string='Finansal Gün Aralığı',
        default=15,
        help='Son kaç güne ait finansal işlemler çekilsin',
    )
    platform_fee_rate = fields.Float(
        string='Platform Hizmet Bedeli Oranı (%)',
        default=1.50,
        digits=(5, 2),
    )
    cargo_unit_price = fields.Float(
        string='Kargo Birim Fiyatı (desi)',
        default=95.00,
        digits=(10, 2),
    )
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    order_count = fields.Integer(compute='_compute_order_count', string='Siparişler')
    log_count = fields.Integer(compute='_compute_log_count', string='Loglar')

    def _compute_order_count(self):
        for store in self:
            store.order_count = self.env['sale.order'].search_count([('hb_store_id', '=', store.merchant_id)])

    def _compute_log_count(self):
        for store in self:
            store.log_count = self.env['hepsiburada.sync.log'].search_count([('store_id', '=', store.id)])

    def action_test_connection(self):
        """API bilgilerini test et"""
        self.ensure_one()
        domain = "oms-external-sit.hepsiburada.com" if self.environment == 'test' else "oms-external.hepsiburada.com"
        
        import copy, re
        
        # Remove all whitespace characters and invisible zero-width characters completely
        clean_merchant_id = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.merchant_id) if self.merchant_id else ''
        clean_user = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.api_user) if self.api_user else ''
        clean_pass = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.api_password) if self.api_password else ''
        
        url = f"https://{domain}/orders/merchantId/{clean_merchant_id}"
        
        try:
            from datetime import datetime, timedelta
            end_date = datetime.utcnow()
            begin_date = end_date - timedelta(days=1)
            
            params = {
                'limit': 1,
                'offset': 0,
                'beginDate': begin_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'endDate': end_date.strftime('%Y-%m-%dT%H:%M:%S')
            }

            # 2024 Güncellemesi: Username -> MerchantId, Password -> Servis Anahtarı, User-Agent -> Entegratör Adı
            response = requests.get(
                url,
                auth=HTTPBasicAuth(clean_merchant_id, clean_pass),
                params=params,
                headers={"Accept": "application/json", "User-Agent": clean_user},
                timeout=10
            )

            if response.status_code == 200 or response.status_code == 400:
                # 200 (Sipariş var) veya 400 (Tarih formatı eski vs, ama Auth geçti)
                if response.status_code == 400 and 'GetPackageLinesBadRequestError' not in response.text:
                    raise UserError(f"❌ Bağlantı Hatası: HTTP {response.status_code}\nDetay: {response.text}")
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Hepsiburada Bağlantı',
                        'message': f'✅ Bağlantı başarılı! Mağaza: {self.name} | Ortam: {self.environment}',
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.act_window_close'},
                    }
                }
            elif response.status_code == 401:
                raise UserError(f"❌ Bağlantı Hatası: Yetkisiz Giriş (401).\n(Kullanıcı Adı: '{clean_user}')\nLütfen şifreyi boşluksuz kopyaladığınıza emin olun.")
            else:
                raise UserError(f"❌ Bağlantı Hatası: HTTP {response.status_code}\nDetay: {response.text}")
        except requests.exceptions.RequestException as e:
            raise UserError(f"❌ Ağ hatası oluştu:\n{str(e)}")

    def action_sync_now(self):
        """Bu mağaza için manuel sipariş senkronizasyonu başlatır"""
        self.ensure_one()
        self.env['hepsiburada.order.sync']._sync_store_orders(self)

    def action_view_orders(self):
        return {
            'name': 'Hepsiburada Siparişleri',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('hb_store_id', '=', self.merchant_id)],
            'context': {'create': False}
        }

    def action_view_logs(self):
        return {
            'name': 'Senkronizasyon Logları',
            'type': 'ir.actions.act_window',
            'res_model': 'hepsiburada.sync.log',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id}
        }

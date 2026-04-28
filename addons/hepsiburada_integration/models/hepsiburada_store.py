import logging
import re
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HepsiburadaStore(models.Model):
    _name = 'hepsiburada.store'
    _description = 'Hepsiburada Mağaza'

    name = fields.Char(string='Mağaza Adı', required=True, help="Odoo'daki tanımlayıcı adı")
    active = fields.Boolean(default=True, string='Aktif')

    merchant_id = fields.Char(string='Merchant ID', required=True, groups='base.group_system', help="Hepsiburada Satıcı ID (GUID)")
    api_user = fields.Char(string='API Kullanıcı Adı', required=True, groups='base.group_system')
    api_password = fields.Char(string='API Şifre', required=True, groups='base.group_system')
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

    # ─── İlişkiler ───
    log_ids = fields.One2many('hepsiburada.sync.log', 'store_id', string='Loglar')

    order_count = fields.Integer(compute='_compute_order_count', string='Siparişler')
    log_count = fields.Integer(compute='_compute_log_count', string='Loglar')

    @api.depends()
    def _compute_order_count(self):
        data = self.env['sale.order'].sudo()._read_group(
            [('hb_store_id', 'in', [s.merchant_id for s in self])],
            groupby=['hb_store_id'], aggregates=['__count'],
        )
        counts = {merchant_id: count for merchant_id, count in data}
        for store in self:
            store.order_count = counts.get(store.merchant_id, 0)

    @api.depends('log_ids')
    def _compute_log_count(self):
        data = self.env['hepsiburada.sync.log'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.log_count = counts.get(store.id, 0)

    def _get_api_domain(self):
        """Ortama göre doğru domain'i döndür."""
        self.ensure_one()
        if self.environment == 'test':
            return "oms-external-sit.hepsiburada.com"
        return "oms-external.hepsiburada.com"

    def _get_clean_credentials(self):
        """API kimlik bilgilerini temizle ve döndür."""
        self.ensure_one()
        clean_merchant = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.merchant_id) if self.merchant_id else ''
        clean_user = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.api_user) if self.api_user else ''
        clean_pass = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', self.api_password) if self.api_password else ''
        return clean_merchant, clean_user, clean_pass

    def _get_session(self):
        """Connection pooling ile API session oluştur."""
        self.ensure_one()
        clean_merchant, clean_user, clean_pass = self._get_clean_credentials()
        session = requests.Session()
        session.auth = HTTPBasicAuth(clean_merchant, clean_pass)
        session.headers.update({
            "Accept": "application/json",
            "User-Agent": clean_user,
        })
        return session, clean_merchant

    def action_test_connection(self):
        """API bilgilerini test et"""
        self.ensure_one()
        domain = self._get_api_domain()
        clean_merchant, clean_user, clean_pass = self._get_clean_credentials()
        
        url = f"https://{domain}/orders/merchantId/{clean_merchant}"
        
        try:
            end_date = datetime.utcnow()
            begin_date = end_date - timedelta(days=1)
            
            params = {
                'limit': 1,
                'offset': 0,
                'beginDate': begin_date.strftime('%Y-%m-%dT%H:%M:%S'),
                'endDate': end_date.strftime('%Y-%m-%dT%H:%M:%S')
            }

            response = requests.get(
                url,
                auth=HTTPBasicAuth(clean_merchant, clean_pass),
                params=params,
                headers={"Accept": "application/json", "User-Agent": clean_user},
                timeout=10
            )

            if response.status_code == 200 or response.status_code == 400:
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

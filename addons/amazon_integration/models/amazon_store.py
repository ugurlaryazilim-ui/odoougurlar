import logging

import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AmazonStore(models.Model):
    _name = 'amazon.store'
    _description = 'Amazon Mağazası'

    name = fields.Char('Mağaza Adı', required=True)
    active = fields.Boolean('Aktif', default=True)
    company_id = fields.Many2one('res.company', string='Şirket', default=lambda self: self.env.company)

    # API Ayarları
    environment = fields.Selection([
        ('sandbox', 'Sandbox (Test)'),
        ('production', 'Production (Canlı)')
    ], string='Ortam', default='production', required=True)
    
    region = fields.Selection([
        ('eu', 'Avrupa (TR Dahil) - EU'),
        ('na', 'Kuzey Amerika - NA'),
        ('fe', 'Uzak Doğu - FE')
    ], string='SP-API Bölgesi', default='eu', required=True)
    
    marketplace_id = fields.Char('Marketplace ID', required=True, default='A33AVAJ2PDY3EV')
    
    # API Credentials — groups ile korunmuş
    spapi_app_id = fields.Char('SP-API App ID', groups='base.group_system', help='Developer Console üzerindeki App ID. OAuth yetkilendirmesi için gereklidir.')
    lwa_client_id = fields.Char('LWA Client ID', required=True, groups='base.group_system')
    lwa_client_secret = fields.Char('LWA Client Secret', required=True, groups='base.group_system')
    refresh_token = fields.Char('Refresh Token', groups='base.group_system')
    
    aws_access_key = fields.Char('AWS Access Key', groups='base.group_system',
                                 help="Zorunlu değil, sadece özel IAM Role olan eski uygulamalarda.")
    aws_secret_key = fields.Char('AWS Secret Key', groups='base.group_system')
    aws_role_arn = fields.Char('AWS Role ARN', groups='base.group_system')

    # Sipariş Ayarları
    order_day_range = fields.Integer('Geçmiş Sipariş Süresi (Gün)', default=14)
    order_ref_type = fields.Selection([
        ('amazon_order_id', 'Amazon Sipariş No'),
        ('seller_order_id', 'Satıcı Sipariş No')
    ], string='Sipariş Referans Tipi', default='amazon_order_id', required=True)
    
    default_warehouse_id = fields.Many2one('stock.warehouse', string='Varsayılan Depo', required=True)
    default_pricelist_id = fields.Many2one('product.pricelist', string='Fiyat Listesi')
    partner_sequence_id = fields.Many2one('ir.sequence', string='Müşteri Kodu Serisi')

    # Muhasebe & Kargo Ayarları
    cargo_company_id = fields.Many2one('res.partner', string='Varsayılan Kargo Firması')
    expense_account_id = fields.Many2one('account.account', string='Genel Gider Hesabı')
    commission_account_id = fields.Many2one('account.account', string='Komisyon Gider Hesabı')
    sales_journal_id = fields.Many2one('account.journal', string='Satış Yevmiyesi')
    
    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Senkronizasyon', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=15)
    last_sync = fields.Datetime('Son Senkronizasyon', readonly=True)

    def get_api_endpoint(self):
        """Çevre ve bölgeye göre doğru endpointi döner."""
        endpoints = {
            'eu': {
                'production': 'https://sellingpartnerapi-eu.amazon.com',
                'sandbox': 'https://sandbox.sellingpartnerapi-eu.amazon.com'
            },
            'na': {
                'production': 'https://sellingpartnerapi-na.amazon.com',
                'sandbox': 'https://sandbox.sellingpartnerapi-na.amazon.com'
            },
            'fe': {
                'production': 'https://sellingpartnerapi-fe.amazon.com',
                'sandbox': 'https://sandbox.sellingpartnerapi-fe.amazon.com'
            }
        }
        return endpoints.get(self.region, {}).get(self.environment)

    def action_authorize_amazon(self):
        """Kullanıcıyı Amazon'un OAuth onay sayfasına yönlendirir."""
        self.ensure_one()
        if not self.spapi_app_id:
            raise UserError(_("Amazon ile yetkilendirme yapabilmek için 'SP-API App ID' bilgisini girmelisiniz."))
        
        # Bölgeye göre yetkilendirme linkini belirle
        auth_urls = {
            'eu': 'https://sellercentral-europe.amazon.com',
            'na': 'https://sellercentral.amazon.com',
            'fe': 'https://sellercentraljapan.amazon.com' # veya sellercentral.amazon.co.jp, genel kullanım FE için japan'dır
        }
        base_url = auth_urls.get(self.region, 'https://sellercentral.amazon.com')
        
        # State parametresi olarak kendi mağaza ID'mizi veriyoruz ki Amazon bizi geri gönderdiğinde hangi mağaza için token aldığımızı bilelim.
        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}/apps/authorize/consent?application_id={self.spapi_app_id}&state={self.id}&version=beta",
            'target': 'self'
        }

    def generate_access_token(self):
        """LWA üzerinden refresh token ile yeni bir Access Token alır."""
        self.ensure_one()
        url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.lwa_client_id,
            "client_secret": self.lwa_client_secret
        }
        try:
            res = requests.post(url, data=payload, timeout=20)
            res.raise_for_status()
            data = res.json()
            return data.get("access_token")
        except Exception as e:
            raise UserError(_("Amazon Access Token alınamadı: %s") % str(e))

    def test_connection(self):
        self.ensure_one()
        try:
            token = self.generate_access_token()
            if not token:
                raise UserError(_("Token boş döndü."))
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Başarılı'),
                    'message': _('Amazon LWA bağlantısı başarıyla kuruldu ve Token alındı!'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(str(e))

    def write(self, vals):
        res = super().write(vals)
        if 'sync_interval' in vals or 'auto_sync' in vals:
            self._update_cron_interval()
        return res

    def _update_cron_interval(self):
        cron = self.env.ref('amazon_integration.ir_cron_amazon_sync_orders', raise_if_not_found=False)
        if not cron:
            return
        stores = self.search([('active', '=', True), ('auto_sync', '=', True)])
        if stores:
            min_interval = min(s.sync_interval for s in stores) or 1
            cron.sudo().write({
                'interval_number': max(min_interval, 1),
                'interval_type': 'minutes',
                'active': True,
            })
            _logger.info("Amazon cron aralığı %d dakikaya güncellendi", min_interval)
        else:
            cron.sudo().write({'active': False})
            _logger.info("Amazon aktif mağaza yok, cron devre dışı bırakıldı")

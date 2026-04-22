from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
import logging

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
    
    marketplace_id = fields.Char('Marketplace ID', required=True, default='A33AVAJ2PDY3EV') # TR Market ID
    
    lwa_client_id = fields.Char('LWA Client ID', required=True)
    lwa_client_secret = fields.Char('LWA Client Secret', required=True)
    refresh_token = fields.Char('Refresh Token', required=True)
    
    aws_access_key = fields.Char('AWS Access Key', help="Zorunlu değil, sadece özel IAM Role olan eski uygulamalarda.")
    aws_secret_key = fields.Char('AWS Secret Key')
    aws_role_arn = fields.Char('AWS Role ARN')

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
            raise UserError(f"Amazon Access Token alınamadı: {str(e)}")

    def test_connection(self):
        self.ensure_one()
        try:
            token = self.generate_access_token()
            if not token:
                raise UserError("Token boş döndü.")
                
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Başarılı',
                    'message': 'Amazon LWA bağlantısı başarıyla kuruldu ve Token alındı!',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(str(e))

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    amazon_store_id = fields.Many2one('amazon.store', string='Amazon Mağazası')

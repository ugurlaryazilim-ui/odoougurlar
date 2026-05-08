import json
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_CRON_XMLID = 'shopify_integration.ir_cron_shopify_sync_orders'


class ShopifyStore(models.Model):
    _name = 'shopify.store'
    _description = 'Shopify Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials
    shop_url = fields.Char(
        string='Mağaza URL', required=True,
        help="Örnek: monalureglobal.myshopify.com")
    access_token = fields.Char(
        string='Access Token', required=True,
        groups='base.group_system',
        help="Shopify Admin > Settings > Apps > Custom App > Access Token (shpat_...)")
    api_version = fields.Char(
        string='API Versiyonu', default='2024-04',
        help="Shopify API versiyonu (örn: 2024-04)")

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(
        string='Senkron Aralığı (dk)', default=5,
        help='Cron ile ne sıklıkta Shopify API çağrısı yapılacak')
    order_day_range = fields.Integer(
        string='Senkronizasyon Gün Aralığı', default=3,
        help="Geçmişe dönük kaç günlük sipariş çekilecek?")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)

    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(
        string='Siparişi Otomatik Onayla', default=True,
        help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    sync_only_paid = fields.Boolean(
        string='Sadece Ödenmiş Siparişleri Çek', default=True,
        help="financial_status=paid olan siparişleri çeker")

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(
        string='Müşteri Kodu Ön Ek', default='SHO-',
        help='Shopify müşterilerinin kodlarına eklenen ek')

    # ─── Depo Ayarları ───────────────────────────────────
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Sipariş Deposu',
        help='Shopify siparişlerinin düşeceği depo')

    # ─── Kargo Ayarları ──────────────────────────────────
    default_cargo_company = fields.Char(
        string='Varsayılan Kargo Firması', default='DHL')

    # ─── İlişkiler ───────────────────────────────────────
    order_ids = fields.One2many('shopify.order', 'store_id', string='Siparişler')

    # ─── Counts ──────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')

    @api.depends('order_ids')
    def _compute_order_count(self):
        data = self.env['shopify.order'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.order_count = counts.get(store.id, 0)

    def write(self, vals):
        res = super().write(vals)
        if 'sync_interval' in vals or 'auto_sync' in vals:
            self._sync_cron_settings()
        return res

    def _sync_cron_settings(self):
        """Store'daki sync_interval ve auto_sync değerlerini cron'a yansıt."""
        cron = self.env.ref(_CRON_XMLID, raise_if_not_found=False)
        if not cron:
            return
        stores = self.env['shopify.store'].search([('active', '=', True)])
        any_auto = any(s.auto_sync for s in stores)
        min_interval = min(
            (s.sync_interval for s in stores if s.auto_sync and s.sync_interval > 0),
            default=5)
        cron.sudo().write({
            'active': any_auto,
            'interval_number': max(min_interval, 1),
            'interval_type': 'minutes',
        })
        _logger.info("Shopify cron güncellendi: active=%s, interval=%d dk", any_auto, min_interval)

    def get_api(self):
        """ShopifyAPIClient objesini oluştur ve döndür."""
        self.ensure_one()
        if not self.shop_url or not self.access_token:
            raise UserError(_("Mağaza URL ve Access Token boş olamaz."))
        from .shopify_api import ShopifyAPIClient
        return ShopifyAPIClient(self)

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına."""
        self.ensure_one()
        try:
            api = self.get_api()
            result = api.get_orders_count()
            if result.get('success'):
                count = result.get('data', {}).get('count', 0)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Başarılı'),
                        'message': _('Bağlantı Başarılı! Toplam Sipariş: %d') % count,
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                raise UserError(_("Bağlantı Hatası: %s") % result.get('error'))
        except UserError:
            raise
        except Exception as e:
            raise UserError(_("Bağlantı Hatası: %s") % str(e))

    def action_sync_now(self):
        """Manuel sipariş senkronizasyonu."""
        self.ensure_one()
        sync_model = self.env['shopify.order'].sudo()
        res = sync_model.sync_orders_for_store(self)
        msg = (f"Sipariş Senkronizasyon Tamamlandı.\n"
               f"Yeni: {res.get('created', 0)}\n"
               f"Güncellenen: {res.get('updated', 0)}\n"
               f"Hata: {res.get('errors', 0)}")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Senkronizasyon Sonucu'),
                'message': msg,
                'sticky': False,
                'type': 'success' if res.get('errors') == 0 else 'warning',
            }
        }

    def action_view_orders(self):
        """Shopify sipariş listesini aç."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shopify Siparişleri'),
            'res_model': 'shopify.order',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id},
        }

import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class N11Store(models.Model):
    _name = 'n11.store'
    _description = 'N11 Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials
    n11_app_key = fields.Char(string='App Key', help="N11 API App Key", required=True, groups='base.group_system')
    n11_app_secret = fields.Char(string='App Secret', help="N11 API App Secret", required=True, groups='base.group_system')

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1, help='Bu değer cron ile senkronize çalışarak hangi sıklıkta N11 API\'ye çıkılacağını gösterir.')
    order_day_range = fields.Integer(string='Senkronizasyon Gün Aralığı', default=1, help="Geçmişe dönük kaç günlük sipariş çekilecek?")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)
    
    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişi Otomatik Onayla', default=True, help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(string='Müşteri Kodu Ön Ek', default='N11-', help='N11 müşterilerinin kodlarına eklenen ek')
    skip_customer_email = fields.Boolean(string='Mail Adresi İşlenmesin', default=False, help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)')

    # ─── İade Ayarları ───────────────────────────────────
    process_returns = fields.Boolean(string='İadeleri İşle', default=False, help='İade edilen siparişleri çekip listele')
    return_day_range = fields.Integer(string='İade Gün Aralığı', default=3)
    
    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(string='Otomatik Kargo Kodu Gönder', default=True, help='Depo Picking (Toplama) tamamlandığında kargo bilgisini n11 paneline otomatik yollar')
    n11_warehouse_id = fields.Integer(string='N11 Depo ID', help='N11 Kargo API Barkod oluşturmada kullanılacak Depo ID')
    cargo_include_order_number = fields.Boolean(string='Kargo Koduna Sipariş No Ekle', default=False)
    default_package_count = fields.Integer(string='Varsayılan Koli Sayısı', default=1)
    default_desi = fields.Float(string='Varsayılan Desi', default=1.0)
    
    # ─── Finansal İşlem Ayarları ─────────────────────────
    sync_financials = fields.Boolean(string='Finansal İşlemleri Senkronize Et', default=True)
    financial_day_range = fields.Integer(string='Finansal Gün Aralığı', default=15)
    platform_fee_rate = fields.Float(string='Platform Hizmet Bedeli Oranı (%)', default=1.47, digits=(5, 2))
    cargo_unit_price = fields.Float(string='Kargo Birim Fiyatı (desi)', default=110.39, digits=(10, 2))
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── İlişkiler ───────────────────────────────────────
    order_ids = fields.One2many('n11.order', 'store_id', string='Siparişler')
    settlement_ids = fields.One2many('n11.settlement', 'store_id', string='Finansal İşlemler')

    # ─── Counts ──────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_counts')

    @api.depends('order_ids')
    def _compute_order_count(self):
        data = self.env['n11.order'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.order_count = counts.get(store.id, 0)

    @api.depends('settlement_ids')
    def _compute_counts(self):
        data = self.env['n11.settlement'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.settlement_count = counts.get(store.id, 0)

    def get_api(self):
        """N11Api client objesini oluştur ve döndür."""
        self.ensure_one()
        if not self.n11_app_key or not self.n11_app_secret:
            raise UserError(_("N11 App Key ve App Secret boş olamaz."))
        from .n11_api import N11APIClient
        return N11APIClient(self)

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına."""
        self.ensure_one()
        try:
            api_client = self.get_api()
            
            start_date = datetime.now() - timedelta(days=1)
            end_date = datetime.now()
            
            result = api_client.get_shipment_packages(start_date=start_date, end_date=end_date, status="Created")
            if result.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Başarılı'),
                        'message': _('Bağlantı Başarılı. Sipariş listesi API yanıt verdi.'),
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                raise UserError(_("Bağlantı Hatası: %s" % result.get('error')))
        except Exception as e:
            raise UserError(_("Bağlantı Hatası: %s" % str(e)))

    def action_sync_now(self):
        self.ensure_one()
        sync_model = self.env['n11.order'].sudo()
        res = sync_model.sync_orders_for_store(self)
        msg = f"Sipariş Senkronizasyon Tamamlandı.\nYeni: {res.get('created', 0)}\nGüncellenen: {res.get('updated', 0)}\nHata: {res.get('errors', 0)}"
        
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

    def action_sync_financials(self):
        """N11 için finansal mutabakat servisi henüz desteklenmiyor."""
        self.ensure_one()
        raise UserError(_("N11 için finansal mutabakat servisi bu sürümde desteklenmemektedir. Lütfen paneli kullanınız."))

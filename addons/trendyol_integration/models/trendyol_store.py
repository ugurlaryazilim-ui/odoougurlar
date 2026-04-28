import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .trendyol_api import TrendyolAPI

_logger = logging.getLogger(__name__)


class TrendyolStore(models.Model):
    _name = 'trendyol.store'
    _description = 'Trendyol Mağaza'
    _order = 'sequence, name'
    _rec_name = 'name'

    # ─── Temel Bilgiler ──────────────────────────────────
    name = fields.Char(string='Mağaza Adı', required=True, help='Örn: Uğurlar Trendyol, Uğurlar Outlet')
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(string='Aktif', default=True)
    color = fields.Integer(string='Renk')

    # ─── API Bilgileri ───────────────────────────────────
    api_key = fields.Char(string='API Key', required=True, groups='base.group_system')
    api_secret = fields.Char(string='API Secret', required=True, groups='base.group_system')
    seller_id = fields.Char(string='Seller ID', required=True)
    environment = fields.Selection(
        [('prod', 'PROD (Canlı)'), ('stage', 'STAGE (Test)')],
        string='Ortam',
        default='prod',
        required=True,
    )

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Senkronizasyon', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=15)
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)

    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişleri Otomatik Onayla', default=True)
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)
    order_day_range = fields.Integer(
        string='Sipariş Gün Aralığı',
        default=15,
        help='Son kaç güne ait siparişler çekilsin (performans için önemli)',
    )
    order_ref_type = fields.Selection([
        ('order_number', 'Trendyol Sipariş No'),
        ('package_id', 'Paket ID'),
    ], string='Sipariş Referans Tipi', default='order_number',
        help='Odoo siparişinin referans formatı',
    )

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(
        string='Müşteri Kodu Ön Ek',
        default='TRNDY-',
        help='Trendyol müşterilerinin ref alanına eklenen ön ek',
    )
    micro_export_prefix = fields.Char(
        string='Mikro İ. Müşteri Kodu Ön Ek',
        default='MTY',
        help='Mikro ihracat siparişlerinde müşteri koduna eklenen ön ek',
    )
    skip_customer_email = fields.Boolean(
        string='Mail Adresi İşlenmesin',
        default=False,
        help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)',
    )

    # ─── Komisyon Ayarları ───────────────────────────────
    process_commission = fields.Boolean(
        string='Komisyon Bilgisi İşlensin',
        default=True,
        help='Trendyol komisyon tutarlarını sipariş kaydına ekler',
    )

    # ─── İade Ayarları ───────────────────────────────────
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

    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(
        string='Otomatik Kargo Kodu Gönder',
        default=True,
        help='Picking tamamlandığında kargo bilgisi Trendyol\'a otomatik gönderilir',
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

    # ─── Finansal İşlem Ayarları ─────────────────────────
    sync_financials = fields.Boolean(
        string='Finansal İşlemleri Senkronize Et',
        default=True,
        help='Settlements ve OtherFinancials API\'lerinden finansal verileri çeker',
    )
    financial_day_range = fields.Integer(
        string='Finansal Gün Aralığı',
        default=15,
        help='Son kaç güne ait finansal işlemler çekilsin (max 15 - API limiti)',
    )
    platform_fee_rate = fields.Float(
        string='Platform Hizmet Bedeli Oranı (%)',
        default=1.47,
        digits=(5, 2),
        help='Trendyol platform hizmet bedeli oranı (%). Sipariş net tutarına uygulanır.',
    )
    cargo_unit_price = fields.Float(
        string='Kargo Birim Fiyatı (desi)',
        default=110.39,
        digits=(10, 2),
        help='Platform kargoda 1 desi kargo birim fiyatı (TL). Trendyol panelinden kontrol edin.',
    )
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── İlişkiler ───────────────────────────────────────
    order_ids = fields.One2many('trendyol.order', 'store_id', string='Siparişler')
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    settlement_ids = fields.One2many('trendyol.settlement', 'store_id', string='Finansal İşlemler')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_settlement_count')

    _unique_seller = models.Constraint(
        'UNIQUE(seller_id)',
        'Bu Seller ID zaten kayıtlı!',
    )

    @api.depends('order_ids')
    def _compute_order_count(self):
        data = self.env['trendyol.order'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.order_count = counts.get(store.id, 0)

    @api.depends('settlement_ids')
    def _compute_settlement_count(self):
        data = self.env['trendyol.settlement'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.settlement_count = counts.get(store.id, 0)

    def get_api(self):
        """Bu mağaza için TrendyolAPI instance oluştur."""
        self.ensure_one()
        if not all([self.api_key, self.api_secret, self.seller_id]):
            raise UserError(_('Mağaza "%s" için API bilgileri eksik!') % self.name)
        return TrendyolAPI(self.api_key, self.api_secret, self.seller_id, is_prod=(self.environment == 'prod'))

    def action_test_connection(self):
        """Bağlantı testi butonu."""
        self.ensure_one()
        try:
            api = self.get_api()
            result = api.test_connection()

            if result['success']:
                data = result.get('data', {})
                total = data.get('totalElements', 0) if isinstance(data, dict) else 0
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Trendyol Bağlantı',
                        'message': f'✅ Bağlantı başarılı! Mağaza: {self.name} | '
                                   f'Toplam sipariş: {total} | Ortam: {self.environment}',
                        'type': 'success',
                        'sticky': False,
                    },
                }
            else:
                raise UserError(_('❌ Bağlantı hatası:\n\n%s') % result.get('error', 'Bilinmeyen hata'))
        except UserError:
            raise
        except Exception as e:
            raise UserError(_('❌ Bağlantı hatası:\n\n%s') % str(e))

    def action_sync_now(self):
        """Manuel senkronizasyon butonu — sadece bu mağaza."""
        self.ensure_one()
        TrendyolOrder = self.env['trendyol.order']
        result = TrendyolOrder.sync_orders_for_store(self)
        if result.get('error'):
            raise UserError(_('❌ Senkronizasyon hatası:\n\n%s') % result['error'])

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Trendyol Senkronizasyon',
                'message': f'✅ Senkronizasyon tamamlandı! Mağaza: {self.name} | '
                           f'Yeni: {result.get("created", 0)} | '
                           f'Güncellenen: {result.get("updated", 0)} | '
                           f'Hatalı: {result.get("errors", 0)}',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_view_orders(self):
        """Mağazanın siparişlerini görüntüle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} Siparişleri',
            'res_model': 'trendyol.order',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id},
        }

    def action_sync_financials(self):
        """Manuel finansal senkronizasyon butonu."""
        self.ensure_one()
        Settlement = self.env['trendyol.settlement']
        result = Settlement.sync_financials_for_store(self)
        if result.get('error_details'):
            raise UserError(_(
                '⚠️ Finansal senkronizasyon tamamlandı (hatalarla):\n\n'
                'Mağaza: %s\n'
                'Yeni kayıt: %s\n\n'
                'Hatalar:\n%s'
            ) % (self.name, result.get('created', 0), result.get('error_details', '')))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Trendyol Finansal',
                'message': f'✅ Finansal senkronizasyon tamamlandı! Mağaza: {self.name} | '
                           f'Yeni kayıt: {result.get("created", 0)}',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_view_settlements(self):
        """Mağazanın finansal işlemlerini görüntüle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} Finansal İşlemler',
            'res_model': 'trendyol.settlement',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id},
        }


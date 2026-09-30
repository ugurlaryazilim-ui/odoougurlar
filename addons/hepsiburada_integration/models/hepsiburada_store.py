import logging
import re
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

from odoo import models, fields, api, _
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
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1)
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

    # ─── Tek Sipariş Çekme ───
    fetch_order_number = fields.Char(
        string='Sipariş No',
        copy=False,
        help='Hepsiburada sipariş numarasını yazıp "Sipariş Çek" butonuna basarak tek siparişi çekebilirsiniz',
    )

    # ─── Komisyon Ayarları ───
    process_commission = fields.Boolean(
        string='Komisyon Bilgisi İşlensin',
        default=True,
        help='Hepsiburada komisyon tutar ve oranlarını sipariş satırlarına yazar',
    )

    # ─── İade Ayarları ───
    process_returns = fields.Boolean(
        string='İade İşle',
        default=False,
        help='Hepsiburada iade/değişim taleplerini çekip siparişe bağlar (HB tarafında aksiyon alınmaz)',
    )
    return_day_range = fields.Integer(
        string='İade Gün Aralığı',
        default=3,
        help='Son kaç günde açılan talepler çekilsin (açık talepler bu süre boyunca güncellenir)',
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
        help='Mikro ihracat (yurt dışı) siparişlerinde müşteri koduna eklenen ön ek',
    )
    skip_customer_email = fields.Boolean(
        string='Mail Adresi İşlenmesin',
        default=False,
        help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)',
    )

    # ─── Finansal İşlem Ayarları ───
    sync_financials = fields.Boolean(
        string='Finansal İşlemleri Senkronize Et',
        default=True,
        help='Hepsiburada muhasebe servisinden sipariş bazlı finansal kayıtları (satış, komisyon, kargo, '
             'hizmet bedeli) çeker ve siparişe net hakediş olarak yansıtır',
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
        help='Finansal kayıt oluşmadan önce tahmini net hesaplamasında kullanılır',
    )
    cargo_unit_price = fields.Float(
        string='Kargo Birim Fiyatı (desi)',
        default=95.00,
        digits=(10, 2),
        help='Tahmini net hesaplamasında: sipariş desisi × bu fiyat',
    )
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── İlişkiler ───
    log_ids = fields.One2many('hepsiburada.sync.log', 'store_id', string='Loglar')

    order_count = fields.Integer(compute='_compute_order_count', string='Siparişler')
    log_count = fields.Integer(compute='_compute_log_count', string='Log Sayısı')
    transaction_count = fields.Integer(compute='_compute_fin_counts', string='Finansal Kayıt')
    claim_count = fields.Integer(compute='_compute_fin_counts', string='İade Talebi')

    @api.depends()
    def _compute_order_count(self):
        # merchant_id yalnızca sistem yöneticisine açık → sayım sudo ile
        merchants = {s.id: s.sudo().merchant_id for s in self}
        data = self.env['sale.order'].sudo()._read_group(
            [('hb_store_id', 'in', [m for m in merchants.values() if m])],
            groupby=['hb_store_id'], aggregates=['__count'],
        )
        counts = {merchant_id: count for merchant_id, count in data}
        for store in self:
            store.order_count = counts.get(merchants[store.id], 0)

    @api.depends()
    def _compute_fin_counts(self):
        for model, fname in (('hepsiburada.transaction', 'transaction_count'), ('hepsiburada.claim', 'claim_count')):
            data = self.env[model].sudo()._read_group(
                [('store_id', 'in', self.ids)], groupby=['store_id'], aggregates=['__count'])
            counts = {store.id: count for store, count in data}
            for store in self:
                store[fname] = counts.get(store.id, 0)

    @api.depends('log_ids')
    def _compute_log_count(self):
        data = self.env['hepsiburada.sync.log'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.log_count = counts.get(store.id, 0)

    def write(self, vals):
        res = super().write(vals)
        if 'sync_interval' in vals or 'auto_sync' in vals:
            self._update_cron_interval()
        return res

    def _update_cron_interval(self):
        """Mağaza sync_interval alanına göre cron aralığını dinamik güncelle."""
        cron = self.env.ref('hepsiburada_integration.ir_cron_hepsiburada_order_sync', raise_if_not_found=False)
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
            _logger.info("Hepsiburada cron aralığı %d dakikaya güncellendi", min_interval)
        else:
            cron.sudo().write({'active': False})
            _logger.info("Hepsiburada aktif mağaza yok, cron devre dışı bırakıldı")

    def _get_api_domain(self):
        """Ortama göre doğru domain'i döndür."""
        self.ensure_one()
        if self.environment == 'test':
            return "oms-external-sit.hepsiburada.com"
        return "oms-external.hepsiburada.com"

    def _get_finance_domain(self):
        """Muhasebe servisi ayrı host'ta çalışır."""
        self.ensure_one()
        if self.environment == 'test':
            return "mpfinance-external-sit.hepsiburada.com"
        return "mpfinance-external.hepsiburada.com"

    def _get_clean_credentials(self):
        """API kimlik bilgilerini temizle ve döndür (alanlar yalnızca sistem yöneticisine açık → sudo)."""
        self.ensure_one()
        rec = self.sudo()
        clean_merchant = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', rec.merchant_id) if rec.merchant_id else ''
        clean_user = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', rec.api_user) if rec.api_user else ''
        clean_pass = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', rec.api_password) if rec.api_password else ''
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
        self.env['hepsiburada.order.sync']._sync_store_orders(self.sudo())
        return self._notify('Senkronizasyon', 'Sipariş senkronizasyonu tamamlandı. Detay için loglara bakın.', 'success')

    def action_view_orders(self):
        self.ensure_one()
        return {
            'name': 'Hepsiburada Siparişleri',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('hb_store_id', '=', self.sudo().merchant_id)],
            'context': {'create': False}
        }

    def action_view_transactions(self):
        self.ensure_one()
        return {
            'name': 'Finansal Kayıtlar',
            'type': 'ir.actions.act_window',
            'res_model': 'hepsiburada.transaction',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
        }

    def action_view_claims(self):
        self.ensure_one()
        return {
            'name': 'İade Talepleri',
            'type': 'ir.actions.act_window',
            'res_model': 'hepsiburada.claim',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
        }

    def action_sync_financials(self):
        self.ensure_one()
        if not self.sync_financials:
            raise UserError(_('Bu mağazada "Finansal İşlemleri Senkronize Et" kapalı.'))
        res = self.env['hepsiburada.transaction']._sync_store(self)
        return self._notify(
            'Finans Senkronizasyonu',
            f"✅ {res.get('created', 0)} yeni, {res.get('updated', 0)} güncellenen kayıt"
            + (' (bazı istekler başarısız, loglara bakın)' if res.get('failed') else ''),
            'warning' if res.get('failed') else 'success')

    def action_sync_claims(self):
        self.ensure_one()
        if not self.process_returns:
            raise UserError(_('Bu mağazada "İade İşle" kapalı.'))
        res = self.env['hepsiburada.claim']._sync_store(self)
        return self._notify(
            'İade Talepleri',
            f"✅ {res.get('created', 0)} yeni, {res.get('updated', 0)} güncellenen talep"
            + (' (istek başarısız, loglara bakın)' if res.get('failed') else ''),
            'warning' if res.get('failed') else 'success')

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Hepsiburada - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

    # ─── CRON ───

    @api.model
    def cron_sync_financials(self):
        for store in self.search([('active', '=', True), ('sync_financials', '=', True)]):
            try:
                with self.env.cr.savepoint():
                    self.env['hepsiburada.transaction']._sync_store(store)
            except Exception as e:
                _logger.exception("HB finans senkron hatası [%s]: %s", store.name, e)

    @api.model
    def cron_sync_claims(self):
        for store in self.search([('active', '=', True), ('process_returns', '=', True)]):
            try:
                with self.env.cr.savepoint():
                    self.env['hepsiburada.claim']._sync_store(store)
            except Exception as e:
                _logger.exception("HB iade talebi senkron hatası [%s]: %s", store.name, e)

    def action_view_logs(self):
        return {
            'name': 'Senkronizasyon Logları',
            'type': 'ir.actions.act_window',
            'res_model': 'hepsiburada.sync.log',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id}
        }

    def action_fetch_single_order(self):
        """Sipariş numarası ile tek sipariş çek."""
        self.ensure_one()
        order_number = self.fetch_order_number
        if not order_number:
            raise UserError(_('Lütfen bir sipariş numarası girin!'))

        order_number = order_number.strip()
        _logger.info("HB Tek sipariş çekiliyor: %s (mağaza: %s)", order_number, self.name)

        clean_merchant, clean_user, clean_pass = self._get_clean_credentials()
        if not clean_merchant or not clean_user or not clean_pass:
            raise UserError(_('Mağaza API ayarları eksik!'))

        session, _unused = self._get_session()
        domain = self._get_api_domain()

        # Sipariş detay API
        url = f"https://{domain}/orders/merchantId/{clean_merchant}/orderNumber/{order_number}"

        try:
            response = session.get(url, timeout=30)
        except Exception as e:
            raise UserError(_('❌ API bağlantı hatası:\n\n%s') % str(e))

        if response.status_code != 200:
            raise UserError(
                _('❌ Sipariş bulunamadı: %s\n\nHTTP %s: %s') % (
                    order_number, response.status_code, response.text[:500]
                )
            )

        data = response.json()
        if not data:
            raise UserError(_('❌ Sipariş bulunamadı: %s\n\nAPI boş yanıt döndü.') % order_number)

        # Tek siparişi işle
        OrderSync = self.env['hepsiburada.order.sync']
        packages = [data] if isinstance(data, dict) else data

        try:
            processed, created, errors, msgs = OrderSync._process_orders(packages, self.sudo(), skip_date_filter=True)
        except Exception as e:
            raise UserError(_('❌ Sipariş işleme hatası:\n\n%s') % str(e))

        # Input temizle
        self.fetch_order_number = False

        if errors > 0:
            raise UserError(
                _('⚠️ Sipariş çekildi ama hatalar var:\n\n%s') % '\n'.join(msgs)
            )

        msg = f'✅ Sipariş başarıyla çekildi! ({order_number})'
        if created > 0:
            msg += ' | Yeni oluşturuldu'
        else:
            msg += ' | Zaten mevcut'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hepsiburada Sipariş Çek',
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

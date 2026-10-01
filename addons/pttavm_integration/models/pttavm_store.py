import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PttavmStore(models.Model):
    _name = 'pttavm.store'
    _description = 'Pttavm Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials (Integration)
    api_key = fields.Char(string='Api-Key', required=True, groups='base.group_system', help="PTTAVM Entegrasyon API Key")
    access_token = fields.Char(string='Access-Token', required=True, groups='base.group_system', help="PTTAVM Entegrasyon Access Token")

    # API Credentials (Shipment)
    cargo_username = fields.Char(string='Kargo Username', groups='base.group_system', help="Kargo/Barkod işlemleri için Basic Auth Kullanıcı Adı")
    cargo_password = fields.Char(string='Kargo Password', groups='base.group_system', help="Kargo/Barkod işlemleri için Basic Auth Şifresi")

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1, help='Bu değer cron ile senkronize çalışarak hangi sıklıkta Pttavm API\'ye çıkılacağını gösterir.')
    order_day_range = fields.Integer(string='Senkronizasyon Gün Aralığı', default=30, help="Geçmişe dönük kaç günlük sipariş çekilecek (en fazla 40)? Bu aralıktaki siparişlerin durum değişiklikleri de her senkronda güncellenir.")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)
    last_sync_error = fields.Text(string='Son Senkron Hatası', readonly=True)
    last_sync_error_date = fields.Datetime(string='Hata Zamanı', readonly=True)

    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişi Otomatik Onayla', default=True, help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(string='Müşteri Kodu Ön Ek', default='PTT-', help='Pttavm müşterilerinin kodlarına eklenen ek')
    skip_customer_email = fields.Boolean(string='Mail Adresi İşlenmesin', default=False, help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)')

    # ─── İade Ayarları (PttAVM API'sinde iade servisi yok — kullanılmıyor) ─────
    process_returns = fields.Boolean(string='İadeleri İşle', default=False, help='İade edilen siparişleri çekip listele')
    return_day_range = fields.Integer(string='İade Gün Aralığı', default=3)

    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(string='Otomatik Kargo Barkodu Oluştur', default=True, help='Depo transferi doğrulandığında PttAVM Kargo API\'den barkod talep edilir; oluşan barkod siparişe yazılır.')
    pttavm_warehouse_id = fields.Integer(string='PttAVM Depo ID', help='PttAVM Kargo API Barkod oluşturmada kullanılacak Depo ID')
    cargo_include_order_number = fields.Boolean(string='Kargo Koduna Sipariş No Ekle', default=False)
    default_package_count = fields.Integer(string='Varsayılan Koli Sayısı', default=1)
    default_desi = fields.Float(string='Varsayılan Desi', default=1.0)

    # ─── Fatura ──────────────────────────────────────────
    auto_send_invoice = fields.Boolean(
        string="Faturayı PttAVM'ye Gönder", default=False,
        help="Açıksa, Odoo siparişinin Nebim faturası oluştuğunda e-arşiv/e-fatura linki PttAVM'ye "
             "gönderilir (Nebim usp_Invoice_EArchieveURL ile alınır).")

    # ─── Finansal İşlem Ayarları (PttAVM API'sinde finans servisi yok — kullanılmıyor) ─────
    sync_financials = fields.Boolean(string='Finansal İşlemleri Senkronize Et', default=True)
    financial_day_range = fields.Integer(string='Finansal Gün Aralığı', default=15)
    platform_fee_rate = fields.Float(string='Platform Hizmet Bedeli Oranı (%)', default=1.47, digits=(5, 2))
    cargo_unit_price = fields.Float(string='Kargo Birim Fiyatı (desi)', default=110.39, digits=(10, 2))
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── İlişkiler ───────────────────────────────────────
    order_ids = fields.One2many('pttavm.order', 'store_id', string='Siparişler')
    settlement_ids = fields.One2many('pttavm.settlement', 'store_id', string='Finansal İşlemler')

    # ─── Tek Sipariş Çek ─────────────────────────────────
    fetch_order_number = fields.Char(
        string='Sipariş No', copy=False,
        help='PttAVM sipariş numarası girin (ör: PTTEM-2PR6Q3F2V-270626)'
    )

    # ─── Counts ──────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_counts')
    error_order_count = fields.Integer(string='Hatalı Sipariş', compute='_compute_order_count')

    @api.depends('order_ids')
    def _compute_order_count(self):
        Order = self.env['pttavm.order'].sudo()
        counts = dict(Order._read_group(
            [('store_id', 'in', self.ids)], groupby=['store_id'], aggregates=['__count']))
        errors = dict(Order._read_group(
            [('store_id', 'in', self.ids), ('error_message', '!=', False)],
            groupby=['store_id'], aggregates=['__count']))
        for store in self:
            store.order_count = counts.get(store, 0)
            store.error_order_count = errors.get(store, 0)

    @api.depends('settlement_ids')
    def _compute_counts(self):
        data = self.env['pttavm.settlement'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.settlement_count = counts.get(store.id, 0)

    def _write_sync_state(self, last_sync=None, error=False):
        """Senkron durumunu ayrı cursor ile yazar: cron işlemi mağaza satırına yazmaz, böylece
        aynı anda formdan kaydedilen mağazayla çakışıp (serialization) geri alınmaz."""
        self.ensure_one()
        try:
            with self.pool.cursor() as cr2:
                # Ana işlem satırı kilitlediyse sonsuza dek beklemesin
                cr2.execute("SET LOCAL lock_timeout = '5s'")
                if last_sync:
                    cr2.execute("UPDATE pttavm_store SET last_sync = %s WHERE id = %s", (last_sync, self.id))
                if error:
                    cr2.execute("UPDATE pttavm_store SET last_sync_error = %s, last_sync_error_date = %s WHERE id = %s",
                                (str(error)[:2000], fields.Datetime.now(), self.id))
                elif last_sync:
                    cr2.execute("UPDATE pttavm_store SET last_sync_error = NULL, last_sync_error_date = NULL "
                                "WHERE id = %s AND last_sync_error IS NOT NULL", (self.id,))
            self.invalidate_recordset(['last_sync', 'last_sync_error', 'last_sync_error_date'])
        except Exception as e:
            _logger.warning("PttAVM mağaza senkron durumu yazılamadı (%s): %s", self.name, e)

    def write(self, vals):
        res = super().write(vals)
        if 'sync_interval' in vals or 'auto_sync' in vals:
            self._update_cron_interval()
        return res

    def _update_cron_interval(self):
        """Mağaza sync_interval alanına göre cron aralığını dinamik güncelle."""
        cron = self.env.ref('pttavm_integration.ir_cron_pttavm_sync_orders', raise_if_not_found=False)
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
            _logger.info("PTTAVM cron aralığı %d dakikaya güncellendi", min_interval)
        else:
            cron.sudo().write({'active': False})
            _logger.info("PTTAVM aktif mağaza yok, cron devre dışı bırakıldı")

    def get_api(self):
        """PttavmApi client objesini oluştur ve döndür."""
        self.ensure_one()
        if not self.api_key or not self.access_token:
            raise UserError(_("Api Key ve Access Token boş olamaz."))
        from .pttavm_api import PttavmAPIClient
        return PttavmAPIClient(self)

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına."""
        self.ensure_one()
        try:
            api_client = self.get_api()
            # Sorgu tarihleri TR saatiyle gider (senkronla aynı)
            now_tr = self.env['pttavm.order']._now_turkey()
            result = api_client.get_orders(start_date=now_tr - timedelta(days=3),
                                           end_date=now_tr + timedelta(minutes=5))
        except Exception as e:
            raise UserError(_("Bağlantı Hatası: %s", e))
        if not result.get('success'):
            raise UserError(_("Bağlantı Hatası: %s", result.get('error')))
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

    def action_sync_now(self):
        self.ensure_one()
        sync_model = self.env['pttavm.order'].sudo()
        res = sync_model.sync_orders_for_store(self)
        if res.get('busy'):
            raise UserError(_("Bu mağazada senkronizasyon şu anda zaten çalışıyor. Birkaç dakika sonra tekrar deneyin."))
        if res.get('error'):
            raise UserError(_("PttAVM sipariş çekme hatası:\n\n%s", res['error']))
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

    def action_view_orders(self):
        self.ensure_one()
        domain = [('store_id', '=', self.id)]
        if self.env.context.get('only_errors'):
            domain.append(('error_message', '!=', False))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pttavm Siparişleri'),
            'res_model': 'pttavm.order',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def action_fetch_single_order(self):
        """Sipariş numarası ile tek sipariş çek."""
        self.ensure_one()
        order_number = self.fetch_order_number
        if not order_number:
            raise UserError(_('Lütfen bir sipariş numarası girin!'))

        order_number = order_number.strip()
        _logger.info("PttAVM Tek sipariş çekiliyor: %s (mağaza: %s)", order_number, self.name)

        result = self.get_api().get_order_detail(order_number)
        if not result.get('success'):
            raise UserError(_('❌ PttAVM API hatası:\n\n%s', result.get('error', 'Bilinmeyen hata')))

        data = result.get('data')
        order_list = [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
        order_list = [o for o in order_list if isinstance(o, dict) and o.get('siparisNo')]
        if not order_list:
            raise UserError(_('❌ Sipariş bulunamadı: %s\n\nBu numarada sipariş PttAVM\'de mevcut değil.', order_number))

        PttavmOrder = self.env['pttavm.order']
        actions = []
        for order_json in order_list:
            try:
                with self.env.cr.savepoint():
                    actions.append(PttavmOrder._sync_order_json(self, order_json))
            except Exception as e:
                raise UserError(_('❌ Sipariş işleme hatası:\n\n%s', e))

        # Sipariş çekildikten sonra input temizle
        self.fetch_order_number = False

        rec = PttavmOrder.search([('store_id', '=', self.id), ('order_number', '=', order_list[0]['siparisNo'])], limit=1)
        msg = f'✅ Sipariş başarıyla çekildi! ({order_number})'
        msg += ' | Yeni oluşturuldu' if 'created' in actions else ' | Güncellendi'
        if rec.error_message:
            msg += f'\n⚠️ {rec.error_message}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'PttAVM Sipariş Çek',
                'message': msg,
                'type': 'warning' if rec.error_message else 'success',
                'sticky': bool(rec.error_message),
            },
        }

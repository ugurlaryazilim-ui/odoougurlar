import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_CRON_XMLID = 'idefix_integration.ir_cron_idefix_sync_orders'


class IdefixStore(models.Model):
    _name = 'idefix.store'
    _description = 'Idefix Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials
    client_id = fields.Char(string='API Key', required=True, groups='base.group_system', help="Idefix panelinden alınır")
    client_secret = fields.Char(string='API Secret', required=True, groups='base.group_system')
    vendor_id = fields.Char(string='Satıcı ID (Vendor ID)', required=True, groups='base.group_system')

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1, help='Bu değer cron ile senkronize çalışarak hangi sıklıkta Idefix API\'ye çıkılacağını gösterir.')
    order_day_range = fields.Integer(string='Senkronizasyon Gün Aralığı', default=1, help="Geçmişe dönük kaç günlük sipariş çekilecek? Daha eski açık sevkiyatlar (son 30 gün) shipment ID ile ayrıca yoklanır.")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)
    last_sync_error = fields.Text(string='Son Senkron Hatası', readonly=True)
    last_sync_error_date = fields.Datetime(string='Hata Zamanı', readonly=True)

    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişi Otomatik Onayla', default=True, help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True,
                                 help="Idefix'te iptal edilen / tedarik edilemeyen / bölünen sevkiyatın Odoo siparişi iptal edilir "
                                      "(sevk edilmiş veya faturası kesilmiş siparişlere dokunulmaz).")
    auto_send_picking = fields.Boolean(
        string="Idefix'e 'Hazırlanıyor' Bildir", default=False,
        help="Açıksa Odoo'da onaylanan siparişin sevkiyatı Idefix'te 'picking' statüsüne alınır. "
             "Bu statüden sonra müşteri siparişi iptal edemez.")
    auto_send_invoice = fields.Boolean(
        string="Faturayı Idefix'e Gönder", default=False,
        help="Açıksa, Odoo siparişinin Nebim faturası oluştuğunda sevkiyat Idefix'te 'Faturalandı' yapılır "
             "(fatura no ile) ve e-arşiv/e-fatura linki gönderilir (Nebim usp_Invoice_EArchieveURL).")

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(string='Müşteri Kodu Ön Ek', default='IDE-', help='Idefix müşterilerinin kodlarına eklenen ek')
    skip_customer_email = fields.Boolean(string='Mail Adresi İşlenmesin', default=False, help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)')

    # ─── İade Ayarları ───────────────────────────────────
    process_returns = fields.Boolean(string='İadeleri İşle', default=False,
                                     help="İade taleplerini (claim-list) 30 dakikada bir çekip 'İade Talepleri' menüsünde listeler")
    return_day_range = fields.Integer(string='İade Gün Aralığı', default=30,
                                      help='Geçmişe dönük kaç günlük iade talebi çekilecek')
    last_refund_sync = fields.Datetime(string='Son İade Senkronu', readonly=True)

    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(
        string='Kendi Kargo Anlaşmamla Takip No Gönder', default=False,
        help="YALNIZCA satıcı kargo anlaşmasıyla gönderimde açın. Transfer doğrulanınca Odoo'daki takip "
             "numarası Idefix'e bildirilir; sipariş platform kargo anlaşmasından çıkar ve 'Kargoda' olur. "
             "Platform anlaşmalı kargoda (cargoKey etiketi) kapalı kalmalıdır.")
    cargo_tracking_url = fields.Char(
        string='Kargo Takip Linki Şablonu',
        help="Takip numarası gönderiminde zorunlu. {code} yerine takip numarası yazılır. "
             "Örn: https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={code}")
    send_box_info = fields.Boolean(string='Desi / Koli Bilgisi Gönder', default=False,
                                   help="Transfer doğrulanınca varsayılan koli sayısı ve desi Idefix'e bildirilir (update-box-info)")
    default_package_count = fields.Integer(string='Varsayılan Koli Sayısı', default=1)
    default_desi = fields.Float(string='Varsayılan Desi', default=1.0)

    # ─── Finansal İşlem Ayarları ─────────────────────────
    sync_financials = fields.Boolean(string='Finansal Özeti Oluştur', default=True,
                                     help="Sevkiyat başına komisyon / hakediş kaydı üretilir (Idefix'te ayrı finans servisi yoktur; "
                                          "tutarlar sevkiyat listesinden alınır)")
    financial_day_range = fields.Integer(string='Finansal Gün Aralığı', default=60,
                                         help="'Finansal Özeti Yenile' son kaç günün sevkiyatlarını yeniden hesaplar")
    last_financial_sync = fields.Datetime(string='Son Finansal Yenileme', readonly=True)

    # ─── İlişkiler ───────────────────────────────────────
    order_ids = fields.One2many('idefix.order', 'store_id', string='Siparişler')
    settlement_ids = fields.One2many('idefix.settlement', 'store_id', string='Finansal İşlemler')
    refund_ids = fields.One2many('idefix.refund', 'store_id', string='İadeler')

    # ─── Tek Sipariş Çek ─────────────────────────────────
    fetch_order_number = fields.Char(string='Sipariş No', copy=False, help='Idefix sipariş numarası (IDE...)')

    # ─── Counts ──────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    error_order_count = fields.Integer(string='Hatalı Sipariş', compute='_compute_order_count')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_counts')
    refund_count = fields.Integer(string='İade', compute='_compute_counts')

    @api.depends('order_ids')
    def _compute_order_count(self):
        Order = self.env['idefix.order'].sudo()
        counts = dict(Order._read_group(
            [('store_id', 'in', self.ids)], groupby=['store_id'], aggregates=['__count']))
        errors = dict(Order._read_group(
            [('store_id', 'in', self.ids), ('error_message', '!=', False)],
            groupby=['store_id'], aggregates=['__count']))
        for store in self:
            store.order_count = counts.get(store, 0)
            store.error_order_count = errors.get(store, 0)

    @api.depends('settlement_ids', 'refund_ids')
    def _compute_counts(self):
        settlements = dict(self.env['idefix.settlement'].sudo()._read_group(
            [('store_id', 'in', self.ids)], groupby=['store_id'], aggregates=['__count']))
        refunds = dict(self.env['idefix.refund'].sudo()._read_group(
            [('store_id', 'in', self.ids)], groupby=['store_id'], aggregates=['__count']))
        for store in self:
            store.settlement_count = settlements.get(store, 0)
            store.refund_count = refunds.get(store, 0)

    def _separate_write(self, query, params):
        """Mağaza satırına ayrı cursor ile yazar: cron işlemi satırı kilitlemez, formdan aynı anda
        kaydedilen mağazayla çakışıp (serialization) geri alınmaz."""
        self.ensure_one()
        try:
            with self.pool.cursor() as cr2:
                cr2.execute("SET LOCAL lock_timeout = '5s'")
                cr2.execute(query, params)
            return True
        except Exception as e:
            _logger.warning("Idefix mağaza durumu yazılamadı (%s): %s", self.name, e)
            return False

    def _write_sync_state(self, last_sync=None, error=False):
        self.ensure_one()
        if last_sync:
            self._separate_write("UPDATE idefix_store SET last_sync = %s WHERE id = %s", (last_sync, self.id))
        if error:
            self._separate_write(
                "UPDATE idefix_store SET last_sync_error = %s, last_sync_error_date = %s WHERE id = %s",
                (str(error)[:2000], fields.Datetime.now(), self.id))
        elif last_sync:
            self._separate_write("UPDATE idefix_store SET last_sync_error = NULL, last_sync_error_date = NULL "
                                 "WHERE id = %s AND last_sync_error IS NOT NULL", (self.id,))
        self.invalidate_recordset(['last_sync', 'last_sync_error', 'last_sync_error_date'])

    def _write_refund_sync(self, when):
        self.ensure_one()
        self._separate_write("UPDATE idefix_store SET last_refund_sync = %s WHERE id = %s", (when, self.id))
        self.invalidate_recordset(['last_refund_sync'])

    def write(self, vals):
        res = super().write(vals)
        if 'sync_interval' in vals or 'auto_sync' in vals or 'active' in vals:
            self._sync_cron_settings()
        return res

    def _sync_cron_settings(self):
        """Store'daki sync_interval ve auto_sync değerlerini cron'a yansıt."""
        cron = self.env.ref(_CRON_XMLID, raise_if_not_found=False)
        if not cron:
            return
        stores = self.env['idefix.store'].search([('active', '=', True)])
        any_auto = any(s.auto_sync for s in stores)
        min_interval = min((s.sync_interval for s in stores if s.auto_sync and s.sync_interval > 0), default=5)
        cron.sudo().write({
            'active': any_auto,
            'interval_number': max(min_interval, 1),
            'interval_type': 'minutes',
        })
        _logger.info("Idefix cron güncellendi: active=%s, interval=%d dk", any_auto, min_interval)

    def get_api(self):
        """IdefixAPIClient objesini oluştur ve döndür (API bilgileri sudo ile okunur)."""
        self.ensure_one()
        store = self.sudo()
        if not store.client_id or not store.client_secret or not store.vendor_id:
            raise UserError(_("API Key, API Secret ve Satıcı ID boş olamaz."))
        from .idefix_api import IdefixAPIClient
        return IdefixAPIClient(store)

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına."""
        self.ensure_one()
        result = self.get_api().get_orders(page=1, limit=1)
        if not result.get('success'):
            raise UserError(_("Bağlantı Hatası: %s", result.get('error')))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('Bağlantı Başarılı. Sevkiyat listesi API yanıt verdi.'),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_sync_now(self):
        self.ensure_one()
        res = self.env['idefix.order'].sudo().sync_orders_for_store(self)
        if res.get('busy'):
            raise UserError(_("Bu mağazada senkronizasyon şu anda zaten çalışıyor. Birkaç dakika sonra tekrar deneyin."))
        if res.get('error'):
            raise UserError(_("Idefix sipariş çekme hatası:\n\n%s", res['error']))
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

    def action_fetch_single_order(self):
        """Sipariş numarası ile siparişin tüm sevkiyatlarını çek."""
        self.ensure_one()
        order_number = (self.fetch_order_number or '').strip()
        if not order_number:
            raise UserError(_('Lütfen bir sipariş numarası girin!'))
        Order = self.env['idefix.order']
        api = self.get_api()
        orders, error = Order._fetch_orders(api, order_number=order_number)
        if error:
            raise UserError(_('❌ Idefix API hatası:\n\n%s', error))
        orders = [o for o in orders if str(o.get('orderNumber') or '') == order_number]
        if not orders:
            raise UserError(_('❌ Sipariş bulunamadı: %s', order_number))
        lines = []
        warn = False
        for order_json in orders:
            action = Order._sync_order_json(self, order_json, api)
            rec = Order.search([('store_id', '=', self.id), ('order_id', '=', str(order_json.get('id')))], limit=1)
            line = f"{rec.order_id}: {'Yeni' if action == 'created' else 'Güncellendi'} ({rec.order_status_display})"
            if rec.error_message:
                line += f' ⚠️ {rec.error_message}'
                warn = True
            lines.append(line)
        self.fetch_order_number = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Idefix Sipariş Çek — {order_number}',
                'message': '\n'.join(lines),
                'type': 'warning' if warn else 'success',
                'sticky': warn,
            },
        }

    def action_sync_financials(self):
        """Son N günün sevkiyatlarından finansal özeti yeniden üretir (Idefix API çağrısı yapılmaz)."""
        self.ensure_one()
        if not self.sync_financials:
            raise UserError(_("'Finansal Özeti Oluştur' kapalı."))
        since = fields.Datetime.now() - timedelta(days=self.financial_day_range or 60)
        count = self.env['idefix.order']._rebuild_settlements(self, since)
        self.sudo().write({'last_financial_sync': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Finansal Özet'),
                'message': f"{count} sevkiyatın finans kaydı güncellendi.",
                'sticky': False,
                'type': 'success',
            }
        }

    def action_sync_refunds(self):
        self.ensure_one()
        created, updated, error = self.env['idefix.refund']._sync_refunds(self)
        if error:
            raise UserError(_("Idefix iade listesi alınamadı:\n\n%s", error))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('İade Senkronizasyonu'),
                'message': f"Yeni: {created}\nGüncellenen: {updated}",
                'sticky': False,
                'type': 'success',
            }
        }

    def action_view_orders(self):
        self.ensure_one()
        domain = [('store_id', '=', self.id)]
        if self.env.context.get('only_errors'):
            domain.append(('error_message', '!=', False))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Idefix Siparişleri'),
            'res_model': 'idefix.order',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def action_view_settlements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('idefix_integration.action_idefix_settlements')
        action['domain'] = [('store_id', '=', self.id)]
        return action

    def action_view_refunds(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('idefix_integration.action_idefix_refunds')
        action['domain'] = [('store_id', '=', self.id)]
        return action

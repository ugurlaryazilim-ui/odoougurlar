import json
import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_CRON_XMLID = 'pazarama_integration.ir_cron_pazarama_sync_orders'

class PazaramaStore(models.Model):
    _name = 'pazarama.store'
    _description = 'Pazarama Mağaza Ayarları'
    _order = 'sequence, name'

    name = fields.Char(string='Mağaza Adı', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(default=True)

    # API Credentials
    client_id = fields.Char(string='Client ID (API Key)', required=True, groups='base.group_system', help="isortagim.pazarama.com panelinden alınır")
    client_secret = fields.Char(string='Client Secret (API Secret)', required=True, groups='base.group_system',
                                help="Pazarama API anahtarı en fazla 365 gün geçerlidir; süresi dolunca panelden yenisi üretilmelidir.")

    # Tokens
    access_token = fields.Char(string='Access Token', readonly=True, groups='base.group_system')
    token_expiry = fields.Datetime(string='Token Bitiş Tarihi', readonly=True, groups='base.group_system')

    # ─── Senkronizasyon Ayarları ─────────────────────────
    auto_sync = fields.Boolean(string='Otomatik Sipariş Senkronizasyonu', default=True)
    sync_interval = fields.Integer(string='Senkron Aralığı (dk)', default=1, help='Bu değer cron ile senkronize çalışarak hangi sıklıkta Pazarama API\'ye çıkılacağını gösterir.')
    order_day_range = fields.Integer(string='Senkronizasyon Gün Aralığı', default=1, help="Geçmişe dönük kaç günlük sipariş çekilecek (en fazla 29)? Daha eski açık siparişler sipariş numarasıyla ayrıca yoklanır.")
    last_sync = fields.Datetime(string='Son Senkronizasyon', readonly=True)
    last_sync_error = fields.Text(string='Son Senkron Hatası', readonly=True)
    last_sync_error_date = fields.Datetime(string='Hata Zamanı', readonly=True)

    # ─── Sipariş Ayarları ────────────────────────────────
    auto_confirm = fields.Boolean(string='Siparişi Otomatik Onayla', default=True, help="Odoo'ya düşen siparişler otomatik onaylanır ve Nebim sürecini tetikler.")
    auto_cancel = fields.Boolean(string='İptalleri Otomatik İptal Et', default=True)
    auto_accept_orders = fields.Boolean(
        string="Siparişi Pazarama'da Otomatik Onayla", default=False,
        help="Açıksa Odoo'da onaylanan siparişin 'Sipariş Alındı' kalemleri Pazarama'da 'Hazırlanıyor' "
             "statüsüne alınır (kargo işlemi için zorunlu adım). Kapalıysa onay panelden yapılır.")
    auto_send_invoice = fields.Boolean(
        string="Faturayı Pazarama'ya Gönder", default=False,
        help="Açıksa, Odoo siparişinin Nebim faturası oluştuğunda e-arşiv/e-fatura linki Pazarama'ya "
             "gönderilir (Nebim usp_Invoice_EArchieveURL ile alınır).")

    # ─── Müşteri Ayarları ────────────────────────────────
    customer_prefix = fields.Char(string='Müşteri Kodu Ön Ek', default='PZR-', help='Pazarama müşterilerinin kodlarına eklenen ek')
    skip_customer_email = fields.Boolean(string='Mail Adresi İşlenmesin', default=False, help='Müşteri oluşturulurken e-posta adresi kaydedilmez (KVKK)')

    # ─── İade Ayarları (kullanılmıyor) ───────────────────
    process_returns = fields.Boolean(string='İadeleri İşle', default=False, help='İade edilen siparişleri çekip listele')
    return_day_range = fields.Integer(string='İade Gün Aralığı', default=3)

    # ─── Kargo Ayarları ──────────────────────────────────
    auto_send_cargo = fields.Boolean(string='Otomatik Kargo Kodu Gönder', default=True, help='Depo Picking (Toplama) tamamlandığında kargo bilgisini pazarama paneline otomatik yollar')
    cargo_include_order_number = fields.Boolean(string='Kargo Koduna Sipariş No Ekle', default=False)
    default_package_count = fields.Integer(string='Varsayılan Koli Sayısı', default=1)
    default_desi = fields.Float(string='Varsayılan Desi', default=1.0)

    # ─── Finansal İşlem Ayarları ─────────────────────────
    sync_financials = fields.Boolean(string='Finansal İşlemleri Senkronize Et', default=True)
    financial_day_range = fields.Integer(string='Finansal Gün Aralığı', default=15)
    platform_fee_rate = fields.Float(string='Platform Hizmet Bedeli Oranı (%)', default=1.47, digits=(5, 2))
    cargo_unit_price = fields.Float(string='Kargo Birim Fiyatı (desi)', default=110.39, digits=(10, 2))
    last_financial_sync = fields.Datetime(string='Son Finansal Senkron', readonly=True)

    # ─── İlişkiler ───────────────────────────────────────────
    order_ids = fields.One2many('pazarama.order', 'store_id', string='Siparişler')
    settlement_ids = fields.One2many('pazarama.settlement', 'store_id', string='Finansal İşlemler')

    # ─── Tek Sipariş Çek ─────────────────────────────────
    fetch_order_number = fields.Char(string='Sipariş No', copy=False,
                                     help='Pazarama sipariş numarası (son 6 ay)')

    # ─── Counts ──────────────────────────────────────────────
    order_count = fields.Integer(string='Sipariş Sayısı', compute='_compute_order_count')
    error_order_count = fields.Integer(string='Hatalı Sipariş', compute='_compute_order_count')
    settlement_count = fields.Integer(string='Finansal Kayıt', compute='_compute_counts')

    @api.depends('order_ids')
    def _compute_order_count(self):
        Order = self.env['pazarama.order'].sudo()
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
        data = self.env['pazarama.settlement'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.settlement_count = counts.get(store.id, 0)

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
            _logger.warning("Pazarama mağaza durumu yazılamadı (%s): %s", self.name, e)
            return False

    def _save_token(self, token, expiry):
        self._separate_write("UPDATE pazarama_store SET access_token = %s, token_expiry = %s WHERE id = %s",
                             (token or None, expiry or None, self.id))

    def _write_sync_state(self, last_sync=None, error=False):
        self.ensure_one()
        if last_sync:
            self._separate_write("UPDATE pazarama_store SET last_sync = %s WHERE id = %s", (last_sync, self.id))
        if error:
            self._separate_write(
                "UPDATE pazarama_store SET last_sync_error = %s, last_sync_error_date = %s WHERE id = %s",
                (str(error)[:2000], fields.Datetime.now(), self.id))
        elif last_sync:
            self._separate_write("UPDATE pazarama_store SET last_sync_error = NULL, last_sync_error_date = NULL "
                                 "WHERE id = %s AND last_sync_error IS NOT NULL", (self.id,))
        self.invalidate_recordset(['last_sync', 'last_sync_error', 'last_sync_error_date'])

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
        # En küçük interval'i al (birden fazla store olabilir)
        stores = self.env['pazarama.store'].search([('active', '=', True)])
        any_auto = any(s.auto_sync for s in stores)
        min_interval = min((s.sync_interval for s in stores if s.auto_sync and s.sync_interval > 0), default=5)
        cron.sudo().write({
            'active': any_auto,
            'interval_number': max(min_interval, 1),
            'interval_type': 'minutes',
        })
        _logger.info("Pazarama cron güncellendi: active=%s, interval=%d dk", any_auto, min_interval)

    def get_api(self):
        """PazaramaApi client objesini oluştur ve döndür."""
        self.ensure_one()
        if not self.client_id or not self.client_secret:
            raise UserError(_("Client ID ve Client Secret boş olamaz."))
        from .pazarama_api import PazaramaAPIClient
        return PazaramaAPIClient(self)

    def action_test_connection(self):
        """Bağlantıyı ve yetkilendirmeyi sına (yeni token alınır)."""
        self.ensure_one()
        api = self.get_api()
        token = api.get_access_token(force=True)  # önbellekteki token yerine gerçekten yeni token iste
        if not token:
            raise UserError(_("Bağlantı Hatası: %s", getattr(api, 'token_error', None) or
                              'Token alınamadı, bilgilerinizi kontrol edin.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('Bağlantı Başarılı. Token Alındı.'),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_sync_now(self):
        self.ensure_one()
        sync_model = self.env['pazarama.order'].sudo()
        res = sync_model.sync_orders_for_store(self)
        if res.get('busy'):
            raise UserError(_("Bu mağazada senkronizasyon şu anda zaten çalışıyor. Birkaç dakika sonra tekrar deneyin."))
        if res.get('error'):
            raise UserError(_("Pazarama sipariş çekme hatası:\n\n%s", res['error']))
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
            'name': _('Pazarama Siparişleri'),
            'res_model': 'pazarama.order',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def action_fetch_single_order(self):
        """Sipariş numarası ile tek sipariş çek (son 6 ay)."""
        self.ensure_one()
        order_number = (self.fetch_order_number or '').strip()
        if not order_number:
            raise UserError(_('Lütfen bir sipariş numarası girin!'))
        Order = self.env['pazarama.order']
        api = self.get_api()
        order_json, error = None, None
        # Sipariş tarihi bilinmediği için son 6 ay 1'er aylık pencerelerle aranır
        end = Order._now_turkey() + timedelta(minutes=5)
        for _i in range(6):
            start = end - timedelta(days=29)
            orders, error = Order._fetch_orders(api, start, end, order_number=order_number)
            if error:
                break
            match = [o for o in orders if str(o.get('orderNumber') or '') == order_number]
            if match:
                order_json = match[0]
                break
            end = start
        if error:
            raise UserError(_('❌ Pazarama API hatası:\n\n%s', error))
        if not order_json:
            raise UserError(_('❌ Sipariş bulunamadı: %s (son 6 ay)', order_number))
        action = Order._sync_order_json(self, order_json, api)
        self.fetch_order_number = False
        rec = Order.search([('store_id', '=', self.id), ('order_id', '=', str(order_json.get('orderId')))], limit=1)
        msg = f"✅ Sipariş çekildi ({order_number}) | {'Yeni oluşturuldu' if action == 'created' else 'Güncellendi'}"
        if rec.error_message:
            msg += f'\n⚠️ {rec.error_message}'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pazarama Sipariş Çek',
                'message': msg,
                'type': 'warning' if rec.error_message else 'success',
                'sticky': bool(rec.error_message),
            },
        }

    def action_sync_financials(self):
        """Muhasebe ve Finans Servisi (paymentAgreement) → pazarama.settlement."""
        self.ensure_one()
        Order = self.env['pazarama.order']
        api = self.get_api()
        res = self._fetch_payment_agreements(api)

        body = res.get('data') or {}
        payload = body.get('data') if isinstance(body, dict) else None
        data_list = (payload or {}).get('transactionList') if isinstance(payload, dict) else payload
        if not data_list or not isinstance(data_list, list):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Finansal Senkronizasyon'),
                    'message': 'Belirtilen tarih aralığında finansal işlem bulunamadı.',
                    'sticky': False,
                    'type': 'info',
                }
            }

        created = 0
        updated = 0
        settlement_model = self.env['pazarama.settlement']
        for item in data_list:
            if not isinstance(item, dict):
                continue
            trx_id = str(item.get('trxId') or item.get('id') or '')
            order_id = str(item.get('orderId') or '')  # pratikte sipariş numarası
            if not trx_id and not order_id:
                continue
            domain = [('store_id', '=', self.id), ('trx_id', '=', trx_id), ('order_id', '=', order_id)]
            existing = settlement_model.search(domain, limit=1)
            vals = {
                'store_id': self.id,
                'order_id': order_id,
                'trx_id': trx_id,
                'trx_code': str(item.get('trxCode') or ''),
                'amount': item.get('amount') or 0.0,
                'installment_number': item.get('installmentNumber') or 1,
                'commission_amount': item.get('commissionAmount') or 0.0,
                'coupon_discount': item.get('couponDiscount') or 0.0,
                'allowance_amount': item.get('allowanceAmount') or 0.0,
                'status': item.get('status') or 'Bilinmiyor',
                'transaction_date': Order._parse_tr_datetime(item.get('transactionDate')),
                'transferred_date': Order._parse_tr_datetime(item.get('transferredDate')),
                'raw_data': json.dumps(item, ensure_ascii=False),
            }
            if existing:
                existing.write(vals)
                updated += 1
            else:
                settlement_model.create(vals)
                created += 1

        self.sudo().write({'last_financial_sync': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Finansal Senkronizasyon Başarılı'),
                'message': f"Yeni İşlem: {created}\nGüncellenen: {updated}",
                'sticky': False,
                'type': 'success',
            }
        }

    @api.model
    def _finance_bodies(self, start_day, end_day, today):
        """paymentAgreement için denenecek gövdeler (ad, gövde). Doküman yalnız tek örnek veriyor
        (başlangıç "T03:00:00.000", bitiş geçmiş günün "T23:59:59.999"); Pazarama hatalı biçimde
        yalnızca "İşleminiz şu anda gerçekleştirilemiyor" dediği için biçimler sırayla denenir."""
        def d(day, suffix):
            return day.strftime('%Y-%m-%d') + suffix

        def body(start, end, allowance=False):
            return {
                'startDate': None if allowance else start,
                'endDate': None if allowance else end,
                'allowanceStartDate': start if allowance else None,
                'allowanceEndDate': end if allowance else None,
                'orderId': None,
            }
        return [
            ('doc', body(d(start_day, 'T03:00:00.000'), d(end_day, 'T23:59:59.999'))),
            ('doc_today', body(d(start_day, 'T03:00:00.000'), d(today, 'T23:59:59.999'))),
            ('midnight', body(d(start_day, 'T00:00:00.000'), d(end_day, 'T23:59:59.999'))),
            ('utc_z', body(d(start_day, 'T00:00:00.000Z'), d(end_day, 'T23:59:59.999Z'))),
            ('date_only', body(d(start_day, ''), d(end_day, ''))),
            ('allowance', body(d(start_day, 'T03:00:00.000'), d(end_day, 'T23:59:59.999'), allowance=True)),
        ]

    def _fetch_payment_agreements(self, api):
        """Biçimleri sırayla dener; çalışan biçim hatırlanır ve sonraki seferde önce o denenir.
        Hiçbiri çalışmazsa tüm denemelerin Pazarama yanıtıyla hata verilir."""
        today = self.env['pazarama.order']._now_turkey().date()
        end_day = today - timedelta(days=1)  # bitiş: dün (dokümandaki örnek gibi geçmiş gün)
        start_day = end_day - timedelta(days=max((self.financial_day_range or 15) - 1, 0))
        params = self.env['ir.config_parameter'].sudo()
        known = params.get_param('pazarama_integration.finance_body_variant')
        variants = self._finance_bodies(start_day, end_day, today)
        variants.sort(key=lambda v: v[0] != known)
        errors = []
        for name, body in variants:
            res = api.get_payment_agreements(body)
            if res.get('success'):
                if name != known:
                    params.set_param('pazarama_integration.finance_body_variant', name)
                    _logger.info("Pazarama finans: çalışan istek biçimi '%s': %s", name, json.dumps(body))
                return res
            errors.append(f"{name}: {res.get('error')}")
            _logger.warning("Pazarama finans denemesi '%s' başarısız: %s | gövde: %s",
                            name, res.get('error'), json.dumps(body))
            if res.get('status') in (401, 403):
                break  # yetki sorunu — diğer biçimleri denemenin anlamı yok
        raise UserError(_("Finansal veriler çekilemedi (Pazarama tüm istek biçimlerini reddetti):\n\n%s\n\n"
                          "Bu durumda sorun Pazarama tarafında olabilir; istek gövdeleri sunucu logunda "
                          "'Pazarama finans denemesi' satırlarında. Pazarama desteğine iletilebilir.",
                          '\n'.join(errors)))

    def action_finance_diagnostics(self):
        """Finans servisinin hangi sorgularda çalıştığını ölçer (gün gün, ödeme tarihi, sipariş no).
        Sonuç ekranda ve logda ('Pazarama finans teşhis') görünür; hiçbir kayıt yazılmaz."""
        self.ensure_one()
        api = self.get_api()
        today = self.env['pazarama.order']._now_turkey().date()

        def day_body(day, allowance=False):
            start, end = day.strftime('%Y-%m-%dT03:00:00.000'), day.strftime('%Y-%m-%dT23:59:59.999')
            return {'startDate': None if allowance else start, 'endDate': None if allowance else end,
                    'allowanceStartDate': start if allowance else None,
                    'allowanceEndDate': end if allowance else None, 'orderId': None}

        probes = []
        for i in range(1, 8):
            day = today - timedelta(days=i)
            probes.append((f"işlem tarihi {day:%d.%m}", day_body(day)))
        for i in range(1, 8):
            day = today - timedelta(days=i)
            probes.append((f"ödeme tarihi {day:%d.%m}", day_body(day, allowance=True)))
        old_day = today.replace(year=today.year - 3)
        probes.append((f"çok eski gün {old_day:%d.%m.%Y}", day_body(old_day)))
        delivered = self.env['pazarama.order'].search(
            [('store_id', '=', self.id), ('order_status', '=', 11)], order='order_date desc', limit=2)
        for order in delivered:
            if order.order_number.isdigit():
                probes.append((f"sipariş no {order.order_number}",
                               {'startDate': None, 'endDate': None, 'allowanceStartDate': None,
                                'allowanceEndDate': None, 'orderId': int(order.order_number)}))

        lines = []
        for name, body in probes:
            res = api.get_payment_agreements(body)
            if res.get('success'):
                payload = (res.get('data') or {}).get('data') if isinstance(res.get('data'), dict) else None
                count = len(payload.get('transactionList') or []) if isinstance(payload, dict) else 0
                line = f"✅ {name}: başarılı, {count} işlem"
            else:
                line = f"❌ {name}: {res.get('error')}"
            lines.append(line)
            _logger.info("Pazarama finans teşhis | %s | gövde: %s", line, json.dumps(body))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Pazarama Finans Teşhisi'),
                'message': '\n'.join(lines),
                'sticky': True,
                'type': 'info',
            }
        }

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pazarama Finansal İşlemler'),
            'res_model': 'pazarama.settlement',
            'view_mode': 'list,form',
            'domain': [('store_id', '=', self.id)],
        }

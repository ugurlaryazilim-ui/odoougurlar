import json
import logging
from collections import Counter
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from .idefix_order import (
    IDEFIX_CANCEL_STATUSES, IDEFIX_FINAL_STATUSES, IDEFIX_OPEN_STATUSES, is_inactive_item_status,
)

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

_SYNC_LOCK_NS = 7471032          # mağaza başına senkron kilidi (pg advisory lock ad alanı)
_PAGE_SIZE = 50
_MAX_PAGES = 100
_STALE_CHECK_AFTER = timedelta(minutes=30)  # açık sevkiyatlar en geç bu aralıkla yoklanır
_STALE_CHECK_LIMIT = 200                    # her turda yoklanacak en fazla sevkiyat
_STALE_BATCH = 50                           # 'ids' parametresiyle tek istekte sorgulanan sevkiyat
_STALE_LOOKBACK = timedelta(days=30)        # bundan eski açık sevkiyatlar otomatik yoklanmaz
_AUTO_CANCEL_LOOKBACK = timedelta(days=30)  # bundan eski siparişler otomatik iptal edilmez
_PICKING_RETRY_AFTER = timedelta(minutes=30)


def _digits(value):
    return ''.join(filter(str.isdigit, str(value or '')))


def _money(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _flag(value):
    """isCommercial / isLikeCommercial: kurumsalda "1", bireyselde " " (boş) döner."""
    return str(value or '').strip().lower() in ('1', 'true')


class IdefixOrderSync(models.Model):
    _inherit = 'idefix.order'

    @api.model
    def sync_orders_from_idefix(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['idefix.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("Idefix %s senkronizasyon hatası: %s", store.name, e)
                store._write_sync_state(error=str(e))

    @api.model
    def _now_turkey(self):
        return datetime.now(pytz.UTC).astimezone(IST).replace(tzinfo=None)

    @api.model
    def _to_turkey(self, dt_utc):
        return pytz.UTC.localize(dt_utc).astimezone(IST).replace(tzinfo=None)

    @api.model
    def _parse_datetime(self, value):
        """Idefix tarihleri ISO 8601 (+03:00) gelir — Odoo UTC (naive) saklar.
        Saat dilimi yoksa Türkiye saati kabul edilir."""
        if not value:
            return False
        text = str(value).strip().replace(' ', 'T', 1)
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            try:
                dt = datetime.strptime(text[:19], '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                _logger.warning("Idefix tarih parse hatası: %s", value)
                return False
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        return dt.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def sync_orders_for_store(self, store):
        """Son N gündeki sevkiyatları çeker (yeni + güncellenen), ardından daha eski açık
        sevkiyatları shipment ID ile toplu yoklar (iptal / bölünme / kargo / teslim durumları için)."""
        # Aynı mağazada tek senkron (cron sürerken manuel senkron aynı siparişleri paralel açmasın)
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (_SYNC_LOCK_NS, store.id))
        if not self.env.cr.fetchone()[0]:
            _logger.info("Idefix senkronizasyon [%s] atlandı: başka bir senkron çalışıyor", store.name)
            return {'created': 0, 'updated': 0, 'errors': 0, 'busy': True}

        api_client = store.get_api()
        now = fields.Datetime.now()
        day_range = max(store.order_day_range or 1, 1)
        # Idefix API Türkiye saatinde çalışır — sorgu tarihleri Türkiye saatiyle gider
        now_turkey = self._now_turkey()
        start_date = now_turkey - timedelta(days=day_range)
        end_date = now_turkey + timedelta(minutes=5)
        window_start = now - timedelta(days=day_range)

        _logger.info("Idefix [%s] sipariş çekme (TR saati): %s → %s", store.name, start_date, end_date)

        counters = Counter()
        orders, error = self._fetch_orders(api_client, start_date=start_date, end_date=end_date)
        counters['received'] = len(orders)
        for order_json in orders:
            # Eski sipariş koruması: pencereden eski YENİ sevkiyat açılmaz (mevcutlar güncellenir)
            order_date = self._parse_datetime(order_json.get('orderDate') or order_json.get('createdAt'))
            if order_date and order_date < window_start and not self.search_count([
                    ('store_id', '=', store.id), ('order_id', '=', str(order_json.get('id') or ''))]):
                continue
            self._safe_sync(store, api_client, order_json, counters)

        if not error:
            try:
                self._refresh_stale_orders(store, api_client, counters, window_start)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("Idefix açık sevkiyat yoklama hatası [%s]: %s", store.name, e)

        # ── Veritabanındaki iptal siparişleri tara (tarih filtresi dışındakiler dahil) ──
        try:
            with self.env.cr.savepoint():
                cancel_count = self._cancel_pending_orders(store)
                if cancel_count:
                    _logger.info("Idefix — %d sipariş Odoo'da iptal edildi", cancel_count)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.exception("Idefix iptal tarama hatası: %s", e)

        try:
            self._send_pending_invoices(store, api_client)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.exception("Idefix fatura gönderim hatası [%s]: %s", store.name, e)

        try:
            self.env['idefix.refund']._sync_refunds_if_due(store, api_client)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.exception("Idefix iade senkron hatası [%s]: %s", store.name, e)

        if error:
            _logger.error("Idefix Sipariş Çekme Hatası [%s]: %s", store.name, error)
        store._write_sync_state(last_sync=None if error else now, error=error)
        _logger.info("Idefix [%s] senkron tamamlandı — %d sevkiyat alındı, Yeni: %d, Güncellenen: %d, Hata: %d%s",
                     store.name, counters['received'], counters['created'], counters['updated'], counters['errors'],
                     ' (eksik: API hatası)' if error else '')
        return {'created': counters['created'], 'updated': counters['updated'], 'errors': counters['errors'],
                'error': error}

    @api.model
    def _fetch_orders(self, api_client, start_date=None, end_date=None, ids=None, order_number=None):
        """(sevkiyatlar, hata) döner — tüm sayfalar."""
        orders = []
        for page in range(1, _MAX_PAGES + 1):
            res = api_client.get_orders(start_date=start_date, end_date=end_date, page=page, limit=_PAGE_SIZE,
                                        ids=ids, order_number=order_number)
            if not res.get('success'):
                return orders, res.get('error') or 'Bilinmeyen hata'
            body = res.get('data')
            items = body.get('items') if isinstance(body, dict) else body
            items = [o for o in (items or []) if isinstance(o, dict)] if isinstance(items, list) else []
            orders.extend(items)
            page_count = _int(body.get('pageCount')) if isinstance(body, dict) else 0
            if len(items) < _PAGE_SIZE or (page_count and page >= page_count):
                break
        return orders, False

    @api.private
    def _safe_sync(self, store, api_client, order_json, counters):
        try:
            with self.env.cr.savepoint():
                action = self._sync_order_json(store, order_json, api_client)
            counters[action] += 1
        except Exception as e:
            counters['errors'] += 1
            self.env.invalidate_all(flush=False)
            _logger.exception("Idefix Sipariş İşleme Hatası (%s): %s", order_json.get('orderNumber'), e)

    @api.private
    def _refresh_stale_orders(self, store, api_client, counters, window_start):
        """Sorgu penceresinden eski açık sevkiyatları shipment ID ile (toplu) yoklar."""
        now = fields.Datetime.now()
        orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'not in', list(IDEFIX_FINAL_STATUSES)),
            ('order_date', '<', window_start),
            ('order_date', '>=', now - _STALE_LOOKBACK),
            '|', ('last_checked', '=', False), ('last_checked', '<', now - _STALE_CHECK_AFTER),
        ], limit=_STALE_CHECK_LIMIT, order='last_checked asc nulls first, id')
        for start in range(0, len(orders), _STALE_BATCH):
            batch = orders[start:start + _STALE_BATCH]
            found, error = self._fetch_orders(api_client, ids=batch.mapped('order_id'))
            if error:
                _logger.warning("Idefix açık sevkiyatlar yoklanamadı: %s", error)
                break
            by_id = {str(o.get('id')): o for o in found}
            for order in batch:
                order_json = by_id.get(order.order_id)
                if order_json:
                    self._safe_sync(store, api_client, order_json, counters)
                else:
                    order.last_checked = now

    # ─── JSON → idefix.order ─────────────────────────────────

    @api.private
    def _sync_order_json(self, store, order_json, api_client=None):
        """Tek sevkiyatı işler. 'created' / 'updated' / 'unchanged' / 'skipped' döner."""
        order_id = str(order_json.get('id') or '').strip()
        if not order_id:
            return 'skipped'

        rec = self.search([('store_id', '=', store.id), ('order_id', '=', order_id)], limit=1)
        action = None
        if not rec:
            rec = self.create(self._order_header_vals(store, order_json))
            action = 'created'

        changed = rec._apply_order_json(order_json)
        if changed or action == 'created' or not rec.sale_order_id:
            rec._reconcile_sale_order(store)
        rec._auto_picking(store, api_client)
        if changed or action == 'created':
            rec._upsert_settlement()
        rec.last_checked = fields.Datetime.now()
        if action:
            return action
        return 'updated' if changed else 'unchanged'

    @api.model
    def _order_header_vals(self, store, order_json):
        ship = order_json.get('shippingAddress') or {}
        bill = order_json.get('invoiceAddress') or {}
        is_commercial = _flag(bill.get('isCommercial')) or _flag(bill.get('isLikeCommercial'))
        return {
            'store_id': store.id,
            'order_id': str(order_json.get('id')),
            'order_number': str(order_json.get('orderNumber') or ''),
            'order_date': self._parse_datetime(order_json.get('orderDate') or order_json.get('createdAt'))
                          or fields.Datetime.now(),
            'payment_type': 1,
            'invoice_type': 2 if is_commercial else 1,
            'customer_id': str(order_json.get('customerId') or ''),
            'customer_name': order_json.get('customerContactName') or bill.get('fullName') or '',
            'customer_email': order_json.get('customerContactMail') or '',
            'shipment_address': json.dumps(ship, ensure_ascii=False),
            'billing_address': json.dumps(bill, ensure_ascii=False),
            'shipping_city': ship.get('city') or '',
            'shipping_district': ship.get('county') or '',
            'tax_office': (bill.get('taxOffice') or '').strip() if is_commercial else '',
            'currency': 'TRY',
        }

    @api.model
    def _line_vals(self, item, order_json):
        vat_rate = _int(item.get('vatRate'), 0)
        incl = _money(item.get('discountedTotalPrice'))
        tracking = self._order_tracking(order_json)
        return {
            'item_id': str(item.get('id') or ''),
            'product_id': str(item.get('erpId') or ''),
            'product_name': item.get('productName') or '',
            'product_code': item.get('barcode') or item.get('merchantSku') or '',
            'quantity': 1,  # list servisi her kalemi 1 adet döndürür
            'sale_price_tax_included': incl,
            'sale_price': round(incl / (1 + vat_rate / 100.0), 2) if vat_rate else incl,
            'gross_price': _money(item.get('price')),
            'vat_rate': vat_rate,
            'platform_discount': _money(item.get('platformDiscount')),
            'vendor_discount': _money(item.get('vendorDiscount')),
            'commission_amount': _money(item.get('commissionAmount')),
            'earning_amount': _money(item.get('earningAmount')),
            'vendor_amount': _money(item.get('vendorAmount')),
            'status': item.get('itemStatus') or '',
            'cargo_tracking': tracking,
            'cargo_company': order_json.get('cargoCompany') or '',
        }

    @api.model
    def _order_tracking(self, order_json):
        # cargoTrackingNumber genelde null; platform anlaşmalı kargoda cargoKey etiket barkodudur
        for key in ('cargoTrackingNumber', 'cargoKey', 'shipmentCode'):
            if order_json.get(key):
                return str(order_json[key])
        return ''

    def _apply_order_json(self, order_json):
        """Kalemleri (item id ile), statüyü, kargo ve tutar bilgilerini günceller. Değişiklik olduysa True."""
        self.ensure_one()
        existing = {l.item_id: l for l in self.line_ids if l.item_id}
        commands = []
        line_vals = []
        seen = set()
        for item in order_json.get('items') or []:
            vals = self._line_vals(item, order_json)
            if not vals['item_id'] or vals['item_id'] in seen:
                continue
            seen.add(vals['item_id'])
            line_vals.append(vals)
            line = existing.get(vals['item_id'])
            if line:
                diff = {k: v for k, v in vals.items() if line[k] != v}
                if diff:
                    commands.append((1, line.id, diff))
            else:
                commands.append((0, 0, vals))

        header = {}
        if commands:
            header['line_ids'] = commands
        header.update({
            'order_status': order_json.get('status') or self.order_status or '',
            'status_updated_at': self._parse_datetime(order_json.get('statusUpdatedAt')) or self.status_updated_at,
            'cargo_tracking_number': self._order_tracking(order_json) or self.cargo_tracking_number or '',
            'cargo_tracking_url': order_json.get('cargoTrackingUrl') or self.cargo_tracking_url or '',
            'cargo_provider': order_json.get('cargoCompany') or self.cargo_provider or '',
            'cargo_profile_id': str(order_json.get('cargoProfileId') or self.cargo_profile_id or ''),
            'cargo_profile_name': order_json.get('cargoProfileName') or self.cargo_profile_name or '',
            'total_price': _money(order_json.get('discountedTotalPrice')),
            'gross_price': _money(order_json.get('totalPrice')),
            'platform_discount': _money(order_json.get('totalPlatformDiscount')),
            'vendor_discount': _money(order_json.get('totalVendorDiscount')),
            'commission_amount': round(sum(v['commission_amount'] for v in line_vals), 2),
            'earning_amount': round(sum(v['earning_amount'] for v in line_vals), 2),
            'raw_data': json.dumps(order_json, ensure_ascii=False, sort_keys=True),
        })
        header = {k: v for k, v in header.items() if k == 'line_ids' or self[k] != v}
        if not header:
            return False
        self.write(header)
        return bool(commands) or any(k != 'raw_data' for k in header)

    def _raw_json(self):
        self.ensure_one()
        try:
            data = json.loads(self.raw_data or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ─── idefix.order → sale.order ───────────────────────────

    def _active_lines(self):
        return self.line_ids.filtered(lambda l: not is_inactive_item_status(l.status))

    def _reconcile_sale_order(self, store):
        """Odoo siparişini Idefix sevkiyatıyla eşitler: yoksa açar, sevkiyat kapandıysa
        (iptal / tedarik edilemedi / bölündü) iptal eder, kalem düştüyse kalanlarla yeniden kurar."""
        self.ensure_one()
        lines = self._active_lines()
        cancelled = self.order_status in IDEFIX_CANCEL_STATUSES or not lines
        so = self.sale_order_id
        if not so:
            if cancelled:
                if self.error_message:
                    self.error_message = False
                return
            force = self.env.context.get('idefix_force_create')
            if self.legacy_no_sale and not force:
                return  # güncelleme öncesi kayıt: yalnızca 'Tekrar Dene' ile aktarılır
            if self.order_status not in IDEFIX_OPEN_STATUSES and not force:
                msg = (f"Sevkiyat Odoo'ya ilk kez '{self.order_status_display}' statüsünde geldi; "
                       f"Odoo siparişi otomatik açılmadı (gerekiyorsa Tekrar Dene).")
                if self.error_message != msg:
                    self.error_message = msg
                return
            so = self._create_odoo_sale_order(store)
            if so:
                self.write({'sale_order_id': so.id, 'error_message': False, 'legacy_no_sale': False})
                if store.auto_confirm and so.state in ('draft', 'sent'):
                    so.action_confirm()
            return
        if so.state == 'cancel':
            return
        if cancelled:
            self._cancel_odoo_order(self, store)
            return
        product_map, missing = self._match_products(lines)
        if missing:
            return  # karşılaştırılamaz; mevcut sipariş korunur
        wanted = Counter()
        for line in lines:
            wanted[product_map[line.product_code].id] += line.quantity
        current = Counter()
        for sol in so.order_line.filtered(lambda l: l.idefix_item_id and l.product_id):
            current[sol.product_id.id] += int(sol.product_uom_qty)
        if wanted == current:
            if self.error_message:
                self.error_message = False
        elif any(qty > wanted.get(product_id, 0) for product_id, qty in current.items()):
            self._rebuild_sale_order(store, 'Idefix sevkiyat kalemleri değişti')
        else:
            msg = (f"Odoo siparişi {so.name} Idefix kalemleriyle uyuşmuyor (Odoo'da eksik ürün var); "
                   f"elle kontrol edin.")
            if self.error_message != msg:
                self.error_message = msg

    def _match_products(self, lines):
        Product = self.env['product.product'].sudo()
        codes = [c for c in lines.mapped('product_code') if c]
        product_map = Product.batch_find_by_marketplace_barcodes(codes) if codes else {}
        missing = []
        for line in lines:
            code = line.product_code
            product = product_map.get(code) if code else None
            if not product and code:
                product = Product.find_by_marketplace_barcode(code)
                if product:
                    product_map[code] = product
            if not product:
                missing.append(code or line.product_name or line.item_id)
        return product_map, missing

    def _cancel_blocker(self, so):
        """Otomatik iptali engelleyen durum (sevk edilmiş / faturası kesilmiş) — yoksa False."""
        if so.picking_ids.filtered(lambda p: p.state == 'done'):
            return 'sevk edildiği'
        if so.invoice_ids.filtered(lambda m: m.state == 'posted'):
            return 'faturası kesildiği'
        return False

    def _rebuild_sale_order(self, store, reason):
        """Mevcut Odoo siparişini iptal eder (Nebim'den de silinir), kalan kalemlerle yenisini açar."""
        old = self.sale_order_id
        if old.state == 'cancel':
            return
        if not store.auto_cancel:
            msg = (f"{reason}: Idefix sevkiyatı değişti ancak 'İptalleri Otomatik İptal Et' kapalı; "
                   f"Odoo siparişi {old.name} elle güncellenmeli.")
            if self.error_message != msg:
                self.error_message = msg
                old.message_post(body=msg)
            return
        blocker = self._cancel_blocker(old)
        if blocker:
            msg = f"{reason}: {old.name} {blocker} için otomatik güncellenmedi; elle kontrol edin."
            if self.error_message != msg:
                self.error_message = msg
                old.message_post(body=msg)
            return
        new = self._create_odoo_sale_order(store, partners=(old.partner_id, old.partner_invoice_id,
                                                              old.partner_shipping_id))
        if not new:
            return
        with self.env.cr.savepoint():
            old._action_cancel()
        self.write({'sale_order_id': new.id, 'error_message': False})
        if store.auto_confirm and new.state in ('draft', 'sent'):
            new.action_confirm()
        new.message_post(body=f"{reason}: önceki sipariş {old.name} iptal edildi, kalan ürünlerle yeniden oluşturuldu.")
        old.message_post(body=f"{reason}: yerine {new.name} oluşturuldu.")
        _logger.info("Idefix sevkiyat %s: %s → %s yerine %s", self.order_id, reason, old.name, new.name)

    @api.model
    def _sale_tax_field(self):
        fields_ = self.env['sale.order.line']._fields
        return 'tax_ids' if 'tax_ids' in fields_ else ('tax_id' if 'tax_id' in fields_ else False)

    def _client_order_ref(self):
        """Nebim sipariş belgesi ve mükerrer kontrolü client_order_ref ile yapılır. Aynı Idefix sipariş
        numarasında birden fazla sevkiyat varsa (bölünme / tedarik edilememe) sonrakiler shipment ID
        ekiyle ayrışır — aksi halde Nebim yeni sevkiyatı 'mükerrer' sayıp atlar."""
        self.ensure_one()
        siblings = self.search([
            ('store_id', '=', self.store_id.id),
            ('order_number', '=', self.order_number),
            ('id', '!=', self.id),
            ('sale_order_id', '!=', False),
        ], limit=1)
        return f"{self.order_number}-{self.order_id}" if siblings else self.order_number

    def _create_odoo_sale_order(self, store, partners=None):
        """Aktif Idefix kalemlerinden Odoo siparişi oluşturur. Eşleşmeyen ürün varsa sipariş açılmaz."""
        self.ensure_one()
        lines = self._active_lines()
        product_map, missing = self._match_products(lines)
        if missing:
            msg = 'Ürün bulunamadı: ' + ', '.join(sorted(set(missing)))
            if self.error_message != msg:
                self.error_message = msg
            _logger.warning("Idefix %s: %s", self.order_number, msg)
            return False

        if partners:
            partner, invoice_partner, shipping_partner = partners
        else:
            partner, invoice_partner = self._find_or_create_partner(store)
            shipping_partner = partner

        # Depo ayarını config'den al — Ayarlar > Idefix > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param('idefix_integration.warehouse_id')
        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'idefix_store_id': store.id,
            'idefix_order_id': self.id,
            'client_order_ref': self._client_order_ref(),
            'date_order': self.order_date or fields.Datetime.now(),
            'order_line': [],
        }
        if warehouse_id_str:
            sale_vals['warehouse_id'] = int(warehouse_id_str)

        tax_field = self._sale_tax_field()
        tax_cache = {}
        for line in lines:
            ol_vals = {
                'product_id': product_map[line.product_code].id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price_tax_included,  # KDV DAHİL fiyat
                'idefix_item_id': line.item_id,
            }
            vat_rate = line.vat_rate or 0
            if vat_rate > 0:
                if vat_rate not in tax_cache:
                    tax_cache[vat_rate] = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', vat_rate),
                        ('price_include', '=', True),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                include_tax = tax_cache[vat_rate]
                if include_tax and tax_field:
                    # KDV dahil vergi açıkça atanır: ürünün varsayılan vergisi ne olursa olsun tutar değişmez
                    ol_vals[tax_field] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi yok — KDV hariç fiyat yazılır, ürünün (hariç) vergisi üstüne eklenir
                    ol_vals['price_unit'] = line.sale_price
            sale_vals['order_line'].append((0, 0, ol_vals))

        return self.env['sale.order'].create(sale_vals)

    @api.private
    def _find_turkey_state(self, city_name):
        """İl adından Odoo res.country.state kaydını bul."""
        if not city_name:
            return False
        country_tr = self.env.ref('base.tr')
        State = self.env['res.country.state']
        state = State.search([('country_id', '=', country_tr.id), ('name', '=ilike', city_name.strip())], limit=1)
        if not state:
            # Kısmi eşleşme (İzmir -> İzmir İli gibi)
            state = State.search([('country_id', '=', country_tr.id), ('name', 'ilike', city_name.strip())], limit=1)
        return state or False

    @api.model
    def _street(self, addr):
        """Nebim cari adresi yalnızca 'street' alanını okur — mahalle ve kapı bilgisi buraya eklenir."""
        address1 = (addr.get('address1') or '').strip()
        neighbourhood = (addr.get('neighboorhood') or '').strip()  # Idefix alan adı bu yazımla gelir
        parts = []
        if neighbourhood and neighbourhood.lower() not in address1.lower():
            parts.append(f"{neighbourhood} Mah.")
        parts.append(address1 or (addr.get('fullAddress') or '').strip())
        door = []
        for key, label in (('buildingNumber', 'No:'), ('floor', 'Kat:'), ('doorNumber', 'D:')):
            value = str(addr.get(key) or '').strip()
            if value and f"{label}{value}" not in address1.replace(' ', ''):
                door.append(f"{label}{value}")
        if door and address1:
            parts.append(' '.join(door))
        return ' '.join(p for p in parts if p).strip()

    def _find_or_create_partner(self, store):
        """(ana partner, fatura partneri) döndürür.

        Ana partner teslimat adresini taşır; kurumsal faturada (isCommercial / isLikeCommercial = "1")
        firma unvanı + VKN ile açılır (Nebim cari ve faturayı ana partnerden okur), fatura adresi ayrı
        alt partnerdir."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        country_tr = self.env.ref('base.tr').id
        raw = self._raw_json()
        ship = raw.get('shippingAddress') or {}
        bill = raw.get('invoiceAddress') or {}
        is_commercial = _flag(bill.get('isCommercial')) or _flag(bill.get('isLikeCommercial'))
        vat = _digits(bill.get('taxNumber')) or (_digits(bill.get('identificationNumber')) if is_commercial else '')
        company_name = (bill.get('company') or '').strip()
        phone = ship.get('phone') or ''
        email = '' if store.skip_customer_email else (self.customer_email or '')
        street = self._street(ship)
        district = ship.get('county') or self.shipping_district or ''
        state = self._find_turkey_state(ship.get('city') or self.shipping_city)
        einvoice = 'is_subject_to_einvoice' in Partner._fields

        customer_ref = ''
        if store.customer_prefix and self.customer_id:
            customer_ref = f"{store.customer_prefix}{self.customer_id}"

        partner = Partner
        new_ref = customer_ref
        # Fatura alt partnerleri de aynı ref'i taşır — ana partner yalnızca üst kayıtlarda aranır
        top = [('parent_id', '=', False)]
        if customer_ref:
            if is_commercial and vat:
                # Firma kaydı aynı müşterinin bireysel kaydını ezmesin: firma ayrı ref taşır
                new_ref = f"{customer_ref}-{vat}"
                partner = (Partner.search(top + [('ref', '=', new_ref)], limit=1)
                           or Partner.search(top + [('ref', '=', customer_ref), ('vat', '=', vat)], limit=1))
            else:
                partner = Partner.search(top + [('ref', '=', customer_ref), ('is_company', '=', is_commercial)],
                                         limit=1)
        else:
            # Müşteri no yoksa yalnızca aynı isim + aynı ilçe (+ kurumsalda aynı VKN) eşleşmesi kabul edilir
            name = (company_name if is_commercial else self.customer_name) or ''
            if name:
                domain = top + [('name', '=ilike', name), ('city', '=ilike', district)]
                if is_commercial and vat:
                    domain.append(('vat', '=', vat))
                partner = Partner.search(domain, limit=1)

        if not partner:
            vals = {
                'name': (company_name if is_commercial else '') or self.customer_name or 'Idefix Müşteri',
                'email': email,
                'phone': phone,
                'street': street,
                'city': district,  # İlçe
                'state_id': state.id if state else False,  # İl
                'zip': ship.get('postalCode') or False,
                'country_id': country_tr,
                'ref': new_ref,
                'company_type': 'company' if is_commercial else 'person',
            }
            if is_commercial:
                vals['vat'] = vat
                if einvoice:
                    vals['is_subject_to_einvoice'] = True
            partner = Partner.create(vals)
        else:
            # Teslimat adresi ana partnerde: değiştiyse güncelle (yeni sipariş eski adrese gitmesin)
            update_vals = {}
            if street and partner.street != street:
                update_vals['street'] = street
            if district and partner.city != district:
                update_vals['city'] = district
            if state and partner.state_id != state:
                update_vals['state_id'] = state.id
            if ship.get('postalCode') and partner.zip != ship['postalCode']:
                update_vals['zip'] = ship['postalCode']
            if not partner.country_id:
                update_vals['country_id'] = country_tr
            if phone and not partner.phone:
                update_vals['phone'] = phone
            if email and not partner.email:
                update_vals['email'] = email
            if is_commercial and vat and not partner.vat:
                update_vals['vat'] = vat
            if update_vals:
                partner.write(update_vals)

        invoice_partner = partner
        if is_commercial:
            bill_street = self._street(bill)
            invoice_name = company_name or self.customer_name
            invoice_partner = Partner.search([
                ('parent_id', '=', partner.id), ('type', '=', 'invoice'),
                ('street', '=', bill_street), ('name', '=', invoice_name),
            ], limit=1)
            if not invoice_partner:
                bill_state = self._find_turkey_state(bill.get('city'))
                inv_vals = {
                    'name': invoice_name,
                    'type': 'invoice',
                    'parent_id': partner.id,
                    'street': bill_street,
                    'city': bill.get('county') or '',  # İlçe
                    'state_id': bill_state.id if bill_state else False,  # İl
                    'zip': bill.get('postalCode') or False,
                    'country_id': country_tr,
                    'vat': vat,
                    'ref': new_ref,
                }
                if einvoice:
                    inv_vals['is_subject_to_einvoice'] = True
                invoice_partner = Partner.create(inv_vals)
        return partner, invoice_partner

    # ─── İPTAL YÖNETİMİ ────────────────────────────────────────

    @api.private
    def _cancel_odoo_order(self, idefix_order, store=None):
        """Odoo siparişini iptal et (sevk edilmiş / faturası kesilmiş siparişlere dokunulmaz)."""
        store = store or idefix_order.store_id
        if store and not store.auto_cancel:
            return
        so = idefix_order.sale_order_id
        if not so or so.state in ('cancel', 'done'):
            return
        blocker = idefix_order._cancel_blocker(so)
        if blocker:
            msg = (f"Idefix sevkiyatı '{idefix_order.order_status_display}' oldu ancak {so.name} {blocker} "
                   f"için otomatik iptal edilmedi; elle kontrol edin.")
            if idefix_order.error_message != msg:
                idefix_order.error_message = msg
                so.message_post(body=msg)
            return
        try:
            with self.env.cr.savepoint():
                so._action_cancel()
            so.message_post(body=f"Idefix sevkiyatı '{idefix_order.order_status_display}' olduğu için iptal edildi.")
            _logger.info("Idefix — Odoo sipariş iptal edildi: %s (Idefix: %s / %s)",
                         so.name, idefix_order.order_number, idefix_order.order_id)
        except Exception as e:
            _logger.warning("Idefix — Sipariş iptal hatası: %s - %s", so.name, e)

    @api.private
    def _cancel_pending_orders(self, store):
        """Veritabanındaki kapanmış Idefix sevkiyatlarını tara,
        bağlı Odoo sale order henüz iptal edilmemişse iptal et."""
        if not store.auto_cancel:
            return 0
        cancelled_orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'in', list(IDEFIX_CANCEL_STATUSES)),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', 'not in', ['cancel', 'done']),
            ('order_date', '>=', fields.Datetime.now() - _AUTO_CANCEL_LOOKBACK),
        ])
        count = 0
        for ix_order in cancelled_orders:
            self._cancel_odoo_order(ix_order, store)
            if ix_order.sale_order_id.state == 'cancel':
                count += 1
        return count

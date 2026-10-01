
import json
import logging
from collections import Counter
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

from .pazarama_api import PAZARAMA_MAX_WINDOW_DAYS
from .pazarama_order import (
    PAZARAMA_CANCEL_STATUSES, PAZARAMA_FINAL_STATUSES, PAZARAMA_STATUS_RANK,
)

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

_SYNC_LOCK_NS = 7471031          # mağaza başına senkron kilidi (pg advisory lock ad alanı)
_PAGE_SIZE = 100
_MAX_PAGES = 100
_STALE_CHECK_AFTER = timedelta(hours=6)    # açık siparişler en geç bu aralıkla tek tek yoklanır
_STALE_CHECK_LIMIT = 20                    # her turda yoklanacak en fazla sipariş
_STALE_LOOKBACK = timedelta(days=180)      # sipariş no ile sorgu en fazla 6 ay geriye gider
_ACCEPT_RETRY_AFTER = timedelta(minutes=30)
_ACCEPT_STATUS = 12                        # Siparişiniz Hazırlanıyor


def _digits(value):
    return ''.join(filter(str.isdigit, str(value or '')))


def _money(value):
    """Pazarama tutarları para nesnesi ({value, ...}) ya da sayı olarak gelir."""
    if isinstance(value, dict):
        value = value.get('value')
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class PazaramaOrderSync(models.Model):
    _inherit = 'pazarama.order'

    @api.model
    def sync_orders_from_pazarama(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['pazarama.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("Pazarama %s senkronizasyon hatası: %s", store.name, e)
                store._write_sync_state(error=str(e))

    @api.model
    def _now_turkey(self):
        return datetime.now(pytz.UTC).astimezone(IST).replace(tzinfo=None)

    @api.model
    def _to_turkey(self, dt_utc):
        return pytz.UTC.localize(dt_utc).astimezone(IST).replace(tzinfo=None)

    @api.model
    def _parse_tr_datetime(self, value):
        """Pazarama tarihleri ("2026-02-17 17:23") Türkiye saatidir — Odoo UTC saklar."""
        if not value:
            return False
        text = str(value).replace('T', ' ')
        for fmt, size in (('%Y-%m-%d %H:%M:%S', 19), ('%Y-%m-%d %H:%M', 16), ('%Y-%m-%d', 10)):
            try:
                naive_dt = datetime.strptime(text[:size], fmt)
                break
            except ValueError:
                continue
        else:
            _logger.warning("Pazarama tarih parse hatası: %s", value)
            return False
        return IST.localize(naive_dt).astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def sync_orders_for_store(self, store):
        """Son N gündeki siparişleri çeker (yeni + güncellenen), ardından daha eski açık
        siparişleri sipariş numarasıyla tek tek yoklar (kargo / teslim / iptal durumları için)."""
        # Aynı mağazada tek senkron (cron sürerken manuel senkron aynı siparişleri paralel açmasın)
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (_SYNC_LOCK_NS, store.id))
        if not self.env.cr.fetchone()[0]:
            _logger.info("Pazarama senkronizasyon [%s] atlandı: başka bir senkron çalışıyor", store.name)
            return {'created': 0, 'updated': 0, 'errors': 0, 'busy': True}

        api_client = store.get_api()
        now = fields.Datetime.now()
        day_range = min(max(store.order_day_range or 1, 1), PAZARAMA_MAX_WINDOW_DAYS - 1)
        # Pazarama API Türkiye saatinde çalışır — sorgu tarihleri Türkiye saatiyle gider
        now_turkey = self._now_turkey()
        start_date = now_turkey - timedelta(days=day_range)
        end_date = now_turkey + timedelta(minutes=5)  # bitiş tarihi hariç tutulur → küçük pay

        _logger.info("Pazarama [%s] sipariş çekme (TR saati): %s → %s", store.name, start_date, end_date)

        counters = Counter()
        orders, error = self._fetch_orders(api_client, start_date, end_date)
        counters['received'] = len(orders)
        for order_json in orders:
            self._safe_sync(store, api_client, order_json, counters)

        if not error:
            try:
                self._refresh_stale_orders(store, api_client, counters, now - timedelta(days=day_range))
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("Pazarama açık sipariş yoklama hatası [%s]: %s", store.name, e)

        # ── Veritabanındaki iptal siparişleri tara (tarih filtresi dışındakiler dahil) ──
        try:
            with self.env.cr.savepoint():
                cancel_count = self._cancel_pending_orders(store)
                if cancel_count:
                    _logger.info("Pazarama — %d sipariş Odoo'da iptal edildi", cancel_count)
        except Exception as e:
            _logger.exception("Pazarama iptal tarama hatası: %s", e)

        try:
            self._send_pending_invoices(store, api_client)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.exception("Pazarama fatura gönderim hatası [%s]: %s", store.name, e)

        if error:
            _logger.error("Pazarama Sipariş Çekme Hatası [%s]: %s", store.name, error)
        store._write_sync_state(last_sync=None if error else now, error=error)
        _logger.info("Pazarama [%s] senkron tamamlandı — %d sipariş alındı, Yeni: %d, Güncellenen: %d, Hata: %d%s",
                     store.name, counters['received'], counters['created'], counters['updated'], counters['errors'],
                     ' (eksik: API hatası)' if error else '')
        return {'created': counters['created'], 'updated': counters['updated'], 'errors': counters['errors'],
                'error': error}

    @api.model
    def _extract_orders(self, res):
        body = res.get('data')
        data = body.get('data') if isinstance(body, dict) else body
        if isinstance(data, dict):
            data = data.get('data') or data.get('orders') or []
        return [o for o in (data or []) if isinstance(o, dict)] if isinstance(data, list) else []

    @api.model
    def _fetch_orders(self, api_client, start_date, end_date, order_number=None):
        """(siparişler, hata) döner — tüm sayfalar."""
        orders = []
        for page in range(1, _MAX_PAGES + 1):
            res = api_client.get_orders(start_date=start_date, end_date=end_date, page=page,
                                        size=_PAGE_SIZE, order_number=order_number)
            if not res.get('success'):
                return orders, res.get('error') or 'Bilinmeyen hata'
            data_list = self._extract_orders(res)
            orders.extend(data_list)
            if len(data_list) < _PAGE_SIZE:
                break
        return orders, False

    @api.model
    def _fetch_single_order(self, api_client, order_number, order_date=None):
        """Sipariş numarasıyla tek sipariş (sipariş tarihi çevresinde dar bir aralıkla)."""
        if order_date:
            center = self._to_turkey(order_date)
            start, end = center - timedelta(days=1), center + timedelta(days=2)
        else:
            end = self._now_turkey() + timedelta(minutes=5)
            start = end - timedelta(days=PAZARAMA_MAX_WINDOW_DAYS - 1)
        orders, error = self._fetch_orders(api_client, start, end, order_number=order_number)
        match = [o for o in orders if str(o.get('orderNumber') or '') == str(order_number)]
        return (match[0] if match else None), error

    @api.private
    def _safe_sync(self, store, api_client, order_json, counters):
        try:
            with self.env.cr.savepoint():
                action = self._sync_order_json(store, order_json, api_client)
            counters[action] += 1
        except Exception as e:
            counters['errors'] += 1
            self.env.invalidate_all(flush=False)
            _logger.exception("Pazarama Sipariş İşleme Hatası (%s): %s", order_json.get('orderNumber'), e)

    @api.private
    def _refresh_stale_orders(self, store, api_client, counters, window_start):
        """Sorgu penceresinden eski açık siparişleri sipariş numarasıyla yoklar."""
        now = fields.Datetime.now()
        orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'not in', list(PAZARAMA_FINAL_STATUSES)),
            ('order_date', '<', window_start),
            ('order_date', '>=', now - _STALE_LOOKBACK),
            '|', ('last_checked', '=', False), ('last_checked', '<', now - _STALE_CHECK_AFTER),
        ], limit=_STALE_CHECK_LIMIT, order='last_checked asc nulls first, id')
        for order in orders:
            order_json, error = self._fetch_single_order(api_client, order.order_number, order.order_date)
            if error:
                _logger.warning("Pazarama sipariş yoklanamadı %s: %s", order.order_number, error)
                break
            if order_json:
                self._safe_sync(store, api_client, order_json, counters)
            else:
                order.last_checked = now

    # ─── JSON → pazarama.order ───────────────────────────────

    @api.private
    def _sync_order_json(self, store, order_json, api_client=None):
        """Tek siparişi işler. 'created' / 'updated' / 'unchanged' / 'skipped' döner."""
        order_id = str(order_json.get('orderId') or '').strip()
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
        rec._auto_accept(store, api_client)
        rec.last_checked = fields.Datetime.now()
        if action:
            return action
        return 'updated' if changed else 'unchanged'

    @api.model
    def _order_header_vals(self, store, order_json):
        shipment_addr = order_json.get('shipmentAddress') or {}
        billing_addr = order_json.get('billingAddress') or {}
        return {
            'store_id': store.id,
            'order_id': str(order_json.get('orderId')),
            'order_number': str(order_json.get('orderNumber') or ''),
            'order_date': self._parse_tr_datetime(order_json.get('orderDate')) or fields.Datetime.now(),
            'order_status': _int(order_json.get('orderStatus')),
            'payment_type': _int(order_json.get('paymentType'), 1),
            'invoice_type': _int(billing_addr.get('invoiceType'), 1),
            'customer_id': str(order_json.get('customerId') or ''),
            'customer_name': order_json.get('customerName') or shipment_addr.get('nameSurname') or '',
            'customer_email': order_json.get('customerEmail') or shipment_addr.get('customerEmail') or '',
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr.get('cityName') or '',
            'shipping_district': shipment_addr.get('districtName') or '',
            'tax_office': billing_addr.get('taxOffice') or '',
            'currency': order_json.get('currency') or 'TRY',
        }

    @api.model
    def _line_vals(self, item):
        product = item.get('product') or {}
        cargo = item.get('cargo') or {}
        tracking = (str(cargo['trackingNumber']) if cargo.get('trackingNumber') else '') or \
                   (str(item['shipmentCode']) if item.get('shipmentCode') else '')
        return {
            'item_id': str(item.get('orderItemId') or ''),
            'product_id': str(product.get('productId') or ''),
            'product_name': product.get('name') or '',
            'product_code': product.get('code') or product.get('stockCode') or '',
            'quantity': _int(item.get('quantity'), 1) or 1,
            # salePrice: KDV dahil birim satış fiyatı (Pazarama destek onayı: KDV dahil fatura edilir)
            'sale_price': _money(item.get('salePrice')),
            'vat_rate': float(product.get('vatRate') or 0),
            'status': _int(item.get('orderItemStatus')),
            'cargo_tracking': tracking,
            'cargo_company': cargo.get('companyName') or '',
            'cargo_company_id': str(cargo.get('companyId') or ''),
        }

    def _apply_order_json(self, order_json):
        """Kalemleri (orderItemId ile) ve başlık durumunu günceller. Değişiklik olduysa True."""
        self.ensure_one()
        existing = {l.item_id: l for l in self.line_ids if l.item_id}
        commands = []
        line_vals = []
        seen = set()
        for item in order_json.get('items') or []:
            vals = self._line_vals(item)
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
        header.update(self._header_status_vals(line_vals, order_json))
        active = [v for v in line_vals if v['status'] not in PAZARAMA_CANCEL_STATUSES] or line_vals
        tracking = next((v['cargo_tracking'] for v in active if v['cargo_tracking']), '') \
            or (str(order_json['shipmentCode']) if order_json.get('shipmentCode') else '')
        provider = next((v['cargo_company'] for v in active if v['cargo_company']), '')
        header['cargo_tracking_number'] = tracking or self.cargo_tracking_number or ''
        header['cargo_provider'] = provider or self.cargo_provider or ''
        header['total_price'] = _money(order_json.get('orderAmount'))
        header['raw_data'] = json.dumps(order_json, ensure_ascii=False, sort_keys=True)
        header = {k: v for k, v in header.items() if k == 'line_ids' or self[k] != v}
        if not header:
            return False
        self.write(header)
        return bool(commands) or any(k != 'raw_data' for k in header)

    @api.model
    def _header_status_vals(self, line_vals, order_json):
        """Sipariş durumu kalem durumlarından: tümü iptalse iptal, değilse en geride kalan aktif kalem."""
        if not line_vals:
            return {'order_status': _int(order_json.get('orderStatus'))}
        live = [v['status'] for v in line_vals if v['status'] not in PAZARAMA_CANCEL_STATUSES]
        if not live:
            statuses = [v['status'] for v in line_vals]
            status = next((s for s in PAZARAMA_CANCEL_STATUSES if s in statuses), statuses[0])
            partial = False
        else:
            status = min(live, key=lambda s: PAZARAMA_STATUS_RANK.get(s, 0))
            partial = len(live) < len(line_vals)
        return {'order_status': status, 'partially_cancelled': partial}

    def _raw_json(self):
        self.ensure_one()
        try:
            data = json.loads(self.raw_data or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # ─── pazarama.order → sale.order ─────────────────────────

    def _active_lines(self):
        return self.line_ids.filtered(lambda l: l.status not in PAZARAMA_CANCEL_STATUSES)

    def _reconcile_sale_order(self, store):
        """Odoo siparişini Pazarama kalemleriyle eşitler: yoksa açar, tamamen iptalse iptal eder,
        kalem düştüyse (kısmi iptal) kalanlarla yeniden kurar."""
        self.ensure_one()
        lines = self._active_lines()
        cancelled = self.order_status in PAZARAMA_CANCEL_STATUSES or not lines
        so = self.sale_order_id
        if not so:
            if cancelled:
                return
            if self.legacy_no_sale and not self.env.context.get('pazarama_force_create'):
                return  # güncelleme öncesi kayıt: yalnızca 'Tekrar Dene' ile aktarılır
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
        for sol in so.order_line.filtered(lambda l: l.pazarama_item_id and l.product_id):
            current[sol.product_id.id] += int(sol.product_uom_qty)
        if wanted == current:
            if self.error_message:
                self.error_message = False
        elif any(qty > wanted.get(product_id, 0) for product_id, qty in current.items()):
            reason = 'Kısmi iptal' if self.partially_cancelled else 'Pazarama sipariş kalemleri değişti'
            self._rebuild_sale_order(store, reason)
        else:
            msg = (f"Odoo siparişi {so.name} Pazarama kalemleriyle uyuşmuyor (Odoo'da eksik ürün var); "
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

    def _rebuild_sale_order(self, store, reason):
        """Mevcut Odoo siparişini iptal eder (Nebim'den de silinir), kalan kalemlerle yenisini açar."""
        old = self.sale_order_id
        if old.state == 'cancel':
            return
        if not store.auto_cancel:
            msg = (f"{reason}: Pazarama siparişi değişti ancak 'İptalleri Otomatik İptal Et' kapalı; "
                   f"Odoo siparişi {old.name} elle güncellenmeli.")
            if self.error_message != msg:
                self.error_message = msg
                old.message_post(body=msg)
            return
        if old.picking_ids.filtered(lambda p: p.state == 'done'):
            msg = f"{reason}: {old.name} sevk edildiği için otomatik güncellenmedi; elle kontrol edin."
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
        _logger.info("Pazarama sipariş %s: %s → %s yerine %s", self.order_number, reason, old.name, new.name)

    @api.model
    def _sale_tax_field(self):
        fields_ = self.env['sale.order.line']._fields
        return 'tax_ids' if 'tax_ids' in fields_ else ('tax_id' if 'tax_id' in fields_ else False)

    def _create_odoo_sale_order(self, store, partners=None):
        """Aktif Pazarama kalemlerinden Odoo siparişi oluşturur. Eşleşmeyen ürün varsa sipariş açılmaz."""
        self.ensure_one()
        lines = self._active_lines()
        product_map, missing = self._match_products(lines)
        if missing:
            msg = 'Ürün bulunamadı: ' + ', '.join(sorted(set(missing)))
            if self.error_message != msg:
                self.error_message = msg
            _logger.warning("Pazarama %s: %s", self.order_number, msg)
            return False

        if partners:
            partner, invoice_partner, shipping_partner = partners
        else:
            partner, invoice_partner = self._find_or_create_partner(store)
            shipping_partner = partner

        # Depo ayarını config'den al — Ayarlar > Pazarama > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param('pazarama_integration.warehouse_id')
        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'pazarama_store_id': store.id,
            'pazarama_order_id': self.id,
            'client_order_ref': self.order_number,
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
                'price_unit': line.sale_price,  # KDV DAHİL fiyat
                'pazarama_item_id': line.item_id,
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
                    ol_vals['price_unit'] = round(line.sale_price / (1 + vat_rate / 100.0), 2)
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

    def _find_or_create_partner(self, store):
        """(ana partner, fatura partneri) döndürür.

        Ana partner teslimat adresini taşır; kurumsal faturada (invoiceType=2) firma unvanı + VKN ile
        açılır (Nebim cari ve faturayı ana partnerden okur), fatura adresi ayrı alt partnerdir."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        country_tr = self.env.ref('base.tr').id
        raw = self._raw_json()
        ship = raw.get('shipmentAddress') or {}
        bill = raw.get('billingAddress') or {}
        is_commercial = _int(bill.get('invoiceType'), 1) == 2
        vat = _digits(bill.get('taxNumber')) or _digits(bill.get('identityNumber'))
        company_name = (bill.get('companyName') or '').strip()
        phone = ship.get('phoneNumber') or ''
        email = '' if store.skip_customer_email else (self.customer_email or '')
        street = ship.get('displayAddressText') or ship.get('addressDetail') or ''
        district = ship.get('districtName') or self.shipping_district or ''
        state = self._find_turkey_state(ship.get('cityName') or self.shipping_city)
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
                'name': (company_name if is_commercial else '') or self.customer_name or 'Pazarama Müşteri',
                'email': email,
                'phone': phone,
                'street': street,
                'city': district,  # İlçe
                'state_id': state.id if state else False,  # İl
                'country_id': country_tr,
                'ref': new_ref,
                'company_type': 'company' if is_commercial else 'person',
            }
            if is_commercial:
                vals['vat'] = vat
                if einvoice:
                    vals['is_subject_to_einvoice'] = bool(bill.get('isEInvoiceObliged'))
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
            if not partner.country_id:
                update_vals['country_id'] = country_tr
            if email and not partner.email:
                update_vals['email'] = email
            if is_commercial and vat and not partner.vat:
                update_vals['vat'] = vat
            if update_vals:
                partner.write(update_vals)

        invoice_partner = partner
        if is_commercial:
            bill_street = bill.get('displayAddressText') or bill.get('addressDetail') or ''
            invoice_name = company_name or self.customer_name
            invoice_partner = Partner.search([
                ('parent_id', '=', partner.id), ('type', '=', 'invoice'),
                ('street', '=', bill_street), ('name', '=', invoice_name),
            ], limit=1)
            if not invoice_partner:
                bill_state = self._find_turkey_state(bill.get('cityName'))
                inv_vals = {
                    'name': invoice_name,
                    'type': 'invoice',
                    'parent_id': partner.id,
                    'street': bill_street,
                    'city': bill.get('districtName') or '',  # İlçe
                    'state_id': bill_state.id if bill_state else False,  # İl
                    'country_id': country_tr,
                    'vat': vat,
                    'ref': new_ref,
                }
                if einvoice:
                    inv_vals['is_subject_to_einvoice'] = bool(bill.get('isEInvoiceObliged'))
                invoice_partner = Partner.create(inv_vals)
        return partner, invoice_partner

    # ─── ONAY (3 → 12 Hazırlanıyor) ──────────────────────────

    def _auto_accept(self, store, api_client=None):
        """'Siparişi Pazarama'da otomatik onayla' açıksa, Odoo'da onaylı siparişin
        'Sipariş Alındı' (3) kalemlerini 'Hazırlanıyor' (12) yapar."""
        self.ensure_one()
        if not store.auto_accept_orders:
            return
        so = self.sale_order_id
        if not so or so.state != 'sale':
            return
        lines = self.line_ids.filtered(lambda l: l.status == 3)
        if not lines:
            return
        now = fields.Datetime.now()
        if self.accept_attempt_date and now - self.accept_attempt_date < _ACCEPT_RETRY_AFTER:
            return
        self.accept_attempt_date = now
        self._accept_lines(lines, so, 'Otomatik onay', api_client)

    def _accept_lines(self, lines, record, source, api_client=None):
        """Kalemleri Pazarama'da 'Hazırlanıyor' (12) yapar; sonucu chatter'a yazar. Başarılı kalemleri döner."""
        api_client = api_client or self.store_id.get_api()
        ok_lines = self.env['pazarama.order.line']
        errors = []
        for line in lines:
            res = api_client.update_item_status(self.order_number, line.item_id, _ACCEPT_STATUS)
            if res.get('success'):
                ok_lines |= line
            else:
                errors.append(f"✗ {line.product_code or line.item_id}: {res.get('error')}")
        if ok_lines:
            ok_lines.write({'status': _ACCEPT_STATUS})
            self.write(self._header_status_vals(
                [{'status': l.status} for l in self.line_ids], {}))
        parts = [f"Pazarama siparişi onaylandı ({source}): {len(ok_lines)} kalem 'Hazırlanıyor' statüsüne alındı."]
        parts.extend(errors)
        record.message_post(body='\n'.join(parts))
        if errors:
            _logger.warning("Pazarama %s onay hatası: %s", self.order_number, '; '.join(errors))
        return ok_lines

    # ─── İPTAL YÖNETİMİ ────────────────────────────────────────

    @api.private
    def _cancel_odoo_order(self, pazarama_order, store=None):
        """Odoo siparişini iptal et."""
        store = store or pazarama_order.store_id
        if store and not store.auto_cancel:
            return
        so = pazarama_order.sale_order_id
        if so and so.state not in ('cancel', 'done'):
            try:
                with self.env.cr.savepoint():
                    so._action_cancel()
                _logger.info("Pazarama — Odoo sipariş iptal edildi: %s (PZ: %s)", so.name, pazarama_order.order_number)
            except Exception as e:
                _logger.warning("Pazarama — Sipariş iptal hatası: %s - %s", so.name, e)

    @api.private
    def _cancel_pending_orders(self, store):
        """Veritabanındaki iptal Pazarama siparişlerini tara,
        bağlı Odoo sale order henüz iptal edilmemişse iptal et."""
        if not store.auto_cancel:
            return 0
        cancelled_orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'in', list(PAZARAMA_CANCEL_STATUSES)),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', 'not in', ['cancel', 'done']),
        ])
        for pz_order in cancelled_orders:
            self._cancel_odoo_order(pz_order, store)
        return len(cancelled_orders)

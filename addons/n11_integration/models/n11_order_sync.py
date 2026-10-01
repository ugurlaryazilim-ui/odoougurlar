import json
import logging
from collections import Counter, OrderedDict, defaultdict
from datetime import timedelta

from odoo import api, fields, models

from .n11_api import N11_MAX_WINDOW_DAYS, n11_datetime
from .n11_order import N11_CANCEL_STATUSES, N11_INACTIVE_LINE_STATUSES, N11_STATUS_RANK

_logger = logging.getLogger(__name__)

# n11 epoch'ları veride gerçek UTC; dokümanda ise "GMT+3" yazıyor. Hangi yorumla okunursa okunsun
# pencere boşa düşmesin diye: geriye 3 saat + 10 dk örtüşme, ileriye 3 saat pay (fazlası zararsız: upsert).
_SYNC_OVERLAP = timedelta(hours=3, minutes=10)
_FUTURE_MARGIN = timedelta(hours=3)
_SYNC_LOCK_NS = 7471011  # mağaza başına senkron kilidi (pg advisory lock ad alanı)
_MAX_LOOKBACK = timedelta(days=30)         # uzun kesintiden sonra en fazla bu kadar geriye gidilir
_STALE_CHECK_AFTER = timedelta(hours=6)    # açık siparişler en geç bu aralıkla tek tek yoklanır
_STALE_CHECK_LIMIT = 20                    # her turda yoklanacak en fazla sipariş
_ACCEPT_RETRY_AFTER = timedelta(minutes=30)
_OPEN_STATUSES = ('Created', 'Picking', 'Shipped')
_DUMMY_TC = '11111111111'


def _status(value):
    # packageHistories durumları baştaki boşlukla gelebiliyor (" Shipped")
    return (value or '').strip()


def _pkg_key(pkg):
    # Konuma özel teslimat siparişlerinde paket id boş gelebilir → sipariş numarası
    return str(pkg.get('id') or f"order:{pkg.get('orderNumber')}")


def _pkg_status(pkg):
    return _status(pkg.get('shipmentPackageStatus'))


def _addr_text(addr):
    return (addr.get('address') or addr.get('fullAddress') or addr.get('address1') or '').strip()


class N11OrderSync(models.Model):
    _inherit = 'n11.order'

    @api.model
    def sync_orders_from_n11(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['n11.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("N11 %s senkronizasyon hatası: %s", store.name, e)
                store._write_sync_state(error=str(e))

    @api.model
    def sync_orders_for_store(self, store):
        """Mağazanın son senkrondan bu yana DEĞİŞEN paketlerini (lastModifiedDate) çeker.

        Böylece yeni siparişlerle birlikte eski siparişlerin iptal / kargo / teslim durumları da gelir.
        last_sync yalnızca tüm pencereler eksiksiz alındıysa ilerler."""
        # Aynı mağazada tek senkron (cron sürerken manuel senkron aynı paketleri paralel işlemesin)
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (_SYNC_LOCK_NS, store.id))
        if not self.env.cr.fetchone()[0]:
            _logger.info("N11 senkronizasyon [%s] atlandı: başka bir senkron çalışıyor", store.name)
            return {'created': 0, 'updated': 0, 'errors': 0, 'busy': True}

        api_client = store.get_api()
        now = fields.Datetime.now()
        cutoff_new = now - timedelta(days=max(store.order_day_range or 1, 1))
        start = (store.last_sync - _SYNC_OVERLAP) if store.last_sync else cutoff_new
        start = max(start, now - _MAX_LOOKBACK)

        counters = Counter()
        error_text = False
        query_end = now + _FUTURE_MARGIN
        win_start = start
        while win_start < query_end:
            win_end = min(win_start + timedelta(days=N11_MAX_WINDOW_DAYS - 1), query_end)
            packages, error_text = self._fetch_modified_packages(api_client, win_start, win_end)
            counters['received'] += len(packages)
            self._process_packages(store, api_client, packages, cutoff_new, counters)
            if error_text:
                _logger.error("N11 Sipariş Çekme Hatası [%s]: %s", store.name, error_text)
                break
            win_start = win_end

        try:
            self._refresh_stale_orders(store, api_client, counters)
        except Exception as e:
            _logger.exception("N11 açık sipariş yoklama hatası [%s]: %s", store.name, e)

        # ── Veritabanındaki iptal siparişleri tara (tarih filtresi dışındakiler dahil) ──
        try:
            with self.env.cr.savepoint():
                cancel_count = self._cancel_pending_orders(store)
                if cancel_count:
                    _logger.info("N11 — %d sipariş Odoo'da iptal edildi", cancel_count)
        except Exception as e:
            _logger.exception("N11 iptal tarama hatası: %s", e)

        store._write_sync_state(last_sync=None if error_text else now, error=error_text)
        _logger.info("N11 senkronizasyon [%s] tamamlandı: %d paket alındı, %d yeni, %d güncellenen, %d hata%s",
                     store.name, counters['received'], counters['created'], counters['updated'], counters['errors'],
                     ' (eksik: API hatası)' if error_text else '')
        return {'created': counters['created'], 'updated': counters['updated'], 'errors': counters['errors']}

    @api.private
    def _fetch_modified_packages(self, api_client, start, end):
        """[start, end] aralığında değişen paketler (en fazla 15 gün). (paketler, hata) döner."""
        packages = []
        page = 0
        while page < 200:
            res = api_client.get_shipment_packages(
                start_date=start, end_date=end, page=page, by_last_modified=True, direction='ASC')
            if not res.get('success'):
                return packages, res.get('error') or 'Bilinmeyen hata'
            data = res.get('data') or {}
            content = (data.get('content') or []) if isinstance(data, dict) else []
            packages.extend(content)
            page += 1
            total_pages = (data.get('totalPages') or 0) if isinstance(data, dict) else 0
            if not content or page >= total_pages:
                break
        return packages, False

    @api.private
    def _process_packages(self, store, api_client, packages, cutoff_new, counters):
        groups = OrderedDict()
        for pkg in packages:
            order_number = str(pkg.get('orderNumber') or '').strip()
            if order_number:
                groups.setdefault(order_number, []).append(pkg)
        for order_number, pkgs in groups.items():
            try:
                with self.env.cr.savepoint():
                    action = self._sync_order_packages(store, api_client, order_number, pkgs, cutoff_new)
                counters[action] += 1
            except Exception as e:
                counters['errors'] += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("N11 Sipariş İşleme Hatası (%s): %s", order_number, e)

    @api.private
    def _refresh_stale_orders(self, store, api_client, counters):
        """Açık siparişleri sipariş numarasıyla tek tek yoklar (değişiklik sorgusunun kaçırdığı
        iptal / teslim durumlarına karşı güvenlik ağı)."""
        now = fields.Datetime.now()
        orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'in', _OPEN_STATUSES),
            ('order_date', '>=', now - _MAX_LOOKBACK),
            '|', ('last_checked', '=', False), ('last_checked', '<', now - _STALE_CHECK_AFTER),
        ], limit=_STALE_CHECK_LIMIT, order='last_checked asc nulls first, id')
        for order in orders:
            res = api_client.get_order_packages(order.order_number)
            if not res.get('success'):
                _logger.warning("N11 sipariş yoklanamadı %s: %s", order.order_number, res.get('error'))
                break
            try:
                with self.env.cr.savepoint():
                    if res.get('data'):
                        action = self._sync_order_packages(
                            store, api_client, order.order_number, res['data'], None, refetch=False)
                        counters[action] += 1
                    else:
                        order.last_checked = now
            except Exception as e:
                counters['errors'] += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("N11 sipariş yoklama hatası %s: %s", order.order_number, e)

    # ─── PAKET → n11.order ───────────────────────────────────

    @api.private
    def _sync_order_packages(self, store, api_client, order_number, pkgs, cutoff_new=None, refetch=True):
        """Bir siparişin gelen paketlerini işler. 'created' / 'updated' / 'unchanged' / 'skipped' döner.

        Paket bölünmesinde (Unpacked) aynı sipariş numarasıyla yeni paketler ve yeni kalem ID'leri
        gelir; eksik görüntü oluşmasın diye bu durumda siparişin tüm paketleri yeniden istenir."""
        rec = self.search([('store_id', '=', store.id), ('order_number', '=', order_number)], limit=1)
        known = rec._get_packages() if rec else {}
        incoming = {_pkg_key(p): p for p in pkgs}

        need_full = refetch and api_client and (
            (rec and any(k not in known for k in incoming))
            or (not rec and (len(incoming) > 1 or any(_pkg_status(p) == 'Unpacked' for p in pkgs))))
        if need_full:
            res = api_client.get_order_packages(order_number)
            full = [p for p in (res.get('data') or []) if str(p.get('orderNumber')) == str(order_number)] \
                if res.get('success') else []
            if full:
                incoming = {_pkg_key(p): p for p in full}

        merged = dict(known)
        merged.update(incoming)

        action = 'updated'
        if not rec:
            order_date = self._n11_order_date(merged.values())
            if cutoff_new and order_date and order_date < cutoff_new:
                # Odoo'da olmayan eski sipariş (yalnızca durumu değişmiş) — yeniden açılmaz
                return 'skipped'
            rec = self.create(self._order_header_vals(store, order_number, merged, order_date))
            action = 'created'

        changed = rec._apply_packages(merged)
        if changed or not rec.sale_order_id:
            rec._reconcile_sale_order(store)
        rec._auto_accept(store)
        rec.last_checked = fields.Datetime.now()
        if action == 'created':
            return action
        return 'updated' if changed else 'unchanged'

    def _get_packages(self):
        self.ensure_one()
        if self.packages_data:
            try:
                data = json.loads(self.packages_data)
                if isinstance(data, dict):
                    return data
            except ValueError:
                pass
        if self.raw_data:
            try:
                pkg = json.loads(self.raw_data)
                if isinstance(pkg, dict):
                    return {_pkg_key(pkg): pkg}
            except ValueError:
                pass
        return {}

    @api.model
    def _n11_order_date(self, pkgs):
        """Sipariş tarihi: paketlerdeki 'Created' geçmiş kaydının en erkeni (orderDate gelirse o)."""
        dates = []
        for pkg in pkgs:
            if pkg.get('orderDate'):
                dates.append(n11_datetime(pkg['orderDate']))
            for hist in pkg.get('packageHistories') or []:
                if _status(hist.get('status')) == 'Created':
                    dates.append(n11_datetime(hist.get('createdDate')))
        dates = [d for d in dates if d]
        if dates:
            return min(dates)
        modified = [n11_datetime(p.get('lastModifiedDate')) for p in pkgs]
        modified = [d for d in modified if d]
        return min(modified) if modified else fields.Datetime.now()

    @api.model
    def _primary_package(self, pkgs):
        """Başlık / kargo bilgisi için esas paket: iptal olmayan, en son değişen paket."""
        pkgs = list(pkgs)
        ranked = sorted(pkgs, key=lambda p: (
            _pkg_status(p) != 'Unpacked',
            _pkg_status(p) not in N11_CANCEL_STATUSES,
            int(p.get('lastModifiedDate') or 0),
        ), reverse=True)
        return ranked[0] if ranked else {}

    @api.model
    def _order_header_vals(self, store, order_number, pkgs, order_date):
        pkg = self._primary_package(pkgs.values())
        ship = pkg.get('shippingAddress') or {}
        bill = pkg.get('billingAddress') or {}
        tax_number = str(bill.get('taxId') or pkg.get('taxId') or '').strip()
        try:
            invoice_type = int(bill.get('invoiceType') or 1)
        except (TypeError, ValueError):
            invoice_type = 1
        if tax_number and len(tax_number) == 10:
            invoice_type = 2  # VKN varsa kurumsal fatura
        return {
            'store_id': store.id,
            'order_id': _pkg_key(pkg),
            'order_number': str(order_number),
            'order_date': order_date,
            'order_status': _pkg_status(pkg),
            'invoice_type': invoice_type,
            'tax_number': tax_number if invoice_type == 2 else '',
            'customer_id': str(pkg.get('customerId') or ''),
            'customer_name': (
                (pkg.get('customerfullName') or '').strip()
                or (ship.get('fullName') or '').strip()
                or (bill.get('fullName') or '').strip()
            ),
            'customer_email': pkg.get('customerEmail') or '',
            'tax_office': bill.get('taxHouse') or pkg.get('taxOffice') or '',
            'shipment_address': json.dumps(ship, ensure_ascii=False),
            'billing_address': json.dumps(bill, ensure_ascii=False),
            'shipping_city': ship.get('city', ''),
            'shipping_district': ship.get('district', ''),
            'currency': pkg.get('currencyCode') or 'TRY',
        }

    @api.model
    def _line_vals(self, item, pkg):
        qty = int(item.get('quantity') or 1)
        # n11 sellerInvoiceAmount KDV DAHİL satır tutarıdır (satıcı indirimleri düşülmüş,
        # n11'in karşıladığı mallDiscount hariç). Odoo'da price_include vergi ile tam eşleşir.
        seller_invoice_amount = float(item.get('sellerInvoiceAmount') or 0.0)
        if seller_invoice_amount > 0 and qty > 0:
            unit_price = seller_invoice_amount / qty
        else:
            unit_price = float(item.get('price') or 0.0)
        status = 'Unpacked' if _pkg_status(pkg) == 'Unpacked' else (
            _status(item.get('orderItemLineItemStatusName')) or _pkg_status(pkg))
        return {
            'item_id': str(item.get('orderLineId') or ''),
            'package_id': str(pkg.get('id') or ''),
            'product_id': str(item.get('productId') or ''),
            'product_name': item.get('productName') or '',
            'product_code': item.get('barcode') or item.get('stockCode') or '',
            'quantity': qty,
            'sale_price': unit_price,
            'vat_rate': float(item.get('vatRate') or 0),
            'status': status,
            'cargo_tracking': str(pkg.get('cargoTrackingNumber') or ''),
            'cargo_company': pkg.get('cargoProviderName') or '',
        }

    def _apply_packages(self, packages):
        """Paketleri kayda işler (kalemler orderLineId ile eşleşir). Değişiklik olduysa True."""
        self.ensure_one()
        pkgs = list(packages.values())
        existing = {l.item_id: l for l in self.line_ids if l.item_id}
        commands = []
        seen = set()
        for pkg in pkgs:
            for item in pkg.get('lines') or []:
                vals = self._line_vals(item, pkg)
                if not vals['item_id'] or vals['item_id'] in seen:
                    continue
                seen.add(vals['item_id'])
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
        header.update(self._header_status_vals(pkgs))
        header['packages_data'] = json.dumps(packages, ensure_ascii=False, sort_keys=True)
        header = {k: v for k, v in header.items() if k == 'line_ids' or self[k] != v}
        if not header:
            return False
        self.write(header)
        return bool(commands) or any(k != 'packages_data' for k in header)

    def _header_status_vals(self, pkgs):
        """Sipariş durumu, kısmi iptal ve kargo bilgisi — kalem ve paket durumlarından."""
        active_pkgs = [p for p in pkgs if _pkg_status(p) != 'Unpacked'] or pkgs
        line_statuses = []
        for pkg in active_pkgs:
            for item in pkg.get('lines') or []:
                line_statuses.append(_status(item.get('orderItemLineItemStatusName')) or _pkg_status(pkg))
        live_pkgs = [p for p in active_pkgs if _pkg_status(p) not in N11_CANCEL_STATUSES]
        live_lines = [s for s in line_statuses if s not in N11_CANCEL_STATUSES]

        if (line_statuses and not live_lines) or not live_pkgs:
            pkg_statuses = {_pkg_status(p) for p in active_pkgs} | set(line_statuses)
            status = 'UnSupplied' if pkg_statuses <= {'UnSupplied'} else 'Cancelled'
            partial = False
        else:
            status = min((_pkg_status(p) for p in live_pkgs), key=lambda s: N11_STATUS_RANK.get(s, 0))
            partial = len(live_lines) < len(line_statuses)

        primary = self._primary_package(active_pkgs)
        live_total = 0.0
        for pkg in live_pkgs:
            for item in pkg.get('lines') or []:
                if _status(item.get('orderItemLineItemStatusName')) not in N11_CANCEL_STATUSES:
                    live_total += float(item.get('sellerInvoiceAmount') or 0.0)
        agreed = [n11_datetime(p.get('agreedDeliveryDate')) for p in live_pkgs]
        agreed = [d for d in agreed if d]
        modified = [n11_datetime(p.get('lastModifiedDate')) for p in pkgs]
        modified = [d for d in modified if d]
        return {
            'order_id': _pkg_key(primary),
            'order_status': status,
            'partially_cancelled': partial,
            'cargo_tracking_number': str(primary.get('cargoTrackingNumber') or ''),
            'cargo_provider': primary.get('cargoProviderName') or '',
            'cargo_tracking_link': primary.get('cargoTrackingLink') or '',
            'agreed_delivery_date': min(agreed) if agreed else False,
            'last_modified_date': max(modified) if modified else False,
            'delivery_address_type': primary.get('deliveryAddressType') or '',
            'is_micro': bool(primary.get('micro')),
            'total_price': sum(float(p.get('totalAmount') or 0.0) for p in active_pkgs),
            'seller_invoice_total': round(live_total, 2),
            'raw_data': json.dumps(primary, ensure_ascii=False),
        }

    # ─── n11.order → sale.order ──────────────────────────────

    def _active_lines(self):
        return self.line_ids.filtered(lambda l: l.status not in N11_INACTIVE_LINE_STATUSES)

    def _reconcile_sale_order(self, store):
        """Odoo siparişini n11 kalemleriyle eşitler: yoksa açar, tamamen iptalse iptal eder,
        kalemler değiştiyse (kısmi iptal) kalanlarla yeniden kurar."""
        self.ensure_one()
        lines = self._active_lines()
        cancelled = self.order_status in N11_CANCEL_STATUSES or not lines
        so = self.sale_order_id
        if not so:
            if cancelled:
                return
            so = self._create_odoo_sale_order(store)
            if so:
                self.write({'sale_order_id': so.id, 'error_message': False})
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
        so_lines = so.order_line.filtered(lambda l: l.n11_item_id and l.product_id)
        current = Counter()
        for sol in so_lines:
            current[sol.product_id.id] += int(sol.product_uom_qty)
        if wanted == current:
            self._remap_item_ids(so_lines, lines, product_map)
        elif any(qty > wanted.get(product_id, 0) for product_id, qty in current.items()):
            # n11'de kalem düştü (kısmi iptal / tedarik edilemedi) → kalanlarla yeniden kur
            reason = 'Kısmi iptal' if self.partially_cancelled else "n11 sipariş kalemleri değişti"
            self._rebuild_sale_order(store, reason)
        else:
            msg = (f"Odoo siparişi {so.name} n11 kalemleriyle uyuşmuyor (Odoo'da eksik ürün var); "
                   f"elle kontrol edin.")
            if self.error_message != msg:
                self.error_message = msg

    def _match_products(self, lines):
        Product = self.env['product.product']
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

    def _remap_item_ids(self, so_lines, lines, product_map):
        """Paket bölünmesinde kalem ID'leri değişir; Odoo satırlarındaki n11_item_id güncellenir."""
        ids_by_product = defaultdict(list)
        for line in lines:
            ids_by_product[product_map[line.product_code].id].append(line.item_id)
        for product_id, ids in ids_by_product.items():
            sols = so_lines.filtered(lambda l: l.product_id.id == product_id)
            if len(sols) == len(ids):
                pairs = zip(sols, ids)
            else:
                pairs = [(sols[0], ','.join(ids))] + [(s, '') for s in sols[1:]]
            for sol, item_id in pairs:
                if sol.n11_item_id != item_id and item_id:
                    sol.n11_item_id = item_id

    def _rebuild_sale_order(self, store, reason):
        """Mevcut Odoo siparişini iptal eder (Nebim'den de silinir), kalan kalemlerle yenisini açar."""
        old = self.sale_order_id
        if old.state == 'cancel':
            return
        if not store.auto_cancel:
            self.error_message = (f"{reason}: n11 siparişi değişti ancak 'İptalleri Otomatik İptal Et' kapalı; "
                                  f"Odoo siparişi {old.name} elle güncellenmeli.")
            return
        if old.picking_ids.filtered(lambda p: p.state == 'done'):
            self.error_message = f"{reason}: {old.name} sevk edildiği için otomatik güncellenmedi; elle kontrol edin."
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
        _logger.info("N11 sipariş %s: %s → %s yerine %s", self.order_number, reason, old.name, new.name)

    @api.model
    def _sale_tax_field(self):
        fields_ = self.env['sale.order.line']._fields
        return 'tax_ids' if 'tax_ids' in fields_ else ('tax_id' if 'tax_id' in fields_ else False)

    def _create_odoo_sale_order(self, store, partners=None):
        """Aktif n11 kalemlerinden Odoo siparişi oluşturur. Eşleşmeyen ürün varsa sipariş açılmaz."""
        self.ensure_one()
        lines = self._active_lines()
        product_map, missing = self._match_products(lines)
        if missing:
            msg = 'Ürün bulunamadı: ' + ', '.join(sorted(set(missing)))
            if self.error_message != msg:
                self.error_message = msg
            _logger.warning("N11 %s: %s", self.order_number, msg)
            return False

        if partners:
            partner, invoice_partner, shipping_partner = partners
        else:
            partner, invoice_partner, shipping_partner = self._find_or_create_partner(store)

        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param('n11_integration.warehouse_id')
        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': shipping_partner.id,
            'n11_store_id': store.id,
            'n11_order_id': self.id,
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
                'n11_item_id': line.item_id,
            }
            # Mikro ihracatta yurt dışına KDV uygulanmaz
            vat_rate = 0 if self.is_micro else (line.vat_rate or 0)
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
                    ol_vals[tax_field] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi bulunamadı, manuel dönüşüm yap
                    ol_vals['price_unit'] = line.sale_price / (1 + vat_rate / 100)
                    _logger.warning("N11: %%%d KDV dahil vergi bulunamadı, manuel dönüşüm yapıldı", int(vat_rate))
            sale_vals['order_line'].append((0, 0, ol_vals))

        return self.env['sale.order'].create(sale_vals)

    def _find_or_create_partner(self, store):
        """Müşteri (ana partner), fatura ve teslimat partnerlerini döndürür.

        Kurumsal siparişte (invoiceType=2 / VKN) ana partner firma olur: Nebim cari ve faturayı
        sale_order.partner_id'den okur. Firma kaydı aynı müşterinin bireysel kaydını ezmesin diye
        ayrı ref ({önek}{customerId}-{VKN}) kullanır."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        country_tr = self.env.ref('base.tr')
        pkg = self._primary_package(self._get_packages().values())
        ship = pkg.get('shippingAddress') or {}
        bill = pkg.get('billingAddress') or {}
        commercial = self.invoice_type == 2 and bool(self.tax_number)
        main_addr = bill if commercial and _addr_text(bill) else ship

        prefix = store.customer_prefix or ''
        customer_ref = f"{prefix}{self.customer_id}" if self.customer_id else ''
        if commercial:
            customer_ref = f"{customer_ref}-{self.tax_number}" if customer_ref else f"{prefix}VKN-{self.tax_number}"

        tc_id = str(pkg.get('tcIdentityNumber') or bill.get('tcId') or ship.get('tcId') or '').strip()
        # TC boş/kısa geliyorsa 11 haneli varsayılan ata (Nebim 11 hane zorunlu tutuyor)
        if len(tc_id) < 11:
            tc_id = _DUMMY_TC
        vat = self.tax_number if commercial else tc_id
        email = '' if store.skip_customer_email else (self.customer_email or '')

        def state_of(addr):
            city = addr.get('city') or ''
            if not city:
                return False
            state = self.env['res.country.state'].search(
                [('name', '=ilike', city), ('country_id', '=', country_tr.id)], limit=1)
            return state.id or False

        def addr_vals(addr):
            vals = {
                'street': _addr_text(addr)[:128],
                'street2': addr.get('neighborhood') or '',
                'city': addr.get('district') or addr.get('city') or '',
                'zip': addr.get('postalCode') or '',
                'country_id': country_tr.id,
            }
            state_id = state_of(addr)
            if state_id:
                vals['state_id'] = state_id
            return vals

        partner = Partner.search([('ref', '=', customer_ref)], limit=1) if customer_ref else Partner
        if not partner and not customer_ref:
            # Müşteri no yoksa yalnızca aynı isim + aynı il/ilçe eşleşmesi kabul edilir
            domain = [('name', '=ilike', self.customer_name), ('parent_id', '=', False),
                      ('city', '=ilike', main_addr.get('district') or main_addr.get('city') or '')]
            partner = Partner.search(domain, limit=1) if self.customer_name else Partner

        if not partner:
            vals = addr_vals(main_addr)
            vals.update({
                'name': self.customer_name or 'N11 Müşteri',
                'email': email,
                'phone': main_addr.get('gsm') or ship.get('gsm') or '',
                'ref': customer_ref,
                'company_type': 'company' if commercial else 'person',
                'vat': vat,
                'customer_rank': 1,
            })
            partner = Partner.create(vals)
        else:
            update_vals = {}
            for key, value in addr_vals(main_addr).items():
                current = partner[key].id if key in ('state_id', 'country_id') else partner[key]
                if value and current != value:
                    update_vals[key] = value
            if not partner.vat and vat:
                update_vals['vat'] = vat
            if update_vals:
                partner.write(update_vals)

        invoice_partner = shipping_partner = partner
        ship_text, bill_text = _addr_text(ship), _addr_text(bill)
        if commercial and ship_text and ship_text != partner.street:
            shipping_partner = self._child_partner(partner, 'delivery', ship, ship.get('fullName'), addr_vals)
        elif not commercial and bill_text and bill_text != ship_text:
            invoice_partner = self._child_partner(partner, 'invoice', bill, bill.get('fullName'), addr_vals, vat=tc_id)
        return partner, invoice_partner, shipping_partner

    def _child_partner(self, parent, ptype, addr, name, addr_vals, vat=None):
        Partner = self.env['res.partner'].sudo()
        text = _addr_text(addr)[:128]
        child = Partner.search([('parent_id', '=', parent.id), ('type', '=', ptype), ('street', '=', text)], limit=1)
        if child:
            return child
        vals = addr_vals(addr)
        vals.update({'parent_id': parent.id, 'type': ptype, 'name': (name or '').strip() or parent.name,
                     'phone': addr.get('gsm') or ''})
        if vat:
            vals['vat'] = vat
        return Partner.create(vals)

    # ─── ONAY (Created → Picking) ────────────────────────────

    def _auto_accept(self, store):
        """'Siparişi n11'de otomatik onayla' açıksa, Odoo'da onaylı siparişin Created kalemlerini onaylar."""
        self.ensure_one()
        if not store.auto_accept_orders:
            return
        so = self.sale_order_id
        if not so or so.state != 'sale':
            return
        lines = self.line_ids.filtered(lambda l: l.status == 'Created')
        if not lines:
            return
        now = fields.Datetime.now()
        if self.accept_attempt_date and now - self.accept_attempt_date < _ACCEPT_RETRY_AFTER:
            return
        self.accept_attempt_date = now
        self._accept_lines(store, lines, so, 'Otomatik onay')

    def _accept_lines(self, store, lines, record, source):
        """Kalemleri n11'de onaylar; sonucu kaleme ve kaydın (sipariş / transfer) chatter'ına yazar."""
        res = store.get_api().update_order_status_to_picking(lines.mapped('item_id'))
        if not res.get('success'):
            msg = f"N11 onay ({source}) başarısız: {res.get('error')}"
            record.message_post(body=msg)
            _logger.warning("N11 %s: %s", self.order_number, msg)
            return res
        results = res.get('lines') or {}
        ok_lines = lines.filtered(lambda l: results.get(l.item_id, (not results, ''))[0])
        failed = lines - ok_lines
        if ok_lines:
            ok_lines.write({'status': 'Picking'})
        parts = [f"N11 siparişi onaylandı ({source}): {len(ok_lines)} kalem Picking statüsüne alındı."]
        for line in failed:
            parts.append(f"✗ {line.product_code or line.item_id}: {results.get(line.item_id, (False, ''))[1]}")
        record.message_post(body='\n'.join(parts))
        return res

    # ─── İPTAL ────────────────────────────────────────────

    @api.private
    def _cancel_odoo_order(self, n11_order, store=None):
        """Odoo siparişini iptal et (Trendyol mantığıyla aynı)."""
        store = store or n11_order.store_id
        if store and not store.auto_cancel:
            return
        so = n11_order.sale_order_id
        if so and so.state not in ('cancel', 'done'):
            try:
                with self.env.cr.savepoint():
                    so._action_cancel()
                _logger.info("N11 — Odoo sipariş iptal edildi: %s (N11: %s)", so.name, n11_order.order_number)
            except Exception as e:
                _logger.warning("N11 — Sipariş iptal hatası: %s - %s", so.name, e)

    @api.private
    def _cancel_pending_orders(self, store):
        """Veritabanındaki iptal / tedarik edilemedi N11 siparişlerini tara,
        bağlı Odoo sale order henüz iptal edilmemişse iptal et."""
        if not store.auto_cancel:
            return 0
        cancelled_orders = self.search([
            ('store_id', '=', store.id),
            ('order_status', 'in', list(N11_CANCEL_STATUSES)),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', 'not in', ['cancel', 'done']),
        ])
        for n11_order in cancelled_orders:
            self._cancel_odoo_order(n11_order, store)
        return len(cancelled_orders)

    # ─── CRON ────────────────────────────────────────────

    @api.model
    def cron_sync_n11_orders(self):
        """Cron ile otomatik senkronizasyon — tüm aktif mağazalar.

        Trendyol modülündeki gibi güvenli wrapper: hata olsa bile cron çökmez.
        """
        try:
            self.sync_orders_from_n11()
        except Exception as e:
            _logger.exception("N11 cron senkronizasyon hatası: %s", e)

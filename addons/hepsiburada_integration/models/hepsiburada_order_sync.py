import json
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api

from .hepsiburada_order import HB_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

# Sahte/placeholder TC numaraları — HB bunları bireysel müşterilere atar
_DUMMY_TC_NUMBERS = {'11111111111', '00000000000', '99999999999', '12345678901'}

# /packages (gönderime hazır paketler): HB en fazla 10 kayıt döndürür
_OPEN_PAGE_LIMIT = 10
_OPEN_MAX_PAGES = 200
# shipped / delivered / undelivered / cancelled: en fazla 50
_HIST_PAGE_LIMIT = 50
_HIST_MAX_PAGES = 40
# Tarih filtresi reddedilirse eski yöntem (filtresiz) — üst sınır
_FALLBACK_MAX_PAGES = 20
_HB_DATE_FMT = '%Y-%m-%d %H:%M'

# (endpoint, Odoo'ya yazılacak statü, yanıttaki tarih alanı)
_HISTORY_ENDPOINTS = (
    ('shipped', 'Shipped', 'ShippedDate'),
    ('delivered', 'Delivered', 'DeliveredDate'),
    ('undelivered', 'UnDelivered', 'UndeliveredDate'),
)
# Açık paket listesi bu statülerin üzerine yazmasın
_FINAL_STATUSES = HB_CANCEL_STATUSES | {'Shipped', 'InTransit', 'Delivered', 'UnDelivered'}
# Sonradan gelen kalem bu sebeplerle oluştuysa sipariş yeniden kurulmaz (değişim, transfer vb.)
_REBUILD_CREATION_REASONS = {False, None, '', 'OrderCreated', 'DeliveryCreated'}


def _escape_like(value):
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _tr_now():
    """HB servisleri TR yerel saatiyle çalışır."""
    return datetime.utcnow() + timedelta(hours=3)


class HepsiburadaOrderSync(models.AbstractModel):
    _name = 'hepsiburada.order.sync'
    _description = 'Hepsiburada Sipariş Senkronizasyonu'

    @api.model
    def sync_orders(self):
        """Cron tarafından çağrılan ana metod. Tüm aktif mağazaların siparişlerini çeker."""
        stores = self.env['hepsiburada.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        if not stores:
            _logger.debug("Otomatik senkronizasyon için aktif Hepsiburada mağazası bulunamadı.")
            return

        for store in stores:
            self._sync_store_orders(store)

    @api.model
    def _store_domain(self, store):
        """Eski kayıtlarda store_id boş olabilir → merchant_id ile de eşleş."""
        return ['|', ('store_id', '=', store.id), ('merchant_id', '=', store.merchant_id)]

    @api.model
    def _sync_store_orders(self, store):
        store = store.sudo()
        sync_log = self.env['hepsiburada.sync.log'].sudo().create({
            'store_id': store.id,
            'sync_type': 'order',
            'name': f"Sipariş Senkronizasyonu - {fields.Datetime.now()}",
        })

        clean_merchant, clean_user, clean_pass = store._get_clean_credentials()

        if not clean_merchant or not clean_user or not clean_pass:
            error_msg = "Mağaza API ayarları (Merchant ID, User, Password) eksik. Lütfen kontrol edin."
            _logger.error(error_msg)
            sync_log.mark_error(error_msg)
            return

        # Connection pooling — tek session ile tüm istekler
        session, _unused = store._get_session()

        total_fetched = 0
        success_count = 0
        error_count = 0
        log_msgs = []

        # 1. İptaller ÖNCE (kalem bazlı): kısmi iptalde kalan ürünlerle sipariş yeniden kurulur
        cancel_count = 0
        try:
            with self.env.cr.savepoint():
                cancel_count = self._sync_cancellations(store, session, clean_merchant)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            log_msgs.append(f"İptal senkronizasyonu hatası: {e}")
            _logger.exception("HB iptal senkronizasyonu hatası [%s]: %s", store.name, e)

        # 2. Gönderime hazır paketler — önce tüm sayfalar toplanır, sonra tek seferde işlenir
        #    (aynı siparişin paketleri farklı sayfalara düşse de birlikte gruplanır)
        packages, fetch_error = self._fetch_open_packages(store, session, clean_merchant)
        if fetch_error:
            _logger.error("HB paket listesi alınamadı [%s]: %s", store.name, fetch_error)
            sync_log.mark_error(fetch_error)
            return

        processed, scsc, errc, msgs = self._process_orders(packages, store)
        total_fetched += processed
        success_count += scsc
        error_count += errc
        log_msgs.extend(msgs)

        # 3. Geçmiş sipariş statüleri (Kargoda, Teslim Edildi, Teslim Edilemedi)
        hist_processed, hist_succ, hist_err, hist_msgs = self._fetch_historical_statuses(store, session, clean_merchant)
        total_fetched += hist_processed
        success_count += hist_succ
        error_count += hist_err
        log_msgs.extend(hist_msgs)

        # 4. Bozulan (unpack) paketler — yalnızca bilgi amaçlı statü
        try:
            with self.env.cr.savepoint():
                self._sync_unpacked(store, session, clean_merchant)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.warning("HB unpack senkronizasyonu atlandı [%s]: %s", store.name, e)

        # 5. Veritabanındaki tam iptal siparişleri tara (önceki denemede iptal edilemeyenler dahil)
        try:
            with self.env.cr.savepoint():
                pending = self._cancel_pending_orders(store)
                if pending:
                    _logger.info("HB — %d sipariş Odoo'da iptal edildi", pending)
        except Exception as e:
            self.env.invalidate_all(flush=False)
            _logger.exception("HB iptal tarama hatası: %s", e)

        try:
            with self.env.cr.savepoint():
                store.write({'last_sync': fields.Datetime.now()})
        except Exception as _e:
            _logger.warning("HB mağaza last_sync güncelleme atlandı: %s", _e)
        if cancel_count:
            log_msgs.append(f"{cancel_count} siparişte iptal işlendi.")
        details_txt = "\n".join(log_msgs) if log_msgs else "Tüm kayıtlar sorunsuz aktarıldı."
        try:
            with self.env.cr.savepoint():
                sync_log.mark_done(
                    processed=total_fetched,
                    created=success_count,
                    failed=error_count,
                    details=details_txt
                )
        except Exception as _e:
            _logger.warning("HB sync log güncelleme atlandı: %s", _e)
        log_level = logging.INFO if (error_count or cancel_count) else logging.DEBUG
        _logger.log(log_level, "[%s] HB sipariş senk. tamamlandı. Toplam: %s, hata: %s, iptal: %s",
                    store.name, total_fetched, error_count, cancel_count)
        return True

    # ═════════════════════════════════════════════════════════════
    # API YARDIMCILARI
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _fetch_paged(self, session, url, limit, extra_params=None, max_pages=_HIST_MAX_PAGES):
        """limit/offset ile tüm sayfaları çeker. HTTP hatası → None, kayıt yok (404) → []."""
        items = []
        seen = set()
        for page in range(max_pages):
            params = dict(extra_params or {}, limit=limit, offset=page * limit)
            try:
                res = session.get(url, params=params, timeout=30)
            except Exception as e:
                _logger.warning("HB istek hatası %s: %s", url, e)
                return None
            if res.status_code == 404:
                break
            if res.status_code != 200:
                _logger.debug("HB HTTP %s %s: %s", res.status_code, url, res.text[:300])
                return None
            data = res.json()
            page_items = data if isinstance(data, list) else (data or {}).get('items', [])
            if not page_items:
                break
            # Güvenlik: offset yok sayılırsa aynı sayfa sonsuza kadar dönmesin
            new_items = []
            for item in page_items:
                key = json.dumps(item, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    new_items.append(item)
            if not new_items:
                break
            items.extend(new_items)
            if len(page_items) < limit:
                break
        return items

    @api.private
    def _fetch_windowed(self, session, url, days, limit):
        """Son N günü 24 saatlik pencerelerle çeker (HB bazı servislerde aralığı 24 saatle sınırlar).
        Tarih filtresi reddedilirse None döner."""
        now = _tr_now()
        items = []
        for i in range(max(days, 1)):
            end = now - timedelta(days=i)
            start = end - timedelta(days=1)
            got = self._fetch_paged(session, url, limit, {
                'begindate': start.strftime(_HB_DATE_FMT),
                'enddate': end.strftime(_HB_DATE_FMT),
            })
            if got is None:
                return None
            items.extend(got)
        return items

    @api.private
    def _fetch_open_packages(self, store, session, merchant):
        """Gönderime hazır paketler (otomatik paketleme açıkken yeni siparişler buradan gelir)."""
        url = f"https://{store._get_api_domain()}/packages/merchantid/{merchant}"
        packages = []
        seen = set()
        for page in range(_OPEN_MAX_PAGES):
            params = {'limit': _OPEN_PAGE_LIMIT, 'offset': page * _OPEN_PAGE_LIMIT}
            try:
                response = session.get(url, params=params, timeout=30)
            except Exception as e:
                return None, f"API İstek Hatası: {e}"
            if response.status_code != 200:
                return None, f"API Hatası HTTP {response.status_code}: {response.text[:500]}"
            data = response.json()
            items = data if isinstance(data, list) else (data or {}).get('items', [])
            if not items:
                break
            new_items = [p for p in items if (p.get('id') or p.get('packageNumber')) not in seen]
            if not new_items:
                break
            seen.update(p.get('id') or p.get('packageNumber') for p in new_items)
            packages.extend(new_items)
            if len(items) < _OPEN_PAGE_LIMIT:
                break
        return packages, None

    @api.private
    def _fetch_historical_statuses(self, store, session, merchant_id):
        """Kargoya verilen / teslim edilen / teslim edilemeyen paketlerin statülerini günceller;
        Odoo'da olmayan siparişlerin tam detayını çekip oluşturur."""
        day_limit = store.order_day_range or 3
        cutoff_date = _tr_now() - timedelta(days=day_limit)
        domain = store._get_api_domain()
        HbOrder = self.env['hepsiburada.order']

        processed_count = 0
        success_count = 0
        error_count = 0
        log_msgs = []
        missing_orders = []

        for endpoint, new_status, date_key in _HISTORY_ENDPOINTS:
            url = f"https://{domain}/packages/merchantid/{merchant_id}/{endpoint}"
            items = self._fetch_windowed(session, url, day_limit, _HIST_PAGE_LIMIT)
            if items is None:
                _logger.debug("HB %s: tarih filtresi kabul edilmedi, filtresiz deneniyor", endpoint)
                items = self._fetch_paged(session, url, _HIST_PAGE_LIMIT, max_pages=_FALLBACK_MAX_PAGES) or []

            for item in items:
                date_str = item.get(date_key) or item.get(date_key[0].lower() + date_key[1:])
                if date_str:
                    try:
                        item_date = datetime.strptime(str(date_str).split('.')[0][:19], '%Y-%m-%dT%H:%M:%S')
                        if item_date < cutoff_date:
                            continue
                    except ValueError:
                        pass

                order_nos = item.get('OrderNumbers') or [
                    item.get('OrderNumber') or item.get('orderNumber')]
                for order_no in filter(None, order_nos):
                    order_no = str(order_no)
                    hb_existing = HbOrder.search(
                        [('hb_order_number', '=', order_no)] + self._store_domain(store), limit=1)
                    if hb_existing and (hb_existing.sale_order_id
                                        or not any(l.remaining_qty for l in hb_existing.line_ids)):
                        if hb_existing.status != new_status and hb_existing.status not in HB_CANCEL_STATUSES:
                            hb_existing.write({'status': new_status})
                        continue
                    if order_no not in missing_orders:
                        missing_orders.append(order_no)

        # Eksik siparişlerin tam JSON'larını çek
        for m_order in missing_orders:
            full_json = self._fetch_full_order_detail(m_order, store, session, merchant_id)
            if full_json:
                p, s, e_c, m = self._process_orders([full_json], store)
                processed_count += p
                success_count += s
                error_count += e_c
                log_msgs.extend(m)

        return processed_count, success_count, error_count, log_msgs

    @api.private
    def _sync_unpacked(self, store, session, merchant_id):
        """Bozulan paketler: yalnızca paket numarasıyla gelir, statü bilgi amaçlı güncellenir.
        (Kalemler tekrar paketlenince açık paket listesinden yeni paket numarasıyla gelir.)"""
        url = f"https://{store._get_api_domain()}/packages/merchantid/{merchant_id}/status/unpacked"
        items = self._fetch_windowed(session, url, 1, _OPEN_PAGE_LIMIT) or []
        package_numbers = {str(i.get('packageNumber')) for i in items if i.get('packageNumber')}
        if not package_numbers:
            return
        orders = self.env['hepsiburada.order'].search([
            ('package_number', 'in', list(package_numbers)),
            ('status', 'not in', list(_FINAL_STATUSES | {'Unpacked'})),
        ] + self._store_domain(store))
        if orders:
            orders.write({'status': 'Unpacked'})

    @api.private
    def _fetch_full_order_detail(self, order_no, store, session, merchant_id):
        """Spesifik bir siparişin Müşteri ve Tutar dahil full JSON kopyasını çeker."""
        domain = store._get_api_domain()
        url = f"https://{domain}/orders/merchantId/{merchant_id}/orderNumber/{order_no}"

        try:
            res = session.get(url, timeout=30)
            if res.status_code == 200:
                return res.json()
            _logger.debug("HB sipariş detayı alınamadı (%s): HTTP %s", order_no, res.status_code)
        except Exception as e:
            _logger.error("Eksik Sipariş (No: %s) full detay API hatası: %s", order_no, e)

        return None

    # ═════════════════════════════════════════════════════════════
    # İPTAL YÖNETİMİ — kalem bazlı
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _sync_cancellations(self, store, session, merchant_id):
        """/orders/.../cancelled: iptal edilen KALEMLERİ (lineItemId + adet) döndürür."""
        url = f"https://{store._get_api_domain()}/orders/merchantid/{merchant_id}/cancelled"
        day_limit = store.order_day_range or 3
        items = self._fetch_windowed(session, url, day_limit, _HIST_PAGE_LIMIT)
        if items is None:
            _logger.warning("HB iptal listesi tarih filtresiyle alınamadı, filtresiz deneniyor [%s]", store.name)
            items = self._fetch_paged(session, url, _HIST_PAGE_LIMIT, max_pages=_FALLBACK_MAX_PAGES)
            if items is None:
                _logger.warning("HB iptal listesi alınamadı [%s]", store.name)
                return 0

        by_order = {}
        for item in items:
            order_no = item.get('orderNumber') or item.get('OrderNumber')
            line_id = item.get('lineItemId') or item.get('LineItemId') or item.get('id')
            if not order_no or not line_id:
                _logger.warning("HB iptal kaydı tanınamadı: %s", json.dumps(item, ensure_ascii=False)[:500])
                continue
            qty = int(item.get('quantity') or item.get('Quantity') or 0)
            key = f"{line_id}|{item.get('cancelDate') or item.get('CancelDate') or ''}|{qty}"
            by_order.setdefault(str(order_no), []).append((str(line_id), qty, key))

        HbOrder = self.env['hepsiburada.order']
        count = 0
        for order_no, cancels in by_order.items():
            hb_order = HbOrder.search([('hb_order_number', '=', order_no)] + self._store_domain(store), limit=1)
            if not hb_order:
                continue  # Odoo'ya hiç düşmemiş sipariş: iptal kalemleri zaten aktarılmaz
            try:
                with self.env.cr.savepoint():
                    if self._apply_cancellations(hb_order, cancels, store):
                        count += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("HB iptal işlenemedi (%s): %s", order_no, e)
        return count

    @api.private
    def _apply_cancellations(self, hb_order, cancels, store):
        """İptal kalemlerini düşer. Tamamı iptalse sipariş iptal; kısmiyse kalanlarla yeniden kurulur.
        Aynı iptal kaydı iki kez işlenmez (cancel_keys). Değişiklik olduysa True."""
        changed = False
        for line_id, qty, key in cancels:
            lines = hb_order.line_ids.filtered(lambda l: l.line_item_id == line_id)
            if not lines:
                continue
            if any(key in (l.cancel_keys or '').split('\n') for l in lines):
                continue
            to_cancel = qty or sum(lines.mapped('quantity'))
            for idx, line in enumerate(lines):
                vals = {}
                take = min(max(line.quantity - line.cancelled_qty, 0), to_cancel)
                if take > 0:
                    vals['cancelled_qty'] = line.cancelled_qty + take
                    to_cancel -= take
                    changed = True
                if idx == 0:
                    vals['cancel_keys'] = '\n'.join(filter(None, [line.cancel_keys, key]))
                if vals.get('cancelled_qty', line.cancelled_qty) >= line.quantity:
                    vals['status'] = 'Cancelled'
                line.write(vals)

        if not changed:
            return False

        if all(l.remaining_qty <= 0 for l in hb_order.line_ids):
            hb_order.write({'status': 'Cancelled', 'partially_cancelled': False})
            self._cancel_odoo_order(hb_order, store)
            _logger.info("HB sipariş %s: tüm kalemler iptal edildi", hb_order.hb_order_number)
        else:
            hb_order.write({'partially_cancelled': True})
            self._rebuild_sale_order(hb_order, store, 'Kısmi iptal')
        return True

    @api.private
    def _rebuild_sale_order(self, hb_order, store, reason):
        """Mevcut Odoo siparişini iptal eder (Nebim'den de silinir), kalan kalemlerle yenisini açar."""
        old = hb_order.sale_order_id
        if old and old.state == 'cancel':
            return  # elle iptal edilmiş sipariş yeniden açılmaz
        if old:
            if not store.auto_cancel:
                hb_order.write({'warning_message':
                    f"{reason}: Hepsiburada siparişi değişti ancak 'İptalleri Otomatik İptal Et' kapalı; "
                    f"Odoo siparişi {old.name} elle güncellenmeli."})
                return
            if old.picking_ids.filtered(lambda p: p.state == 'done'):
                hb_order.write({'warning_message':
                    f"{reason}: {old.name} sevk edildiği için otomatik güncellenmedi; elle kontrol edin."})
                return
            old._action_cancel()

        partner = old.partner_id if old else self._find_or_create_partner(hb_order, store)
        new = self._create_sale_order(hb_order, partner, store)
        hb_order.write({'sale_order_id': new.id or False})
        if new and old:
            new.message_post(body=f"{reason}: önceki sipariş {old.name} iptal edildi, "
                                  f"kalan ürünlerle yeniden oluşturuldu.")
            old.message_post(body=f"{reason}: yerine {new.name} oluşturuldu.")
        _logger.info("HB sipariş %s: %s → %s yerine %s",
                     hb_order.hb_order_number, reason, old.name if old else '-', new.name if new else '-')

    @api.private
    def _cancel_odoo_order(self, hb_order, store=None):
        """Odoo siparişini iptal et."""
        if store and not store.auto_cancel:
            return
        so = hb_order.sale_order_id
        if so and so.state != 'cancel':
            try:
                with self.env.cr.savepoint():
                    so._action_cancel()
                _logger.info("HB — Odoo sipariş iptal edildi: %s (HB: %s)", so.name, hb_order.hb_order_number)
            except Exception as e:
                _logger.warning("HB — Sipariş iptal hatası: %s - %s", so.name, e)

    @api.private
    def _cancel_pending_orders(self, store):
        """Tamamen iptal HB siparişlerinden Odoo'da hâlâ açık olanları iptal et."""
        if not store.auto_cancel:
            return 0
        cancelled_orders = self.env['hepsiburada.order'].search([
            ('status', 'in', list(HB_CANCEL_STATUSES) + ['cancelled']),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', '!=', 'cancel'),
        ] + self._store_domain(store))
        for hb_order in cancelled_orders:
            self._cancel_odoo_order(hb_order, store)
        return len(cancelled_orders)

    # ═════════════════════════════════════════════════════════════
    # SİPARİŞ İŞLEME
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _process_orders(self, packages, store, skip_date_filter=False):
        """API'den gelen paket listesini sipariş numarasına göre gruplayıp kaydeder."""
        store = store.sudo()
        _logger.debug("Hepsiburada _process_orders: %s paket", len(packages))
        orders_dict = {}
        for pkg in packages:
            order_no = None
            pkg_items = pkg.get('items', [])

            if store.order_ref_type == 'package_id':
                order_no = pkg.get('packageNumber')
                if not order_no and pkg_items:
                    order_no = pkg_items[0].get('packageNumber')
            else:
                if pkg_items:
                    order_no = pkg_items[0].get('orderNumber')
                if not order_no:
                    order_no = pkg.get('orderNumber') or pkg.get('packageNumber')

            if not order_no:
                continue

            orders_dict.setdefault(str(order_no), []).append(pkg)

        _logger.debug("HB: %s farklı sipariş", len(orders_dict))

        success_count = 0
        error_count = 0
        log_msgs = []

        day_limit = store.order_day_range or 3
        cutoff_date = _tr_now() - timedelta(days=day_limit)
        for order_no, line_items in orders_dict.items():
            # ── Client-side tarih filtresi (tekil çekimde devre dışı) ──
            if not skip_date_filter:
                order_dt = self._parse_hb_datetime(self._order_date_str(line_items[0]))
                if order_dt and order_dt < cutoff_date:
                    _logger.debug("Eski sipariş atlandı (orderDate=%s < %s): %s", order_dt, cutoff_date, order_no)
                    continue

            try:
                with self.env.cr.savepoint():
                    self._create_or_update_order(order_no, line_items, store)
                    success_count += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                err = f"Sipariş No {order_no} işlenirken hata: {str(e)}"
                _logger.error(err)
                log_msgs.append(err)
                error_count += 1

        return len(orders_dict), success_count, error_count, log_msgs

    @api.model
    def _order_date_str(self, pkg):
        """Paket formatında kökte, detay formatında kalemde / createdDate'te gelir."""
        items = pkg.get('items') or [{}]
        return pkg.get('orderDate') or items[0].get('orderDate') or pkg.get('createdDate') or ''

    @api.model
    def _parse_hb_datetime(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None

    @api.model
    def _item_line_id(self, item):
        return str(item.get('id') or item.get('lineItemId') or '')

    # ═════════════════════════════════════════════════════════════
    # SİPARİŞ OLUŞTURMA — HER İKİ API FORMAT DESTEĞİ
    # Format 1 (flat):   /packages/ endpoint → root seviyesinde alanlar
    # Format 2 (nested): /orders/   endpoint → customer/invoice/deliveryAddress
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _create_or_update_order(self, order_no, packages, store):
        env = self.env
        HbOrder = env['hepsiburada.order']

        all_items = []
        for pkg in packages:
            all_items.extend(pkg.get('items', []))
        first_pkg = packages[0]
        first_item = all_items[0] if all_items else {}

        existing = HbOrder.search([('hb_order_number', '=', order_no)] + self._store_domain(store), limit=1)
        if existing:
            return self._update_existing_order(existing, first_pkg, first_item, all_items, store)

        # ── Müşteri Adı ──
        customer_name = (
            first_pkg.get('customer', {}).get('name', '') or   # Format 2
            first_pkg.get('customerName', '') or                # Format 1
            first_pkg.get('recipientName', '') or               # Format 1
            first_pkg.get('companyName', '') or                 # Format 1
            first_item.get('customerName', '')                  # Fallback
        )

        # ── Fatura / Vergi ──
        invoice_obj = first_pkg.get('invoice', {}) or {}
        invoice_addr = invoice_obj.get('address', {}) or {}

        tax_office = invoice_obj.get('taxOffice', '') or first_pkg.get('taxOffice', '') or ''
        tax_number = invoice_obj.get('taxNumber', '') or first_pkg.get('taxNumber', '') or ''
        tc_number = invoice_obj.get('turkishIdentityNumber', '') or first_pkg.get('identityNo', '') or ''
        tax_id_value = tax_number or tc_number

        # ── Email / Telefon ──
        delivery_addr = first_pkg.get('deliveryAddress', {}) or {}
        customer_email = invoice_addr.get('email', '') or first_pkg.get('email', '') or ''
        customer_phone = (
            delivery_addr.get('phoneNumber', '') or
            delivery_addr.get('alternatePhoneNumber', '') or
            invoice_addr.get('phoneNumber', '') or
            first_pkg.get('phoneNumber', '') or ''
        )

        # ── Teslimat Adresi ──
        shipping_address = delivery_addr.get('address', '') or first_pkg.get('shippingAddressDetail', '') or ''
        shipping_city = delivery_addr.get('city', '') or first_pkg.get('shippingCity', '') or ''
        shipping_district = delivery_addr.get('town', '') or first_pkg.get('shippingTown', '') or ''
        country_code = (
            delivery_addr.get('countryCode', '') or first_pkg.get('shippingCountryCode', '') or 'TR'
        )

        # ── Durum / Kargo ──
        status = first_item.get('status', '') or first_pkg.get('status', '') or ''
        cargo_company = first_item.get('cargoCompany', '') or first_pkg.get('cargoCompany', '') or ''
        cargo_model = first_item.get('cargoCompanyModel', {}) or {}
        cargo_provider = cargo_model.get('name', '') or cargo_model.get('shortName', '') or cargo_company
        package_number = first_item.get('packageNumber', '') or first_pkg.get('packageNumber', '') or ''
        cargo_tracking = first_item.get('barcode', '') or first_pkg.get('barcode', '') or ''

        # ── Sipariş Tarihi ── HB TR yerel saatinde gelir (UTC+3), Odoo UTC bekler
        order_date = False
        dt_local = self._parse_hb_datetime(self._order_date_str(first_pkg))
        if dt_local:
            order_date = fields.Datetime.to_string(dt_local - timedelta(hours=3))

        # ── Toplam Tutar ──
        root_total = first_pkg.get('totalPrice', {})
        total_price = root_total.get('amount', 0.0) if isinstance(root_total, dict) else 0.0
        items_total = sum((item.get('totalPrice') or {}).get('amount', 0.0) for item in all_items)
        if items_total > 0:
            total_price = items_total

        currency = 'TRY'
        if all_items and isinstance(all_items[0].get('totalPrice', {}), dict):
            currency = all_items[0]['totalPrice'].get('currency', 'TRY')

        # ── Desi ── (paket formatında kökte, detayda kalem bazında)
        total_deci = sum(float(p.get('totalDeci') or 0.0) for p in packages)
        if not total_deci:
            total_deci = sum(float(i.get('totalDeci') or 0.0) for i in all_items)

        hb_order = HbOrder.create({
            'hb_order_number': order_no,
            'merchant_id': store.merchant_id,
            'store_id': store.id,
            'order_date': order_date,
            'status': status,
            'is_micro_export': any(i.get('isMicroExport') for i in all_items),
            'cargo_company': cargo_company,
            'cargo_provider': cargo_provider,
            'cargo_tracking_number': cargo_tracking,
            'package_number': package_number,
            'total_deci': total_deci,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'tax_office': tax_office,
            'tax_number': tax_id_value,
            'shipping_address': shipping_address,
            'shipping_city': shipping_city,
            'shipping_district': shipping_district,
            'shipping_country_code': (country_code or 'TR').upper(),
            'total_price': total_price,
            'currency': currency,
            'raw_payload': json.dumps(packages, ensure_ascii=False)
        })

        self._create_lines(hb_order, all_items, store)

        # Detaydan gelen siparişte tüm kalemler zaten iptal olabilir → Odoo siparişi açılmaz
        if hb_order.line_ids and not any(l.remaining_qty for l in hb_order.line_ids):
            hb_order.write({'status': 'Cancelled'})
        else:
            if any(l.cancelled_qty for l in hb_order.line_ids):
                hb_order.write({'partially_cancelled': True})
            partner = self._find_or_create_partner(hb_order, store)
            sale_order = self._create_sale_order(hb_order, partner, store)
            hb_order.write({'sale_order_id': sale_order.id or False})

        # Finans / iade kayıtları siparişten önce geldiyse bağla
        env['hepsiburada.transaction']._link_orphans(hb_order)
        env['hepsiburada.claim'].sudo().search([
            ('order_id', '=', False), ('store_id', '=', store.id),
            ('order_number', '=', hb_order.hb_order_number),
        ]).write({'order_id': hb_order.id})
        return hb_order

    @api.private
    def _update_existing_order(self, existing, first_pkg, first_item, all_items, store):
        vals = {}
        new_status = first_item.get('status', '') or first_pkg.get('status', '') or ''
        if new_status and existing.status != new_status and existing.status not in _FINAL_STATUSES:
            vals['status'] = new_status
        # Paket bozulup yeniden paketlenince paket numarası / barkod değişir
        package_number = first_item.get('packageNumber', '') or first_pkg.get('packageNumber', '') or ''
        if package_number and existing.package_number != str(package_number):
            vals['package_number'] = str(package_number)
        barcode = first_item.get('barcode', '') or first_pkg.get('barcode', '') or ''
        if barcode and existing.cargo_tracking_number != barcode:
            vals['cargo_tracking_number'] = barcode
        if not existing.store_id:
            vals['store_id'] = store.id
        if vals:
            existing.write(vals)

        # Sonradan gelen kalem (ayrı paketlenmiş vb.) — sipariş kalemleriyle yeniden kurulur
        known = set(existing.line_ids.mapped('line_item_id'))
        new_items = [it for it in all_items if self._item_line_id(it) and self._item_line_id(it) not in known]
        if new_items:
            self._create_lines(existing, new_items, store)
            reasons = {it.get('creationReason') for it in new_items}
            if reasons <= _REBUILD_CREATION_REASONS and existing.status not in _FINAL_STATUSES:
                self._rebuild_sale_order(existing, store, 'Yeni kalem')
            else:
                existing.write({'warning_message':
                    "Siparişe sonradan yeni kalem geldi (%s); Odoo siparişine otomatik eklenmedi, "
                    "elle kontrol edin." % ', '.join(sorted(filter(None, map(str, reasons))) or ['-'])})
            return existing

        # sale.order silinmiş ve iptal olmayan kalem varsa yeniden oluştur
        if existing.sale_order_id.exists() or not any(l.remaining_qty for l in existing.line_ids):
            return existing
        _logger.info("HB sipariş %s: sale.order bulunamadı, yeniden oluşturuluyor.", existing.hb_order_number)
        partner = self._find_or_create_partner(existing, store)
        sale_order = self._create_sale_order(existing, partner, store)
        existing.write({'sale_order_id': sale_order.id or False})
        return existing

    @api.private
    def _create_lines(self, hb_order, items, store):
        OrderLine = self.env['hepsiburada.order.line']
        for item in items:
            item_total = (item.get('totalPrice') or {}).get('amount', 0.0) if isinstance(item.get('totalPrice'), dict) else 0.0
            # unitPrice (her iki formatta dict)
            up_obj = item.get('unitPrice', {})
            item_unit = up_obj.get('amount', item_total) if isinstance(up_obj, dict) else item_total
            # merchantUnitPrice (Format 1'de dict, Format 2'de yok)
            mup_obj = item.get('merchantUnitPrice', {})
            merch_unit = mup_obj.get('amount', item_unit) if isinstance(mup_obj, dict) else (mup_obj or item_unit)
            # price fallback (Format 1)
            price_obj = item.get('price', {})
            if isinstance(price_obj, dict) and item_total == 0:
                item_total = price_obj.get('amount', 0.0)

            commission = item.get('commission', {})
            quantity = int(item.get('quantity', 1) or 1)
            line_status = item.get('status', '') or hb_order.status or ''
            vals = {
                'order_id': hb_order.id,
                'line_item_id': self._item_line_id(item),
                'sku': item.get('sku', '') or item.get('hbSku', ''),
                'merchant_sku': (
                    item.get('merchantSKU', '') or      # Format 2: büyük SKU
                    item.get('merchantSku', '') or      # Format 1: küçük sku
                    item.get('productBarcode', '') or ''
                ),
                'product_name': item.get('name', '') or item.get('productName', ''),
                'quantity': quantity,
                'price': item_total,
                'merchant_unit_price': merch_unit,
                'vat': item.get('vat', 0.0),
                'vat_rate': item.get('vatRate', 0.0),
                'status': line_status,
            }
            if store.process_commission:
                vals['commission_amount'] = commission.get('amount', 0.0) if isinstance(commission, dict) else 0.0
                vals['commission_rate'] = item.get('commissionRate', 0.0)
            # Detay servisinde iptal kalemler de gelir → baştan iptal say
            if line_status in HB_CANCEL_STATUSES:
                vals['cancelled_qty'] = quantity
                vals['cancel_keys'] = f"{vals['line_item_id']}|detail"
            OrderLine.create(vals)

    # ═════════════════════════════════════════════════════════════
    # MÜŞTERİ — e-posta ile eşleşir (Nebim cari eşleştirmesi ve Trendyol ile aynı)
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _find_or_create_partner(self, hb_order, store):
        ResPartner = self.env['res.partner']
        if hb_order.is_micro_export and store.micro_export_prefix:
            prefix = store.micro_export_prefix
        else:
            prefix = store.customer_prefix or 'HB-'

        # Gerçek TC/VKN mi sahte mi kontrol et
        tax_no = (hb_order.tax_number or '').strip()
        is_real_tax = bool(tax_no) and tax_no not in _DUMMY_TC_NUMBERS and len(tax_no) >= 10
        email = (hb_order.customer_email or '').strip()
        use_email = bool(email) and not store.skip_customer_email

        # Ref oluşturma — sahte TC ile ref oluşturMA
        if is_real_tax:
            ref_val = f"{prefix}{tax_no}"
        elif hb_order.customer_name:
            ref_val = f"{prefix}{hb_order.customer_name}"
        else:
            ref_val = ''

        # ── Müşteri eşleştirme ──
        partner = ResPartner
        # 1. Gerçek vergi numarası
        if is_real_tax:
            partner = ResPartner.search([('ref', '=', ref_val)], limit=1)
            if not partner:
                partner = ResPartner.search([('vat', '=', tax_no)], limit=1)
        # 2. E-posta (aynı kişi — Nebim'de de cari e-postadan eşleşir)
        if not partner and use_email:
            partner = ResPartner.search([('email', '=ilike', _escape_like(email))], order='id desc', limit=1)
        # 3. E-posta kullanılamıyorsa: ad + telefon birlikte (yalnızca ad → farklı kişiler birleşirdi)
        if not partner and not use_email and hb_order.customer_name and hb_order.customer_phone:
            partner = ResPartner.search([
                ('name', '=ilike', _escape_like(hb_order.customer_name)),
                ('phone', '=', hb_order.customer_phone),
            ], order='id desc', limit=1)

        # ── Ülke / İl ──
        country = self.env['res.country'].search(
            [('code', '=', (hb_order.shipping_country_code or 'TR').upper())], limit=1) or self.env.ref('base.tr')
        state_id = False
        city_name = hb_order.shipping_district or ''
        if hb_order.shipping_city and country.code == 'TR':
            state = self.env['res.country.state'].search([
                ('name', '=ilike', hb_order.shipping_city),
                ('country_id', '=', country.id),
            ], limit=1)
            state_id = state.id or False

        if not partner:
            vals = {
                'name': hb_order.customer_name or 'Bilinmeyen Müşteri',
                'phone': hb_order.customer_phone,
                'email': email if use_email else '',
                'country_id': country.id,
                'state_id': state_id,
                'city': city_name,
                'street': hb_order.shipping_address,
            }
            if ref_val:
                vals['ref'] = ref_val
            if is_real_tax:
                vals['vat'] = tax_no
                vals['company_type'] = 'company' if len(tax_no) == 10 else 'person'
            return ResPartner.create(vals)

        update_vals = {}
        # İsim güncelle — eski "Adsız" kayıtlarını düzelt
        if hb_order.customer_name and (not partner.name or partner.name in ('Adsız', 'Bilinmeyen Müşteri')):
            update_vals['name'] = hb_order.customer_name
        if ref_val and not partner.ref:
            update_vals['ref'] = ref_val
        # Aynı kişi (vergi no / e-posta / ad+telefon) → güncel teslimat adresi
        if hb_order.shipping_address and partner.street != hb_order.shipping_address:
            update_vals['street'] = hb_order.shipping_address
        if state_id and partner.state_id.id != state_id:
            update_vals['state_id'] = state_id
        if city_name and partner.city != city_name:
            update_vals['city'] = city_name
        if country and partner.country_id != country:
            update_vals['country_id'] = country.id
        if is_real_tax and not partner.vat:
            update_vals['vat'] = tax_no
        if hb_order.customer_phone and not partner.phone:
            update_vals['phone'] = hb_order.customer_phone
        if use_email and not partner.email:
            update_vals['email'] = email
        if update_vals:
            partner.write(update_vals)
        return partner

    # ═════════════════════════════════════════════════════════════
    # SATIŞ SİPARİŞİ OLUŞTURMA
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _create_sale_order(self, hb_order, partner, store):
        """Kalan (iptal edilmemiş) kalemlerle Odoo siparişi açar.
        Ürünü bulunamayan kalem varsa sipariş onaylanmaz (eksik sipariş Nebim'e gitmesin)."""
        SaleOrder = self.env['sale.order']
        Product = self.env['product.product']

        lines = hb_order.line_ids.filtered(lambda l: l.remaining_qty > 0)
        if not lines:
            return SaleOrder

        # Batch ürün arama — merkezî metod
        all_codes = [c for line in lines for c in (line.merchant_sku, line.sku) if c]
        product_map = Product.batch_find_by_marketplace_barcodes(all_codes) if all_codes else {}

        # Tax cache — N+1 önleme
        tax_cache = {}
        tax_field = 'tax_ids' if 'tax_ids' in self.env['sale.order.line']._fields else (
            'tax_id' if 'tax_id' in self.env['sale.order.line']._fields else False)

        order_lines = []
        missing = []
        for line in lines:
            # Ürünü bul — batch'ten, yoksa tekli fallback
            product = product_map.get(line.merchant_sku) or product_map.get(line.sku)
            if not product and line.merchant_sku:
                product = Product.find_by_marketplace_barcode(line.merchant_sku)
            if not product and line.sku:
                product = Product.find_by_marketplace_barcode(line.sku)

            if not product:
                _logger.warning("HB Ürün bulunamadı: merchant_sku=%s, sku=%s, ürün adı=%s",
                                line.merchant_sku, line.sku, line.product_name)
                missing.append(line)
                continue

            # HB line.price = totalPrice (satır toplamı, KDV DAHİL, orijinal adet için)
            # merchant_unit_price zaten birim fiyat olduğu için bölmeye gerek yok
            raw_price = line.price if line.price > 0 else line.merchant_unit_price
            orig_qty = line.quantity or 1
            unit_price = raw_price / orig_qty if (line.price > 0 and orig_qty > 1) else raw_price

            ol_vals = {
                'product_id': product.id,
                'product_uom_qty': line.remaining_qty,
                'price_unit': unit_price,
                'name': f"[HB] {line.product_name}",
            }

            # KDV dahil vergi bul — yuvarlama farkı olmasın
            vat_rate = line.vat_rate
            if vat_rate > 0:
                if vat_rate not in tax_cache:
                    tax_cache[vat_rate] = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', vat_rate),
                        ('price_include', '=', True),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                include_tax = tax_cache[vat_rate]
                if include_tax:
                    if tax_field:
                        ol_vals[tax_field] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi bulunamadı — manuel dönüşüm
                    ol_vals['price_unit'] = unit_price / (1 + vat_rate / 100)
                    _logger.warning("HB: %%%d KDV dahil vergi bulunamadı, manuel dönüşüm", int(vat_rate))

            order_lines.append((0, 0, ol_vals))

        if missing:
            note = "⚠ Odoo'da bulunamayan Hepsiburada ürünleri:\n" + "\n".join(
                f"- {l.product_name or '-'} | Stok kodu: {l.merchant_sku or '-'} | "
                f"HB SKU: {l.sku or '-'} | Adet: {l.remaining_qty}" for l in missing)
            order_lines.append((0, 0, {'display_type': 'line_note', 'name': note}))

        ICP = self.env['ir.config_parameter'].sudo()
        # ── Depo — Trendyol modeli: parametre varsa set et, yoksa Odoo default ──
        warehouse_id = int(ICP.get_param('hepsiburada_integration.warehouse_id', 0))

        sale_vals = {
            'partner_id': partner.id,
            'client_order_ref': hb_order.hb_order_number,
            'hb_order_id': hb_order.id,
            'hb_store_id': hb_order.merchant_id,
            'origin': hb_order.hb_order_number,
            'order_line': order_lines,
        }
        if hb_order.order_date:
            sale_vals['date_order'] = hb_order.order_date
        if warehouse_id and 'warehouse_id' in self.env['sale.order']._fields:
            sale_vals['warehouse_id'] = warehouse_id

        # Dedup kontrolü — iptal edilmiş eski sipariş (kısmi iptal) yeniden kurulumu engellemez
        ref_names = list(filter(None, [hb_order.hb_order_number, f"HB-{hb_order.hb_order_number}"]))
        existing_so = self.env['sale.order'].search([
            ('state', '!=', 'cancel'),
            '|', '|',
            ('client_order_ref', 'in', ref_names),
            ('origin', 'in', ref_names),
            ('name', 'in', ref_names)
        ], limit=1)
        if existing_so:
            _logger.info("HB: Odoo'da %s sipariş referanslı kayıt (%s) zaten var.",
                         hb_order.hb_order_number, existing_so.name)
            return existing_so

        sale_order = SaleOrder.create(sale_vals)
        _logger.info(
            "HB sipariş %s: sale.order oluşturuldu (%s), warehouse=%s",
            hb_order.hb_order_number, sale_order.name,
            sale_order.warehouse_id.name if sale_order.warehouse_id else 'Odoo default')

        warning = False
        if missing:
            warning = (
                f"{len(missing)} ürün Odoo'da bulunamadı "
                f"({', '.join(l.merchant_sku or l.sku or '-' for l in missing)}). "
                f"Sipariş onaylanmadı: ürünü eşleştirip {sale_order.name} siparişine ekleyin ve elle onaylayın.")
        elif store.auto_confirm:
            # ── Otomatik onayla — savepoint korumalı (Trendyol modeli) ──
            try:
                with self.env.cr.savepoint():
                    sale_order.action_confirm()
                    _logger.info("HB sipariş %s: sipariş onaylandı (%s).",
                                 hb_order.hb_order_number, sale_order.name)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                warning = f"Otomatik onay başarısız, sipariş taslakta bırakıldı: {e}"
                _logger.warning("HB sipariş %s: onay hatası (draft bırakıldı): %s",
                                hb_order.hb_order_number, e)
        hb_order.write({'warning_message': warning})
        return sale_order

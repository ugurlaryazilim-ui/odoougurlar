
"""Trendyol sipariş senkronizasyon logic'i — API'den çekme, işleme, güncelleme."""
import json
import logging
import time

from datetime import datetime, timedelta

from odoo import api, fields, models
from .trendyol_api import TrendyolAPI, ty_datetime

_logger = logging.getLogger(__name__)

# Trendyol'un sipariş servislerinde izin verdiği en uzun tarih aralığı
_MAX_WINDOW_DAYS = 14
# Akış (stream) sayfaları arası önerilen bekleme
_STREAM_PAGE_DELAY = 5
_STREAM_MAX_PAGES = 100
# Son senkrondan geriye güvenlik payı (gecikmeli güncellenen paketler kaçmasın)
_STREAM_OVERLAP = timedelta(minutes=30)
# Ödeme onayı bekleyen paketler: doküman "Created olana kadar işlem yapmayın" diyor
_SKIP_STATUSES = {'awaiting', 'verified'}
_CANCEL_STATUSES = {'cancelled', 'unsupplied'}
# Mağaza başına senkron kilidi (pg advisory lock ad alanı)
_SYNC_LOCK_NS = 7471001


class TrendyolOrderSync(models.Model):
    """Senkronizasyon ve sipariş işleme metodları."""
    _inherit = 'trendyol.order'

    @api.model
    def sync_orders_from_trendyol(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['trendyol.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        if not stores:
            _logger.warning("Senkronize edilecek aktif mağaza bulunamadı!")
            return {'created': 0, 'updated': 0, 'errors': 0}

        total_created = 0
        total_updated = 0
        total_errors = 0

        for store in stores:
            try:
                result = self.sync_orders_for_store(store)
                total_created += result.get('created', 0)
                total_updated += result.get('updated', 0)
                total_errors += result.get('errors', 0)
            except Exception as e:
                _logger.exception("Mağaza %s senkronizasyon hatası: %s", store.name, e)
                total_errors += 1

        return {
            'created': total_created,
            'updated': total_updated,
            'errors': total_errors,
        }

    @api.model
    def sync_orders_for_store(self, store):
        """Tek bir mağazadan siparişleri senkronize et.

        Trendyol'un periyodik senkron için önerdiği akış (stream) servisi kullanılır: son
        senkrondan beri değişen TÜM statülerdeki paketler tek akışta gelir. Akış servisi
        yanıt vermezse statü bazlı v2 sorgularına düşülür.
        """
        store_name = store.name or ''
        store_id = store.id

        # Aynı mağaza için tek senkron: cron sürerken "Şimdi Senkronize Et" (veya ikinci cron
        # işçisi) aynı paketleri paralel işleyip duplicate key / serialization hataları üretiyordu.
        # İşlem (transaction) bitince kilit kendiliğinden bırakılır.
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (_SYNC_LOCK_NS, store_id))
        if not self.env.cr.fetchone()[0]:
            _logger.info("Trendyol senkronizasyon [%s] atlandı: başka bir senkron çalışıyor", store_name)
            return {'error': f"{store_name} mağazasında senkronizasyon şu anda zaten çalışıyor. "
                             f"Birkaç dakika sonra tekrar deneyin.",
                    'busy': True, 'created': 0, 'updated': 0, 'errors': 0}

        try:
            api = store.get_api()
        except Exception as e:
            return {'error': str(e), 'created': 0, 'updated': 0, 'errors': 0}

        SyncLog = self.env['trendyol.sync.log'].sudo()
        log = SyncLog.create({
            'sync_type': 'order',
            'state': 'running',
            'start_date': fields.Datetime.now(),
            'store_id': store_id,
        })

        run_started = fields.Datetime.now()
        counters = {'created': 0, 'updated': 0, 'errors': 0, 'received': 0}
        error_details = []

        # Yeni sipariş olarak içeri alınacak en eski sipariş tarihi
        day_range = min(store.order_day_range or _MAX_WINDOW_DAYS, _MAX_WINDOW_DAYS)
        order_cutoff = datetime.utcnow() - timedelta(days=day_range)

        stream_ok = False
        try:
            stream_ok = self._sync_via_stream(api, store, order_cutoff, counters, error_details)
            if stream_ok is None:
                _logger.warning("Trendyol akış servisi kullanılamadı [%s], statü bazlı sorguya geçiliyor",
                                store_name)
                stream_ok = self._sync_via_status_queries(api, store, order_cutoff, counters, error_details)

            # last_sync yalnız eksiksiz tamamlanan senkronda ilerler (bir sonraki akış buradan başlar);
            # ayrı cursor ile güncelle (serialization çakışmasını önler)
            if stream_ok:
                try:
                    with self.pool.cursor() as new_cr:
                        new_cr.execute(
                            "UPDATE trendyol_store SET last_sync = %s, write_date = %s WHERE id = %s",
                            (run_started, fields.Datetime.now(), store.id)
                        )
                except Exception as store_e:
                    _logger.warning("Mağaza last_sync güncelleme atlandı (%s): %s", store_name, str(store_e))

            try:
                with self.env.cr.savepoint():
                    log.write({
                        'state': 'error' if (counters['errors'] or not stream_ok) else 'done',
                        'end_date': fields.Datetime.now(),
                        'records_processed': counters['received'],
                        'records_created': counters['created'],
                        'records_updated': counters['updated'],
                        'records_failed': counters['errors'],
                        'log_details': f"[{store_name}] Yeni: {counters['created']}, "
                                       f"Güncellenen: {counters['updated']}, Hata: {counters['errors']}",
                        'error_details': '\n'.join(error_details) if error_details else '',
                    })
            except Exception as log_e:
                _logger.warning("SyncLog güncelleme atlandı (%s): %s", store_name, str(log_e))

        except Exception as e:
            try:
                log.write({
                    'state': 'error',
                    'end_date': fields.Datetime.now(),
                    'error_details': str(e),
                })
            except Exception:
                pass
            _logger.error("Trendyol senkronizasyon genel hatası [%s]: %s", store_name, str(e))

        _logger.info(
            "Trendyol senkronizasyon [%s] tamamlandı: %s paket alındı, %s yeni, %s güncellenen, %s hata",
            store_name, counters['received'], counters['created'], counters['updated'], counters['errors'],
        )

        return dict(counters)

    # ─── AKIŞ (STREAM) ───────────────────────────────────

    @api.private
    def _sync_via_stream(self, api, store, order_cutoff, counters, error_details):
        """Son güncellenme tarihine göre akış. Tamamı işlendiyse True, akış hiç
        başlatılamadıysa None (statü bazlı sorguya düşülür), yarıda kaldıysa False."""
        now = datetime.utcnow()
        start = (store.last_sync - _STREAM_OVERLAP) if store.last_sync else order_cutoff
        start = max(start, now - timedelta(days=_MAX_WINDOW_DAYS) + timedelta(minutes=1))

        packages = []
        cursor = None
        for page in range(_STREAM_MAX_PAGES):
            if page:
                time.sleep(_STREAM_PAGE_DELAY)
            result = api.get_orders_stream(start, now, next_cursor=cursor)
            if not result.get('success'):
                if page == 0:
                    return None
                error_details.append(f"Akış hatası (sayfa {page}): {result.get('error')}")
                break
            data = result.get('data') or {}
            packages.extend(data.get('content') or [])
            cursor = data.get('nextCursor')
            if not data.get('hasMore') or not cursor:
                self._process_package_batch(packages, store, order_cutoff, counters, error_details)
                return True
        else:
            error_details.append(f"Akış {_STREAM_MAX_PAGES} sayfayı aştı; kalan paketler sonraki senkronda")

        # Yarıda kalan akış: alınan paketleri yine işle, last_sync ilerlemesin
        self._process_package_batch(packages, store, order_cutoff, counters, error_details)
        return False

    @api.private
    def _process_package_batch(self, packages, store, order_cutoff, counters, error_details):
        """Paketleri işle: iptaller önce (kısmi iptalde eski paket kapanıp Nebim'den silinmeden
        yeni paket işlenirse yeni sipariş Nebim'de "mükerrer" sayılıp gönderilmez)."""
        counters['received'] = counters.get('received', 0) + len(packages)
        # Aynı paket akışta birden çok kez gelebilir: en son hali kalsın
        by_id = {}
        for pkg in packages:
            key = str(pkg.get('id') or pkg.get('shipmentPackageId') or '')
            if key:
                by_id[key] = pkg
        ordered = sorted(by_id.values(), key=lambda p: 0 if self._pkg_status(p) in _CANCEL_STATUSES else 1)

        for package in ordered:
            status = self._pkg_status(package)
            if status in _SKIP_STATUSES:
                continue
            try:
                with self.env.cr.savepoint():
                    res = self._sync_one_package(package, store, order_cutoff)
                    self.env.flush_all()
                if res == 'created':
                    counters['created'] += 1
                elif res == 'updated':
                    counters['updated'] += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                counters['errors'] += 1
                error_details.append(f"Sipariş {package.get('orderNumber', '?')}: {e}")
                _logger.error("Sipariş işleme hatası [%s]: %s", store.name, e)

    @api.model
    def _pkg_status(self, package):
        return (package.get('status') or package.get('shipmentPackageStatus') or '').lower()

    @api.private
    def _sync_one_package(self, package, store, order_cutoff):
        """Tek paket: mevcutsa güncelle; yoksa (yeterince yeniyse) içeri al."""
        status = self._pkg_status(package)
        package_id = str(package.get('id') or package.get('shipmentPackageId') or '')
        order_number = str(package.get('orderNumber') or '')

        known = (self._find_existing_package(package_id, order_number, store)
                 or self._split_origin(package, store)
                 or self._split_cancel_origin(package, store))
        if not known:
            if status == 'returned' and not store.process_returns:
                return 'skipped'
            # Akış son güncellemeye göre gelir: eski bir siparişin durum değişikliği yeni
            # sipariş gibi içeri alınmasın (iade edilen paketler hariç)
            order_ts = package.get('orderDate')
            if status != 'returned' and order_ts and ty_datetime(order_ts) < order_cutoff:
                return 'skipped'

        res = self._process_package(package, store)

        # Odoo'ya hiç düşmeden iptal olmuş sipariş: içeri alınıp iptal edilir (mevcut davranış)
        if not known and status in _CANCEL_STATUSES and res == 'created':
            new_rec = self.search([('shipment_package_id', '=', package_id)], limit=1)
            if new_rec:
                if new_rec.trendyol_status != status:
                    new_rec.write({'trendyol_status': status})
                self._cancel_odoo_order(new_rec, store)
        return res

    # ─── STATÜ BAZLI SORGU (yedek yol) ───────────────────

    @api.private
    def _sync_via_status_queries(self, api, store, order_cutoff, counters, error_details):
        """Akış servisi kullanılamazsa: v2 sipariş listesi statü statü sorgulanır."""
        start_date = order_cutoff
        ok = True
        packages = []
        statuses = ['Cancelled', 'UnSupplied', 'Created', 'Picking', 'Invoiced', 'Shipped',
                    'AtCollectionPoint', 'Delivered', 'UnDelivered']
        if store.process_returns:
            statuses.append('Returned')
        for status in statuses:
            page = 0
            while True:
                result = api.get_orders(status=status, page=page, size=200, start_date=start_date)
                if not result['success']:
                    ok = False
                    error_details.append(f"API hatası ({status}): {result.get('error')}")
                    _logger.error("Trendyol sipariş çekme hatası [%s] (%s): %s",
                                  store.name, status, result.get('error'))
                    break
                data = result.get('data', {})
                content = data.get('content', [])
                if not content:
                    break
                packages.extend(content)
                page += 1
                if page >= min(data.get('totalPages', 1), 50):  # v2: en fazla 10.000 kayıt
                    break
        self._process_package_batch(packages, store, order_cutoff, counters, error_details)
        return ok

    @api.private
    def _cancel_odoo_order(self, trendyol_order, store=None):
        """Odoo siparişini iptal et."""
        if store and not store.auto_cancel:
            return
        if not store:
            if trendyol_order.store_id and not trendyol_order.store_id.auto_cancel:
                return

        so = trendyol_order.sale_order_id
        if so and so.state not in ('cancel', 'done'):
            try:
                so._action_cancel()
                _logger.info("Odoo sipariş iptal edildi: %s", so.name)
            except Exception as e:
                _logger.warning("Sipariş iptal hatası: %s - %s", so.name, e)

    # ─── CRON ────────────────────────────────────────────

    @api.model
    def cron_sync_trendyol_orders(self):
        """Cron ile otomatik senkronizasyon — tüm aktif mağazalar."""
        try:
            self.sync_orders_from_trendyol()
        except Exception as e:
            _logger.exception("Trendyol cron senkronizasyon hatası: %s", e)

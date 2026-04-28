
"""Trendyol sipariş senkronizasyon logic'i — API'den çekme, işleme, güncelleme."""
import json
import logging

from datetime import datetime, timedelta

from odoo import api, fields, models
from .trendyol_api import TrendyolAPI

_logger = logging.getLogger(__name__)


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
        """Tek bir mağazadan siparişleri senkronize et."""
        try:
            api = store.get_api()
        except Exception as e:
            return {'error': str(e), 'created': 0, 'updated': 0, 'errors': 0}

        SyncLog = self.env['trendyol.sync.log'].sudo()
        log = SyncLog.create({
            'sync_type': 'order',
            'state': 'running',
            'start_date': fields.Datetime.now(),
            'store_id': store.id,
        })
        # Log kaydı transaction sonunda otomatik commit edilir

        created_count = 0
        updated_count = 0
        error_count = 0
        error_details = []

        # ── Sipariş gün aralığı filtresi ──
        start_date = None
        if store.order_day_range and store.order_day_range > 0:
            start_date = datetime.now() - timedelta(days=store.order_day_range)

        try:
            for status in ['Created', 'Picking', 'Invoiced', 'Shipped', 'Delivered']:
                page = 0
                while True:
                    result = api.get_orders(status=status, page=page, size=50, start_date=start_date)
                    if not result['success']:
                        err_msg = f"API hatası ({status}): {result.get('error')}"
                        _logger.error("Trendyol sipariş çekme hatası [%s] (%s): %s", store.name, status, result.get('error'))
                        error_details.append(err_msg)
                        break

                    data = result.get('data', {})
                    content = data.get('content', [])
                    if not content:
                        break

                    for package in content:
                        try:
                            with self.env.cr.savepoint():
                                res = self._process_package(package, store)
                                if res == 'created':
                                    created_count += 1
                                elif res == 'updated':
                                    updated_count += 1
                        except Exception as e:
                            error_count += 1
                            pkg_id = package.get('orderNumber', '?')
                            err_msg = f"Sipariş {pkg_id}: {str(e)}"
                            error_details.append(err_msg)
                            _logger.exception("Sipariş işleme hatası [%s]: %s", store.name, e)

                    total_pages = data.get('totalPages', 1)
                    page += 1
                    if page >= total_pages:
                        break

            # İptalleri kontrol et
            try:
                with self.env.cr.savepoint():
                    cancel_result = self._sync_cancelled_orders(api, store, start_date)
                    updated_count += cancel_result.get('updated', 0)
            except Exception as e:
                error_details.append(f"İptal sync: {e}")
                _logger.exception("İptal sync hatası [%s]", store.name)

            # ── İade işleme ──
            if store.process_returns:
                try:
                    return_start = None
                    if store.return_day_range and store.return_day_range > 0:
                        return_start = datetime.now() - timedelta(days=store.return_day_range)
                    with self.env.cr.savepoint():
                        return_result = self._sync_returned_orders(api, store, return_start)
                        created_count += return_result.get('created', 0)
                        updated_count += return_result.get('updated', 0)
                except Exception as e:
                    error_details.append(f"İade sync: {e}")
                    _logger.exception("İade sync hatası [%s]", store.name)

            store.sudo().write({'last_sync': fields.Datetime.now()})

            log.write({
                'state': 'error' if error_count else 'done',
                'end_date': fields.Datetime.now(),
                'records_processed': created_count + updated_count + error_count,
                'records_created': created_count,
                'records_updated': updated_count,
                'records_failed': error_count,
                'log_details': f"[{store.name}] Yeni: {created_count}, Güncellenen: {updated_count}, Hata: {error_count}",
                'error_details': '\n'.join(error_details) if error_details else '',
            })

        except Exception as e:
            log.write({
                'state': 'error',
                'end_date': fields.Datetime.now(),
                'error_details': str(e),
            })
            raise

        _logger.info(
            "Trendyol senkronizasyon [%s] tamamlandı: %s yeni, %s güncellenen, %s hata",
            store.name, created_count, updated_count, error_count,
        )

        return {
            'created': created_count,
            'updated': updated_count,
            'errors': error_count,
        }

    @api.private
    def _sync_cancelled_orders(self, api, store, start_date=None):
        """İptal edilen siparişleri senkronize et (sayfalama ile)."""
        updated = 0
        page = 0
        while True:
            result = api.get_orders(status='Cancelled', page=page, size=50, start_date=start_date)
            if not result['success']:
                break

            data = result.get('data', {})
            content = data.get('content', [])
            if not content:
                break

            for package in content:
                package_id = str(package.get('id') or package.get('shipmentPackageId', ''))
                existing = self.search([('shipment_package_id', '=', package_id)], limit=1)
                if existing and existing.trendyol_status != 'cancelled':
                    existing.write({'trendyol_status': 'cancelled'})
                    self._cancel_odoo_order(existing, store)
                    updated += 1

            total_pages = data.get('totalPages', 1)
            page += 1
            if page >= total_pages:
                break

        return {'updated': updated}

    @api.private
    def _sync_returned_orders(self, api, store, start_date=None):
        """İade edilen siparişleri senkronize et."""
        created = 0
        updated = 0
        page = 0
        while True:
            result = api.get_orders(status='Returned', page=page, size=50, start_date=start_date)
            if not result['success']:
                break

            data = result.get('data', {})
            content = data.get('content', [])
            if not content:
                break

            for package in content:
                try:
                    res = self._process_package(package, store)
                    if res == 'created':
                        created += 1
                    elif res == 'updated':
                        updated += 1
                except Exception as e:
                    _logger.exception("İade işleme hatası [%s]: %s", store.name, e)

            total_pages = data.get('totalPages', 1)
            page += 1
            if page >= total_pages:
                break

        return {'created': created, 'updated': updated}

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

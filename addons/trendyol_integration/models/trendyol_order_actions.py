"""Trendyol sipariş toplu işlemleri — retry, refresh, delete, mark."""
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# trendyol_order.py'den import
from .trendyol_order import TRENDYOL_STATUS


class TrendyolOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'trendyol.order'

    def action_retry_sync(self):
        """Seçili hatalı sipariş kayıtlarını tekrar dene."""
        errors = self.filtered(lambda o: o.state == 'error' and o.raw_data)
        if not errors:
            return self._notify('Uyarı', 'Seçili kayıtlarda tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                package_data = json.loads(order.raw_data)
                store = order.store_id
                if not store:
                    store = self.env['trendyol.store'].search([('active', '=', True)], limit=1)
                if not store:
                    order.write({'error_message': 'Aktif mağaza bulunamadı!'})
                    fail += 1
                    continue
                sale_order = order._create_sale_order(package_data, store)
                order.write({
                    'sale_order_id': sale_order.id,
                    'partner_id': sale_order.partner_id.id,
                    'state': 'synced',
                    'error_message': '',
                    'store_id': store.id,
                })
                success += 1
            except Exception as e:
                order.write({'error_message': str(e)})
                fail += 1
                _logger.exception("Tekrar deneme hatası %s: %s", order.name, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_trendyol(self):
        """Seçili siparişlerin durumunu Trendyol API'den güncelle."""
        if not self:
            return

        store_orders = {}
        for order in self:
            store = order.store_id
            if not store:
                continue
            if store.id not in store_orders:
                store_orders[store.id] = {'store': store, 'orders': self.env['trendyol.order']}
            store_orders[store.id]['orders'] |= order

        updated = 0
        for data in store_orders.values():
            store = data['store']
            try:
                api = store.get_api()
            except Exception as e:
                _logger.warning("API bağlantı hatası [%s]: %s", store.name, e)
                continue

            for order in data['orders']:
                if not order.trendyol_order_number:
                    continue
                try:
                    result = api.get_orders(order_number=order.trendyol_order_number, size=1)
                    if result['success']:
                        content = result.get('data', {}).get('content', [])
                        if content:
                            pkg = content[0]
                            new_status = (pkg.get('status') or pkg.get('shipmentPackageStatus', '')).lower()
                            vals = {
                                'trendyol_status': new_status if new_status in dict(TRENDYOL_STATUS) else order.trendyol_status,
                                'raw_data': json.dumps(pkg, ensure_ascii=False),
                            }
                            if pkg.get('cargoTrackingNumber'):
                                vals['cargo_tracking_number'] = str(pkg['cargoTrackingNumber'])
                            if pkg.get('cargoTrackingLink'):
                                vals['cargo_tracking_link'] = pkg['cargoTrackingLink']
                            if pkg.get('cargoProviderName'):
                                vals['cargo_provider'] = pkg['cargoProviderName']
                            if store.process_commission:
                                vals.update(self._extract_commission(pkg))

                            order.write(vals)
                            updated += 1
                except Exception as e:
                    _logger.warning("Durum güncelleme hatası %s: %s", order.name, e)

        return self._notify(
            'Durum Güncelleme',
            f'✅ {updated}/{len(self)} sipariş Trendyol\'dan güncellendi.',
            'success' if updated else 'warning',
        )

    def action_delete_error_orders(self):
        to_delete = self.filtered(lambda o: o.state == 'error' and not o.sale_order_id)
        if not to_delete:
            return self._notify('Bilgi', 'Silinecek hatalı kayıt yok.', 'warning')
        count = len(to_delete)
        to_delete.unlink()
        return self._notify('Silme', f'🗑️ {count} hatalı kayıt silindi.', 'success')

    def action_mark_synced(self):
        to_mark = self.filtered(lambda o: o.state != 'synced')
        if not to_mark:
            return self._notify('Bilgi', 'İşaretlenecek kayıt yok.', 'info')
        to_mark.write({'state': 'synced', 'error_message': ''})
        return self._notify('Durum', f'✅ {len(to_mark)} sipariş senkronize olarak işaretlendi.', 'success')

    def action_retry_all_errors(self):
        errors = self.search([('state', '=', 'error')])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Trendyol - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

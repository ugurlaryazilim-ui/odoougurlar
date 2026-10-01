"""N11 sipariş toplu işlemleri — retry, refresh, delete, mark."""
import logging

from odoo import models

from .n11_order import N11_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

class N11OrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'n11.order'

    def action_retry_sync(self):
        """Odoo siparişi oluşmamış kayıtları tekrar dene (ör. ürün sonradan eklendiyse)."""
        errors = self.filtered(lambda o: not o.sale_order_id)
        if not errors:
            return self._notify('Uyarı', 'Tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                with self.env.cr.savepoint():
                    order._reconcile_sale_order(order.store_id)
                    order._auto_accept(order.store_id)
                if order.sale_order_id:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("N11 Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan (iptal veya ürün eksik): {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_n11(self):
        """Seçili siparişleri sipariş numarasıyla N11 API'den yeniden çekip güncelle."""
        if not self:
            return

        updated = 0
        apis = {}
        for order in self:
            store = order.store_id
            if not store or not order.order_number:
                continue
            try:
                if store.id not in apis:
                    apis[store.id] = store.get_api()
                api = apis[store.id]
                result = api.get_order_packages(order.order_number)
                if not result.get('success') or not result.get('data'):
                    _logger.warning("Durum güncelleme hatası %s: %s", order.order_number,
                                    result.get('error') or 'paket bulunamadı')
                    continue
                with self.env.cr.savepoint():
                    self._sync_order_packages(store, api, order.order_number, result['data'], None, refetch=False)
                updated += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Durum Güncelleme',
            f'✅ {updated}/{len(self)} sipariş N11\'dan güncellendi.',
            'success' if updated else 'warning',
        )

    def action_delete_error_orders(self):
        to_delete = self.filtered(lambda o: not o.sale_order_id)
        if not to_delete:
            return self._notify('Bilgi', 'Silinecek taslak/hatalı kayıt yok.', 'warning')
        count = len(to_delete)
        to_delete.unlink()
        return self._notify('Silme', f'🗑️ {count} hatalı kayıt silindi.', 'success')

    def action_retry_all_errors(self):
        errors = self.search([('sale_order_id', '=', False), ('order_status', 'not in', list(N11_CANCEL_STATUSES))])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'N11 - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

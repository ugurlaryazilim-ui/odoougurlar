"""Idefix sipariş toplu işlemleri — retry, refresh, delete."""
import logging

from odoo import models

from .idefix_order import IDEFIX_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

_REFRESH_BATCH = 50


class IdefixOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'idefix.order'

    def action_retry_sync(self):
        """Odoo siparişi oluşmamış kayıtları kayıtlı kalemlerle tekrar dene (ör. ürün sonradan eklendiyse)."""
        errors = self.filtered(lambda o: not o.sale_order_id and o.order_status not in IDEFIX_CANCEL_STATUSES)
        if not errors:
            return self._notify('Uyarı', 'Tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                with self.env.cr.savepoint():
                    order.with_context(idefix_force_create=True)._reconcile_sale_order(order.store_id)
                if order.sale_order_id:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("Idefix Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_idefix(self):
        """Seçili sevkiyatları shipment ID ile Idefix'ten çekip tamamen güncelle."""
        if not self:
            return

        updated = 0
        failed = []
        for store in self.mapped('store_id'):
            orders = self.filtered(lambda o: o.store_id == store and o.order_id)
            try:
                api = store.get_api()
            except Exception as e:
                failed.append(f"{store.name}: {e}")
                continue
            for start in range(0, len(orders), _REFRESH_BATCH):
                batch = orders[start:start + _REFRESH_BATCH]
                found, error = self._fetch_orders(api, ids=batch.mapped('order_id'))
                if error:
                    failed.append(f"{store.name}: {error}")
                    break
                by_id = {str(o.get('id')): o for o in found}
                for order in batch:
                    order_json = by_id.get(order.order_id)
                    if not order_json:
                        failed.append(f"{order.order_number} / {order.order_id}: Idefix'te bulunamadı")
                        continue
                    try:
                        with self.env.cr.savepoint():
                            self._sync_order_json(store, order_json, api)
                        updated += 1
                    except Exception as e:
                        self.env.invalidate_all(flush=False)
                        failed.append(f"{order.order_number}: {e}")
                        _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        msg = f'✅ {updated}/{len(self)} sevkiyat Idefix\'ten güncellendi.'
        if failed:
            msg += '\n' + '\n'.join(failed[:10])
        return self._notify('Durum Güncelleme', msg, 'success' if not failed else 'warning')

    def action_delete_error_orders(self):
        to_delete = self.filtered(lambda o: not o.sale_order_id)
        if not to_delete:
            return self._notify('Bilgi', 'Silinecek taslak/hatalı kayıt yok.', 'warning')
        count = len(to_delete)
        to_delete.unlink()
        return self._notify('Silme', f'🗑️ {count} hatalı kayıt silindi.', 'success')

    def action_retry_all_errors(self):
        errors = self.search([('sale_order_id', '=', False),
                              ('order_status', 'not in', list(IDEFIX_CANCEL_STATUSES))])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Idefix - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

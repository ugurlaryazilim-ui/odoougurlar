"""Pazarama sipariş toplu işlemleri — retry, refresh, delete, mark."""
import logging

from odoo import models

from .pazarama_order import PAZARAMA_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

class PazaramaOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'pazarama.order'

    def action_retry_sync(self):
        """Odoo siparişi oluşmamış kayıtları kayıtlı kalemlerle tekrar dene (ör. ürün sonradan eklendiyse)."""
        errors = self.filtered(lambda o: not o.sale_order_id and o.order_status not in PAZARAMA_CANCEL_STATUSES)
        if not errors:
            return self._notify('Uyarı', 'Tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                with self.env.cr.savepoint():
                    order.with_context(pazarama_force_create=True)._reconcile_sale_order(order.store_id)
                if order.sale_order_id:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("Pazarama Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_pazarama(self):
        """Seçili siparişleri sipariş numarasıyla Pazarama'dan çekip tamamen güncelle."""
        if not self:
            return

        updated = 0
        failed = []
        apis = {}
        for order in self:
            store = order.store_id
            if not store or not order.order_number:
                continue
            try:
                api = apis.get(store.id) or apis.setdefault(store.id, store.get_api())
                order_json, error = self._fetch_single_order(api, order.order_number, order.order_date)
                if error:
                    failed.append(f"{order.order_number}: {error}")
                    continue
                if not order_json:
                    failed.append(f"{order.order_number}: Pazarama'da bulunamadı")
                    continue
                with self.env.cr.savepoint():
                    self._sync_order_json(store, order_json, api)
                updated += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                failed.append(f"{order.order_number}: {e}")
                _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        msg = f'✅ {updated}/{len(self)} sipariş Pazarama\'dan güncellendi.'
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
                              ('order_status', 'not in', list(PAZARAMA_CANCEL_STATUSES))])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Pazarama - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

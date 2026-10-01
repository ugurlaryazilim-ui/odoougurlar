
"""Pttavm sipariş toplu işlemleri — retry, refresh, delete, mark."""
import logging

from odoo import models

from .pttavm_order import PTTAVM_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

class PttavmOrderActions(models.Model):
    """Toplu işlem ve UI aksiyon metodları."""
    _inherit = 'pttavm.order'

    def action_retry_sync(self):
        """Odoo siparişi oluşmamış kayıtları kayıtlı satırlarla tekrar dene (ör. ürün sonradan eklendiyse)."""
        errors = self.filtered(lambda o: not o.sale_order_id and o.order_status not in PTTAVM_CANCEL_STATUSES)
        if not errors:
            return self._notify('Uyarı', 'Tekrar denenecek hatalı sipariş yok.', 'warning')

        success = 0
        fail = 0
        for order in errors:
            try:
                with self.env.cr.savepoint():
                    order._reconcile_sale_order(order.store_id)
                if order.sale_order_id:
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                self.env.invalidate_all(flush=False)
                _logger.exception("Pttavm Tekrar deneme hatası %s: %s", order.order_number, e)

        return self._notify(
            'Tekrar Deneme Sonucu',
            f'✅ Başarılı: {success}\n❌ Başarısız/Atlanan: {fail}',
            'success' if fail == 0 else 'warning',
        )

    def action_refresh_from_pttavm(self):
        """Seçili siparişleri PttAVM sipariş detayından (GET /orders/{siparisNo}) güncelle."""
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
                res = api.get_order_detail(order.order_number)
                if not res.get('success'):
                    failed.append(f"{order.order_number}: {res.get('error')}")
                    continue
                data = res.get('data')
                order_list = [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
                order_json = next((o for o in order_list if isinstance(o, dict)
                                   and str(o.get('siparisNo') or '') == order.order_number), None)
                if not order_json:
                    failed.append(f"{order.order_number}: PttAVM'de bulunamadı")
                    continue
                with self.env.cr.savepoint():
                    self._sync_order_json(store, order_json)
                updated += 1
            except Exception as e:
                self.env.invalidate_all(flush=False)
                failed.append(f"{order.order_number}: {e}")
                _logger.warning("Durum güncelleme hatası %s: %s", order.order_number, e)

        msg = f'✅ {updated}/{len(self)} sipariş Pttavm\'dan güncellendi.'
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
                              ('order_status', 'not in', list(PTTAVM_CANCEL_STATUSES))])
        if not errors:
            return self._notify('Bilgi', 'Tekrar denenecek hatalı sipariş yok.', 'info')
        return errors.action_retry_sync()

    def _notify(self, title, message, ntype='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Pttavm - {title}',
                'message': message,
                'type': ntype,
                'sticky': ntype in ('danger', 'warning'),
            },
        }

import logging
from odoo import models

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında PttAVM'den kargo barkodu talep et."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            sale_order = picking.sale_id
            if not sale_order or not sale_order.pttavm_order_id:
                continue

            pttavm_order = sale_order.pttavm_order_id
            store = pttavm_order.store_id
            if not store or not store.auto_send_cargo:
                continue
            # Aynı sipariş için ikinci kez talep gönderme (bekleyen / oluşmuş barkod)
            if pttavm_order.cargo_barcode_state in ('pending', 'completed'):
                continue

            try:
                with self.env.cr.savepoint():
                    ok, msg = pttavm_order._request_cargo_barcode(store, record=picking)
                if ok:
                    _logger.info("PttAVM kargo barkodu talep edildi [%s]: %s", pttavm_order.order_number, msg)
            except Exception as e:
                _logger.exception("Kargo bilgisi PttAVM gönderme hatası [%s]: %s", store.name, e)

        return res

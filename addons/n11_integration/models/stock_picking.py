import logging
from odoo import models

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında N11'de henüz onaylanmamış (Created) kalemleri onayla."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            sale_order = picking.sale_id
            if not sale_order or not sale_order.n11_order_id:
                continue

            n11_order = sale_order.n11_order_id
            store = n11_order.store_id
            if not store or not store.auto_send_cargo:
                continue

            # n11 yalnızca 'Created' kalemlerin onayını kabul eder; onaylıları tekrar göndermeyelim
            lines = n11_order.line_ids.filtered(lambda l: l.status == 'Created' and l.item_id)
            if not lines:
                continue

            try:
                n11_order._accept_lines(store, lines, picking, 'Transfer doğrulandı')
            except Exception as e:
                _logger.exception("N11 onay gönderme hatası [%s]: %s", store.name, e)

        return res

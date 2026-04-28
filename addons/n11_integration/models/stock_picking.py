import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında N11'ya kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            # N11 siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            
            if not sale_order or not sale_order.n11_order_id:
                continue

            n11_order = sale_order.n11_order_id
            store = n11_order.store_id
            
            if not store or not store.auto_send_cargo:
                continue

            try:
                api = store.get_api()
                
                # Sipariş hazır/kargo bilgisi talep et
                line_ids = [int(l.n11_item_id) for l in sale_order.order_line if l.n11_item_id]
                if not line_ids:
                    continue

                result = api.update_order_status_to_picking(line_ids)
                
                if result.get('success'):
                    picking.message_post(body="N11 Siparişi Picking (Onaylandı) Statüsüne alındı.")
                else:
                    _logger.warning("N11 API Hatası [%s]: %s", n11_order.order_number, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi N11 gönderme hatası [%s]: %s", store.name, e)

        return res

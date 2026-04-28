import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında Idefix'ya kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            # Idefix siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            
            if not sale_order or not sale_order.idefix_order_id:
                continue

            idefix_order = sale_order.idefix_order_id
            store = idefix_order.store_id
            
            if not store or not store.auto_send_cargo:
                continue

            # Kargo takip numarası (Odoo'da varsa veya barcode sisteminden geldiyse)
            tracking_number = picking.carrier_tracking_ref or ''
            tracking_url = "" # Eğer Odoo kargo entegrasyonu url veriyorsa burdan eklenebilir.
            
            # Kargo koduna sipariş numarası ekle
            if store.cargo_include_order_number and idefix_order.order_number:
                if tracking_number:
                    tracking_number = f"{tracking_number}-{idefix_order.order_number}"
                else:
                    tracking_number = idefix_order.order_number

            if not tracking_number:
                _logger.info("Kargo takip numarası yok, Idefix'ya gönderilmedi: %s", idefix_order.order_number)
                continue

            try:
                api = store.get_api()
                
                # Idefix update-tracking-number servisini çağır
                result = api.update_tracking_number(
                    shipment_id=idefix_order.order_id,
                    tracking_number=tracking_number,
                    tracking_url=tracking_url
                )
                
                if result.get('success'):
                    _logger.info("Kargo bilgisi Idefix'ya gönderildi [%s]: %s",
                                 idefix_order.order_number, tracking_number)
                else:
                    _logger.warning("Kargo bilgisi Idefix'ya gönderilemedi [%s]: %s",
                                    idefix_order.order_number, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi Idefix gönderme hatası [%s]: %s", store.name, e)

        return res

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında Trendyol'a kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik Trendyol bildirimi yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue
            # Trendyol siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            if not sale_order or not sale_order.trendyol_order_id:
                continue

            trendyol_order = sale_order.trendyol_order_id
            store = trendyol_order.store_id
            if not store or not store.auto_send_cargo:
                continue

            # Kargo takip numarası
            tracking_number = picking.carrier_tracking_ref or ''

            # Kargo koduna sipariş numarası ekle
            if store.cargo_include_order_number and trendyol_order.trendyol_order_number:
                if tracking_number:
                    tracking_number = f"{tracking_number}-{trendyol_order.trendyol_order_number}"
                else:
                    tracking_number = trendyol_order.trendyol_order_number

            if not tracking_number:
                _logger.info("Kargo takip numarası yok, Trendyol'a gönderilmedi: %s", trendyol_order.name)
                continue

            try:
                api = store.get_api()
                result = api.update_tracking_number(
                    trendyol_order.shipment_package_id,
                    tracking_number,
                )
                if result['success']:
                    _logger.info("Kargo bilgisi Trendyol'a gönderildi [%s]: %s → %s",
                                 store.name, trendyol_order.name, tracking_number)
                else:
                    _logger.warning("Kargo bilgisi gönderilemedi [%s]: %s — %s",
                                    store.name, trendyol_order.name, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi gönderme hatası [%s]: %s", store.name, e)

        return res

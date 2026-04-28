import json
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında Pazarama'ya kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            # Pazarama siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            
            if not sale_order or not sale_order.pazarama_order_id:
                continue

            pazarama_order = sale_order.pazarama_order_id
            store = pazarama_order.store_id
            
            if not store or not store.auto_send_cargo:
                continue

            # Kargo takip numarası (Odoo'da varsa, veya barcode sisteminden geldiyse)
            tracking_number = picking.carrier_tracking_ref or ''

            # Kargo koduna sipariş numarası ekle
            if store.cargo_include_order_number and pazarama_order.order_number:
                if tracking_number:
                    tracking_number = f"{tracking_number}-{pazarama_order.order_number}"
                else:
                    tracking_number = pazarama_order.order_number

            if not tracking_number:
                _logger.info("Kargo takip numarası yok, Pazarama'ya gönderilmedi: %s", pazarama_order.order_number)
                continue

            try:
                api = store.get_api()
                
                # JSON parse loop DIŞINDA tek sefer yapılır
                raw_data = json.loads(pazarama_order.raw_data) if pazarama_order.raw_data else {}
                raw_items = raw_data.get('items', [])
                # item_id → cargo company ID mapping oluştur (O(n) dict lookup)
                cargo_id_map = {}
                for raw_item in raw_items:
                    item_id = raw_item.get('orderItemId')
                    if item_id:
                        cargo_id_map[item_id] = raw_item.get('cargo', {}).get('companyId', '')

                for line in pazarama_order.line_ids:
                    cargo_com_id = cargo_id_map.get(line.item_id, '')
                    
                    if not cargo_com_id:
                        _logger.warning("Pazarama Kargo Firma ID'si bulunamadi. Tracking iptal: %s", line.item_id)
                        continue

                    # Kargo bildirim API'sini çağır
                    result = api.update_tracking_number(
                        order_number=pazarama_order.order_number,
                        order_item_id=line.item_id,
                        tracking_number=tracking_number,
                        cargo_company_id=cargo_com_id
                    )
                    
                    if result.get('success'):
                        _logger.info("Kargo bilgisi Pazarama'ya gönderildi [%s/Item: %s]: %s",
                                     pazarama_order.order_number, line.item_id, tracking_number)
                    else:
                        _logger.warning("Kargo bilgisi Pazarama'ya gönderilemedi [%s]: %s",
                                        pazarama_order.order_number, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi Pazarama gönderme hatası [%s]: %s", store.name, e)

        return res

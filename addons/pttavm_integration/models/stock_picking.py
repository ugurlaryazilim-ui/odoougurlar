import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında Pttavm'ya kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            # Pttavm siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            
            if not sale_order or not sale_order.pttavm_order_id:
                continue

            pttavm_order = sale_order.pttavm_order_id
            store = pttavm_order.store_id
            
            if not store or not store.auto_send_cargo:
                continue

            if not store.pttavm_warehouse_id:
                _logger.warning("PttAVM Depo ID ayarlanmamış, kargo barkodu yaratılamıyor: %s", store.name)
                continue

            try:
                api = store.get_api()
                
                # Barkod talep et
                result = api.create_barcode(
                    order_id=pttavm_order.order_number,
                    warehouse_id=store.pttavm_warehouse_id
                )
                
                if result.get('success'):
                    res_data = result.get('data', {})
                    if res_data.get('code') in [200, 201] or res_data.get('success'):
                        tracking_id = res_data.get('tracking_id')
                        _logger.info("Kargo barkod talebi PttAVM'ye gönderildi [%s], Tracking ID: %s",
                                     pttavm_order.order_number, tracking_id)
                        
                        # Odoo'daki sale order uzerinde veya picking üzerinde tracking id kaydedilebilir
                        picking.message_post(body=f"PttAVM Barkod Talebi Oluşturuldu. Tracking ID: {tracking_id}")
                    else:
                        _logger.warning("Kargo barkod talebi reddedildi [%s]: %s",
                                        pttavm_order.order_number, res_data)
                else:
                    _logger.warning("Kargo barkod API Hatası [%s]: %s",
                                    pttavm_order.order_number, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi PttAVM gönderme hatası [%s]: %s", store.name, e)

        return res

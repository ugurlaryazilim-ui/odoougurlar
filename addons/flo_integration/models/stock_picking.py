# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Picking tamamlandığında Flo'ya kargo bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done':
                continue

            # Flo siparişi mi?
            sale_order = picking.sale_id or (picking.group_id and self.env['sale.order'].search(
                [('procurement_group_id', '=', picking.group_id.id)], limit=1
            ))
            
            if not sale_order or not sale_order.flo_order_id:
                continue

            flo_order = sale_order.flo_order_id
            store = flo_order.store_id
            
            if not store or not store.auto_send_cargo:
                continue

            try:
                api = store.get_api()
                
                # Sipariş hazır/kargo bilgisi talep et
                result = api.update_package(increment_id=flo_order.order_number)
                
                if result.get('success'):
                    res_data = result.get('data', {})
                    if res_data.get('success'):
                        inner_data = res_data.get('data', {})
                        shipment_service = inner_data.get('shipmentService')
                        
                        pdf_content = inner_data.get('pdf', '')
                        msg = f"Flo Barkod Talebi Oluşturuldu. Kargo: {shipment_service}"
                        if pdf_content:
                            msg += "<br/>Kargo Etiketi (PDF) başarıyla çekildi."
                            
                        # PDF'i attachment olarak ekleyebiliriz veya mesaja yazabiliriz
                        picking.message_post(body=msg)
                    else:
                        _logger.warning("Kargo barkod talebi reddedildi [%s]: %s",
                                        flo_order.order_number, res_data)
                else:
                    _logger.warning("Kargo barkod API Hatası [%s]: %s",
                                    flo_order.order_number, result.get('error'))
            except Exception as e:
                _logger.exception("Kargo bilgisi Flo gönderme hatası [%s]: %s", store.name, e)

        return res

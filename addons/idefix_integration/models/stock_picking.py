import logging
from odoo import models

from .idefix_order import IDEFIX_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

# Kargo / desi bildirimi yapılabilecek (henüz kargoya verilmemiş) sevkiyat statüleri
_SHIPPABLE_STATUSES = ('created', 'shipment_ready', 'shipment_picking', 'shipment_invoiced')


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Transfer tamamlandığında (ayarlıysa) Idefix'e desi/koli ve satıcı kargo takip bilgisi gönder."""
        res = super().button_validate()

        # Wizard döndüyse (backorder vb.) şimdilik bildirim yapmayalım
        if isinstance(res, dict):
            return res

        for picking in self:
            if picking.state != 'done' or picking.picking_type_code != 'outgoing':
                continue
            sale_order = picking.sale_id
            if not sale_order or not sale_order.idefix_order_id:
                continue
            idefix_order = sale_order.idefix_order_id
            store = idefix_order.store_id
            if not store or idefix_order.order_status in IDEFIX_CANCEL_STATUSES:
                continue
            if idefix_order.order_status not in _SHIPPABLE_STATUSES:
                continue
            if not (store.send_box_info or store.auto_send_cargo):
                continue
            try:
                picking._idefix_send_shipping_info(idefix_order, store)
            except Exception as e:
                _logger.exception("Idefix kargo bildirimi hatası [%s]: %s", store.name, e)

        return res

    def _idefix_send_shipping_info(self, idefix_order, store):
        """Desi/koli ve (satıcı kargo anlaşmasında) takip numarasını gönderir; sonucu transferin geçmişine yazar."""
        self.ensure_one()
        api = store.get_api()
        messages = []

        if store.send_box_info:
            result = api.update_box_info(idefix_order.order_id, store.default_package_count or 1,
                                         store.default_desi or 1)
            messages.append("Desi/koli bildirildi." if result.get('success')
                            else f"Desi/koli bildirilemedi: {result.get('error')}")

        if store.auto_send_cargo:
            tracking_number = (self.carrier_tracking_ref or '').strip()
            if not tracking_number:
                messages.append("Kargo takip numarası yok, Idefix'e gönderilmedi.")
            elif tracking_number == (idefix_order.cargo_tracking_number or ''):
                # Platform anlaşmalı kargo kodu (cargoKey) — Idefix zaten biliyor
                messages.append("Takip numarası Idefix'in kendi kargo kodu; tekrar gönderilmedi.")
            elif not store.cargo_tracking_url or '{code}' not in store.cargo_tracking_url:
                messages.append("Kargo takip linki şablonu ({code} içermeli) tanımlı değil; takip numarası gönderilmedi.")
            else:
                url = store.cargo_tracking_url.replace('{code}', tracking_number)
                result = api.update_tracking_number(idefix_order.order_id, tracking_number, url)
                if result.get('success'):
                    idefix_order.write({'cargo_tracking_number': tracking_number, 'cargo_tracking_url': url,
                                        'order_status': 'shipment_in_cargo'})
                    messages.append(f"Kargo takip numarası Idefix'e gönderildi: {tracking_number}")
                else:
                    messages.append(f"Kargo takip numarası gönderilemedi: {result.get('error')}")

        if messages:
            self.message_post(body=f"Idefix ({idefix_order.order_id}): " + ' '.join(messages))
            _logger.info("Idefix kargo bildirimi [%s]: %s", idefix_order.order_number, ' '.join(messages))

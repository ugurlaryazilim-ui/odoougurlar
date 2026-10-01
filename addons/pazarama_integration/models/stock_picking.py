import logging
from odoo import models

from .pazarama_order import PAZARAMA_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

# Kargo bildirimi yapılabilecek kalem durumları: 3 Sipariş Alındı (önce 12'ye alınır), 12 Hazırlanıyor
_SHIPPABLE_STATUSES = (3, 12)


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

            sale_order = picking.sale_id
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
                picking._pazarama_send_tracking(pazarama_order, store, tracking_number)
            except Exception as e:
                _logger.exception("Kargo bilgisi Pazarama gönderme hatası [%s]: %s", store.name, e)

        return res

    def _pazarama_send_tracking(self, pazarama_order, store, tracking_number):
        """İptal edilmemiş, henüz kargolanmamış kalemler için kargo bilgisini gönderir;
        sonucu transferin geçmişine yazar."""
        lines = pazarama_order.line_ids.filtered(
            lambda l: l.status in _SHIPPABLE_STATUSES and l.status not in PAZARAMA_CANCEL_STATUSES)
        if not lines:
            return
        api = store.get_api()
        # Pazarama kargo işleminden önce kalemin 'Hazırlanıyor' (12) olmasını ister
        waiting = lines.filtered(lambda l: l.status == 3)
        if waiting and store.auto_accept_orders:
            pazarama_order._accept_lines(waiting, self, 'Transfer doğrulandı', api)

        sent, errors = [], []
        for line in lines:
            if not line.cargo_company_id:
                errors.append(f"✗ {line.product_code or line.item_id}: kargo firma ID'si yok")
                continue
            result = api.update_tracking_number(
                order_number=pazarama_order.order_number,
                order_item_id=line.item_id,
                tracking_number=tracking_number,
                cargo_company_id=line.cargo_company_id,
            )
            if result.get('success'):
                sent.append(line)
            else:
                errors.append(f"✗ {line.product_code or line.item_id}: {result.get('error')}")
        if sent:
            for line in sent:
                line.status = 5
        msg = [f"Pazarama kargo bildirimi ({tracking_number}): {len(sent)}/{len(lines)} kalem gönderildi."]
        msg.extend(errors)
        self.message_post(body='\n'.join(msg))
        if errors:
            _logger.warning("Pazarama kargo bildirimi [%s]: %s", pazarama_order.order_number, '; '.join(errors))

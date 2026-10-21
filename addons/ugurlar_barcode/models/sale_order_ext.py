"""Satış siparişi: fatura kapısı (sipariş başına tek fatura, tüm giden sevkiyatlar bitince)."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrderExt(models.Model):
    _inherit = 'sale.order'

    def _ugurlar_customer_outs(self):
        """Siparişin giden (müşteri) sevkiyatları; sipariş bağı kopuk olanlar origin ile."""
        self.ensure_one()
        pickings = self.picking_ids | self.env['stock.picking'].sudo().search(
            [('origin', '=', self.name)])
        return pickings.filtered(lambda p: p.picking_type_code == 'outgoing')

    def _ugurlar_outs_closed(self):
        """Fatura kapısı (tek tanım): iptal olmayan tüm giden sevkiyatlar done ve en az biri
        done. Kardeş / sonradan açılan / backorder sevkiyatı açıkken kesilen fatura onun
        ürününü içermiyordu ve `_trigger_nebim_sync` fatura varken yenisini kesmiyordu.
        İptal edilen sevkiyat beklenmez (iptal backorder faturayı açar)."""
        self.ensure_one()
        states = set(self._ugurlar_customer_outs().mapped('state'))
        return bool(states) and states <= {'done', 'cancel'} and 'done' in states

    def _ugurlar_needs_invoice(self):
        """Kapı açık, aktif satış faturası yok ve faturalanacak miktar var."""
        self.ensure_one()
        if self.state == 'cancel' or self.invoice_status != 'to invoice':
            return False
        if self.invoice_ids.filtered(
                lambda i: i.state in ('draft', 'posted') and i.move_type == 'out_invoice'):
            return False
        return self._ugurlar_outs_closed()

    def _ugurlar_invoice_now(self):
        """Kapısı açılmış siparişlerin faturasını paketlemenin Nebim akışıyla keser
        (`stock.picking._ugurlar_schedule_invoice` commit sonrası çağırır). Hiçbir hata
        dışarı çıkmaz: commit sonrası istisna kullanıcıya hata / isteğin yeniden denenmesi
        olarak dönerdi."""
        from odoo.addons.ugurlar_barcode.controllers.packing_api import PackingApiController
        for order in self:
            try:
                if not order._ugurlar_needs_invoice():
                    continue
                picking = order._ugurlar_customer_outs().filtered(
                    lambda p: p.state == 'done')[:1]
                _logger.info("Fatura kapısı açıldı (paketleme dışı kapanış): %s → %s",
                             order.name, picking.name)
                PackingApiController()._trigger_nebim_sync(picking)
            except Exception:
                _logger.exception("Sipariş %s faturası kesilemedi (paketleme dışı kapanış)",
                                  order.name)
                order.env.cr.rollback()

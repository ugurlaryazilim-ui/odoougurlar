"""Idefix'e statü bildirimi (picking / invoiced) ve fatura linki gönderimi."""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .idefix_order import IDEFIX_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

_PICKING_RETRY_AFTER = timedelta(minutes=30)
_INVOICE_RETRY_AFTER = timedelta(minutes=30)
_INVOICE_LOOKBACK = timedelta(days=30)
_INVOICE_BATCH = 10

# 'picking' bildirimi yalnızca hazırlanmaya hazır sevkiyata yapılır
_PICKABLE_STATUSES = ('shipment_ready',)
# 'invoiced' bildirimi yapılabilecek statüler (öncesinde picking gerekir)
_INVOICEABLE_STATUSES = ('shipment_ready', 'shipment_picking')
# Fatura linki gönderilebilecek statüler
_INVOICE_LINK_STATUSES = ('shipment_ready', 'shipment_picking', 'shipment_invoiced', 'shipment_in_cargo',
                          'shipment_delivered', 'shipment_undeliver', 'shipment_approved')


class IdefixOrderInvoice(models.Model):
    _inherit = 'idefix.order'

    # ─── 'Hazırlanıyor' (picking) ────────────────────────────

    def _send_picking(self, api_client=None, source='Otomatik'):
        """Sevkiyatı Idefix'te 'picking' yapar (müşteri artık iptal edemez). Başarılıysa True."""
        self.ensure_one()
        self.picking_attempt_date = fields.Datetime.now()
        api_client = api_client or self.store_id.get_api()
        res = api_client.update_shipment_status(self.order_id, 'picking')
        record = self.sale_order_id or self
        if res.get('success'):
            self.write({'picking_sent': True, 'order_status': 'shipment_picking'})
            record.message_post(body=f"Idefix sevkiyatı {self.order_id} 'Hazırlanıyor' (picking) bildirildi ({source}).")
            return True
        error = str(res.get('error') or 'Bilinmeyen hata')[:250]
        record.message_post(body=f"Idefix 'Hazırlanıyor' bildirimi başarısız ({source}): {error}")
        _logger.warning("Idefix picking bildirimi başarısız %s: %s", self.order_id, error)
        return False

    def _auto_picking(self, store, api_client=None):
        """'Idefix'e Hazırlanıyor Bildir' açıksa, Odoo'da onaylanmış sevkiyatı 'picking' yapar."""
        self.ensure_one()
        if not store.auto_send_picking or self.picking_sent:
            return
        if self.order_status not in _PICKABLE_STATUSES:
            return
        so = self.sale_order_id
        if not so or so.state != 'sale':
            return
        now = fields.Datetime.now()
        if self.picking_attempt_date and now - self.picking_attempt_date < _PICKING_RETRY_AFTER:
            return
        self._send_picking(api_client)

    def action_send_picking(self):
        """Form butonu: sevkiyatı Idefix'te 'Hazırlanıyor' yap."""
        for rec in self:
            if rec.order_status not in _PICKABLE_STATUSES:
                raise UserError(_("%s: yalnızca 'Sevke Hazır' sevkiyat 'Hazırlanıyor' yapılabilir (şu an: %s).",
                                  rec.order_number, rec.order_status_display))
            if not rec._send_picking(source='Manuel'):
                raise UserError(_("%s: Idefix bildirimi başarısız. Ayrıntı sipariş geçmişinde.", rec.order_number))
        return self._notify('Hazırlanıyor', "Sevkiyat Idefix'te 'Hazırlanıyor' statüsüne alındı.", 'success')

    # ─── Fatura (invoiced + fatura linki) ────────────────────

    def _get_nebim_invoice(self):
        """Nebim e-arşiv / e-fatura linki ve numarası: (url, fatura_no, hata)."""
        self.ensure_one()
        so = self.sale_order_id
        if 'odoougurlar.nebim.connector' not in self.env:
            return False, False, 'Nebim modülü yüklü değil'
        doc_number = so.client_order_ref or so.name
        try:
            result = self.env['odoougurlar.nebim.connector'].sudo().run_proc(
                'usp_Invoice_EArchieveURL', [{'Name': 'DocumentNumber', 'Value': doc_number}])
        except Exception as e:
            return False, False, f'Nebim fatura linki alınamadı: {e}'
        row = (result[0] if isinstance(result, list) and result else result) or {}
        if not isinstance(row, dict):
            row = {}
        url = row.get('InvoiceURL') or ''
        number = row.get('EInvoiceNumber') or ''
        if not number:
            posted = so.invoice_ids.filtered(lambda m: m.state == 'posted')
            number = next((n for n in posted.mapped('nebim_invoice_number') if n), '') \
                if 'nebim_invoice_number' in posted._fields else ''
        if not url:
            return False, number, 'Fatura linki henüz oluşmamış'
        return url, number, False

    def _send_invoice_to_idefix(self, api_client=None, source='Otomatik'):
        """Idefix'e 'invoiced' statüsünü (fatura no ile) ve Nebim fatura linkini gönderir. Başarılıysa True."""
        self.ensure_one()
        now = fields.Datetime.now()
        self.invoice_attempt_date = now
        so = self.sale_order_id
        if not so:
            self.invoice_error = 'Odoo siparişi yok'
            return False
        if self.order_status in IDEFIX_CANCEL_STATUSES:
            self.invoice_error = f"Sevkiyat {self.order_status_display}"
            return False
        url, number, error = self._get_nebim_invoice()
        if not url:
            self.invoice_error = error
            return False
        api_client = api_client or self.store_id.get_api()

        # 1) Statü: hazırlanıyor → faturalandı (Idefix sırayı bekler)
        if self.order_status == 'shipment_ready' and not self._send_picking(api_client, source):
            self.invoice_error = "'Hazırlanıyor' bildirimi başarısız"
            return False
        if self.order_status in _INVOICEABLE_STATUSES:
            res = api_client.update_shipment_status(self.order_id, 'invoiced', invoice_number=number or '')
            if not res.get('success'):
                self.invoice_error = f"Faturalandı bildirimi: {str(res.get('error') or 'Bilinmeyen hata')[:220]}"
                _logger.warning("Idefix invoiced bildirimi başarısız %s: %s", self.order_id, self.invoice_error)
                return False
            self.write({'order_status': 'shipment_invoiced', 'invoice_number': number or False})
            so.message_post(body=f"Idefix sevkiyatı {self.order_id} 'Faturalandı' bildirildi ({source})"
                                 f"{f' — fatura no {number}' if number else ''}.")
        elif self.order_status not in _INVOICE_LINK_STATUSES:
            self.invoice_error = f"Sevkiyat statüsü fatura gönderimine uygun değil: {self.order_status_display}"
            return False

        # 2) Fatura linki
        res = api_client.send_invoice_link(self.order_id, url)
        if res.get('success'):
            self.write({'invoice_sent': True, 'invoice_url': url, 'invoice_sent_date': now, 'invoice_error': False,
                        'invoice_number': number or self.invoice_number})
            so.message_post(body=f"Fatura linki Idefix'e gönderildi ({source}): {url}")
            return True
        self.invoice_error = str(res.get('error') or 'Bilinmeyen hata')[:250]
        _logger.warning("Idefix fatura linki gönderilemedi %s: %s", self.order_id, self.invoice_error)
        return False

    @api.private
    def _send_pending_invoices(self, store, api_client):
        """'Faturayı Idefix'e Gönder' açıksa, faturası kesilmiş sevkiyatların fatura bilgisini gönderir."""
        if not store.auto_send_invoice:
            return
        now = fields.Datetime.now()
        candidates = self.search([
            ('store_id', '=', store.id),
            ('invoice_sent', '=', False),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', '=', 'sale'),
            ('order_status', 'in', list(_INVOICE_LINK_STATUSES)),
            ('order_date', '>=', now - _INVOICE_LOOKBACK),
            '|', ('invoice_attempt_date', '=', False),
            ('invoice_attempt_date', '<', now - _INVOICE_RETRY_AFTER),
        ], order='invoice_attempt_date asc nulls first, id', limit=200)
        # Yalnızca Odoo'da faturası onaylanmış siparişler (Nebim faturası bu adımda kesilir)
        candidates = candidates.filtered(
            lambda o: o.sale_order_id.invoice_ids.filtered(lambda m: m.state == 'posted'))[:_INVOICE_BATCH]
        for rec in candidates:
            try:
                with self.env.cr.savepoint():
                    rec._send_invoice_to_idefix(api_client)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("Idefix fatura gönderim hatası %s: %s", rec.order_number, e)

    def action_send_invoice(self):
        """Form butonu: faturalandı statüsü + fatura linkini Idefix'e gönder."""
        for rec in self:
            if not rec._send_invoice_to_idefix(source='Manuel'):
                raise UserError(_("%s: fatura gönderilemedi — %s", rec.order_number, rec.invoice_error))
        return self._notify('Fatura', "Fatura bilgisi Idefix'e gönderildi.", 'success')

    # ─── Tedarik edilemedi ───────────────────────────────────

    def action_open_unsupplied_wizard(self):
        self.ensure_one()
        if self.order_status in IDEFIX_CANCEL_STATUSES:
            raise UserError(_("%s: sevkiyat zaten kapalı (%s).", self.order_number, self.order_status_display))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tedarik Edilemedi Bildir'),
            'res_model': 'idefix.unsupplied.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_idefix_order_id': self.id},
        }

"""Pazarama fatura linki gönderimi ve manuel sipariş onayı."""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .pazarama_order import PAZARAMA_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

_INVOICE_RETRY_AFTER = timedelta(minutes=30)
_INVOICE_LOOKBACK = timedelta(days=30)
_INVOICE_BATCH = 10


class PazaramaOrderInvoice(models.Model):
    _inherit = 'pazarama.order'

    def _get_nebim_invoice_url(self):
        """Nebim e-arşiv / e-fatura linki: (url, hata)."""
        self.ensure_one()
        so = self.sale_order_id
        if 'odoougurlar.nebim.connector' not in self.env:
            return False, 'Nebim modülü yüklü değil'
        doc_number = so.client_order_ref or so.name
        try:
            result = self.env['odoougurlar.nebim.connector'].sudo().run_proc(
                'usp_Invoice_EArchieveURL', [{'Name': 'DocumentNumber', 'Value': doc_number}])
        except Exception as e:
            return False, f'Nebim fatura linki alınamadı: {e}'
        row = (result[0] if isinstance(result, list) and result else result) or {}
        url = row.get('InvoiceURL') if isinstance(row, dict) else ''
        if not url:
            return False, 'Fatura linki henüz oluşmamış'
        return url, False

    def _send_invoice_to_pazarama(self, api_client=None, source='Otomatik'):
        """Nebim fatura linkini Pazarama'ya gönderir (siparişin tamamı için). Başarılıysa True."""
        self.ensure_one()
        now = fields.Datetime.now()
        self.invoice_attempt_date = now
        if not self.sale_order_id:
            self.invoice_error = 'Odoo siparişi yok'
            return False
        url, error = self._get_nebim_invoice_url()
        if not url:
            self.invoice_error = error
            return False
        api_client = api_client or self.store_id.get_api()
        res = api_client.send_invoice_link(self.order_id, url)
        if res.get('success'):
            self.write({'invoice_sent': True, 'invoice_url': url, 'invoice_sent_date': now, 'invoice_error': False})
            self.sale_order_id.message_post(body=f"Fatura linki Pazarama'ya gönderildi ({source}): {url}")
            return True
        self.invoice_error = str(res.get('error') or 'Bilinmeyen hata')[:250]
        _logger.warning("Pazarama fatura gönderilemedi %s: %s", self.order_number, self.invoice_error)
        return False

    @api.private
    def _send_pending_invoices(self, store, api_client):
        """'Faturayı Pazarama'ya Gönder' açıksa, faturası kesilmiş siparişlerin linkini gönderir."""
        if not store.auto_send_invoice:
            return
        now = fields.Datetime.now()
        candidates = self.search([
            ('store_id', '=', store.id),
            ('invoice_sent', '=', False),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', '=', 'sale'),
            ('order_status', 'not in', list(PAZARAMA_CANCEL_STATUSES)),
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
                    rec._send_invoice_to_pazarama(api_client)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("Pazarama fatura gönderim hatası %s: %s", rec.order_number, e)

    def action_send_invoice(self):
        """Form butonu: fatura linkini Pazarama'ya gönder."""
        for rec in self:
            if not rec._send_invoice_to_pazarama(source='Manuel'):
                raise UserError(_("%s: fatura gönderilemedi — %s", rec.order_number, rec.invoice_error))
        return self._notify('Fatura', "Fatura linki Pazarama'ya gönderildi.", 'success')

    def action_accept_order(self):
        """Form butonu: 'Sipariş Alındı' kalemlerini Pazarama'da 'Hazırlanıyor' yap."""
        for rec in self:
            lines = rec.line_ids.filtered(lambda l: l.status == 3)
            if not lines:
                raise UserError(_("%s: onaylanacak ('Sipariş Alındı') kalem yok.", rec.order_number))
            if not rec.sale_order_id:
                raise UserError(_("%s: önce Odoo siparişi oluşmalı.", rec.order_number))
            if not rec._accept_lines(lines, rec.sale_order_id, 'Manuel'):
                raise UserError(_("%s: Pazarama onayı başarısız. Pazarama yanıtı için logu kontrol edin.",
                                  rec.order_number))
        return self._notify('Onay', "Kalemler Pazarama'da 'Hazırlanıyor' statüsüne alındı.", 'success')

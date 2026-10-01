"""PttAVM kargo barkodu (Shipment API) ve fatura linki gönderimi."""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .pttavm_order import PTTAVM_CANCEL_STATUSES

_logger = logging.getLogger(__name__)

_BARCODE_POLL_LIMIT = 20
_INVOICE_RETRY_AFTER = timedelta(minutes=30)
_INVOICE_LOOKBACK = timedelta(days=30)
_INVOICE_BATCH = 10


class PttavmOrderCargo(models.Model):
    _inherit = 'pttavm.order'

    # ─── KARGO BARKODU ───────────────────────────────────────

    def _request_cargo_barcode(self, store=None, record=None):
        """PttAVM'den kargo barkodu talep eder (asenkron). (başarılı mı, mesaj) döner.
        Sonuç sonraki senkronda barcode-status ile sorgulanır."""
        self.ensure_one()
        store = store or self.store_id
        record = record or self.sale_order_id
        if not store.pttavm_warehouse_id:
            return False, f"PttAVM Depo ID ayarlanmamış ({store.name})"
        res = store.get_api().create_barcode(order_id=self.order_number, warehouse_id=store.pttavm_warehouse_id)
        data = res.get('data') if isinstance(res.get('data'), dict) else {}
        tracking_id = data.get('tracking_id')
        ok = res.get('success') and tracking_id and not data.get('error') and data.get('success', True) is not False
        now = fields.Datetime.now()
        if ok:
            self.write({
                'cargo_barcode_tracking_id': tracking_id,
                'cargo_barcode_state': 'pending',
                'cargo_barcode_message': False,
                'cargo_barcode_date': now,
            })
            msg = f"PttAVM kargo barkodu talep edildi (talep no: {tracking_id})."
        else:
            reason = data.get('message') or res.get('error') or str(data)[:200] or 'Bilinmeyen hata'
            self.write({'cargo_barcode_state': 'error', 'cargo_barcode_message': reason[:250],
                        'cargo_barcode_date': now})
            msg = f"PttAVM kargo barkodu talebi başarısız: {reason}"
            _logger.warning("PttAVM %s: %s", self.order_number, msg)
        if record:
            record.message_post(body=msg)
        return bool(ok), msg

    def _apply_barcode_status(self, data):
        """barcode-status yanıtını kayda işler. Durum değiştiyse True."""
        self.ensure_one()
        status = (data.get('status') or '').lower()
        if status == 'completed':
            barcodes = []
            rows = data.get('data') or []
            for row in rows:
                if isinstance(row, dict) and str(row.get('order_id') or '') == self.order_number:
                    barcodes.extend(row.get('barcodes') or [])
            if not barcodes and len(rows) == 1 and isinstance(rows[0], dict):
                barcodes = list(rows[0].get('barcodes') or [])
            barcode = ','.join(str(b) for b in barcodes if b)
            vals = {'cargo_barcode_state': 'completed', 'cargo_barcode': barcode, 'cargo_barcode_message': False}
            if barcode and not self.cargo_tracking_number:
                vals['cargo_tracking_number'] = barcode
            self.write(vals)
            so = self.sale_order_id
            if so:
                so.message_post(body=f"PttAVM kargo barkodu oluşturuldu: {barcode or '-'}")
                if barcode:
                    pickings = so.picking_ids.filtered(
                        lambda p: p.picking_type_code == 'outgoing' and p.state != 'cancel'
                        and not p.carrier_tracking_ref)
                    if pickings and 'carrier_tracking_ref' in pickings._fields:
                        pickings.write({'carrier_tracking_ref': barcode})
            return True
        if status == 'error':
            reason = data.get('error') or data.get('message') or 'Barkod oluşturulamadı'
            reason = str(reason)[:250]
            self.write({'cargo_barcode_state': 'error', 'cargo_barcode_message': reason})
            if self.sale_order_id:
                self.sale_order_id.message_post(body=f"PttAVM kargo barkodu oluşturulamadı: {reason}")
            return True
        return False  # pending

    @api.private
    def _poll_cargo_barcodes(self, store, api_client):
        """Bekleyen barkod taleplerinin sonucunu sorgular."""
        pending = self.search([
            ('store_id', '=', store.id),
            ('cargo_barcode_state', '=', 'pending'),
            ('cargo_barcode_tracking_id', '!=', False),
        ], limit=_BARCODE_POLL_LIMIT, order='cargo_barcode_date asc')
        for rec in pending:
            res = api_client.get_barcode_status(rec.cargo_barcode_tracking_id)
            if not res.get('success'):
                _logger.warning("PttAVM barkod durumu sorgulanamadı %s: %s", rec.order_number, res.get('error'))
                break
            data = res.get('data') if isinstance(res.get('data'), dict) else {}
            try:
                with self.env.cr.savepoint():
                    rec._apply_barcode_status(data)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("PttAVM barkod durumu işlenemedi %s: %s", rec.order_number, e)

    def action_create_cargo_barcode(self):
        """Form butonu: kargo barkodu talep et (tekrar dene)."""
        for rec in self:
            if rec.cargo_barcode_state == 'completed':
                raise UserError(_("%s için barkod zaten oluşturulmuş: %s", rec.order_number, rec.cargo_barcode))
            ok, msg = rec._request_cargo_barcode()
            if not ok:
                raise UserError(msg)
        return self._notify('Kargo Barkodu', 'Barkod talebi gönderildi; sonuç birkaç dakika içinde siparişe yazılır.',
                            'success')

    def action_check_cargo_barcode(self):
        """Form butonu: bekleyen barkod talebinin sonucunu hemen sorgula."""
        for rec in self.filtered('cargo_barcode_tracking_id'):
            res = rec.store_id.get_api().get_barcode_status(rec.cargo_barcode_tracking_id)
            if not res.get('success'):
                raise UserError(_("Barkod durumu sorgulanamadı: %s", res.get('error')))
            data = res.get('data') if isinstance(res.get('data'), dict) else {}
            if not rec._apply_barcode_status(data):
                return self._notify('Kargo Barkodu', 'Barkod henüz hazır değil (bekliyor).', 'warning')
        return self._notify('Kargo Barkodu', 'Barkod durumu güncellendi.', 'success')

    # ─── FATURA LİNKİ ────────────────────────────────────────

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

    def _send_invoice_to_pttavm(self, api_client=None, source='Otomatik'):
        """Nebim fatura linkini PttAVM'ye gönderir. Başarılıysa True."""
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
        line_ids = [int(l.item_id) for l in self._active_lines() if (l.item_id or '').isdigit()]
        if not line_ids:
            self.invoice_error = 'Gönderilecek satır (lineItemId) yok'
            return False
        api_client = api_client or self.store_id.get_api()
        res = api_client.send_invoice(self.order_number, line_ids, url=url)
        data = res.get('data') if isinstance(res.get('data'), dict) else {}
        ok = res.get('success') and data.get('success', True) is not False
        if ok:
            self.write({'invoice_sent': True, 'invoice_url': url, 'invoice_sent_date': now, 'invoice_error': False})
            self.sale_order_id.message_post(body=f"Fatura linki PttAVM'ye gönderildi ({source}): {url}")
            return True
        reason = data.get('error_Message') or data.get('errorMessage') or res.get('error') or 'Bilinmeyen hata'
        self.invoice_error = str(reason)[:250]
        _logger.warning("PttAVM fatura gönderilemedi %s: %s", self.order_number, reason)
        return False

    @api.private
    def _send_pending_invoices(self, store, api_client):
        """'Faturayı PttAVM'ye Gönder' açıksa, faturası kesilmiş siparişlerin linkini gönderir."""
        if not store.auto_send_invoice:
            return
        now = fields.Datetime.now()
        candidates = self.search([
            ('store_id', '=', store.id),
            ('invoice_sent', '=', False),
            ('sale_order_id', '!=', False),
            ('sale_order_id.state', '=', 'sale'),
            ('order_status', 'not in', list(PTTAVM_CANCEL_STATUSES)),
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
                    rec._send_invoice_to_pttavm(api_client)
            except Exception as e:
                self.env.invalidate_all(flush=False)
                _logger.exception("PttAVM fatura gönderim hatası %s: %s", rec.order_number, e)

    def action_send_invoice(self):
        """Form butonu: fatura linkini PttAVM'ye gönder."""
        for rec in self:
            if not rec._send_invoice_to_pttavm(source='Manuel'):
                raise UserError(_("%s: fatura gönderilemedi — %s", rec.order_number, rec.invoice_error))
        return self._notify('Fatura', "Fatura linki PttAVM'ye gönderildi.", 'success')

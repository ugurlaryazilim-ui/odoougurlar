import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """Fatura modeline Nebim entegrasyon alanları eklenir."""
    _inherit = 'account.move'

    nebim_sent = fields.Boolean(
        string='Nebim\'e Gönderildi',
        default=False,
        readonly=True,
        help='Bu fatura Nebim\'e başarıyla iletildi mi?',
    )
    nebim_sent_date = fields.Datetime(
        string='Nebim Gönderim Tarihi',
        readonly=True,
    )
    nebim_response = fields.Text(
        string='Nebim Yanıtı',
        readonly=True,
        help='Nebim API\'sinden dönen yanıt',
    )
    nebim_error = fields.Text(
        string='Nebim Hata',
        readonly=True,
        help='Gönderim sırasında oluşan hata mesajı',
    )
    nebim_invoice_number = fields.Char(
        string='Nebim Fatura No',
        readonly=True,
        help='Nebim tarafında oluşan fatura numarası (UGE/UGI serisi)',
    )

    def action_post(self):
        """
        Fatura onaylandığında UGO serisi ile numaralandır.
        
        Odoo 19: move.name doğrudan set edilebilir (super() çağrısı sonrasında).
        Alternatif: journal'da sequence_override_regex kullanılabilir.
        """
        res = super().action_post()
        for move in self:
            try:
                if move.move_type == 'out_invoice' and move.name and move.name.startswith(('INV/', 'RINV/', '/')):
                    seq = self.env['ir.sequence'].next_by_code('ugo.invoice.sequence')
                    if seq:
                        move.name = seq
                        _logger.info("Fatura numarası UGO serisi ile güncellendi: %s", seq)
            except Exception as e:
                _logger.warning("UGO seri numarası atanamadı (fatura yine de onaylandı): %s", e)
        return res

    def action_retry_nebim_send(self):
        """Hata almış faturayı Nebim'e tekrar gönder."""
        self.ensure_one()
        if self.nebim_sent:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Bilgi', 'message': 'Bu fatura zaten Nebim\'e gönderilmiş.', 'type': 'info'}}
        try:
            invoice_proc = self.env['odoougurlar.invoice.processor'].sudo()
            connector = self.env['odoougurlar.nebim.connector'].sudo()
            payload = invoice_proc._build_invoice_payload(self)
            result = connector.post_data('Post', payload)
            
            if isinstance(result, dict) and 'ExceptionMessage' in result:
                raise Exception(result['ExceptionMessage'])
            
            # Nebim fatura numarasını ayrıştır
            nebim_inv_no = ''
            if isinstance(result, dict):
                nebim_inv_no = result.get('DocumentNumber', '') or result.get('EInvoiceNumber', '') or result.get('InvoiceNumber', '')
            elif isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                nebim_inv_no = result[0].get('DocumentNumber', '') or result[0].get('EInvoiceNumber', '') or result[0].get('InvoiceNumber', '')
            
            write_vals = {
                'nebim_sent': True,
                'nebim_sent_date': fields.Datetime.now(),
                'nebim_response': str(result),
                'nebim_error': False,
            }
            if nebim_inv_no:
                write_vals['nebim_invoice_number'] = nebim_inv_no
            self.write(write_vals)
            
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Başarılı', 'message': f'Fatura Nebim\'e gönderildi: {nebim_inv_no}', 'type': 'success'}}
        except Exception as e:
            self.write({'nebim_error': str(e)})
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Hata', 'message': f'Nebim gönderim hatası: {str(e)}', 'type': 'danger'}}

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
    nebim_request = fields.Text(
        string='Nebim İstek',
        readonly=True,
        help='Nebim API\'sine gönderilen JSON payload',
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
            import json
            invoice_proc = self.env['odoougurlar.invoice.processor'].sudo()
            connector = self.env['odoougurlar.nebim.connector'].sudo()
            payload = invoice_proc._build_invoice_payload(self)
            self.write({'nebim_request': json.dumps(payload, ensure_ascii=False, indent=2, default=str)})
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

    def action_view_earchive_invoice(self):
        """Nebim'den e-arşiv fatura URL'sini alıp yeni sekmede açar.
        
        usp_Invoice_EArchieveURL stored procedure'ü:
            @DocumentNumber → InvoiceURL, EInvoiceNumber, InvoiceDate
        """
        self.ensure_one()

        # 1. İlişkili satış siparişini bul
        doc_number = ''
        if self.invoice_origin:
            sale_orders = self.env['sale.order'].sudo().search(
                [('name', '=', self.invoice_origin.split(',')[0].strip())], limit=1
            )
            if sale_orders:
                doc_number = sale_orders.client_order_ref or sale_orders.name

        if not doc_number:
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Hata',
                               'message': 'Bu fatura için sipariş referansı (DocumentNumber) bulunamadı.',
                               'type': 'warning'}}

        # 2. Nebim SP çağır
        try:
            connector = self.env['odoougurlar.nebim.connector'].sudo()
            params = [{'Name': 'DocumentNumber', 'Value': doc_number}]
            result = connector.run_proc('usp_Invoice_EArchieveURL', params)

            if not result or (isinstance(result, list) and len(result) == 0):
                return {'type': 'ir.actions.client', 'tag': 'display_notification',
                        'params': {'title': 'Bilgi',
                                   'message': f'DocumentNumber "{doc_number}" için e-arşiv fatura bulunamadı.',
                                   'type': 'warning'}}

            # 3. URL'yi çıkar
            row = result[0] if isinstance(result, list) else result
            invoice_url = row.get('InvoiceURL', '') if isinstance(row, dict) else ''

            if not invoice_url:
                return {'type': 'ir.actions.client', 'tag': 'display_notification',
                        'params': {'title': 'Bilgi',
                                   'message': f'Fatura URL\'si henüz oluşmamış. (EInvoice: {row.get("EInvoiceNumber", "")})',
                                   'type': 'warning'}}

            # 4. Modal viewer'da göster
            einvoice_number = row.get('EInvoiceNumber', '') if isinstance(row, dict) else ''
            return {
                'type': 'ir.actions.client',
                'tag': 'earchive_viewer',
                'name': 'E-Arşiv Fatura',
                'params': {
                    'invoice_url': invoice_url,
                    'einvoice_number': einvoice_number,
                },
            }

        except Exception as e:
            _logger.error("E-Arşiv fatura URL hatası (DocumentNumber=%s): %s", doc_number, e)
            return {'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': 'Hata',
                               'message': f'E-arşiv fatura sorgulanırken hata: {str(e)}',
                               'type': 'danger'}}

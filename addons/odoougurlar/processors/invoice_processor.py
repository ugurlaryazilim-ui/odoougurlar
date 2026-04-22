import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class InvoiceProcessor(models.AbstractModel):
    """
    Odoo'da onaylanmış satış faturalarını toplayıp Nebim'e gönderen processor.
    
    Nebim ModelType 8 (Perakende Satış Faturası) veya 24 (İhracat Faturası).
    """
    _name = 'odoougurlar.invoice.processor'
    _description = 'Nebim Fatura Processor'

    def process_invoices(self):
        """
        Gönderilmemiş onaylı faturaları Nebim'e iletir.
        
        Returns:
            dict: İstatistikler
        """
        stats = {'processed': 0, 'updated': 0, 'failed': 0}

        # Gönderilmemiş, onaylanmış satış faturalarını bul
        invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('nebim_sent', '=', False),
        ])

        if not invoices:
            _logger.info("Gönderilecek fatura yok.")
            return stats

        connector = self.env['odoougurlar.nebim.connector']

        for invoice in invoices:
            stats['processed'] += 1
            try:
                with self.env.cr.savepoint():
                    payload = self._build_invoice_payload(invoice)
                    result = connector.post_data('Post', payload)

                    invoice.write({
                        'nebim_sent': True,
                        'nebim_sent_date': fields.Datetime.now(),
                        'nebim_response': str(result),
                        'nebim_error': False,
                    })
                    stats['updated'] += 1
                    _logger.info("Fatura Nebim'e gönderildi: %s", invoice.name)

            except Exception as e:
                stats['failed'] += 1
                try:
                    invoice.write({'nebim_error': str(e)})
                except Exception:
                    _logger.warning("Fatura hata kaydı yazılamadı: %s", invoice.name)
                _logger.error(
                    "Fatura gönderim hatası [%s]: %s",
                    invoice.name, str(e)
                )

        return stats

    def _build_invoice_payload(self, invoice):
        """
        Odoo faturasını Nebim JSON formatına dönüştürür.
        
        İhracat (ModelType 24): HamurLabs formatına birebir uyumlu.
        Perakende (ModelType 8): Hamurlabs InvoiceR_SiparisBazli.txt şablonuna uygun.
        """
        sale_order = invoice.line_ids.sale_line_ids.order_id[:1]
            
        mapping = False
        if sale_order:
            mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                'Trendyol', sale_order.partner_id.country_id.id
            )

        # Müşteri kodunu önce sale_order'dan al (Nebim cari oluştururken kaydettiğimiz)
        customer_code = ''
        if sale_order and sale_order.nebim_customer_code:
            customer_code = sale_order.nebim_customer_code
        elif mapping and mapping.nebim_customer_code:
            customer_code = mapping.nebim_customer_code
        else:
            customer_code = invoice.partner_id.vat or invoice.partner_id.ref or 'B2C'
            
        model_type = int(mapping.nebim_invoice_model_type) if mapping and mapping.nebim_invoice_model_type else 8
        is_export = model_type == 24
        
        # Adres ID
        address_id = ''
        if sale_order and sale_order.nebim_address_id:
            address_id = sale_order.nebim_address_id
        elif mapping and mapping.nebim_address_id:
            address_id = mapping.nebim_address_id

        if is_export:
            return self._build_export_invoice(invoice, sale_order, mapping, customer_code, address_id)
        else:
            return self._build_retail_invoice(invoice, sale_order, mapping, customer_code, model_type, address_id)

    # ═══════════════════════════════════════════════════════════════
    # İHRACAT FATURASI (ModelType 24) — HamurLabs formatına uyumlu
    # ═══════════════════════════════════════════════════════════════

    def _build_export_invoice(self, invoice, sale_order, mapping, customer_code, address_id):
        """ModelType 24 — İhracat Faturası (Mikro İhracat dahil).
        
        Gerçek HamurLabs üretim payload'una birebir uyumlu.
        """
        
        # Tarih formatı: YYYYMMDD (HamurLabs gerçek payload: "20260409")
        invoice_date_str = invoice.invoice_date.strftime('%Y%m%d') if invoice.invoice_date else ''
        
        # Mapping'den ihracat değerlerini al
        m_store = (mapping.store_code if mapping and mapping.store_code else '002')
        m_warehouse = (mapping.warehouse_code if mapping and mapping.warehouse_code else '002')
        m_sales_url = (mapping.sales_url if mapping and mapping.sales_url else 'www.trendyol.com')
        m_sales_person = (mapping.sales_person_code if mapping and mapping.sales_person_code else 'TRD')
        m_export_type = '001' # UI'dan gelen manuel 2 veya 002 denemelerini ezmek için sabitlendi!
        m_tax_exemption = (mapping.tax_exemption_code if mapping and mapping.tax_exemption_code else '301')
        m_incoterm = (mapping.incoterm_code if mapping and getattr(mapping, 'incoterm_code', None) else 'FCA')
        m_payment_means = (mapping.payment_means_code if mapping and getattr(mapping, 'payment_means_code', None) else '10')
        m_cc_type = (mapping.credit_card_type_code if mapping and mapping.credit_card_type_code else 'TRD')
        
        # ExportFileNumber — Siparişte atanan numaranın AYNISI kullanılmalı!
        export_file_number = ''
        if sale_order and sale_order.nebim_export_file_number:
            export_file_number = sale_order.nebim_export_file_number
            _logger.info("Fatura ExportFileNumber siparişten alındı: %s", export_file_number)
        else:
            try:
                connector = self.env['odoougurlar.nebim.connector']
                next_num_res = connector.run_proc('sp_GetNextExportFileNumber_Hamurlabs')
                if next_num_res and isinstance(next_num_res, list) and len(next_num_res) > 0:
                    export_file_number = str(next_num_res[0].get('NextExportFileNumber') or '')
                    _logger.info("Nebim ExportFileNumber hesaplandı (YENİ): %s", export_file_number)
            except Exception as e:
                _logger.warning("ExportFileNumber alınırken hata oluştu (sp_GetNextExportFileNumber_Hamurlabs eksik olabilir): %s", e)
        
        # E-posta adresi
        email_address = ''
        if sale_order and hasattr(sale_order, 'trendyol_order_id') and sale_order.trendyol_order_id:
            email_address = sale_order.trendyol_order_id.customer_email or ''
        elif invoice.partner_id.email:
            email_address = invoice.partner_id.email or ''
        
        # InternalDescription — "paketID_siparişNo" formatı
        internal_desc = ''
        if sale_order and hasattr(sale_order, 'trendyol_order_id') and sale_order.trendyol_order_id:
            ty = sale_order.trendyol_order_id
            pkg_id = ty.shipment_package_id or ''
            order_no = ty.trendyol_order_number or ''
            internal_desc = f"{pkg_id}_{order_no}" if pkg_id and order_no else (pkg_id or order_no)
        
        # Description — Odoo fatura numarası (HamurLabs: "UGE2026000003293")
        description = invoice.name or (sale_order.name if sale_order else '')
        
        # ── Satır verileri — HamurLabs: OrderLineID + Qty1 + ExportFileNumber + UsedBarcode + Price + SalesPersonCode ──
        lines = []
        for line in invoice.invoice_line_ids:
            if not line.product_id:
                continue

            sale_line = line.sale_line_ids[0] if line.sale_line_ids else False
            
            line_data = {
                'Qty1': float(line.quantity),
                'ExportFileNumber': export_file_number,
                'UsedBarcode': line.product_id.barcode or '',
                'Price': float(line.price_unit),
                'SalesPersonCode': m_sales_person,
            }
            
            if sale_line and sale_line.nebim_order_line_id:
                line_data['OrderLineID'] = sale_line.nebim_order_line_id

            lines.append(line_data)

        # ── Tarih hesaplamaları ──
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        payment_date_str = sale_order.date_order.strftime('%Y-%m-%d %H:%M:%S') if sale_order and sale_order.date_order else now_str
            
        epoch_s = int(datetime.now().timestamp())
        document_date_str = f"\\/Date({epoch_s})\\/"
        
        # ── Ana payload — İnternet deposu (002) kurallarını aşmak için tam internet payload'u ──
        payload = {
            'IsCompleted': True,
            'IsOrderBase': True,
            'IsShipmentBase': False,
            'SendInvoiceByEMail': True,
            'POSTerminalID': '0',
            'ModelType': 24,
            'CustomerCode': customer_code,
            'OfficeCode': 'M',
            'StoreCode': m_store,
            'WarehouseCode': m_warehouse,
            'ExportFileNumber': export_file_number,
            'TaxExemptionCode': m_tax_exemption,
            'IncotermCode1': m_incoterm,
            'ShipmentMethodCode': '1',
            'InvoiceDate': invoice_date_str,
            'OperationDate': invoice_date_str,
            'DeliveryCompanyCode': '',
            'Description': description[:50],
            'InternalDescription': (internal_desc or sale_order.name if sale_order else '')[:50],
            'EMailAddress': email_address,
            'IsSalesViaInternet': True,
            'InvoiceHeaderExtension': {
                'ExportTypeCode': m_export_type,
                'PaymentMeansCode': m_payment_means,
            },
            'Payments': [{
                'CreditCardTypeCode': m_cc_type,
                'Code': '',
                'InstallmentCount': 1,
                'DocumentDate': document_date_str,
                'PaymentType': '2',
                'Amount': float(invoice.amount_total),
                'CurrencyCode': 'TRY',
            }],
            'SalesViaInternetInfo': {
                'PaymentTypeDescription': 'KREDIKARTI/BANKAKARTI',
                'SendDate': now_str,
                'PaymentDate': payment_date_str,
                'SalesURL': m_sales_url,
                'PaymentTypeCode': 1,
                'PaymentAgent': ''
            },
            'Lines': lines,
            'DocumentTypeCode': 5
        }
        
        _logger.info("İhracat faturası payload hazırlandı: %s (MT24)", invoice.name)
        _logger.info(f"FATURA MT24 PAYLOAD: {payload}")
        return payload

    # ═══════════════════════════════════════════════════════════════
    # PERAKENDE FATURASI (ModelType 8) — Mevcut format korunuyor
    # ═══════════════════════════════════════════════════════════════

    def _build_retail_invoice(self, invoice, sale_order, mapping, customer_code, model_type, address_id):
        """ModelType 8 — Perakende Fatura (e-Arşiv)."""
        
        # Tarih formatı: YYYYMMDD
        invoice_date_str = invoice.invoice_date.strftime('%Y%m%d') if invoice.invoice_date else ''
        
        # Sipariş Bazlı mı? (OrderLineID var mı kontrol et)
        is_order_base = False
        lines = []
        for line in invoice.invoice_line_ids:
            if not line.product_id:
                continue

            sale_line = line.sale_line_ids[0] if line.sale_line_ids else False
            if sale_line and sale_line.nebim_order_line_id:
                # Sipariş Bazlı Fatura (OrderLineID kullanılır)
                is_order_base = True
                line_data = {
                    'OrderLineID': sale_line.nebim_order_line_id,
                    'Qty1': line.quantity,
                }
                if line.product_id.barcode:
                    line_data['UsedBarcode'] = line.product_id.barcode
            else:
                # Serbest Fatura (Fiyat ve ItemCode gönderilir)
                line_data = {
                    'ItemCode': line.product_id.default_code or '',
                    'Qty1': line.quantity,
                    'PriceVI': line.price_unit,
                }
                if line.product_id.barcode:
                    line_data['UsedBarcode'] = line.product_id.barcode

            lines.append(line_data)

        # Mapping'den değerleri al
        m_store = (mapping.store_code if mapping and mapping.store_code else '002')
        m_warehouse = (mapping.warehouse_code if mapping and mapping.warehouse_code else '002')
        m_delivery = (mapping.delivery_company_code if mapping and mapping.delivery_company_code else 'YRT')
        m_sales_url = (mapping.sales_url if mapping and mapping.sales_url else 'www.trendyol.com')

        # SalesViaInternetInfo tarihler
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        payment_date_str = ''
        if sale_order and sale_order.date_order:
            payment_date_str = sale_order.date_order.strftime('%Y-%m-%d %H:%M:%S')

        # Hamurlabs InvoiceR_SiparisBazli.txt şablonuna göre payload
        payload = {
            'ModelType': model_type,
            'CustomerCode': customer_code,
            'Description': sale_order.client_order_ref or sale_order.name if sale_order else invoice.name,
            'InvoiceDate': invoice_date_str,
            'OfficeCode': 'M',
            'StoreCode': m_store,
            'WarehouseCode': m_warehouse,
            'POSTerminalID': 1,
            'ShipmentMethodCode': '2',
            'DeliveryCompanyCode': m_delivery,
            'IsOrderBase': is_order_base,
            'IsSalesViaInternet': True,
            'IsCompleted': True,
            'Lines': lines,
            'Payments': [{
                'PaymentType': '2',
                'Code': '',
                'CreditCardTypeCode': mapping.credit_card_type_code if mapping and mapping.credit_card_type_code else 'TRD',
                'InstallmentCount': 1,
                'CurrencyCode': 'TRY',
                'AmountVI': invoice.amount_total,
            }],
            'SalesViaInternetInfo': {
                'SalesURL': m_sales_url,
                'PaymentTypeCode': 1,
                'PaymentTypeDescription': 'KREDIKARTI/BANKAKARTI',
                'PaymentDate': payment_date_str,
                'SendDate': now_str,
            },
        }
        
        # Adres ID varsa ekle
        if address_id:
            payload['BillingPostalAddressID'] = address_id
            payload['ShippingPostalAddressID'] = address_id

        # Kurumsal müşteri ve E-Fatura kaydı VARSA → E-Fatura bilgileri ekle
        # E-Fatura bloğu SADECE Nebim'de e-fatura mükellefi olarak kayıtlı müşteriler için gönderilir
        # Aksi halde Nebim "EInvoice not found!" hatası verir
        # TODO: Trendyol'dan gelen isEInvoiceAvailable bayrağını trendyol.order modeline ekleyip buradan kontrol et
        # Şimdilik e-fatura bloğu göndermiyoruz — Nebim zaten e-fatura mükellefi ise otomatik keser

        return payload

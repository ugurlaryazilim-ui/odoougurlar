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
            raw_result = None
            try:
                with self.env.cr.savepoint():
                    payload = self._build_invoice_payload(invoice)
                    raw_result = connector.post_data('Post', payload)

                    # ExceptionMessage kontrolu
                    if isinstance(raw_result, dict) and raw_result.get('ExceptionMessage'):
                        raise Exception(raw_result['ExceptionMessage'])

                    # Nebim fatura numarasını çıkar
                    nebim_invoice_number = ''
                    if isinstance(raw_result, dict):
                        nebim_invoice_number = (
                            raw_result.get('InvoiceNumber')
                            or raw_result.get('HeaderID')
                            or ''
                        )

                    invoice.write({
                        'nebim_sent': True,
                        'nebim_sent_date': fields.Datetime.now(),
                        'nebim_response': str(raw_result),
                        'nebim_error': False,
                        'nebim_invoice_number': str(nebim_invoice_number),
                    })
                    stats['updated'] += 1
                    _logger.info("Fatura Nebim'e gönderildi: %s → %s", invoice.name, nebim_invoice_number)

            except Exception as e:
                stats['failed'] += 1
                _logger.error("Fatura gönderim hatası [%s]: %s", invoice.name, str(e))
                # Hata kaydını savepoint DIŞINDA yaz — savepoint rollback yapsa bile
                # bu write çalışır ve kullanıcı hatayı Nebim Yanıt alanında görebilir.
                try:
                    invoice.write({
                        'nebim_error': str(e),
                        'nebim_response': str(raw_result) if raw_result is not None else 'Yanıt alınamadı',
                    })
                    self.env.cr.commit()
                except Exception as write_err:
                    _logger.warning("Fatura hata kaydı yazılamadı: %s — %s", invoice.name, write_err)

        return stats

    @api.private
    def _build_payment_entry(self, mapping, cc_type_code, amount, document_date=None, amount_key='Amount'):
        """Ödeme bloğu oluştur — tüm fatura tipleri için ortak.
        
        BankCode, mapping'deki bank_code alanından alınır.
        """
        entry = {
            'PaymentType': '2',
            'Code': '',
            'CreditCardTypeCode': cc_type_code,
            'InstallmentCount': 1,
            'CurrencyCode': 'TRY',
            amount_key: float(amount),
        }
        if document_date:
            entry['DocumentDate'] = document_date
        # Banka Kodu — mapping'den al
        if mapping and getattr(mapping, 'bank_code', ''):
            entry['BankCode'] = mapping.bank_code
        return entry

    @api.private
    def _build_invoice_payload(self, invoice):
        """
        Odoo faturasını Nebim JSON formatına dönüştürür.
        
        İhracat (ModelType 24): HamurLabs formatına birebir uyumlu.
        Perakende (ModelType 8): Hamurlabs InvoiceR_SiparisBazli.txt şablonuna uygun.
        """
        sale_order = invoice.line_ids.sale_line_ids.order_id[:1]
            
        # Pazaryeri tespiti — sale_order üzerindeki pazaryeri alanlarına bakarak
        marketplace_name = 'Trendyol'  # varsayılan fallback
        if sale_order:
            _mp_fields = [
                ('trendyol_order_id', 'Trendyol'),
                ('hb_order_id', 'Hepsiburada'),
                ('amazon_store_id', 'Amazon'),
                ('pazarama_order_id', 'Pazarama'),
                ('n11_order_id', 'N11'),
                ('flo_order_id', 'Flo'),
                ('idefix_order_id', 'Idefix'),
                ('pttavm_order_id', 'PttAvm'),
            ]
            for field, name in _mp_fields:
                if hasattr(sale_order, field) and getattr(sale_order, field):
                    marketplace_name = name
                    break

        mapping = False
        if sale_order:
            mapping = self.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
                marketplace_name, sale_order.partner_id.country_id.id
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

    @api.private
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
            'IsPostingJournal': True,
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
            'Payments': [self._build_payment_entry(
                mapping, m_cc_type, float(invoice.amount_total),
                document_date=document_date_str, amount_key='Amount'
            )],
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
        _logger.debug("FATURA MT24 PAYLOAD: %s", payload)
        return payload

    # ═══════════════════════════════════════════════════════════════
    # PERAKENDE FATURASI (ModelType 8) — Mevcut format korunuyor
    # ═══════════════════════════════════════════════════════════════

    @api.private
    def _build_retail_invoice(self, invoice, sale_order, mapping, customer_code, model_type, address_id):
        """ModelType 8 — Perakende Fatura (e-Arşiv)."""
        
        # Tarih formatı: YYYYMMDD
        invoice_date_str = invoice.invoice_date.strftime('%Y%m%d') if invoice.invoice_date else ''
        
        # ── Satır verileri ──
        # Strateji: OrderLineID varsa → sipariş bazlı fatura (Nebim siparişindeki fiyatı kullanır)
        #           OrderLineID yoksa → serbest fatura (Price alanıyla gönderilir)
        #
        # "Nebim Sıfırla" butonu ile güncel fiyatlarla sipariş Nebim'e gönderilir.
        # Bu siparişteki OrderLineID'ler sale.order.line'a kaydedilir.
        # Fatura bu OrderLineID'lere bağlandığında Nebim siparişteki (doğru) fiyatı kullanır.
        has_order_line_ids = False
        lines = []
        for line in invoice.invoice_line_ids:
            if not line.product_id:
                continue
            if not line.quantity or line.quantity <= 0:
                continue

            # Fatura satırını sipariş satırıyla eşleştir
            sale_line = line.sale_line_ids[0] if line.sale_line_ids else False
            order_line_id = sale_line.nebim_order_line_id if sale_line and sale_line.nebim_order_line_id else ''

            # OrderLineID varsa önce gelir, sonra Qty1 (integer)
            if order_line_id:
                # Sipariş bazlı: OrderLineID önce, Qty1 integer olarak
                line_data = {
                    'OrderLineID': order_line_id,
                    'Qty1': int(line.quantity),
                }
                has_order_line_ids = True
                _logger.info(
                    "Nebim Fatura Satır (SİPARİŞ BAZLI): %s | OrderLineID=%s | Qty=%s",
                    line.product_id.display_name, order_line_id, line.quantity,
                )
            else:
                # Serbest fatura: Price alanı ile fiyat gönderilir
                line_data = {
                    'Qty1': int(line.quantity),
                    'Price': float(line.price_unit),
                }
                if line.product_id.barcode:
                    line_data['UsedBarcode'] = line.product_id.barcode
                if line.product_id.default_code:
                    line_data['ItemCode'] = line.product_id.default_code
                _logger.info(
                    "Nebim Fatura Satır (SERBEST): %s | Barcode=%s | Price(KDV hariç)=%s",
                    line.product_id.display_name,
                    line_data.get('UsedBarcode', 'YOK'),
                    line.price_unit,
                )

            lines.append(line_data)

        is_order_base = has_order_line_ids
        _logger.info("Nebim Fatura Modu: %s", "SİPARİŞ BAZLI" if is_order_base else "SERBEST")

        # Mapping'den değerleri al
        m_store = (mapping.store_code if mapping and mapping.store_code else '002')
        m_warehouse = (mapping.warehouse_code if mapping and mapping.warehouse_code else '002')
        m_delivery = (mapping.delivery_company_code if mapping and mapping.delivery_company_code else 'YRT')
        m_sales_url = (mapping.sales_url if mapping and mapping.sales_url else 'www.trendyol.com')

        # SalesViaInternetInfo tarihler — /Date(epoch_ms)/ formatı (WCF/MS JSON)
        # NOT: \\/Date()\/ YANLIŞ — JSON'da \ gerekmez, sadece /Date()/ yeterli
        import time
        now_epoch_ms = int(time.time() * 1000)
        payment_epoch_ms = now_epoch_ms
        if sale_order and sale_order.date_order:
            payment_epoch_ms = int(sale_order.date_order.timestamp() * 1000)
        now_date_str = f"/Date({now_epoch_ms})/"
        payment_date_str = f"/Date({payment_epoch_ms})/"


        # ── E-posta adresi (e-arşiv fatura için gerekli) ──
        email_address = ''
        payment_agent = ''
        if sale_order:
            # Trendyol
            if hasattr(sale_order, 'trendyol_order_id') and sale_order.trendyol_order_id:
                email_address = sale_order.trendyol_order_id.customer_email or ''
                payment_agent = 'TrendyolMp'
            # Hepsiburada
            elif hasattr(sale_order, 'hb_order_id') and sale_order.hb_order_id:
                email_address = getattr(sale_order.hb_order_id, 'customer_email', '') or ''
                payment_agent = 'HepsiBuradaMp'
            # N11
            elif hasattr(sale_order, 'n11_order_id') and sale_order.n11_order_id:
                email_address = getattr(sale_order.n11_order_id, 'buyer_email', '') or ''
                payment_agent = 'N11Mp'
            # Amazon
            elif hasattr(sale_order, 'amazon_store_id') and sale_order.amazon_store_id:
                payment_agent = 'AmazonMp'
            # PttAvm
            elif hasattr(sale_order, 'pttavm_order_id') and sale_order.pttavm_order_id:
                payment_agent = 'PttAvmMp'
        # Fallback: partner email
        if not email_address and invoice.partner_id.email:
            email_address = invoice.partner_id.email or ''

        m_payment_agent = (mapping.payment_agent if mapping and mapping.payment_agent else payment_agent)

        # Minimal payload — sadece fatura için gereken alanlar
        desc = sale_order.client_order_ref or sale_order.name if sale_order else invoice.name
        payload = {
            'ModelType': model_type,
            'CustomerCode': customer_code,
            'Description': desc,
            'InternalDescription': desc,
            'InvoiceDate': invoice_date_str,
            'OfficeCode': 'M',
            'StoreCode': m_store,
            'WarehouseCode': m_warehouse,
            'POSTerminalID': 1,
            'ShipmentMethodCode': '2',
            'DeliveryCompanyCode': m_delivery,
            'IsOrderBase': is_order_base,
            'IsSalesViaInternet': True,
            'DocumentTypeCode': 4,
            'IsPostingJournal': True,
            'SendInvoiceByEMail': True,
            'EMailAddress': email_address,
            'Lines': lines,
            'SalesViaInternetInfo': {
                'SalesURL': m_sales_url,
                'PaymentTypeCode': 1,
                'PaymentTypeDescription': 'KREDIKARTI/BANKAKARTI',
                'PaymentDate': payment_date_str,
                'SendDate': now_date_str,
                'PaymentAgent': m_payment_agent,
            },
            'IsCompleted': True,
        }

        # ── Fatura PostalAddress — BillingPostalAddressID yerine doğrudan PostalAddress gönder ──
        # Nebim fatura API'si PostalAddress'i GİB e-fatura XML'ine aktarır.
        # BillingPostalAddressID gönderilince PostalAddress boş kalıyor → GİB şematron hatası.
        inv_partner = invoice.partner_id
        inv_vat_raw = (inv_partner.vat or '').strip()
        inv_vat_clean = ''.join(filter(str.isdigit, inv_vat_raw))
        inv_is_sahis = len(inv_vat_clean) == 11

        try:
            inv_nebim_codes = self.env['odoougurlar.customer.processor']._resolve_nebim_address_codes(inv_partner)
        except Exception:
            inv_nebim_codes = {}

        inv_name_parts = (inv_partner.name or '').strip().split()
        inv_first_name = inv_name_parts[0] if inv_name_parts else ''
        inv_last_name = ' '.join(inv_name_parts[1:]) if len(inv_name_parts) > 1 else ''

        payload['PostalAddress'] = {
            'Address':      (inv_partner.street or '')[:200],
            'CityCode':     inv_nebim_codes.get('city_code', ''),
            'CountryCode':  (inv_partner.country_id.code or 'TR').upper(),
            'DistrictCode': inv_nebim_codes.get('district_code', ''),
            'StateCode':    inv_nebim_codes.get('state_code', ''),
            'FirstName':    inv_first_name[:50] if inv_is_sahis else '',
            'LastName':     inv_last_name[:50] if inv_is_sahis else '',
            'IdentityNum':  inv_vat_clean if inv_is_sahis else '',
            'TaxNumber':    '' if inv_is_sahis else inv_vat_clean,
            'TaxOfficeCode': '',
        }

        _logger.info("Perakende fatura payload: %s | PostalAddress FirstName=%s LastName=%s IdentityNum=%s",
                     invoice.name, inv_first_name, inv_last_name, inv_vat_clean)

        return payload


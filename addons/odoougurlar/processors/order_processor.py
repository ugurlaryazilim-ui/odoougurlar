import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class OrderProcessor(models.AbstractModel):
    _name = 'odoougurlar.order.processor'
    _description = 'Nebim Sipariş Processor (Packing anında)'

    def sync_order(self, sale_order, mapping):
        """Siparişi Nebim'e atar ve dönen OrderLineID'leri kaydeder."""
        if not sale_order:
            return False
            
        if sale_order.nebim_order_sent:
            _logger.info("Sipariş zaten Nebim'e gönderilmiş: %s", sale_order.name)
            return True

        connector = self.env['odoougurlar.nebim.connector']
        
        # Mapping veya kayıtlı Cari Kodu al
        customer_code = sale_order.nebim_customer_code or (mapping.nebim_customer_code if mapping else (sale_order.partner_id.vat or 'B2C'))
        model_type = int(mapping.nebim_order_model_type) if mapping and mapping.nebim_order_model_type else 13
        is_export = int(mapping.nebim_invoice_model_type) == 24 if mapping else False
        
        # Siparişi Model 14 yapıyoruz ki Fatura (Model 24) ile bağlanabilsin.
        if is_export:
            model_type = 14

        # ExportFileNumber hesaplama
        export_file_number = ''
        if is_export:
            try:
                # Nebim'den son ExportFileNumber değerini alıp +1 yapan SP'yi çağırıyoruz.
                # SP ayrıca cdExportFile tablosuna da INSERT yapıyor (Nebim bu kaydı şart koşuyor).
                sp_params = [{'Name': 'CurrAccCode', 'Value': customer_code}]
                next_num_res = connector.run_proc('sp_GetNextExportFileNumber_Hamurlabs', sp_params)
                if next_num_res and isinstance(next_num_res, list) and len(next_num_res) > 0:
                    export_file_number = str(next_num_res[0].get('NextExportFileNumber') or '')
                    _logger.info("Nebim ExportFileNumber hesaplandı: %s (cdExportFile'a INSERT yapıldı)", export_file_number)
            except Exception as e:
                _logger.warning("ExportFileNumber alınırken hata oluştu (sp_GetNextExportFileNumber_Hamurlabs eksik olabilir): %s", e)

        lines = []
        for line in sale_order.order_line:
            if not line.product_id:
                continue
                
            line_data = {
                'Qty1': line.product_uom_qty,
                'Price': line.price_unit,
                'UsedBarcode': line.product_id.barcode or '',
                'SalesPersonCode': mapping.sales_person_code if mapping else 'TRD'
            }
            lines.append(line_data)

        # Mapping'den değerleri al, yoksa varsayılan kullan
        m_delivery = (mapping.delivery_company_code if mapping and mapping.delivery_company_code else 'YRT')
        m_store = (mapping.store_code if mapping and mapping.store_code else '002')
        m_warehouse = (mapping.warehouse_code if mapping and mapping.warehouse_code else '002')
        m_payment_agent = (mapping.payment_agent if mapping and mapping.payment_agent else 'TrendyolMp')
        m_sales_url = (mapping.sales_url if mapping and mapping.sales_url else 'www.trendyol.com')
        
        # Nebim Toptan (Model 14) ve Perakende (Model 13), her ikisi de Adres id eksik olunca ağlar
        addr_id = sale_order.nebim_address_id or (mapping.nebim_address_id if mapping else '') or 'adc3d09b-897b-4b74-a29f-b42600863ec3'

        payload = {
            'ModelType': model_type,
            'IsCompleted': True,
            'IsSalesViaInternet': True,
            'CustomerCode': customer_code,
            'OfficeCode': "M",
            'StoreCode': m_store,
            'WarehouseCode': m_warehouse,
            'ExportFileNumber': export_file_number,
            'TaxExemptionCode': (mapping.tax_exemption_code if mapping and mapping.tax_exemption_code else '301'),
            'ShipmentMethodCode': (mapping.shipment_method_code if mapping and getattr(mapping, 'shipment_method_code', None) else ('1' if is_export else '2')),
            'DocumentNumber': sale_order.client_order_ref or sale_order.name,
            'Description': sale_order.client_order_ref or sale_order.name,
            'InternalDescription': sale_order.name,
            'OrderDate': sale_order.date_order.strftime('%Y-%m-%d') if sale_order.date_order else fields.Date.today().strftime('%Y-%m-%d'),
            'DeliveryCompanyCode': ('' if is_export else m_delivery),
            'BillingPostalAddressID': addr_id,
            'ShippingPostalAddressID': addr_id,
            'Lines': lines,
            'OrdersViaInternetInfo': {
                'SalesURL': m_sales_url,
                'PaymentTypeCode': 1,
                'PaymentTypeDescription': "KREDIKARTI/BANKAKARTI",
                'SendDate': fields.Date.today().strftime('%Y-%m-%d'),
                'PaymentDate': sale_order.date_order.strftime('%Y-%m-%d') if sale_order.date_order else fields.Date.today().strftime('%Y-%m-%d'),
                'PaymentAgent': m_payment_agent
            },
        }
        
        # Perakende siparişte POSTerminalID, StoreWareHouseCode ve Payments gerekli
        if not is_export:
            payload['POSTerminalID'] = '1'
            payload['StoreWareHouseCode'] = m_warehouse
            payload['Payments'] = [{
                'PaymentType': '2',
                'Code': '',
                'CreditCardTypeCode': mapping.credit_card_type_code if mapping and mapping.credit_card_type_code else 'TRD',
                'InstallmentCount': 1,
                'CurrencyCode': 'TRY',
                'AmountVI': sale_order.amount_total,
            }]
        
        if is_export and mapping:
            if mapping.tax_exemption_code:
                payload['TaxExemptionCode'] = mapping.tax_exemption_code
        


        try:
            #_logger.info(f"Nebim'e Sipariş Gidiyor: {payload}")
            result = connector.post_data('Post', payload)
            
            # Nebim HTTP 200 dönse bile kendi içinde hata metni yollayabilir
            if isinstance(result, dict) and 'ExceptionMessage' in result:
                raise Exception(result['ExceptionMessage'])
                
            # Nebim sipariş yanıtı dict olarak döner, Lines içinde her satırın LineID'si bulunur
            # Örnek: {'ModelType': 6, ..., 'Lines': [{'LineID': 'guid-xxx', ...}], ...}
            response_lines = []
            if isinstance(result, dict):
                response_lines = result.get('Lines', [])
            elif isinstance(result, list) and len(result) > 0:
                # Bazen list formatında dönebilir
                if isinstance(result[0], dict) and 'Lines' in result[0]:
                    response_lines = result[0].get('Lines', [])
                else:
                    response_lines = result  # Direkt line listesi
            
            _logger.info("Nebim Sipariş Yanıtı - %d satır LineID alındı", len(response_lines))

            # Dönen ID'leri satırlara yaz
            order_lines = sale_order.order_line.filtered(lambda l: l.product_id)
            for idx, ol in enumerate(order_lines):
                if idx < len(response_lines):
                    line_data = response_lines[idx]
                    # LineID veya OrderLineID alanını yakala
                    order_line_id = line_data.get('LineID') or line_data.get('OrderLineID') or ''
                    if order_line_id:
                        ol.write({'nebim_order_line_id': order_line_id})
                        _logger.info("  Satır %d: OrderLineID = %s", idx, order_line_id)
                        
            sale_order.write({
                'nebim_order_sent': True,
                'nebim_order_response': str(result),
                'nebim_export_file_number': export_file_number or '',
            })
            _logger.info("Sipariş başarıyla Nebim'e aktarıldı: %s", sale_order.name)
            return True
            
        except Exception as e:
            _logger.error("Sipariş gönderim hatası: %s", e)
            sale_order.write({'nebim_order_response': str(e)})
            raise Exception(f"Nebim Sipariş Aktarım Hatası: {str(e)}")

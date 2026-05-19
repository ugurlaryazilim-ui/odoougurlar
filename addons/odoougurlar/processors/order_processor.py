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
            if not line.product_uom_qty or line.product_uom_qty <= 0:
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

        # ShipmentMethodCode: 1=İhracat, 2=Yurtiçi Kargo
        # Mapping default'u '1' olabilir ama yurtiçi siparişlerde '2' olmalı
        if is_export:
            m_shipment = (mapping.shipment_method_code if mapping and getattr(mapping, 'shipment_method_code', None) else '1')
        else:
            m_shipment = '2'  # Yurtiçi her zaman kargo

        payload = {
            'ModelType': model_type,
            'IsCompleted': True,
            'IsSalesViaInternet': True,
            'CustomerCode': customer_code,
            'OfficeCode': "M",
            'StoreCode': m_store,
            'WarehouseCode': (m_warehouse if is_export else ''),  # Hamurlabs: yurtiçi boş gönderiyor
            'ShipmentMethodCode': m_shipment,
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
        
        # ── PostalAddress bloğu ──
        # Nebim siparişe adres bilgisini PostalAddress tekil nesnesi olarak da ister.
        # Hamurlabs örneğine göre POSTerminalID'den ONCE gelecek.
        partner = sale_order.partner_id
        postal_address = self._build_postal_address(partner, mapping, sale_order)
        if postal_address:
            payload['PostalAddress'] = postal_address

        # Perakende siparişte POSTerminalID ve Payments gerekli
        # Hamurlabs'ta da sipariş Payments ile gönderiliyor.
        if not is_export:
            payload['POSTerminalID'] = '1'
            import time
            order_epoch = int(sale_order.date_order.timestamp() * 1000) if sale_order.date_order else int(time.time() * 1000)
            payment_entry = {
                'PaymentType': '2',
                'Code': '',
                'CreditCardTypeCode': mapping.credit_card_type_code if mapping and mapping.credit_card_type_code else 'TRD',
                'InstallmentCount': 1,
                'DocumentDate': f"\\/Date({order_epoch})\\/",
                'CurrencyCode': 'TRY',
                'Amount': sale_order.amount_total,
            }
            if mapping and getattr(mapping, 'bank_code', ''):
                payment_entry['BankCode'] = mapping.bank_code
            payload['Payments'] = [payment_entry]

        if is_export:
            payload['ExportFileNumber'] = export_file_number  # Sadece ihracat için
            payload['TaxExemptionCode'] = (mapping.tax_exemption_code if mapping and mapping.tax_exemption_code else '301')



        try:
            import json
            sale_order.write({'nebim_order_request': json.dumps(payload, ensure_ascii=False, indent=2, default=str)})
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
            order_lines = sale_order.order_line.filtered(lambda l: l.product_id and l.product_uom_qty > 0)
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

    def _build_postal_address(self, partner, mapping, sale_order):
        """Sipariş için PostalAddress bloğunu partner bilgilerinden oluşturur.

        ALAN SIRASI Nebim spesifikasyonuna göre sabitlendi:
        Address, CityCode, CompanyName, CountryCode, DistrictCode,
        FirstName, IdentityNum, LastName, StateCode, TaxNumber, TaxOfficeCode

        Tüzel kişi (10h VKN) : CompanyName+TaxNumber+TaxOfficeCode dolu, diğerleri boş
        Şahis firması (11h TCKN): FirstName+LastName+IdentityNum dolu, diğerleri boş
        Bireysel             : FirstName+LastName+IdentityNum dolu, diğerleri boş
        """
        if not partner:
            return {}

        country_code = (partner.country_id.code or 'TR').upper()

        # İl/İlçe kodlarını çöz (nebim.district tablosundan)
        state_code = city_code = district_code = ''
        if country_code == 'TR':
            try:
                district_model = self.env['odoougurlar.nebim.district'].sudo()
                odoo_state = partner.state_id.name if partner.state_id else ''
                odoo_city = partner.city or ''
                if odoo_state or odoo_city:
                    codes = district_model.find_nebim_codes(odoo_state, odoo_city)
                    state_code = codes.get('state_code', '')
                    city_code = codes.get('city_code', '')
                    district_code = codes.get('district_code', '')
            except Exception as e:
                _logger.warning("PostalAddress il/ilçe kodu çözümlenemedi: %s", e)

        # Varsayılan boş değerler
        first_name = last_name = identity_num = company_name = tax_number = ''
        tax_office_code = 'null'

        if partner.is_company:
            vat_raw = partner.vat or ''
            vat_clean = ''.join(filter(str.isdigit, vat_raw))
            is_sahis = len(vat_clean) == 11

            if is_sahis:
                # Şahis firması → TC Kimlik No + Ad/Soyad
                name_parts = (partner.name or '').strip().split()
                first_name = name_parts[0][:50] if name_parts else ''
                last_name = ' '.join(name_parts[1:])[:50] if len(name_parts) > 1 else ''
                identity_num = vat_clean
                # company_name, tax_number boş kalır
            else:
                # Tüzel kişi → VKN + Firma adı
                company_name = (partner.name or '')[:50]
                tax_number = vat_clean if len(vat_clean) == 10 else vat_raw
                # Vergi Dairesi kodu
                tax_office_name = ''
                if sale_order:
                    for attr in ('trendyol_order_id', 'n11_order_id', 'hb_order_id'):
                        obj = getattr(sale_order, attr, None)
                        if obj:
                            tax_office_name = getattr(obj, 'tax_office', '') or ''
                            if tax_office_name:
                                break
                if tax_office_name:
                    tax_mapping = self.env['odoougurlar.tax.mapping'].sudo().search(
                        [('name', '=ilike', tax_office_name.strip())], limit=1)
                    tax_office_code = tax_mapping.nebim_tax_office_code if tax_mapping else 'null'
                # first_name, last_name, identity_num boş kalır
        else:
            # Bireysel müşteri
            name_parts = (partner.name or '').strip().split()
            first_name = name_parts[0][:50] if name_parts else ''
            last_name = ' '.join(name_parts[1:])[:50] if len(name_parts) > 1 else ''
            identity_num = partner.vat or '11111111111'
            # company_name, tax_number boş kalır

        # Nebim spesifikasyonunun kesin alan sırası
        return {
            'Address':      (partner.street or '')[:200],
            'CityCode':     city_code,
            'CompanyName':  company_name,
            'CountryCode':  country_code,
            'DistrictCode': district_code,
            'FirstName':    first_name,
            'IdentityNum':  identity_num,
            'LastName':     last_name,
            'StateCode':    state_code,
            'TaxNumber':    tax_number,
            'TaxOfficeCode': tax_office_code,
        }

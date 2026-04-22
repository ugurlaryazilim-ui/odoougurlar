import logging
from odoo import models

_logger = logging.getLogger(__name__)

class CustomerProcessor(models.AbstractModel):
    _name = 'odoougurlar.customer.processor'
    _description = 'Nebim Cari Processor'

    def sync_customer(self, partner, mapping=None, sale_order=None):
        """Müşteriyi Nebim'e aktarır. B2C için genelde sadece TCKN/isim gönderilmesi yeterli olur."""
        if not partner:
            return False

        connector = self.env['odoougurlar.nebim.connector']
        
        
        
        nebim_codes = {'state_code': '', 'city_code': '', 'district_code': ''}
        try:
            district_model = self.env['odoougurlar.nebim.district'].sudo()
            odoo_state = partner.state_id.name if partner.state_id else ''
            odoo_city = partner.city or ''
            nebim_codes = district_model.find_nebim_codes(odoo_state, odoo_city)
            _logger.info("İl/İlçe eşleştirmesi: %s/%s → %s", odoo_state, odoo_city, nebim_codes)
        except Exception as e:
            _logger.warning("İl/İlçe eşleştirme hatası (devam ediliyor): %s", e)
        
        country_code = (partner.country_id.code or 'TR').upper()
        if country_code != 'TR':
            state_code = country_code
            city_code = country_code
            district_code = country_code
        else:
            state_code = nebim_codes.get('state_code', '')
            city_code = nebim_codes.get('city_code', '')
            district_code = nebim_codes.get('district_code', '')
        order_model_type = int(mapping.nebim_order_model_type) if mapping and mapping.nebim_order_model_type else 13
        invoice_model_type = int(mapping.nebim_invoice_model_type) if mapping and mapping.nebim_invoice_model_type else 8
        is_export = invoice_model_type == 24
        
        # Yurtiçi (perakende) müşteriler → ModelType 3
        # Yurtdışı (ihracat) müşteriler → ModelType 2
        cari_model_type = 2 if is_export else 3

        if partner.is_company:
            payload = {
                'ModelType': cari_model_type,
                'CurrAccDescription': partner.name[:50],
                'FirstName': partner.name[:50],
                'LastName': '',
                'IsIndividualAcc': False,
                'TaxNumber': partner.vat or '',
                'OfficeCode': 'M',
                'CurrencyCode': 'TRY',
            }
            # Yurt içi kurumsal müşteriler için e-fatura bayrağı açıkça gönderilir
            # Yurt dışı (ihracat) için GÖNDERİLMEZ — Nebim tetiklememeli!
            if not is_export:
                payload['IsSubjectToEInvoice'] = True
            
            # Pazaryeri Vergi Dairesi Adı -> Nebim Vergi Dairesi Kodu eşleştirmesi
            # Trendyol, Hepsiburada veya diğer pazaryerlerinden gelen tax_office alanı
            tax_office_name = ''
            if sale_order:
                # Trendyol
                if hasattr(sale_order, 'trendyol_order_id') and sale_order.trendyol_order_id:
                    tax_office_name = sale_order.trendyol_order_id.tax_office or ''
                # N11
                elif hasattr(sale_order, 'n11_order_id') and sale_order.n11_order_id:
                    tax_office_name = sale_order.n11_order_id.tax_office or ''
                # Hepsiburada (gelecek genişleme)
                elif hasattr(sale_order, 'hb_order_id') and sale_order.hb_order_id:
                    tax_office_name = getattr(sale_order.hb_order_id, 'tax_office', '') or ''
                
            if tax_office_name:
                tax_mapping = self.env['odoougurlar.tax.mapping'].sudo().search([('name', '=ilike', tax_office_name.strip())], limit=1)
                if tax_mapping:
                    payload['TaxOfficeCode'] = tax_mapping.nebim_tax_office_code
                    _logger.info("Vergi Dairesi Eşleştirildi: '%s' → Kod: %s", tax_office_name, tax_mapping.nebim_tax_office_code)
                else:
                    _logger.warning("Eksik Vergi Dairesi Eşleştirmesi: '%s' için kayıt bulunamadı.", tax_office_name)
            
            # KVKK uyumlu loglama — VKN maskeleniyor
            masked_vat = f"{(partner.vat or '')[:3]}***{(partner.vat or '')[-2:]}" if partner.vat and len(partner.vat) > 5 else '***'
            _logger.info("KURUMSAL MÜŞTERİ: %s | VKN: %s | IsSubjectToEInvoice: True", partner.name, masked_vat)
        else:
            payload = {
                'ModelType': cari_model_type,
                'CurrAccCode': '',
                'CurrAccDescription': (partner.name or 'BIREYSEL')[:50],
                'IsIndividualAcc': True,
                'FirstName': partner.name.split(' ', 1)[0][:50] if partner.name else '',
                'LastName': partner.name.split(' ', 1)[-1][:50] if ' ' in partner.name else '',
                'IdentityNum': partner.vat or '11111111111',
                'OfficeCode': 'M',
                'CurrencyCode': 'TRY',
            }
            # İhracat müşterisi ise ek alanlar
            if is_export:
                payload['TaxNumber'] = '1111111111'
                payload['CustomerTypeCode'] = 3

        payload['PostalAddresses'] = [{
                'AddressTypeCode': "1",
                'CountryCode': country_code,
                'StateCode': state_code,
                'CityCode': city_code,
                'DistrictCode': district_code,
                'Address': (partner.street or 'Test Address, Riyadh')[:200],
            }]
        
        # Muhasebe hesap kodları (Nebim Müşteri Kartı -> GLAccounts sekmesi için)
        if not is_export and mapping and getattr(mapping, 'nebim_customer_code', False):
            payload['GLAccounts'] = [{
                "CompanyCode": 1,
                "GLAccCode": mapping.nebim_customer_code,
                "OrderAdvanceGLAccCode": getattr(mapping, 'sales_advance_code', ''),
            }]
        
        

        
        # Gerçek üretimde (Production) Nebim'in "sp_RetailCustomer" veya "ModelType 2" zorunluluğuna göre şekillenir.
        customer_code = mapping.nebim_customer_code if mapping else ''
        address_id = ''
        try:
            result = connector.post_data('Post', payload)
            _logger.info("Cari bilgisi işlendi (Nebim): %s - Sonuc: OK", partner.name)
            
            # Nebim'den hata dönerse (200 OK gelse bile HTTP içinde json hatası olabilir)
            if isinstance(result, dict) and 'ExceptionMessage' in result:
                error_msg = result['ExceptionMessage']
                _logger.error("Nebim Cari Hatası: %s", error_msg)
                raise Exception(f"Nebim Cari Hatası: {error_msg}")
                
            # Eğer Nebim kendi yarattığı bir kodu döndürüyorsa JSON içinden al (isteğe bağlı)
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                customer_code = result[0].get('CurrAccCode', result[0].get('CustomerCode', customer_code))
                address_tmp = result[0].get('CurrAccDefault', {})
                address_id = address_tmp.get('ShippingAddressID') or address_tmp.get('BillingAddressID') or address_tmp.get('PostalAddressID') or ''
            elif isinstance(result, dict):
                customer_code = result.get('CurrAccCode', result.get('CustomerCode', customer_code))
                address_tmp = result.get('CurrAccDefault', {})
                address_id = address_tmp.get('ShippingAddressID') or address_tmp.get('BillingAddressID') or address_tmp.get('PostalAddressID') or result.get('PostalAddressID') or result.get('AddressID') or ''
                
            _logger.info("Oluşan Nebim Müşteri Kodu: %s, Adres ID: %s", customer_code, address_id)
            return customer_code, address_id
        except Exception as e:
            _logger.error("Cari Nebim'e gönderilemedi. Hata: %s", e)
            raise Exception(f"Cari oluşturma başarısız: {str(e)}")

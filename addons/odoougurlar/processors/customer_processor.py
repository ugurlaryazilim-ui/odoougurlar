import json as _json
import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class NebimCustomerError(Exception):
    """Nebim cari hatası — request JSON'u taşır, savepoint rollback sonrası kaydedilir."""
    def __init__(self, message, request_json=''):
        super().__init__(message)
        self.request_json = request_json

# Türkçe → ASCII normalize mapping
_TR_MAP = str.maketrans({
    'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g',
    'Ü': 'U', 'ü': 'u', 'Ş': 'S', 'ş': 's',
    'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c',
})


def _norm(text):
    """Türkçe karakterleri ASCII karşılığına çevir ve lowercase yap."""
    return (text or '').strip().translate(_TR_MAP).upper()


class CustomerProcessor(models.AbstractModel):
    _name = 'odoougurlar.customer.processor'
    _description = 'Nebim Cari Processor'

    def sync_customer(self, partner, mapping=None, sale_order=None):
        """Müşteriyi Nebim'e aktarır. B2C için genelde sadece TCKN/isim gönderilmesi yeterli olur."""
        if not partner:
            return False

        connector = self.env['odoougurlar.nebim.connector']
        
        # ─── İl/İlçe/Bölge Kodu Çözümleme ───
        nebim_codes = self._resolve_nebim_address_codes(partner)
        
        # ─── Ülke Kodu: sp_GetCountry_Hamurlabs tablosundan Nebim'e özgü kodu al ───
        # find_nebim_country → odoougurlar.nebim.country tablosuna bakar (SP'den senkronize edilmiş)
        # Eşleşme yoksa ISO kodu fallback olarak kullanılır (AZ, GR, TR...)
        country_code = (
            self.env['odoougurlar.nebim.country'].sudo().find_nebim_country(partner.country_id.id)
            if partner.country_id else 'TR'
        ) or 'TR'
        country_code = country_code.upper()

        if country_code != 'TR':
            # Mikro ihracat / yurtdışı: Bölge + İl + İlçe = ülke kodu (AZ, GR, BH...)
            # Nebim yabancı adreslerde detaylı il/ilçe kodu gerektirmez
            state_code = country_code
            city_code = country_code
            district_code = country_code
            _logger.info("Yurtdışı müşteri (%s): StateCode=CityCode=DistrictCode='%s'",
                         partner.name, country_code)
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
            # ─── Vergi Numarası / TC Kimlik No Ayrımı ───
            # Tüzel kişi (Ltd., A.Ş.) → 10 haneli VKN → Nebim TaxNumber + IsIndividualAcc=False
            # Şahıs firması → 11 haneli TCKN → Nebim IdentityNum + IsIndividualAcc=True
            vat_raw = partner.vat or ''
            vat_clean = ''.join(filter(str.isdigit, vat_raw))  # Sadece rakamlar
            is_sahis = len(vat_clean) == 11  # 11 hane = TC Kimlik No = Şahıs firması

            if is_sahis:
                # ─── ŞAHIS FİRMASI (11 hane TCKN) ───
                # TEST: TC'nin ilk 10 hanesini TaxNumber olarak gönder
                # FirstName/LastName/IdentityNum boş, CurrAccDescription dolu
                tax_number_10 = vat_clean[:10]  # 11 haneden son haneyi sil

                payload = {
                    'ModelType': cari_model_type,  # Cari API için 3 (perakende müşteri)
                    'CurrAccCode': '',
                    'CurrAccDescription': partner.name[:50],
                    'FirstName': '',
                    'LastName': '',
                    'IsIndividualAcc': True,
                    'IsSubjectToEInvoice': True,
                    'IdentityNum': '',
                    'TaxNumber': tax_number_10,
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
                _logger.info("KURUMSAL (ŞAHIS FİRMASI): %s | TaxNumber(10h)=%s | Orijinal TCKN=%s",
                             partner.name, tax_number_10, vat_clean)
            else:
                # ─── TÜZEL KİŞİ (10 hane VKN veya diğer) ───
                payload = {
                    'ModelType': cari_model_type,
                    'CurrAccDescription': partner.name[:50],
                    'IsIndividualAcc': False,
                    'TaxNumber': vat_clean if len(vat_clean) == 10 else vat_raw,
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
                if len(vat_clean) == 10:
                    _logger.info("KURUMSAL (TÜZEL KİŞİ): %s | VKN → TaxNumber (10 hane)", partner.name)
                else:
                    _logger.warning("KURUMSAL: %s | Vergi no uzunluğu beklenmeyen: %d hane", partner.name, len(vat_clean))

            # E-fatura bayrağı — SADECE tüzel kişi (10h VKN) için
            # Şahıs firmalarında (11h TCKN) e-fatura ayrımı FATURA seviyesinde yapılır
            # Hamurlabs referansı: şahıs carisinde IsSubjectToEInvoice işaretli DEĞİL
            if not is_export and not is_sahis:
                payload['IsSubjectToEInvoice'] = True
                _logger.info("TÜZEL KİŞİ E-FATURA: %s → IsSubjectToEInvoice=True", partner.name)
            
            # Pazaryeri Vergi Dairesi Adı -> Nebim Vergi Dairesi Kodu eşleştirmesi
            # Hem tüzel kişi hem de şahıs firması için vergi dairesini gönderiyoruz
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
            masked_vat = f"{vat_clean[:3]}***{vat_clean[-2:]}" if len(vat_clean) > 5 else '***'
            _logger.info("KURUMSAL MÜŞTERİ: %s | VKN/TCKN: %s | Hane: %d | Şahıs: %s", partner.name, masked_vat, len(vat_clean), is_sahis)
        else:
            name_parts = (partner.name or '').strip().split()
            first_name = name_parts[0] if name_parts else ''
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            payload = {
                'ModelType': cari_model_type,
                'CurrAccCode': '',
                'CurrAccDescription': (partner.name or 'BIREYSEL')[:50],
                'IsIndividualAcc': True,
                'FirstName': first_name[:50],
                'LastName': last_name[:50],
                'IdentityNum': partner.vat or '11111111111',
                'OfficeCode': 'M',
                'CurrencyCode': 'TRY',
            }
            # İhracat müşterisi ise ek alanlar
            if is_export:
                payload['TaxNumber'] = '1111111111'
                payload['CustomerTypeCode'] = 3

        payload['PostalAddresses'] = [{
            'AddressTypeCode': "2",  # Hamurlabs "2" gönderiyor (Teslimat)
            'CountryCode': country_code,
            'StateCode': state_code,
            'CityCode': city_code,
            'DistrictCode': district_code,
            'Address': (partner.street or 'Adres bilgisi yok')[:200],
        }]
        
        # İletişim bilgileri (Telefon + Email)
        # Nebim referansı: CommunicationTypeCode 7=Telefon, 3=Email
        comm_list = []
        cust_phone = (partner.phone or getattr(partner, 'mobile', '') or '').strip()
        cust_email = (partner.email or '').strip()
        if cust_email:
            comm_list.append({
                'CommunicationTypeCode': 3,
                'CommAddress': cust_email,
                'CanSendAdvert': False,
            })
        if cust_phone:
            comm_list.append({
                'CommunicationTypeCode': 7,
                'CommAddress': cust_phone,
                'CanSendAdvert': False,
            })
        if comm_list:
            payload['Communications'] = comm_list
        
        _logger.info("Nebim Cari PostalAddresses: Country=%s, State=%s, City=%s, District=%s",
                     country_code, state_code, city_code, district_code)
        
        # Muhasebe hesap kodları (Nebim Müşteri Kartı -> GLAccounts sekmesi için)
        # İhracat ve yurtiçi müşteriler dahil — tüm cari tiplere gönderilir
        if mapping and getattr(mapping, 'nebim_customer_code', False):
            gl_acc = {
                "CompanyCode": 1,
                "GLAccCode": mapping.nebim_customer_code,
                "OrderAdvanceGLAccCode": getattr(mapping, 'sales_advance_code', ''),
            }
            # E-Fatura Satış Hesabı — mapping'deki Banka Kodu (BankCode) alanından
            if getattr(mapping, 'bank_code', ''):
                gl_acc["EInvoiceSalesGLAccCode"] = mapping.bank_code
            payload['GLAccounts'] = [gl_acc]
        

        
        # Gerçek üretimde (Production) Nebim'in "sp_RetailCustomer" veya "ModelType 2" zorunluluğuna göre şekillenir.
        customer_code = mapping.nebim_customer_code if mapping else ''
        address_id = ''
        # Request JSON'u oluştur (hata durumunda da kaydedilecek)
        request_json = ''
        try:
            request_json = _json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            pass

        try:
            # İstek payload'unu sale_order'a kaydet (debug için)
            if sale_order:
                try:
                    sale_order.sudo().write({
                        'nebim_customer_request': request_json,
                    })
                except Exception:
                    pass

            result = connector.post_data('Post', payload)
            _logger.info("Cari bilgisi işlendi (Nebim): %s - Sonuc: OK", partner.name)
            
            # Yanıt JSON'unu sale_order'a kaydet (debug için)
            if sale_order:
                try:
                    sale_order.sudo().write({
                        'nebim_customer_response': _json.dumps(result, ensure_ascii=False, default=str) if result else '',
                    })
                except Exception:
                    pass
            
            # Nebim'den hata dönerse (200 OK gelse bile HTTP içinde json hatası olabilir)
            if isinstance(result, dict) and 'ExceptionMessage' in result:
                error_msg = result['ExceptionMessage']
                _logger.error("Nebim Cari Hatası: %s", error_msg)
                raise NebimCustomerError(f"Nebim Cari Hatası: {error_msg}", request_json=request_json)
                
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
        except NebimCustomerError:
            raise  # Zaten request_json taşıyor
        except Exception as e:
            _logger.error("Cari Nebim'e gönderilemedi. Hata: %s", e)
            raise NebimCustomerError(f"Cari oluşturma başarısız: {str(e)}", request_json=request_json)

    def _resolve_nebim_address_codes(self, partner):
        """
        Partner'ın il/ilçe bilgisinden Nebim bölge/il/ilçe kodlarını çözümler.
        
        Strateji (sıralı):
        1. Odoo nebim.district tablosundan bul (önbellekli, hızlı)
        2. Tablo boşsa veya eşleşme yoksa → Nebim SP'yi doğrudan çağır ve bul
        """
        empty = {'state_code': '', 'city_code': '', 'district_code': ''}
        
        odoo_state = partner.state_id.name if partner.state_id else ''
        odoo_city = partner.city or ''
        country_code = (partner.country_id.code or '').upper()  # 'TR', 'AZ', 'GR' vb.

        _logger.info("Nebim İl/İlçe çözümleme başladı: state='%s', city='%s', country='%s', partner='%s'",
                     odoo_state, odoo_city, country_code, partner.name)

        if not odoo_state and not odoo_city and not country_code:
            _logger.warning("Partner '%s' adres bilgisi boş!", partner.name)
            return empty

        # ─── Yöntem 1: Odoo tablosundan bul ───
        district_model = self.env['odoougurlar.nebim.district'].sudo()
        table_count = district_model.search_count([])

        if table_count > 0:
            result = district_model.find_nebim_codes(odoo_state, odoo_city)
            if result.get('city_code'):
                return result
            _logger.info("Odoo tablosunda eşleşme bulunamadı, Nebim SP ile denenecek...")
        else:
            _logger.info("Nebim İlçe tablosu boş, SP'den doğrudan çekilecek...")

        # ─── Yöntem 2: Nebim SP'yi doğrudan çağır ───
        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_data = connector.run_proc('sp_GetDistrict_Hamurlabs')

            if not isinstance(sp_data, list):
                _logger.error("SP beklenmeyen yanıt döndü: %s", type(sp_data))
                return empty

            _logger.info("SP'den %d ilçe kaydı alındı, eşleştirme yapılıyor...", len(sp_data))

            norm_city = _norm(odoo_city)
            norm_state = _norm(odoo_state)

            best_match = None
            city_only_match = None
            country_match = None  # Ülke bazlı fallback (TR olmayan ülkeler için)

            for row in sp_data:
                city_desc = row.get('CityDescription', '') or row.get('CityName', '') or ''
                district_desc = row.get('DistrictDescription', '') or row.get('DistrictName', '') or ''
                row_country = (row.get('CountryCode', '') or '').upper()

                norm_row_city = _norm(city_desc)
                norm_row_district = _norm(district_desc)

                # Tam eşleşme: İlçe + İl
                if norm_city and norm_city == norm_row_district:
                    if norm_state and norm_state == norm_row_city:
                        best_match = row
                        break
                    elif not norm_state:
                        best_match = row
                        break

                # İl eşleşmesi (fallback)
                if norm_state and norm_state == norm_row_city and not city_only_match:
                    city_only_match = row

                # Ülke kodu eşleşmesi (TR olmayan ülkeler için son çare)
                if country_code and country_code != 'TR' and row_country == country_code and not country_match:
                    country_match = row

            match = best_match or city_only_match or (country_match if country_code != 'TR' else None)
            if match:
                result = {
                    'state_code': match.get('StateCode', '') or match.get('stateCode', '') or '',
                    'city_code': match.get('CityCode', '') or match.get('cityCode', '') or '',
                    'district_code': match.get('DistrictCode', '') or match.get('districtCode', '') or '' if (best_match or city_only_match) else '',
                }
                _logger.info(
                    "✅ Nebim İl/İlçe eşleşti: %s/%s (country=%s) → state=%s, city=%s, district=%s",
                    odoo_state, odoo_city, country_code,
                    result['state_code'], result['city_code'], result['district_code']
                )

                # Tablo boşsa veya eksikse sonucu kaydet
                if table_count == 0 or not best_match:
                    self._save_sp_to_table(sp_data, district_model)

                return result
            else:
                _logger.warning(
                    "❌ Nebim İl/İlçe eşleşMEDİ: il='%s' (norm='%s'), ilçe='%s' (norm='%s'), country='%s' — %d kayıt kontrol edildi",
                    odoo_state, norm_state, odoo_city, norm_city, country_code, len(sp_data)
                )
                return empty

        except Exception as e:
            _logger.error("Nebim SP çağrısı başarısız: %s", e)
            return empty

    def _save_sp_to_table(self, sp_data, district_model):
        """SP verilerini Odoo tablosuna kaydet (arka planda, gelecek aramalar için)."""
        try:
            count = 0
            for row in sp_data:
                district_code = row.get('DistrictCode', '') or row.get('districtCode', '') or ''
                if not district_code:
                    continue
                existing = district_model.search([('district_code', '=', district_code)], limit=1)
                if not existing:
                    city_nm = row.get('CityDescription', '') or row.get('CityName', '') or row.get('cityName', '') or ''
                    district_nm = row.get('DistrictDescription', '') or row.get('DistrictName', '') or row.get('districtName', '') or ''
                    district_model.create({
                        'country_code': row.get('CountryCode', '') or 'TR',
                        'state_code': row.get('StateCode', '') or row.get('stateCode', '') or '',
                        'city_code': row.get('CityCode', '') or row.get('cityCode', '') or '',
                        'district_code': district_code,
                        'state_name': row.get('StateDescription', '') or row.get('StateName', '') or '',
                        'city_name': city_nm,
                        'district_name': district_nm,
                        'normalized_city_name': _norm(city_nm).lower(),
                        'normalized_district_name': _norm(district_nm).lower(),
                    })
                    count += 1
            if count:
                _logger.info("SP verisi Odoo tablosuna kaydedildi: %d yeni kayıt", count)
        except Exception as e:
            _logger.warning("SP verileri tabloya yazılırken hata (kritik değil): %s", e)

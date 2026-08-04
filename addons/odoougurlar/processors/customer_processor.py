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
        email = (partner.email or '').strip().lower()

        # ═══════════════════════════════════════════════════════════════════
        # CONCURRENCY KORUMASI: Partner bazlı BLOCKING advisory lock
        # Aynı müşteri için eş zamanlı sync_customer çağrılarını SERİLEŞTİRİR.
        # 2. çağrı BEKLER → lock aldığında committed state görür.
        # ═══════════════════════════════════════════════════════════════════
        partner_lock_id = partner.id + 700000000
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [partner_lock_id])

        # Lock aldıktan sonra committed state kontrol:
        # Önceki transaction bu partner için cari kodu yazmış olabilir.
        self.env.cr.execute(
            "SELECT nebim_customer_code, nebim_customer_sent FROM res_partner WHERE id = %s",
            [partner.id]
        )
        committed_row = self.env.cr.fetchone()
        if committed_row and committed_row[0] and committed_row[1]:
            committed_code = committed_row[0]
            committed_addr = ''
            # Address ID'yi de oku
            try:
                self.env.cr.execute(
                    "SELECT nebim_address_id FROM res_partner WHERE id = %s",
                    [partner.id]
                )
                addr_row = self.env.cr.fetchone()
                committed_addr = (addr_row[0] if addr_row else '') or ''
            except Exception:
                pass
            _logger.info(
                "Cari kodu DB'den taze okundu (lock sonrası): %s -> %s",
                partner.name, committed_code
            )
            return committed_code, committed_addr

        # ═══════════════════════════════════════════════════════════════════
        # NEBİM = TEK GERÇEK KAYNAK (Source of Truth)
        # Sıra: 1. Nebim SP → 2. Odoo partner/email dedup → 3. Yeni POST
        # Nebim SP bulamazsa → Odoo'daki eski kodları TEMİZLE
        # ═══════════════════════════════════════════════════════════════════

        # ─── KATMAN 1: NEBİM SQL SERVER CANLI SORGU (sp_GetCustomer_Hamurlabs) ───
        # Bu SP BillingAddressID döndürür — sipariş için kritik!
        nebim_verified_code = None
        nebim_verified_addr = ''

        if email:
            try:
                sp_res = connector.run_proc('sp_GetCustomer_Hamurlabs', [
                    {'Name': 'CommunicationTypeCode', 'Value': 3},   # 3 = Email
                    {'Name': 'CommAddress', 'Value': email},
                    {'Name': 'TypeCode', 'Value': 4},                # 4 = Perakende
                    {'Name': 'CustomerType', 'Value': 4}
                ])
                if sp_res and isinstance(sp_res, list) and len(sp_res) > 0:
                    first = sp_res[0]
                    if isinstance(first, dict):
                        found_code = first.get('CurrAccCode') or ''
                        found_addr = first.get('BillingAddressID') or ''
                        if found_code:
                            nebim_verified_code = found_code
                            nebim_verified_addr = found_addr
                            _logger.info(
                                "NEBİM CANLI: Cari bulundu (%s): %s -> %s (AddrID=%s)",
                                email, partner.name, found_code, found_addr
                            )
            except Exception as e:
                _logger.warning("Nebim SP (sp_GetCustomer_Hamurlabs) sorgu hatası: %s", e)

            # sp_GetCustomer_Hamurlabs bulamadıysa, usp_GetCustomer_ent ile de dene
            if not nebim_verified_code:
                try:
                    sp_name2 = connector._get_sp_name('customer') or 'usp_GetCustomer_ent'
                    sp_res2 = connector.run_proc(sp_name2, [
                        {'Name': 'pCommValue', 'Value': email},
                        {'Name': 'pCommType', 'Value': 3},
                        {'Name': 'pCustomerType', 'Value': 4}
                    ])
                    if sp_res2 and isinstance(sp_res2, list) and len(sp_res2) > 0:
                        first2 = sp_res2[0]
                        if isinstance(first2, dict):
                            found_code2 = first2.get('customerCode') or first2.get('CurrAccCode') or ''
                            if found_code2:
                                nebim_verified_code = found_code2
                                _logger.info(
                                    "NEBİM CANLI (yedek SP): Cari bulundu (%s): %s -> %s",
                                    email, partner.name, found_code2
                                )
                except Exception as e:
                    _logger.warning("Nebim SP (usp_GetCustomer_ent) sorgu hatası: %s", e)

        cust_phone = (partner.phone or getattr(partner, 'mobile', '') or '').strip()
        cust_phone_clean = ''.join(filter(str.isdigit, cust_phone))

        # Telefon ile de Nebim SP'de canlı ara (CommunicationTypeCode 7 = Telefon)
        if not nebim_verified_code and cust_phone_clean:
            try:
                sp_res_p = connector.run_proc('sp_GetCustomer_Hamurlabs', [
                    {'Name': 'CommunicationTypeCode', 'Value': 7},   # 7 = Telefon
                    {'Name': 'CommAddress', 'Value': cust_phone},
                    {'Name': 'TypeCode', 'Value': 4},                # 4 = Perakende
                    {'Name': 'CustomerType', 'Value': 4}
                ])
                if sp_res_p and isinstance(sp_res_p, list) and len(sp_res_p) > 0:
                    first_p = sp_res_p[0]
                    if isinstance(first_p, dict):
                        found_code = first_p.get('CurrAccCode') or ''
                        found_addr = first_p.get('BillingAddressID') or ''
                        if found_code:
                            nebim_verified_code = found_code
                            nebim_verified_addr = found_addr
                            _logger.info(
                                "NEBİM CANLI (Telefon): Cari bulundu (%s): %s -> %s (AddrID=%s)",
                                cust_phone, partner.name, found_code, found_addr
                            )
            except Exception as e:
                _logger.warning("Nebim SP telefon sorgu hatası: %s", e)

        # ─── Odoo DB: Aynı email veya telefon ile daha önce Nebim cari kodu almış partner var mı? ───
        if not nebim_verified_code:
            search_conds = []
            if email:
                search_conds.append(('email', '=ilike', email))
            if cust_phone:
                search_conds.append(('phone', '=', cust_phone))
            if search_conds:
                db_cond = ['|'] * (len(search_conds) - 1) + search_conds
                other_p = self.env['res.partner'].sudo().search([
                    ('id', '!=', partner.id),
                    ('nebim_customer_sent', '=', True),
                    ('nebim_customer_code', '!=', False),
                    ('nebim_customer_code', '!=', ''),
                ] + db_cond, limit=1)
                if other_p and other_p.nebim_customer_code:
                    nebim_verified_code = other_p.nebim_customer_code
                    nebim_verified_addr = other_p.nebim_address_id or ''
                    _logger.info(
                        "ODOO DB: Benzer partner'dan mevcut Nebim cari kodu alındı (%s): %s -> %s",
                        partner.name, other_p.name, nebim_verified_code
                    )

        # ─── Nebim cariyi BULDU → partner'ı güncelle ve dön ───
        if nebim_verified_code:
            partner.sudo().write({
                'nebim_customer_sent': True,
                'nebim_customer_code': nebim_verified_code,
                'nebim_address_id': nebim_verified_addr or ''
            })
            return nebim_verified_code, nebim_verified_addr

        # ─── Nebim cariyi BULAMADI → Odoo'daki eski kodları TEMİZLE ───
        old_code = partner.sudo().nebim_customer_code
        if old_code:
            _logger.warning(
                "NEBİM CANLI: %s e-postalı cari Nebim'de BULUNAMADI! "
                "Odoo'daki eski kod '%s' TEMİZLENİYOR.",
                email, old_code
            )
            partner.sudo().write({
                'nebim_customer_sent': False,
                'nebim_customer_code': False,
                'nebim_address_id': False
            })

        # ─── KATMAN 2: Odoo'da aynı email ile başka bir partner'da Nebim kodu var mı? ───
        # NOT: Bu kodlar da eski olabilir, ama Nebim SP yukarıda zaten kontrol etti.
        # Buraya sadece Nebim SP'nin email ile bulamadığı durumlarda gelinir.

        # ─── Hiçbir katmanda bulunamadı → Nebim V3 API ile yeni cari POST et ───
        _logger.info("Cari Nebim'de bulunamadı (%s / %s), yeni cari POST edilecek.", partner.name, email)


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
                name_parts = (partner.name or '').strip().split()
                first_name = name_parts[0] if name_parts else (partner.name or 'Müşteri')
                last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else first_name

                payload = {
                    'ModelType': cari_model_type,  # Cari API için 3 (perakende müşteri)
                    'CurrAccCode': '',
                    'CurrAccDescription': partner.name[:50],
                    'FirstName': first_name[:50],
                    'LastName': last_name[:50],
                    'IsIndividualAcc': True,
                    'IsSubjectToEInvoice': True,
                    'IdentityNum': vat_clean,  # 11 haneli TCKN
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
                _logger.info("KURUMSAL (ŞAHIS FİRMASI): %s | FirstName=%s LastName=%s",
                             partner.name, first_name, last_name)
            else:
                # ─── TÜZEL KİŞİ (10 hane VKN veya diğer) ───
                tax_office_name = ''
                if sale_order:
                    for attr in ('trendyol_order_id', 'n11_order_id', 'hb_order_id'):
                        obj = getattr(sale_order, attr, None)
                        if obj:
                            tax_office_name = getattr(obj, 'tax_office', '') or ''
                            if tax_office_name:
                                break
                
                tax_office_code = ''
                if tax_office_name:
                    tax_mapping = self.env['odoougurlar.tax.mapping'].sudo().search(
                        [('name', '=ilike', tax_office_name.strip())], limit=1
                    )
                    tax_office_code = tax_mapping.nebim_tax_office_code if tax_mapping else ''

                payload = {
                    'ModelType': cari_model_type,
                    'CurrAccCode': '',
                    'CurrAccDescription': partner.name[:50],
                    'IsIndividualAcc': False,
                    'TaxNumber': vat_clean if len(vat_clean) == 10 else vat_raw,
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
                if tax_office_code:
                    payload['TaxOfficeCode'] = tax_office_code
                _logger.info("KURUMSAL (TÜZEL KİŞİ): %s | TaxNumber=%s, TaxOfficeCode=%s",
                             partner.name, vat_clean, tax_office_code)

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
            first_name = name_parts[0] if name_parts else (partner.name or 'Müşteri')
            last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else first_name

            # ─── Bireysel müşteride VKN kontrolü ───
            # Pazaryerleri bazen commercial=False gönderir ama partner.vat
            # 10 haneli VKN içerir (GİB e-fatura mükellefi).
            # Bu durumda Nebim'e kurumsal olarak aktarılmalı.
            vat_raw = partner.vat or ''
            vat_clean = ''.join(filter(str.isdigit, vat_raw))

            if len(vat_clean) == 10:
                # ─── 10 HANELİ VKN → KURUMSAL (TÜZEL KİŞİ) ───
                # Partner bireysel kaydedilmiş ama VKN'si var
                payload = {
                    'ModelType': cari_model_type,
                    'CurrAccCode': '',
                    'CurrAccDescription': (partner.name or 'KURUMSAL')[:50],
                    'IsIndividualAcc': False,
                    'TaxNumber': vat_clean,
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
                _logger.info(
                    "BİREYSEL→KURUMSAL DÖNÜŞÜM: %s | VKN (10 hane) tespit edildi → "
                    "IsIndividualAcc=False, TaxNumber=%s***",
                    partner.name, vat_clean[:3])
            elif len(vat_clean) == 11:
                # ─── 11 HANELİ TCKN → BİREYSEL (ŞAHIS) ───
                payload = {
                    'ModelType': cari_model_type,
                    'CurrAccCode': '',
                    'CurrAccDescription': (partner.name or 'BIREYSEL')[:50],
                    'IsIndividualAcc': True,
                    'FirstName': first_name[:50],
                    'LastName': last_name[:50],
                    'IdentityNum': vat_clean,
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
            else:
                # ─── VKN/TCKN YOK veya geçersiz → BİREYSEL (varsayılan) ───
                payload = {
                    'ModelType': cari_model_type,
                    'CurrAccCode': '',
                    'CurrAccDescription': (partner.name or 'BIREYSEL')[:50],
                    'IsIndividualAcc': True,
                    'FirstName': first_name[:50],
                    'LastName': last_name[:50],
                    'IdentityNum': vat_clean if vat_clean else '11111111111',
                    'OfficeCode': 'M',
                    'CurrencyCode': 'TRY',
                }
            # İhracat müşterisi ise ek alanlar
            if is_export:
                payload['TaxNumber'] = '1111111111'
                payload['CustomerTypeCode'] = 3

            # ─── E-fatura ve Vergi Dairesi (10h VKN dönüşümü için de) ───
            if len(vat_clean) == 10 and not is_export:
                payload['IsSubjectToEInvoice'] = True
                _logger.info("BİREYSEL→KURUMSAL E-FATURA: %s → IsSubjectToEInvoice=True", partner.name)

            # Vergi dairesi eşleştirmesi (VKN varsa gerekli)
            if len(vat_clean) == 10 and sale_order:
                tax_office_name = ''
                if hasattr(sale_order, 'trendyol_order_id') and sale_order.trendyol_order_id:
                    tax_office_name = sale_order.trendyol_order_id.tax_office or ''
                elif hasattr(sale_order, 'n11_order_id') and sale_order.n11_order_id:
                    tax_office_name = sale_order.n11_order_id.tax_office or ''
                elif hasattr(sale_order, 'hb_order_id') and sale_order.hb_order_id:
                    tax_office_name = getattr(sale_order.hb_order_id, 'tax_office', '') or ''

                if tax_office_name:
                    tax_mapping = self.env['odoougurlar.tax.mapping'].sudo().search(
                        [('name', '=ilike', tax_office_name.strip())], limit=1)
                    if tax_mapping:
                        payload['TaxOfficeCode'] = tax_mapping.nebim_tax_office_code
                        _logger.info("BİREYSEL→KURUMSAL Vergi Dairesi: '%s' → %s",
                                     tax_office_name, tax_mapping.nebim_tax_office_code)

        payload['PostalAddresses'] = [
            {
                'AddressTypeCode': "1",  # 1 = Fatura Adresi (Billing) — Nebim CurrAccCode için ZORUNLU!
                'CountryCode': country_code,
                'StateCode': state_code,
                'CityCode': city_code,
                'DistrictCode': district_code,
                'Address': (partner.street or 'Adres bilgisi yok')[:200],
            },
            {
                'AddressTypeCode': "2",  # 2 = Teslimat Adresi (Shipping) — Sipariş için ZORUNLU!
                'CountryCode': country_code,
                'StateCode': state_code,
                'CityCode': city_code,
                'DistrictCode': district_code,
                'Address': (partner.street or 'Adres bilgisi yok')[:200],
            }
        ]
        
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
            result_item = None
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                result_item = result[0]
            elif isinstance(result, dict):
                result_item = result
            
            if result_item:
                customer_code = result_item.get('CurrAccCode', result_item.get('CustomerCode', customer_code))
                
                # Adres ID çekme — birden fazla kaynaktan dene
                address_tmp = result_item.get('CurrAccDefault', {})
                address_id = (
                    address_tmp.get('ShippingAddressID')
                    or address_tmp.get('BillingAddressID')
                    or address_tmp.get('PostalAddressID')
                    or result_item.get('PostalAddressID')
                    or result_item.get('AddressID')
                    or ''
                )
                
                # PostalAddresses array'inden de kontrol et (Nebim bazen burada döndürür)
                if not address_id:
                    postal_addrs = result_item.get('PostalAddresses', [])
                    for pa in (postal_addrs or []):
                        if isinstance(pa, dict):
                            pa_id = pa.get('PostalAddressID') or pa.get('AddressID') or ''
                            if pa_id:
                                address_id = pa_id
                                break
                
            _logger.info("Oluşan Nebim Müşteri Kodu: %s, Adres ID: %s", customer_code, address_id)
            
            # Adres ID hala boşsa → Nebim SP ile çek
            if customer_code and not address_id:
                try:
                    cust_email = (partner.email or '').strip().lower()
                    if cust_email:
                        sp_res = connector.run_proc('sp_GetCustomer_Hamurlabs', [
                            {'Name': 'CommunicationTypeCode', 'Value': 3},
                            {'Name': 'CommAddress', 'Value': cust_email},
                            {'Name': 'TypeCode', 'Value': 4},
                            {'Name': 'CustomerType', 'Value': 4}
                        ])
                        if sp_res and isinstance(sp_res, list) and len(sp_res) > 0:
                            first = sp_res[0]
                            if isinstance(first, dict):
                                address_id = first.get('BillingAddressID') or first.get('ShippingAddressID') or ''
                                if address_id:
                                    _logger.info("Adres ID Nebim SP ile çekildi: %s → %s", customer_code, address_id)
                except Exception as e:
                    _logger.warning("Cari sonrası Adres ID SP hatası: %s", e)

            # ORM üzerinde res.partner'ı güncelle
            try:
                partner.sudo().write({
                    'nebim_customer_sent': True,
                    'nebim_customer_code': customer_code,
                    'nebim_address_id': address_id or ''
                })
            except Exception as e:
                _logger.warning("Partner ORM yazma uyarısı: %s", e)

            return customer_code, address_id
        except NebimCustomerError:
            raise  # Zaten request_json taşıyor
        except Exception as e:
            _logger.error("Cari Nebim'e gönderilemedi. Hata: %s", e)
            raise NebimCustomerError(f"Cari oluşturma başarısız: {str(e)}", request_json=request_json)

    def _save_partner_nebim_code(self, partner_id, customer_code, address_id=''):
        """Partner'a nebim_customer_code ve nebim_customer_sent değerini yazar."""
        if not partner_id or not customer_code:
            return
        try:
            p = self.env['res.partner'].sudo().browse(partner_id)
            if p.exists():
                p.write({
                    'nebim_customer_sent': True,
                    'nebim_customer_code': customer_code,
                    'nebim_address_id': address_id or ''
                })
        except Exception as e:
            _logger.warning("Partner Nebim cari kodu kayıt hatası: %s", e)

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

        # Nebim'de "Mersin" ili "İçel" olarak kayıtlıdır
        if _norm(odoo_state) == 'MERSIN':
            odoo_state = 'İçel'
            _logger.info("Mersin → İçel eşlemesi uygulandı (partner: %s)", partner.name)

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

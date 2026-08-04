import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class OrderProcessor(models.AbstractModel):
    _name = 'odoougurlar.order.processor'
    _description = 'Nebim Sipariş Processor (Packing anında)'

    def sync_order(self, sale_order, mapping, customer_code=None, address_id=None):
        """Siparişi Nebim'e atar ve dönen OrderLineID'leri kaydeder.
        
        Args:
            customer_code: Direkt cari kodu. ORM cache sorunlarını bypass etmek için
                          caller'dan explicit olarak geçirilmeli.
            address_id: Direkt adres ID. ORM cache sorunlarını bypass etmek için
                       caller'dan explicit olarak geçirilmeli.
        """
        if not sale_order:
            return False

        # ═══════════════════════════════════════════════════════════════════
        # CONCURRENCY KORUMASI: PostgreSQL Advisory Lock
        # Aynı sale.order için eş zamanlı sync_order çağrılarını engeller.
        # pg_try_advisory_xact_lock → transaction sonuna kadar tutar,
        # savepoint rollback'ten etkilenmez.
        # ═══════════════════════════════════════════════════════════════════
        # Önce ORM cache'deki bekleyen write'ları DB'ye yaz (caller'dan gelen)
        self.env.flush_all()

        lock_id = sale_order.id + 900000000  # advisory lock namespace offset
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", [lock_id])
        got_lock = self.env.cr.fetchone()[0]
        if not got_lock:
            _logger.warning("Sipariş %s için eş zamanlı sync_order çağrısı engellendi (advisory lock).", sale_order.name)
            return True  # Diğer transaction zaten işliyor

        # 1. Bu sipariş nesnesi zaten Nebim'e gönderildi mi? (DB'den taze oku)
        self.env.cr.execute(
            "SELECT nebim_order_sent FROM sale_order WHERE id = %s",
            [sale_order.id]
        )
        row = self.env.cr.fetchone()
        if row and row[0]:
            _logger.info("Sipariş zaten Nebim'e gönderilmiş (DB taze): %s", sale_order.name)
            return True

        # 2. Aynı sipariş numarasına/referansına sahip başka bir sipariş Nebim'e gönderilmiş mi?
        raw_ref = (sale_order.client_order_ref or sale_order.origin or sale_order.name or '').strip()
        import re
        clean_ref = re.sub(r'^(TY|HB|N11|PZR|FLO|AMZ|SHP|IDE|PTT|PTTAVM)-', '', raw_ref, flags=re.IGNORECASE).strip()
        
        if clean_ref:
            ref_search = list(set(filter(None, [
                clean_ref,
                f"TY-{clean_ref}",
                f"HB-{clean_ref}",
                f"N11-{clean_ref}",
                f"PZR-{clean_ref}",
                f"FLO-{clean_ref}",
                f"SHP-{clean_ref}",
                f"IDE-{clean_ref}",
                f"PTT-{clean_ref}",
                sale_order.client_order_ref,
                sale_order.origin,
                sale_order.name
            ])))
            
            existing_sent_so = self.env['sale.order'].sudo().search([
                ('id', '!=', sale_order.id),
                ('nebim_order_sent', '=', True),
                '|', '|',
                ('client_order_ref', 'in', ref_search),
                ('name', 'in', ref_search),
                ('origin', 'in', ref_search)
            ], limit=1)
            
            if existing_sent_so:
                _logger.info("Sipariş referansı (%s) Nebim'e %s numaralı siparişle zaten aktarılmış! Çift aktarım engellendi.",
                             clean_ref, existing_sent_so.name)
                sale_order.sudo().write({
                    'nebim_order_sent': True,
                    'nebim_header_id': existing_sent_so.nebim_header_id or 'DEDUP'
                })
                return True

            # 3. Nebim SQL Server'da bu sipariş belgesi zaten var mı? (Tüm ref varyasyonları ile canlı kontrol)
            try:
                connector_check = self.env['odoougurlar.nebim.connector']
                for check_val in ref_search:
                    if not check_val:
                        continue
                    sp_res = connector_check.run_proc('usp_CheckOrderExists_ent', [{'Name': 'InternalDescription', 'Value': check_val}])
                    if sp_res and isinstance(sp_res, list) and len(sp_res) > 0:
                        first = sp_res[0]
                        if isinstance(first, dict) and first.get('OrderExists'):
                            _logger.info("Nebim SQL'de sipariş zaten mevcut (InternalDescription=%s). Çift aktarım engellendi.", check_val)
                            sale_order.sudo().write({
                                'nebim_order_sent': True,
                                'nebim_header_id': 'NEBIM_DEDUP'
                            })
                            return True
            except Exception as e:
                _logger.debug("Nebim sipariş canlı kontrol SP çalıştırılamadı: %s", e)

        connector = self.env['odoougurlar.nebim.connector']
        
        # Cari Kodu: caller'dan gelen > order > partner > mapping > fallback
        if not customer_code:
            customer_code = (
                sale_order.nebim_customer_code
                or sale_order.partner_id.nebim_customer_code
                or (mapping.nebim_customer_code if mapping else (sale_order.partner_id.vat or 'B2C'))
            )
        
        if not customer_code:
            raise Exception("Cari Hesap Kodu Boş Olamaz — sync_order'a customer_code geçirilmedi ve ORM'de de bulunamadı.")
        
        _logger.info("Sipariş %s için kullanılan CurrAccCode: %s", sale_order.name, customer_code)
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
                
            # PriceVI: KDV dahil birim fiyat — Odoo price_total zaten KDV dahil hesaplar
            price_vi = float(line.price_total / line.product_uom_qty) if line.product_uom_qty else float(line.price_unit)

            line_data = {
                'Qty1': line.product_uom_qty,
                'SalesPersonCode': mapping.sales_person_code if mapping else 'TRD',
                'UsedBarcode': line.product_id.barcode or '',
                'PriceVI': price_vi
            }
            lines.append(line_data)

        # Mapping'den değerleri al, yoksa varsayılan kullan
        m_delivery = (mapping.delivery_company_code if mapping and mapping.delivery_company_code else 'YRT')
        m_store = (mapping.store_code if mapping and mapping.store_code else '002')
        m_warehouse = (mapping.warehouse_code if mapping and mapping.warehouse_code else '002')
        m_payment_agent = (mapping.payment_agent if mapping and mapping.payment_agent else 'TrendyolMp')
        m_sales_url = (mapping.sales_url if mapping and mapping.sales_url else 'www.trendyol.com')
        
        # Adres ID — caller'dan gelen > siparişte > partner'da > mapping'de > SP fallback
        addr_id = address_id or sale_order.nebim_address_id or sale_order.partner_id.nebim_address_id or (mapping.nebim_address_id if mapping else '') or ''

        # addr_id boş veya geçersiz ise → Nebim SP ile cari kartının gerçek adres ID'sini çek
        if not addr_id or addr_id == 'adc3d09b-897b-4b74-a29f-b42600863ec3':
            cust_email = (sale_order.partner_id.email or '').strip().lower()
            if cust_email and customer_code:
                try:
                    sp_res = connector.run_proc('sp_GetCustomer_Hamurlabs', [
                        {'Name': 'CommunicationTypeCode', 'Value': 3},
                        {'Name': 'CommAddress', 'Value': cust_email},
                        {'Name': 'TypeCode', 'Value': 4},
                        {'Name': 'CustomerType', 'Value': 4}
                    ])
                    if sp_res and isinstance(sp_res, list) and len(sp_res) > 0:
                        first = sp_res[0]
                        if isinstance(first, dict):
                            sp_addr = first.get('BillingAddressID') or ''
                            if sp_addr:
                                addr_id = sp_addr
                                _logger.info("Adres ID Nebim SP'den çekildi: %s → %s", customer_code, addr_id)
                                # Partner'ı da güncelle (gelecek siparişler için)
                                try:
                                    sale_order.partner_id.sudo().write({'nebim_address_id': addr_id})
                                    sale_order.sudo().write({'nebim_address_id': addr_id})
                                except Exception:
                                    pass
                except Exception as e:
                    _logger.warning("Adres ID SP sorgusu hatası: %s", e)
        
        if not addr_id:
            addr_id = 'adc3d09b-897b-4b74-a29f-b42600863ec3'  # Ultimum fallback

        # ShipmentMethodCode: 1=İhracat, 2=Yurtiçi Kargo
        if is_export:
            m_shipment = (mapping.shipment_method_code if mapping and getattr(mapping, 'shipment_method_code', None) else '1')
        else:
            m_shipment = '2'  # Yurtiçi her zaman kargo

        # Tarihler — Hamurlabs "YYYY-MM-DD" string formatı kullanıyor
        order_date_str = sale_order.date_order.strftime('%Y-%m-%d') if sale_order.date_order else fields.Date.today().strftime('%Y-%m-%d')
        send_date_str = fields.Date.today().strftime('%Y-%m-%d')
        payment_date_str = sale_order.date_order.strftime('%Y-%m-%d') if sale_order.date_order else send_date_str

        # Payment.DocumentDate: Hamurlabs epoch SANIYE cinsinden gönderiyor
        import time
        if sale_order.date_order:
            payment_epoch_sec = int(sale_order.date_order.timestamp())
        else:
            payment_epoch_sec = int(time.time())
        payment_doc_date = f"\\/Date({payment_epoch_sec})\\/"

        # ── Nebim payload ── Hamurlabs alan sırası birebir
        doc_ref = sale_order.client_order_ref or sale_order.name
        
        payload = {
            'IsCompleted':          True,
            'OrdersViaInternetInfo': {
                'PaymentTypeDescription': 'KREDIKARTI/BANKAKARTI',
                'SendDate':               send_date_str,
                'PaymentDate':            payment_date_str,
                'SalesURL':               m_sales_url,
                'PaymentTypeCode':        1,
                'PaymentAgent':           m_payment_agent,
            },
            'POSTerminalID':        '1',
            'BillingPostalAddressID': addr_id,
            'Lines': lines,
            'OfficeCode':           'M',
            'DocumentNumber':       doc_ref,
            'Payments': [{
                'CreditCardTypeCode': mapping.credit_card_type_code if mapping and mapping.credit_card_type_code else 'TRD',
                'Code':               '',
                'InstallmentCount':   1,
                'DocumentDate':       payment_doc_date,
                'PaymentType':        '2',
                'Amount':             sale_order.amount_total,
                'CurrencyCode':       'TRY',
            }],
            'IsSalesViaInternet':   True,
            'ShipmentMethodCode':   m_shipment,
            'StoreCode':            m_store,
            'WarehouseCode':        m_warehouse,
            'InternalDescription':  doc_ref,
            'Description':          doc_ref,
            'DeliveryCompanyCode':  ('' if is_export else m_delivery),
            'ModelType':            model_type,
            'OrderDate':            order_date_str,
            'CustomerCode':         customer_code,
            'ShippingPostalAddressID': addr_id,
        }

        if is_export:
            payload['ExportFileNumber'] = export_file_number
            payload['TaxExemptionCode'] = (mapping.tax_exemption_code if mapping and mapping.tax_exemption_code else '301')

        try:
            import json
            sale_order.write({'nebim_order_request': json.dumps(payload, ensure_ascii=False, indent=2, default=str)})
            result = connector.post_data('Post', payload)
            
            # Nebim HTTP 200 dönse bile kendi içinde hata metni yollayabilir
            if isinstance(result, dict) and 'ExceptionMessage' in result:
                raise Exception(result['ExceptionMessage'])
                
            # Nebim sipariş yanıtı dict olarak döner, Lines içinde her satırın LineID'si bulunur
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
            
            header_id = (
                result.get('HeaderID') or result.get('ApplicationID') or ''
            ) if isinstance(result, dict) else ''

            sale_order.sudo().write({
                'nebim_order_sent': True,
                'nebim_order_response': str(result),
                'nebim_export_file_number': export_file_number or '',
                'nebim_header_id': header_id,
            })
            _logger.info("Sipariş başarıyla Nebim'e aktarıldı: %s (HeaderID: %s)", 
                        sale_order.name, header_id)
            return True
            
        except Exception as e:
            _logger.error("Sipariş gönderim hatası: %s", e)
            sale_order.write({'nebim_order_response': str(e)})
            raise Exception(f"Nebim Sipariş Aktarım Hatası: {str(e)}")

    def _build_postal_address(self, partner, mapping, sale_order):
        """Sipariş için PostalAddress bloğunu Nebim resmi formatında oluşturur.

        Nebim resmi dökümantasyonundan alınan birebir alan sırası ve yapısı.
        Tüzel kişi (10h VKN) : CompanyName + TaxNumber + TaxOfficeCode dolu
        Şahıs firması (11h TCKN): FirstName + LastName + IdentityNum dolu
        Bireysel (11111...) : FirstName + LastName + IdentityNum dolu
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
        first_name = last_name = identity_num = company_name = tax_number = tax_office_code = ''

        if partner.is_company:
            vat_raw = partner.vat or ''
            vat_clean = ''.join(filter(str.isdigit, vat_raw))
            is_sahis = len(vat_clean) == 11

            if is_sahis:
                # Şahıs firması → TC Kimlik No + Ad/Soyad
                name_parts = (partner.name or '').strip().split()
                first_name = name_parts[0][:50] if name_parts else ''
                last_name = ' '.join(name_parts[1:])[:50] if len(name_parts) > 1 else ''
                identity_num = vat_clean
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
                    tax_office_code = tax_mapping.nebim_tax_office_code if tax_mapping else ''
        else:
            # Bireysel müşteri
            name_parts = (partner.name or '').strip().split()
            first_name = name_parts[0][:50] if name_parts else ''
            last_name = ' '.join(name_parts[1:])[:50] if len(name_parts) > 1 else ''
            identity_num = partner.vat or '11111111111'

        # Nebim resmi dökümantasyonundan birebir alan sırası
        return {
            'Address':      (partner.street or '')[:200],
            'AddressID':    0,
            'BuildingName': '',
            'BuildingNum':  '',
            'CityCode':     city_code,
            'CompanyName':  company_name,
            'CountryCode':  country_code,
            'DistrictCode': district_code,
            'DoorNum':      0,
            'FirstName':    first_name,
            'FloorNum':     0,
            'IdentityNum':  identity_num,
            'LastName':     last_name,
            'QuarterCode':  0,
            'QuarterName':  '',
            'SiteName':     '',
            'StateCode':    state_code,
            'StreetCode':   0,
            'StreetName':   '',
            'TaxNumber':    tax_number,
            'TaxOfficeCode': tax_office_code,
            'ZipCode':      '',
        }


# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class PazaramaOrderSync(models.Model):
    _inherit = 'pazarama.order'

    @api.model
    def sync_orders_from_pazarama(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['pazarama.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("Pazarama %s senkronizasyon hatası: %s", store.name, e)

    @api.model
    def sync_orders_for_store(self, store):
        """Seçilen mağazaya göre Pazarama'dan siparişleri çeker."""
        api_client = store.get_api()
        
        created_count = 0
        updated_count = 0
        error_count = 0
        
        # Son 1, 3 veya 5 günlük siparişleri çek (store.order_day_range)
        start_date = datetime.now() - timedelta(days=store.order_day_range or 1)
        end_date = datetime.now()
        
        page = 1
        while True:
            res = api_client.get_orders(start_date=start_date, end_date=end_date, page=page, size=100)
            
            if not res.get('success'):
                _logger.error("Pazarama Sipariş Çekme Hatası: %s", res.get('error'))
                break
            
            data_list = res.get('data', {}).get('data', [])
            if not data_list:
                break
                
            for order_json in data_list:
                try:
                    with self.env.cr.savepoint():
                        action = self._process_order_json(order_json, store)
                        if action == 'created':
                            created_count += 1
                        elif action == 'updated':
                            updated_count += 1
                except Exception as e:
                    error_count += 1
                    _logger.exception("Pazarama Sipariş İşleme Hatası: %s", e)
            
            # Paging check (isortagim api does not give totalPages in the same way, but we can check if data_list < limit
            if len(data_list) < 100:
                break
            page += 1
            
        store.sudo().write({'last_sync': fields.Datetime.now()})
        return {'created': created_count, 'updated': updated_count, 'errors': error_count}

    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, PazaramaOrder ve SaleOrder yaratır."""
        order_id = order_json.get('orderId')
        if not order_id:
            return 'skipped'

        existing_pazarama = self.search([('order_id', '=', order_id)], limit=1)
        
        # Sadece Created (3), Hazırlanıyor (12) gibi statüleri işleyebiliriz,
        # Örnek olarak Pazarama 'orderStatus' veriyor.
        order_status = order_json.get('orderStatus', 0)
        
        if existing_pazarama:
            # Guncelleme islemleri eklenebilir, iptal takibi vs.
            # Şimdilik sadece statü güncelleyelim.
            existing_pazarama.write({'order_status': order_status})
            return 'updated'

        # Tarih formatı: "2023-01-25 15:22" -> Odoo formatına çevir
        order_date_str = order_json.get('orderDate')
        order_date = False
        if order_date_str:
            try:
                order_date = datetime.strptime(order_date_str, '%Y-%m-%d %H:%M')
            except Exception:
                order_date = fields.Datetime.now()
        else:
            order_date = fields.Datetime.now()
            
        # Adresler
        shipment_addr = order_json.get('shipmentAddress') or {}
        billing_addr = order_json.get('billingAddress') or {}
        
        # Müşteri Email / Telefon
        customer_email = order_json.get('customerEmail') or shipment_addr.get('customerEmail') or ''
        phone_number = shipment_addr.get('phoneNumber') or ''

        # Pazarama.Order kaydı oluştur
        vals = {
            'store_id': store.id,
            'order_id': order_id,
            'order_number': str(order_json.get('orderNumber', '')),
            'order_date': order_date,
            'order_status': order_status,
            'payment_type': order_json.get('paymentType', 1),
            'invoice_type': billing_addr.get('invoiceType', 1),
            'customer_id': order_json.get('customerId', ''),
            'customer_name': order_json.get('customerName', '') or shipment_addr.get('nameSurname', ''),
            'customer_email': customer_email,
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr.get('cityName', ''),
            'shipping_district': shipment_addr.get('districtName', ''),
            'total_price': order_json.get('orderAmount', 0.0),
            'currency': order_json.get('currency', 'TRY'),
            'raw_data': json.dumps(order_json, ensure_ascii=False),
            'line_ids': [],
        }

        cargo_tracking = ''
        cargo_provider = ''

        items = order_json.get('items', [])
        for item in items:
            product = item.get('product', {})
            cargo = item.get('cargo', {})
            
            if not cargo_tracking and cargo.get('trackingNumber'):
                cargo_tracking = str(cargo.get('trackingNumber'))
            if not cargo_provider and cargo.get('companyName'):
                cargo_provider = str(cargo.get('companyName'))

            price_info = item.get('salePrice') or {}
            
            line_vals = {
                'item_id': item.get('orderItemId'),
                'product_id': product.get('productId'),
                'product_name': product.get('name'),
                'product_code': product.get('code') or product.get('stockCode'),
                'quantity': item.get('quantity', 1),
                'sale_price': price_info.get('value', 0.0),
                'status': item.get('orderItemStatus', 0),
                'cargo_tracking': cargo.get('trackingNumber'),
                'cargo_company': cargo.get('companyName'),
            }
            vals['line_ids'].append((0, 0, line_vals))
            
        vals['cargo_tracking_number'] = cargo_tracking
        vals['cargo_provider'] = cargo_provider
        
        pazarama_order = self.create(vals)
        
        # Sadece Odoo'da faturalandırma aşamasına girenleri içeri al (Örn: orderStatus == 3 'Sipariş Alındı' ise)
        if order_status == 3:
            sale_order = self._create_odoo_sale_order(pazarama_order, store, shipment_addr, billing_addr, customer_email, phone_number)
            pazarama_order.write({'sale_order_id': sale_order.id})
            
            # Otomatik onay
            if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
                
        return 'created'

    def _create_odoo_sale_order(self, p_order, store, ship_addr, bill_addr, customer_email, phone):
        """Odoo Sale Order & Res Partner yaratır."""
        
        # Müşteriyi bul veya oluştur
        partner_env = self.env['res.partner']
        country_tr = self.env.ref('base.tr').id
        
        # Adres text
        # "Merkez Mah Cami sk. NO: 5/ Merkez / Kütahya"
        display_text = ship_addr.get('displayAddressText', ship_addr.get('addressDetail', ''))
        
        # Ön Ek (Prefix) Uygulaması
        customer_ref = ''
        if store.customer_prefix and p_order.customer_id:
            customer_ref = f"{store.customer_prefix}{p_order.customer_id}"

        # KVKK: Email gizleme
        final_email = '' if store.skip_customer_email else customer_email

        partner_domain = [('name', '=ilike', p_order.customer_name)]
        if phone:
            partner_domain = ['|'] + partner_domain + [('phone', '=', phone)]
            
        partner = partner_env.search(partner_domain, limit=1)
        
        if not partner:
            partner = partner_env.create({
                'name': p_order.customer_name,
                'email': final_email,
                'phone': phone,
                'street': display_text,
                'city': p_order.shipping_city,
                'country_id': country_tr,
                'ref': customer_ref,
                'company_type': 'person' if bill_addr.get('invoiceType') == 1 else 'company'
            })
            
            # Eğer kurumsalsa fatura adresi bilgilerine göre vergi bilgilerini güncelle
            if bill_addr.get('invoiceType') == 2:
                partner.write({
                    'name': bill_addr.get('companyName') or p_order.customer_name,
                    'vat': bill_addr.get('taxNumber') or bill_addr.get('identityNumber'),
                    'is_subject_to_einvoice': bill_addr.get('isEInvoiceObliged', False)
                })
        
        # Fatura adresi farklıysa onu oluştur
        invoice_partner = partner
        if bill_addr and bill_addr.get('invoiceType') == 2:
            bill_display = bill_addr.get('displayAddressText', bill_addr.get('addressDetail', ''))
            invoice_partner = partner_env.create({
                'name': bill_addr.get('companyName') or p_order.customer_name,
                'type': 'invoice',
                'parent_id': partner.id,
                'street': bill_display,
                'city': bill_addr.get('cityName', ''),
                'vat': bill_addr.get('taxNumber') or bill_addr.get('identityNumber'),
                'is_subject_to_einvoice': bill_addr.get('isEInvoiceObliged', False),
                'ref': customer_ref,
            })

        # Sipariş oluştur
        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': partner.id,
            'pazarama_store_id': store.id,
            'pazarama_order_id': p_order.id,
            # Satiyorsan Odoo referansi Pazarama order_number baslasın
            'client_order_ref': p_order.order_number,
            'date_order': p_order.order_date,
            'order_line': [],
        }
        
        for line in p_order.line_ids:
            # Urunu bul
            product = self.env['product.product'].search([
                ('default_code', '=', line.product_code)
            ], limit=1)
            
            if not product:
                product = self.env['product.product'].search([
                    ('barcode', '=', line.product_code)
                ], limit=1)
            
            if not product:
                # Eger urun bulunamazsa hata veya taslak urun eklenebilir,
                # Bu demo icin basit tutalim
                _logger.warning("Pazarama Urun Bulunamadi: %s", line.product_code)
                continue
                
            sale_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,
                'pazarama_item_id': line.item_id,
            }))
            
        return self.env['sale.order'].create(sale_vals)

# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class IdefixOrderSync(models.Model):
    _inherit = 'idefix.order'

    @api.model
    def sync_orders_from_idefix(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['idefix.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("Idefix %s senkronizasyon hatası: %s", store.name, e)

    @api.model
    def sync_orders_for_store(self, store):
        """Seçilen mağazaya göre Idefix'dan siparişleri çeker."""
        api_client = store.get_api()
        
        created_count = 0
        updated_count = 0
        error_count = 0
        
        # Son X günlük siparişleri çek (store.order_day_range)
        start_date = datetime.now() - timedelta(days=store.order_day_range or 1)
        end_date = datetime.now()
        
        page = 1
        while True:
            res = api_client.get_orders(start_date=start_date, end_date=end_date, page=page, limit=50)
            
            if not res.get('success'):
                _logger.error("Idefix Sipariş Çekme Hatası: %s", res.get('error'))
                break
            
            data_dict = res.get('data', {})
            data_list = data_dict.get('items', [])
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
                    _logger.exception("Idefix Sipariş İşleme Hatası: %s", e)
            
            if len(data_list) < 50:
                break
            page += 1
            
        store.sudo().write({'last_sync': fields.Datetime.now()})
        return {'created': created_count, 'updated': updated_count, 'errors': error_count}

    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, IdefixOrder ve SaleOrder yaratır."""
        order_id = str(order_json.get('id', ''))
        if not order_id:
            return 'skipped'

        existing_idefix = self.search([('order_id', '=', order_id)], limit=1)
        
        order_status = order_json.get('status', '')
        
        if existing_idefix:
            existing_idefix.write({'order_status': order_status})
            return 'updated'

        order_date_str = order_json.get('orderDate') or order_json.get('createdAt')
        order_date = False
        if order_date_str:
            try:
                order_date = datetime.strptime(order_date_str[:19].replace('T',' '), '%Y-%m-%d %H:%M:%S')
            except Exception:
                order_date = fields.Datetime.now()
        else:
            order_date = fields.Datetime.now()
            
        shipment_addr = order_json.get('shippingAddress') or {}
        billing_addr = order_json.get('invoiceAddress') or {}
        
        customer_email = order_json.get('customerContactMail') or ''
        phone_number = shipment_addr.get('phone') or ''

        # Sipariş Durumu
        # Idefix 'created', 'shipment_ready', vb string gonderiyor
        # Biz bunu db kaydında string olarak tutacağız

        vals = {
            'store_id': store.id,
            'order_id': order_id,
            'order_number': str(order_json.get('orderNumber', '')),
            'order_date': order_date,
            'order_status': order_status,
            'payment_type': 1, # Default
            'invoice_type': 2 if billing_addr.get('isCommercial') == '1' else 1,
            'customer_id': str(order_json.get('customerId', '')),
            'customer_name': order_json.get('customerContactName') or billing_addr.get('fullName', ''),
            'customer_email': customer_email,
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr.get('city', ''),
            'shipping_district': shipment_addr.get('county', ''),
            'total_price': order_json.get('discountedTotalPrice', 0.0), # İndirimler düşülmüş tutar
            'currency': 'TRY',
            'raw_data': json.dumps(order_json, ensure_ascii=False),
            'line_ids': [],
        }

        cargo_tracking = order_json.get('cargoTrackingNumber') or ''
        cargo_provider = order_json.get('cargoCompany') or ''

        items = order_json.get('items', [])
        for item in items:
            line_vals = {
                'item_id': str(item.get('id', '')),
                'product_id': str(item.get('erpId', '')), # We might map ERP ID
                'product_name': item.get('productName'),
                'product_code': item.get('barcode') or item.get('merchantSku'),
                'quantity': 1, # Idefix gives items as flat list usually, but defaulting 1
                'sale_price': item.get('discountedTotalPrice', 0.0),
                'status': item.get('itemStatus', ''),
                'cargo_tracking': cargo_tracking,
                'cargo_company': cargo_provider,
            }
            vals['line_ids'].append((0, 0, line_vals))
            
        vals['cargo_tracking_number'] = cargo_tracking
        vals['cargo_provider'] = cargo_provider
        
        idefix_order = self.create(vals)
        
        # Odoo'da sipariş oluştur (Örn: created veya shipment_ready statüsünde olanları içeri al)
        if order_status in ['created', 'shipment_ready']:
            sale_order = self._create_odoo_sale_order(idefix_order, store, shipment_addr, billing_addr, customer_email, phone_number)
            idefix_order.write({'sale_order_id': sale_order.id})
            
            # Otomatik onay
            if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
                
        return 'created'

    def _create_odoo_sale_order(self, p_order, store, ship_addr, bill_addr, customer_email, phone):
        """Odoo Sale Order & Res Partner yaratır."""
        
        # Müşteriyi bul veya oluştur
        partner_env = self.env['res.partner']
        country_tr = self.env.ref('base.tr').id
        
        display_text = ship_addr.get('fullAddress') or ship_addr.get('address1', '')
        
        # Ön Ek Uygulaması
        customer_ref = ''
        if store.customer_prefix and p_order.customer_id:
            customer_ref = f"{store.customer_prefix}{p_order.customer_id}"

        # KVKK: Email gizleme
        final_email = '' if store.skip_customer_email else customer_email

        partner_domain = [('name', '=ilike', p_order.customer_name)]
        if phone:
            partner_domain = ['|'] + partner_domain + [('phone', '=', phone)]
            
        partner = partner_env.search(partner_domain, limit=1)
        
        is_commercial = bill_addr.get('isCommercial') == '1'
        
        if not partner:
            partner = partner_env.create({
                'name': bill_addr.get('company') or p_order.customer_name or 'Bilinmeyen Müşteri',
                'email': final_email,
                'phone': phone,
                'street': display_text,
                'city': p_order.shipping_city,
                'country_id': country_tr,
                'ref': customer_ref,
                'company_type': 'company' if is_commercial else 'person'
            })
            
            if is_commercial:
                partner.write({
                    'vat': bill_addr.get('taxNumber'),
                    'is_subject_to_einvoice': True
                })
        
        # Fatura adresi farklıysa onu oluştur
        invoice_partner = partner
        if is_commercial and bill_addr:
            bill_display = bill_addr.get('fullAddress') or bill_addr.get('address1', '')
            invoice_partner = partner_env.create({
                'name': bill_addr.get('company') or p_order.customer_name,
                'type': 'invoice',
                'parent_id': partner.id,
                'street': bill_display,
                'city': bill_addr.get('city', ''),
                'vat': bill_addr.get('taxNumber'),
                'is_subject_to_einvoice': True,
                'ref': customer_ref,
            })

        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': partner.id,
            'idefix_store_id': store.id,
            'idefix_order_id': p_order.id,
            'client_order_ref': p_order.order_number,
            'date_order': p_order.order_date,
            'order_line': [],
        }
        
        for line in p_order.line_ids:
            # Urunu barcode dan bul
            product = self.env['product.product'].search([
                ('barcode', '=', line.product_code)
            ], limit=1)
            
            if not product:
                product = self.env['product.product'].search([
                    ('default_code', '=', line.product_code)
                ], limit=1)
            
            if not product:
                _logger.warning("Idefix Urun Bulunamadi: %s", line.product_code)
                continue
                
            sale_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,
                'idefix_item_id': line.item_id,
            }))
            
        return self.env['sale.order'].create(sale_vals)

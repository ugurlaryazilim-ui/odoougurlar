
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class N11OrderSync(models.Model):
    _inherit = 'n11.order'

    @api.model
    def sync_orders_from_n11(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['n11.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.exception("N11 %s senkronizasyon hatası: %s", store.name, e)

    @api.model
    def sync_orders_for_store(self, store):
        """Seçilen mağazaya göre N11'dan siparişleri çeker."""
        api_client = store.get_api()
        
        created_count = 0
        updated_count = 0
        error_count = 0
        
        start_date = datetime.now() - timedelta(days=store.order_day_range or 1)
        end_date = datetime.now()
        
        page = 0
        total_pages = 1
        
        while page < total_pages:
            res = api_client.get_shipment_packages(start_date=start_date, end_date=end_date, status=None, page=page, size=100)
            
            if not res.get('success'):
                _logger.error("N11 Sipariş Çekme Hatası: %s", res.get('error'))
                break
                
            data = res.get('data', {})
            total_pages = data.get('totalPages', 1)
            content = data.get('content', [])
            
            if not content:
                break
                
            for order_json in content:
                try:
                    with self.env.cr.savepoint():
                        action = self._process_order_json(order_json, store)
                        if action == 'created':
                            created_count += 1
                        elif action == 'updated':
                            updated_count += 1
                except Exception as e:
                    error_count += 1
                    _logger.exception("N11 Sipariş İşleme Hatası: %s", e)
            
            page += 1
        
        store.sudo().write({'last_sync': fields.Datetime.now()})
        return {'created': created_count, 'updated': updated_count, 'errors': error_count}

    @api.private
    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, N11Order ve SaleOrder yaratır."""
        order_number = order_json.get('orderNumber')
        if not order_number:
            return 'skipped'

        existing_n11 = self.search([('order_number', '=', order_number)], limit=1)
        
        order_status = order_json.get('shipmentPackageStatus', '')
        
        if existing_n11:
            existing_n11.write({'order_status': order_status})
            return 'updated'

        order_date_ts = order_json.get('orderDate')
        order_date = False
        if order_date_ts:
            try:
                # UNIX timestamp → UTC (Odoo Datetime alanları UTC saklar)
                order_date = datetime.utcfromtimestamp(int(order_date_ts))
            except Exception:
                order_date = fields.Datetime.now()
        else:
            order_date = fields.Datetime.now()
            
        customer_email = order_json.get('customerEmail', '')
        
        shipment_addr = order_json.get('shippingAddress') or {}
        billing_addr = order_json.get('billingAddress') or {}
        
        phone_number = shipment_addr.get('gsm', '')

        # Fatura Tipi
        company_name = billing_addr.get('company', '')
        tax_number = billing_addr.get('taxNumber', '')
        is_commercial = True if company_name or tax_number else False

        # N11.Order kaydı oluştur
        vals = {
            'store_id': store.id,
            'order_id': str(order_json.get('id', order_number)), 
            'order_number': str(order_number),
            'order_date': order_date,
            'order_status': order_status,
            'payment_type': 1,
            'invoice_type': 2 if is_commercial else 1,
            'customer_id': str(order_json.get('customerId', '')),
            'customer_name': order_json.get('customerfullName', '').strip(),
            'customer_email': customer_email,
            'tax_office': billing_addr.get('taxHouse') or billing_addr.get('taxOffice') or order_json.get('taxOffice') or '',
            'shipment_address': json.dumps(shipment_addr, ensure_ascii=False),
            'billing_address': json.dumps(billing_addr, ensure_ascii=False),
            'shipping_city': shipment_addr.get('city', ''),
            'shipping_district': shipment_addr.get('district', ''),
            'total_price': float(order_json.get('totalAmount', 0.0)),
            'currency': order_json.get('currencyCode', 'TRY'),
            'cargo_tracking_number': order_json.get('cargoTrackingNumber', ''),
            'cargo_provider': order_json.get('cargoProviderName', ''),
            'raw_data': json.dumps(order_json, ensure_ascii=False),
            'line_ids': [],
        }

        products = order_json.get('lines', [])

        for item in products:
            qty = int(item.get('quantity', 1))
            
            # n11 faturaya yansıyacak tutar: sellerInvoiceAmount
            # Eğer Odoo bunu baz alıp fatura kesecekse net birim tutar bulunmalıdır.
            seller_invoice_amount = float(item.get('sellerInvoiceAmount', 0.0))
            if seller_invoice_amount > 0 and qty > 0:
                net_sale_price = seller_invoice_amount / qty
            else:
                net_sale_price = float(item.get('price', 0.0))
                
            line_vals = {
                'item_id': str(item.get('orderLineId', '')),
                'product_id': str(item.get('productId', '')),
                'product_name': item.get('productName', ''),
                'product_code': item.get('barcode') or item.get('stockCode'),
                'quantity': qty,
                'sale_price': net_sale_price,
                'status': item.get('orderItemLineItemStatusName', ''),
            }
            vals['line_ids'].append((0, 0, line_vals))
            
        n11_order = self.create(vals)
        
        # Odoo'ya aktarilacak durumlar (N11 için geçmiş faturaları da alabilmek adına kısıtlama kaldırıldı)
        if order_status not in ['Rejected', 'Rejected By Seller']:
            sale_order = self._create_odoo_sale_order(n11_order, store, shipment_addr, billing_addr, customer_email, phone_number, order_json)
            n11_order.write({'sale_order_id': sale_order.id})
            
            if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
                
        return 'created'

    @api.private
    def _create_odoo_sale_order(self, p_order, store, ship_addr, bill_addr, customer_email, phone, raw_json):
        """Odoo Sale Order & Res Partner yaratır."""
        
        partner_env = self.env['res.partner']
        country_tr = self.env.ref('base.tr').id
        
        display_text = ship_addr.get('address') or ship_addr.get('fullAddress') or ship_addr.get('address1') or ''
        
        customer_ref = ''
        if store.customer_prefix and p_order.customer_id:
            customer_ref = f"{store.customer_prefix}{p_order.customer_id}"

        final_email = '' if store.skip_customer_email else customer_email

        partner = False
        if customer_ref:
            partner = partner_env.search([('ref', '=', customer_ref)], limit=1)
            
        if not partner:
            # N11 numaraları "5XXXXXXXXX" şeklinde maskelediği için ASLA telefon ile OR araması yapılmamalı.
            partner = partner_env.search([('name', '=ilike', p_order.customer_name)], limit=1)
        
        company_name = bill_addr.get('company', '')
        is_commercial = True if company_name else False
        
        n11_city_name = p_order.shipping_city
        n11_district_name = p_order.shipping_district

        state_id = False
        if n11_city_name:
            state = self.env['res.country.state'].search([
                ('name', '=ilike', n11_city_name),
                ('country_id', '=', country_tr)
            ], limit=1)
            if state:
                state_id = state.id
                
        tc_id = raw_json.get('tcIdentityNumber') or ship_addr.get('tcId') or p_order.customer_id
        
        if not partner:
            partner = partner_env.create({
                'name': company_name if is_commercial else p_order.customer_name,
                'email': final_email,
                'phone': phone,
                'street': display_text,
                'street2': ship_addr.get('neighborhood') or '',
                'city': n11_district_name,
                'state_id': state_id,
                'zip': ship_addr.get('postalCode', ''),
                'country_id': country_tr,
                'ref': customer_ref,
                'company_type': 'company' if is_commercial else 'person',
                'vat': bill_addr.get('taxNumber') if is_commercial else tc_id,
            })
        else:
            update_vals = {}
            if display_text:
                update_vals['street'] = display_text
            if ship_addr.get('neighborhood'):
                update_vals['street2'] = ship_addr.get('neighborhood')
            if n11_district_name:
                update_vals['city'] = n11_district_name
            if state_id:
                update_vals['state_id'] = state_id
            if ship_addr.get('postalCode'):
                update_vals['zip'] = ship_addr.get('postalCode')
            if not partner.vat and (bill_addr.get('taxNumber') or tc_id):
                update_vals['vat'] = bill_addr.get('taxNumber') if is_commercial else tc_id
                
            if update_vals:
                partner.write(update_vals)
        
        invoice_partner = partner
        # Fatura adresi ID'leri farkliysa
        if bill_addr and bill_addr.get('id') != ship_addr.get('id'):
            bill_display = bill_addr.get('address') or bill_addr.get('fullAddress') or bill_addr.get('address1') or ''
            bill_city_name = bill_addr.get('city', '')
            bill_district_name = bill_addr.get('district', '')
            
            bill_state_id = False
            if bill_city_name:
                b_state = self.env['res.country.state'].search([
                    ('name', '=ilike', bill_city_name),
                    ('country_id', '=', country_tr)
                ], limit=1)
                if b_state:
                    bill_state_id = b_state.id
                    
            invoice_partner = partner_env.create({
                'name': company_name if is_commercial else f"{bill_addr.get('firstName','')} {bill_addr.get('lastName','')}".strip(),
                'type': 'invoice',
                'parent_id': partner.id,
                'street': bill_display,
                'street2': bill_addr.get('neighborhood') or '',
                'city': bill_district_name,
                'state_id': bill_state_id,
                'zip': bill_addr.get('postalCode', ''),
                'country_id': country_tr,
                'vat': bill_addr.get('taxNumber') if is_commercial else tc_id,
                'ref': customer_ref,
            })

        # Depo ayarını config'den al — Ayarlar > N11 > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param(
            'n11_integration.warehouse_id')
        warehouse_id = int(warehouse_id_str) if warehouse_id_str else False

        sale_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': invoice_partner.id,
            'partner_shipping_id': partner.id,
            'n11_store_id': store.id,
            'n11_order_id': p_order.id,
            'client_order_ref': p_order.order_number,
            'date_order': p_order.order_date,
            'order_line': [],
        }
        if warehouse_id:
            sale_vals['warehouse_id'] = warehouse_id
        
        # Batch ürün arama (N+1 önleme) — önce barcode, sonra nebim, sonra default_code
        Product = self.env['product.product'].sudo()
        codes = [line.product_code for line in p_order.line_ids if line.product_code]
        product_map = {}
        if codes:
            products = Product.search([('barcode', 'in', codes)])
            for p in products:
                if p.barcode:
                    product_map[p.barcode] = p
            # nebim_barcode fallback
            missing = [c for c in codes if c not in product_map]
            if missing and 'nebim_barcode' in Product._fields:
                for bc in missing:
                    p = Product.search([('nebim_barcode', '=', bc)], limit=1)
                    if not p:
                        p = Product.search([('nebim_barcode', 'ilike', bc)], limit=1)
                    if p:
                        product_map[bc] = p
            # default_code fallback
            still_missing = [c for c in codes if c not in product_map]
            if still_missing:
                products = Product.search([('default_code', 'in', still_missing)])
                for p in products:
                    if p.default_code:
                        product_map[p.default_code] = p

        for line in p_order.line_ids:
            product = product_map.get(line.product_code)
            
            if not product:
                _logger.warning("N11 Urun Bulunamadi: %s", line.product_code)
                continue
                
            sale_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,
                'n11_item_id': line.item_id,
            }))
            
        return self.env['sale.order'].create(sale_vals)

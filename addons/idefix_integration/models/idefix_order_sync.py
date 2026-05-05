
import json
import logging
import pytz
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

IST = pytz.timezone('Europe/Istanbul')

# Idefix'in kabul ettiği sipariş statüleri (string)
IDEFIX_VALID_ORDER_STATUSES = ('created', 'shipment_ready')

class IdefixOrderSync(models.Model):
    _inherit = 'idefix.order'

    @api.model
    def sync_orders_from_idefix(self):
        """Tüm aktif mağazalardan siparişleri senkronize et."""
        stores = self.env['idefix.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        _logger.info("Idefix otomatik senkronizasyon başladı — %d aktif mağaza", len(stores))
        for store in stores:
            try:
                res = self.sync_orders_for_store(store)
                _logger.info(
                    "Idefix [%s] senkron tamamlandı — Yeni: %d, Güncellenen: %d, Hata: %d",
                    store.name, res.get('created', 0), res.get('updated', 0), res.get('errors', 0)
                )
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
        # Idefix API Türkiye saatinde çalışır — sorgu tarihlerini Türkiye saatine çevir
        now_turkey = datetime.now(pytz.UTC).astimezone(IST).replace(tzinfo=None)
        start_date = now_turkey - timedelta(days=store.order_day_range or 1)
        end_date = now_turkey + timedelta(minutes=5)  # küçük güvenlik marjı
        
        _logger.info("Idefix [%s] sipariş çekme (TR saati): %s → %s", store.name, start_date, end_date)
        
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

    @api.private
    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, IdefixOrder ve SaleOrder yaratır."""
        order_id = str(order_json.get('id', ''))
        if not order_id:
            return 'skipped'

        existing_idefix = self.search([('order_id', '=', order_id)], limit=1)
        
        order_status = order_json.get('status', '')
        
        if existing_idefix:
            update_vals = {'order_status': order_status}
            # Kargo bilgisi sonradan gelebilir — güncelle
            cargo_tracking = order_json.get('cargoTrackingNumber') or ''
            cargo_provider = order_json.get('cargoCompany') or ''
            if cargo_tracking and not existing_idefix.cargo_tracking_number:
                update_vals['cargo_tracking_number'] = cargo_tracking
            if cargo_provider and not existing_idefix.cargo_provider:
                update_vals['cargo_provider'] = cargo_provider
            existing_idefix.write(update_vals)
            return 'updated'

        order_date_str = order_json.get('orderDate') or order_json.get('createdAt')
        order_date = False
        if order_date_str:
            try:
                # Idefix API Türkiye saati döner (+03:00) — Odoo UTC saklar
                # Türkiye → UTC çeviriyoruz, Odoo kullanıcı tz'sine göre geri çevirir
                naive_dt = datetime.strptime(order_date_str[:19].replace('T',' '), '%Y-%m-%d %H:%M:%S')
                turkey_dt = IST.localize(naive_dt)
                order_date = turkey_dt.astimezone(pytz.UTC).replace(tzinfo=None)
            except Exception:
                _logger.warning("Idefix tarih parse hatası: %s", order_date_str)
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
        
        # Geçerli statülerdeki siparişler için Sale Order oluştur
        if order_status in IDEFIX_VALID_ORDER_STATUSES:
            sale_order = self._create_odoo_sale_order(idefix_order, store, shipment_addr, billing_addr, customer_email, phone_number)
            idefix_order.write({'sale_order_id': sale_order.id})
            
            # Otomatik onay
            if store.auto_confirm and sale_order.state in ['draft', 'sent']:
                sale_order.action_confirm()
        else:
            _logger.info("Idefix sipariş %s statüsü '%s' — Sale Order oluşturulmadı (beklenen: %s)",
                         order_id, order_status, IDEFIX_VALID_ORDER_STATUSES)
                
        return 'created'

    @api.private
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

        # Müşteri eşleştirme — önce ref ile, sonra phone, sonra name
        partner = False
        if customer_ref:
            partner = partner_env.search([('ref', '=', customer_ref)], limit=1)
        if not partner and phone:
            partner = partner_env.search([('phone', '=', phone)], limit=1)
        if not partner:
            partner = partner_env.search([('name', '=ilike', p_order.customer_name)], limit=1)
        
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

        # Depo ayarını config'den al — Ayarlar > Idefix > Depo Ayarları
        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param(
            'idefix_integration.warehouse_id')
        warehouse_id = int(warehouse_id_str) if warehouse_id_str else False

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
                _logger.warning("Idefix Urun Bulunamadi: %s", line.product_code)
                continue
                
            sale_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.sale_price,
                'idefix_item_id': line.item_id,
            }))
            
        return self.env['sale.order'].create(sale_vals)

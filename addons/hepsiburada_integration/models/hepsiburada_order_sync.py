import json
import logging
import re
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class HepsiburadaOrderSync(models.AbstractModel):
    _name = 'hepsiburada.order.sync'
    _description = 'Hepsiburada Sipariş Senkronizasyonu'

    @api.model
    def sync_orders(self):
        """Cron tarafından çağrılan ana metod. Tüm aktif mağazaların siparişlerini çeker."""
        stores = self.env['hepsiburada.store'].search([('active', '=', True), ('auto_sync', '=', True)])
        if not stores:
            _logger.info("Otomatik senkronizasyon için aktif Hepsiburada mağazası bulunamadı.")
            return

        for store in stores:
            self._sync_store_orders(store)

    @api.model
    def _sync_store_orders(self, store):
        sync_log = self.env['hepsiburada.sync.log'].create({
            'store_id': store.id,
            'sync_type': 'order',
            'name': f"Sipariş Senkronizasyonu - {fields.Datetime.now()}",
        })

        clean_merchant, clean_user, clean_pass = store._get_clean_credentials()

        if not clean_merchant or not clean_user or not clean_pass:
            error_msg = "Mağaza API ayarları (Merchant ID, User, Password) eksik. Lütfen kontrol edin."
            _logger.error(error_msg)
            sync_log.mark_error(error_msg)
            return

        domain = store._get_api_domain()
        base_url = f"https://{domain}/packages/merchantid/{clean_merchant}"
        
        # Connection pooling — tek session ile tüm istekler
        session, _ = store._get_session()
        
        limit = 50
        total_fetched = 0
        success_count = 0
        error_count = 0
        log_msgs = []
        
        # Hepsiburada API works best for Open packages by completely omitting date filters.
        offset = 0
        while True:
            params = {
                'limit': limit,
                'offset': offset
            }
            
            try:
                response = session.get(base_url, params=params, timeout=30)
            except Exception as e:
                msg = f"API İstek Hatası: {str(e)}"
                _logger.error(msg)
                sync_log.mark_error(msg)
                return
                
            if response.status_code != 200:
                msg = f"API Hatası HTTP {response.status_code}: {response.text}"
                _logger.error(msg)
                sync_log.mark_error(msg)
                return
            
            data = response.json()
            if isinstance(data, list):
                items = data
            else:
                items = data.get('items', [])
            
            if not items:
                break
                
            # Process orders
            processed, scsc, errc, msgs = self._process_orders(items, store)
            total_fetched += processed
            success_count += scsc
            error_count += errc
            log_msgs.extend(msgs)
            
            # Pagination kontrolü
            if len(items) < limit:
                break
                
            offset += limit

        # 2. Geçmiş Sipariş Statülerini (Shipped, Delivered, Cancelled) Çek
        hist_processed, hist_succ, hist_err, hist_msgs = self._fetch_historical_statuses(store, session, clean_merchant)
        
        total_fetched += hist_processed
        success_count += hist_succ
        error_count += hist_err
        log_msgs.extend(hist_msgs)

        store.write({'last_sync': fields.Datetime.now()})
        details_txt = "\n".join(log_msgs) if log_msgs else "Tüm kayıtlar sorunsuz aktarıldı."
        sync_log.mark_done(
            processed=total_fetched, 
            created=success_count, 
            failed=error_count, 
            details=details_txt
        )
        _logger.info("[%s] Sipariş Senk. tamamlandı. Toplam: %s", store.name, total_fetched)
        return True

    @api.private
    def _fetch_historical_statuses(self, store, session, merchant_id):
        """Çeşitli statülerdeki geçmiş siparişlerin lightweight versiyonlarını tarayıp yeni olanların detayını çeker."""
        day_limit = store.order_day_range if store.order_day_range else 14
        cutoff_date = datetime.utcnow() - timedelta(days=day_limit)
        
        endpoints = ['shipped', 'delivered', 'cancelled', 'unpacked', 'undelivered']
        domain = store._get_api_domain()
        
        processed_count = 0
        success_count = 0
        error_count = 0
        log_msgs = []
        
        for status in endpoints:
            offset = 0
            limit = 50
            status_url = f"https://{domain}/packages/merchantid/{merchant_id}/{status}"
            
            while True:
                try:
                    res = session.get(status_url, params={'limit': limit, 'offset': offset}, timeout=30)
                except Exception as e:
                    _logger.error("[%s] Endpoint bağlantı hatası: %s", status, e)
                    break
                    
                if res.status_code != 200:
                    break
                    
                data = res.json()
                items = data.get('items', [])
                if not items:
                    break
                    
                should_stop_pagination = False
                missing_orders = set()
                
                for item in items:
                    date_str = item.get('DeliveredDate') or item.get('ShippedDate') or item.get('cancelDate') or item.get('UndeliveredDate')
                    
                    try:
                        if date_str:
                            item_date = datetime.strptime(date_str.split('.')[0], '%Y-%m-%dT%H:%M:%S')
                            if item_date < cutoff_date:
                                should_stop_pagination = True
                                continue
                    except Exception:
                        pass
                        
                    order_no = item.get('OrderNumber') or item.get('orderNumber') or item.get('PackageNumber') or item.get('packageNumber')
                    if not order_no:
                        continue
                        
                    existing_order = self.env['sale.order'].search([('client_order_ref', '=', str(order_no)), ('hb_store_id', '=', store.merchant_id)], limit=1)
                    if existing_order:
                        continue
                    else:
                        missing_orders.add(order_no)
                        
                # Eksik siparişlerin tam JSON'larını çek
                for m_order in missing_orders:
                    full_json = self._fetch_full_order_detail(m_order, store, session, merchant_id)
                    if full_json:
                        p, s, e_c, m = self._process_orders([full_json], store)
                        processed_count += p
                        success_count += s
                        error_count += e_c
                        log_msgs.extend(m)
                
                if should_stop_pagination or len(items) < limit:
                    break
                    
                offset += limit
                
        return processed_count, success_count, error_count, log_msgs

    @api.private
    def _fetch_full_order_detail(self, order_no, store, session, merchant_id):
        """Spesifik bir siparişin Müşteri ve Tutar dahil full JSON kopyasını çeker."""
        domain = store._get_api_domain()
        clean_merchant = re.sub(r'[\s\u200B-\u200D\uFEFF]+', '', merchant_id)
        url = f"https://{domain}/orders/merchantId/{clean_merchant}/orderNumber/{order_no}"
        
        try:
            res = session.get(url, timeout=30)
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            _logger.error("Eksik Sipariş (No: %s) full detay API hatası: %s", order_no, e)
            
        return None

    @api.private
    def _process_orders(self, packages, store):
        """API'den gelen paket listesini sipariş numarasına göre gruplayıp kaydeder."""
        _logger.info("Hepsiburada _process_orders called with %s packages.", len(packages))
        orders_dict = {}
        for pkg in packages:
            order_no = None
            pkg_items = pkg.get('items', [])
            
            if store.order_ref_type == 'package_id':
                order_no = pkg.get('packageNumber')
                if not order_no and pkg_items:
                    order_no = pkg_items[0].get('packageNumber')
            else:
                if pkg_items:
                    order_no = pkg_items[0].get('orderNumber')
                if not order_no:
                    order_no = pkg.get('orderNumber') or pkg.get('packageNumber')
                    
            if not order_no:
                continue
                
            if order_no not in orders_dict:
                orders_dict[order_no] = []
            orders_dict[order_no].append(pkg)
            
        _logger.info("Grouped into %s unique orders.", len(orders_dict))
        
        success_count = 0
        error_count = 0
        log_msgs = []

        for order_no, line_items in orders_dict.items():
            try:
                with self.env.cr.savepoint():
                    self._create_or_update_order(order_no, line_items, store)
                    success_count += 1
            except Exception as e:
                err = f"Sipariş No {order_no} işlenirken hata: {str(e)}"
                _logger.error(err)
                log_msgs.append(err)
                error_count += 1

        return len(orders_dict), success_count, error_count, log_msgs

    @api.private
    def _create_or_update_order(self, order_no, packages, store):
        env = self.env
        HbOrder = env['hepsiburada.order']
        
        existing = HbOrder.search([('hb_order_number', '=', order_no)], limit=1)
        if existing:
            return existing

        # Sipariş ana bilgilerini ilk paketten al
        first_pkg = packages[0]
        
        customer_name = first_pkg.get('customerName') or first_pkg.get('recipientName') or ''
        status = first_pkg.get('status')
        cargo_company = first_pkg.get('cargoCompany') or ''
        cargo_provider = cargo_company
        
        # Fatura detayları
        tax_office = first_pkg.get('taxOffice') or ''
        tax_number = first_pkg.get('taxNumber') or first_pkg.get('identityNo') or ''
        
        shipping_city = first_pkg.get('shippingCity') or ''
        shipping_district = first_pkg.get('shippingTown') or ''
        shipping_neighborhood = first_pkg.get('shippingDistrict') or ''
        customer_email = first_pkg.get('email') or ''
        customer_phone = first_pkg.get('phoneNumber') or ''

        # Adres texti oluşturma
        street_parts = []
        if shipping_neighborhood:
            street_parts.append(shipping_neighborhood)
        if first_pkg.get('shippingAddressDetail'):
            street_parts.append(first_pkg.get('shippingAddressDetail'))
        full_address = " ".join(street_parts)
            
        hb_order = HbOrder.create({
            'hb_order_number': order_no,
            'merchant_id': store.merchant_id,
            'order_date': first_pkg.get('orderDate', '').replace('T', ' ')[:19] if first_pkg.get('orderDate') else False,
            'status': status,
            'cargo_company': cargo_company,
            'cargo_provider': cargo_provider,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'tax_office': tax_office,
            'tax_number': tax_number,
            'shipping_address': full_address,
            'shipping_city': shipping_city,
            'shipping_district': shipping_district,
            'total_price': sum(pkg.get('totalPrice', {}).get('amount', 0.0) for pkg in packages),
            'currency': first_pkg.get('totalPrice', {}).get('currency', 'TRY'),
            'raw_payload': json.dumps(packages, ensure_ascii=False)
        })

        # Satırları oluştur (Package içindeki items dizisi)
        for pkg in packages:
            pkg_items = pkg.get('items', [])
            for item in pkg_items:
                env['hepsiburada.order.line'].create({
                    'order_id': hb_order.id,
                    'line_item_id': item.get('lineItemId') or item.get('id'),
                    'sku': item.get('hbSku') or item.get('sku'),
                    'merchant_sku': item.get('merchantSku'),
                    'product_name': item.get('productName', ''),
                    'quantity': item.get('quantity', 1),
                    'price': item.get('price', {}).get('amount', item.get('unitPrice', {}).get('amount', 0.0)),
                    'merchant_unit_price': item.get('merchantUnitPrice', 0.0),
                    'vat': item.get('vat', 0.0),
                    'vat_rate': item.get('vatRate', 0.0),
                    'commission_amount': item.get('commission', {}).get('amount', 0.0),
                    'status': status
                })

        partner = self._find_or_create_partner(hb_order, store)
        sale_order = self._create_sale_order(hb_order, partner, store)
        
        hb_order.write({'sale_order_id': sale_order.id})
        # env.cr.commit() KALDIRILDI — Transaction boundary'yi bozuyordu!
        return hb_order

    @api.private
    def _find_or_create_partner(self, hb_order, store):
        ResPartner = self.env['res.partner']
        prefix = store.customer_prefix or 'HB-'
        ref_val = f"{prefix}{hb_order.tax_number}" if hb_order.tax_number else f"{prefix}{hb_order.customer_name}"
        
        # Müşteri eşleştirme — önce ref, sonra vat, sonra name
        partner = ResPartner.search([('ref', '=', ref_val)], limit=1)
        if not partner and hb_order.tax_number:
            partner = ResPartner.search([('vat', '=', hb_order.tax_number)], limit=1)
        if not partner:
            partner = ResPartner.search([('name', '=ilike', hb_order.customer_name)], limit=1)

        state_id = False
        city_name = hb_order.shipping_district or ''
        
        if hb_order.shipping_city:
            state = self.env['res.country.state'].search([
                ('name', '=ilike', hb_order.shipping_city),
                ('country_id.code', '=', 'TR')
            ], limit=1)
            if state:
                state_id = state.id

        if not partner:
            partner = ResPartner.create({
                'name': hb_order.customer_name,
                'ref': ref_val,
                'phone': hb_order.customer_phone,
                'email': '' if store.skip_customer_email else hb_order.customer_email,
                'vat': hb_order.tax_number,
                'country_id': self.env.ref('base.tr').id,
                'state_id': state_id,
                'city': city_name,
                'street': hb_order.shipping_address,
                'company_type': 'company' if len(hb_order.tax_number or '') == 10 else 'person'
            })
        else:
            update_vals = {}
            if hb_order.shipping_address:
                update_vals['street'] = hb_order.shipping_address
            if state_id:
                update_vals['state_id'] = state_id
            if city_name:
                update_vals['city'] = city_name
            if not partner.vat and hb_order.tax_number:
                update_vals['vat'] = hb_order.tax_number
            if update_vals:
                partner.write(update_vals)
                
        return partner

    @api.private
    def _create_sale_order(self, hb_order, partner, store):
        SaleOrder = self.env['sale.order']
        Product = self.env['product.product'].sudo()

        # Batch ürün arama — N+1 önleme
        all_skus = []
        for line in hb_order.line_ids:
            if line.merchant_sku:
                all_skus.append(line.merchant_sku)
            if line.sku:
                all_skus.append(line.sku)

        product_map = {}
        if all_skus:
            # default_code ile toplu arama
            products = Product.search([('default_code', 'in', all_skus)])
            for p in products:
                if p.default_code:
                    product_map[p.default_code] = p
            # barcode ile toplu arama (fallback)
            missing = [s for s in all_skus if s not in product_map]
            if missing:
                products = Product.search([('barcode', 'in', missing)])
                for p in products:
                    if p.barcode:
                        product_map[p.barcode] = p
            # nebim_barcode fallback
            still_missing = [s for s in all_skus if s not in product_map]
            if still_missing and 'nebim_barcode' in Product._fields:
                for bc in still_missing:
                    p = Product.search([('nebim_barcode', '=', bc)], limit=1)
                    if not p:
                        p = Product.search([('nebim_barcode', 'ilike', bc)], limit=1)
                    if p:
                        product_map[bc] = p

        # Tax cache — N+1 önleme
        tax_cache = {}

        order_lines = []
        for line in hb_order.line_ids:
            # Ürünü bul
            product = product_map.get(line.merchant_sku) or product_map.get(line.sku)
            
            if not product:
                # Ürün bulunamazsa loglayıp devam et (otomatik oluşturma riskli)
                _logger.warning("HB Ürün bulunamadı: merchant_sku=%s, sku=%s, ürün adı=%s",
                               line.merchant_sku, line.sku, line.product_name)
                continue

            unit_price = line.merchant_unit_price if line.merchant_unit_price > 0 else line.price

            # Tax arama — cache ile
            vat_rate = line.vat_rate
            if vat_rate not in tax_cache:
                tax_id = self.env['account.tax'].search([
                    ('type_tax_use', '=', 'sale'),
                    ('amount', '=', vat_rate)
                ], limit=1)
                tax_cache[vat_rate] = tax_id
            tax_id = tax_cache[vat_rate]
            
            tax_lines = [(6, 0, [tax_id.id])] if tax_id else []

            order_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': unit_price,
                'tax_id': tax_lines,
                'name': f"[HB] {line.product_name}"
            }))

        warehouse_id_str = self.env['ir.config_parameter'].sudo().get_param('hepsiburada_integration.warehouse_id')
        warehouse_id = int(warehouse_id_str) if warehouse_id_str else False

        sale_vals = {
            'partner_id': partner.id,
            'client_order_ref': hb_order.hb_order_number,
            'hb_order_id': hb_order.id,
            'hb_store_id': hb_order.merchant_id,
            'origin': hb_order.hb_order_number,
            'order_line': order_lines,
        }
        if warehouse_id:
            sale_vals['warehouse_id'] = warehouse_id

        sale_order = SaleOrder.create(sale_vals)
        if store.auto_confirm:
            sale_order.action_confirm()
        return sale_order

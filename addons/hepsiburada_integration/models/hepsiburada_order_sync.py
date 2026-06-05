import json
import logging
import re
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Sahte/placeholder TC numaraları — HB bunları bireysel müşterilere atar
_DUMMY_TC_NUMBERS = {'11111111111', '00000000000', '99999999999', '12345678901'}


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
                    
                    # hepsiburada.order var ama sale.order yoksa da missing sayılır
                    # (_create_or_update_order orphan fix ile yeniden oluşturulacak)
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

        day_limit = store.order_day_range if store.order_day_range else 14
        cutoff_date = datetime.utcnow() - timedelta(days=day_limit)
        for order_no, line_items in orders_dict.items():
            # ── Client-side tarih filtresi ──
            first_pkg = line_items[0] if line_items else {}
            order_date_str = first_pkg.get('orderDate')
            if order_date_str:
                try:
                    order_dt = datetime.strptime(order_date_str[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                    if order_dt < cutoff_date:
                        _logger.debug("Eski sipariş atlandı (orderDate=%s < startDate=%s): %s",
                                      order_dt, cutoff_date, order_no)
                        continue
                except Exception:
                    pass

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

    # ═════════════════════════════════════════════════════════════
    # SİPARİŞ OLUŞTURMA — HER İKİ API FORMAT DESTEĞİ
    # Format 1 (flat):   /packages/ endpoint → root seviyesinde alanlar
    # Format 2 (nested): /orders/   endpoint → customer/invoice/deliveryAddress
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _create_or_update_order(self, order_no, packages, store):
        env = self.env
        HbOrder = env['hepsiburada.order']
        
        existing = HbOrder.search([('hb_order_number', '=', order_no)], limit=1)
        if existing:
            # sale.order gerçekten var mı kontrol et (silinmiş olabilir)
            sale_exists = False
            if existing.sale_order_id:
                sale_exists = bool(env['sale.order'].search([('id', '=', existing.sale_order_id.id)], limit=1))
            
            if sale_exists:
                return existing
            
            # sale.order silinmiş — yeniden oluştur
            _logger.info("HB sipariş %s: sale.order silinmiş, yeniden oluşturuluyor.", order_no)
            partner = self._find_or_create_partner(existing, store)
            sale_order = self._create_sale_order(existing, partner, store)
            existing.write({'sale_order_id': sale_order.id})
            return existing

        first_pkg = packages[0]
        
        # Tüm item'ları topla
        all_items = []
        for pkg in packages:
            all_items.extend(pkg.get('items', []))
        first_item = all_items[0] if all_items else {}
        
        # ── Müşteri Adı ──
        customer_name = (
            first_pkg.get('customer', {}).get('name', '') or   # Format 2
            first_pkg.get('customerName', '') or                # Format 1
            first_pkg.get('recipientName', '') or               # Format 1
            first_pkg.get('companyName', '') or                 # Format 1
            first_item.get('customerName', '')                  # Fallback
        )
        
        # ── Fatura / Vergi ──
        invoice_obj = first_pkg.get('invoice', {})
        invoice_addr = invoice_obj.get('address', {})
        
        tax_office = (
            invoice_obj.get('taxOffice', '') or first_pkg.get('taxOffice', '') or ''
        )
        tax_number = (
            invoice_obj.get('taxNumber', '') or first_pkg.get('taxNumber', '') or ''
        )
        tc_number = (
            invoice_obj.get('turkishIdentityNumber', '') or first_pkg.get('identityNo', '') or ''
        )
        tax_id_value = tax_number or tc_number
        
        # ── Email / Telefon ──
        delivery_addr = first_pkg.get('deliveryAddress', {})
        customer_email = (
            invoice_addr.get('email', '') or first_pkg.get('email', '') or ''
        )
        customer_phone = (
            delivery_addr.get('phoneNumber', '') or
            delivery_addr.get('alternatePhoneNumber', '') or
            invoice_addr.get('phoneNumber', '') or
            first_pkg.get('phoneNumber', '') or ''
        )
        
        # ── Teslimat Adresi ──
        shipping_address = (
            delivery_addr.get('address', '') or first_pkg.get('shippingAddressDetail', '') or ''
        )
        shipping_city = (
            delivery_addr.get('city', '') or first_pkg.get('shippingCity', '') or ''
        )
        shipping_district = (
            delivery_addr.get('town', '') or first_pkg.get('shippingTown', '') or ''
        )
        
        # ── Durum / Kargo ──
        status = first_item.get('status', '') or first_pkg.get('status', '') or ''
        cargo_company = (
            first_item.get('cargoCompany', '') or first_pkg.get('cargoCompany', '') or ''
        )
        cargo_model = first_item.get('cargoCompanyModel', {}) or {}
        cargo_provider = (
            cargo_model.get('name', '') or cargo_model.get('shortName', '') or cargo_company
        )
        package_number = (
            first_item.get('packageNumber', '') or first_pkg.get('packageNumber', '') or ''
        )
        cargo_tracking = (
            first_item.get('barcode', '') or first_pkg.get('barcode', '') or ''
        )
        
        # ── Sipariş Tarihi ──
        # HB orderDate TR yerel saatinde gelir (UTC+3), Odoo UTC bekler
        order_date = False
        order_date_str = first_pkg.get('orderDate', '')
        if order_date_str:
            try:
                dt_local = datetime.strptime(order_date_str[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                # TR yerel saat (UTC+3) → UTC'ye çevir
                dt_utc = dt_local - timedelta(hours=3)
                order_date = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass
        
        # ── Toplam Tutar ──
        root_total = first_pkg.get('totalPrice', {})
        total_price = root_total.get('amount', 0.0) if isinstance(root_total, dict) else 0.0
        items_total = sum(
            item.get('totalPrice', {}).get('amount', 0.0) for item in all_items
        )
        if items_total > 0:
            total_price = items_total
        
        currency = 'TRY'
        if all_items and isinstance(all_items[0].get('totalPrice', {}), dict):
            currency = all_items[0]['totalPrice'].get('currency', 'TRY')
            
        hb_order = HbOrder.create({
            'hb_order_number': order_no,
            'merchant_id': store.merchant_id,
            'order_date': order_date,
            'status': status,
            'cargo_company': cargo_company,
            'cargo_provider': cargo_provider,
            'cargo_tracking_number': cargo_tracking,
            'package_number': package_number,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'tax_office': tax_office,
            'tax_number': tax_id_value,
            'shipping_address': shipping_address,
            'shipping_city': shipping_city,
            'shipping_district': shipping_district,
            'total_price': total_price,
            'currency': currency,
            'raw_payload': json.dumps(packages, ensure_ascii=False)
        })

        # ── Satırları oluştur ──
        for item in all_items:
            item_total = item.get('totalPrice', {}).get('amount', 0.0)
            # unitPrice (her iki formatta dict)
            up_obj = item.get('unitPrice', {})
            item_unit = up_obj.get('amount', item_total) if isinstance(up_obj, dict) else item_total
            # merchantUnitPrice (Format 1'de dict, Format 2'de yok)
            mup_obj = item.get('merchantUnitPrice', {})
            merch_unit = mup_obj.get('amount', item_unit) if isinstance(mup_obj, dict) else (mup_obj or item_unit)
            # price fallback (Format 1)
            price_obj = item.get('price', {})
            if isinstance(price_obj, dict) and item_total == 0:
                item_total = price_obj.get('amount', 0.0)
            
            commission = item.get('commission', {})
            
            env['hepsiburada.order.line'].create({
                'order_id': hb_order.id,
                'line_item_id': item.get('id', '') or item.get('lineItemId', ''),
                'sku': item.get('sku', '') or item.get('hbSku', ''),
                'merchant_sku': (
                    item.get('merchantSKU', '') or      # Format 2: büyük SKU
                    item.get('merchantSku', '') or      # Format 1: küçük sku
                    item.get('productBarcode', '') or ''
                ),
                'product_name': item.get('name', '') or item.get('productName', ''),
                'quantity': item.get('quantity', 1),
                'price': item_total,
                'merchant_unit_price': merch_unit,
                'vat': item.get('vat', 0.0),
                'vat_rate': item.get('vatRate', 0.0),
                'commission_amount': commission.get('amount', 0.0) if isinstance(commission, dict) else 0.0,
                'commission_rate': item.get('commissionRate', 0.0),
                'status': item.get('status', '') or status,
            })

        partner = self._find_or_create_partner(hb_order, store)
        sale_order = self._create_sale_order(hb_order, partner, store)
        
        hb_order.write({'sale_order_id': sale_order.id})
        return hb_order

    # ═════════════════════════════════════════════════════════════
    # MÜŞTERİ OLUŞTURMA — Sahte TC kontrolü ile
    # ═════════════════════════════════════════════════════════════

    @api.private
    def _find_or_create_partner(self, hb_order, store):
        ResPartner = self.env['res.partner']
        prefix = store.customer_prefix or 'HB-'
        
        # Gerçek TC/VKN mi sahte mi kontrol et
        tax_no = (hb_order.tax_number or '').strip()
        is_real_tax = bool(tax_no) and tax_no not in _DUMMY_TC_NUMBERS and len(tax_no) >= 10
        
        # Ref oluşturma — sahte TC ile ref oluşturMA, isim bazlı yap
        if is_real_tax:
            ref_val = f"{prefix}{tax_no}"
        elif hb_order.customer_name:
            ref_val = f"{prefix}{hb_order.customer_name}"
        else:
            ref_val = ''
        
        # ── Müşteri eşleştirme ──
        partner = None
        
        # 1. Gerçek vergi numarası ile ara
        if is_real_tax:
            partner = ResPartner.search([('ref', '=', ref_val)], limit=1)
            if not partner:
                partner = ResPartner.search([('vat', '=', tax_no)], limit=1)
        
        # 2. Müşteri adı ile ara (sahte TC durumunda birincil yöntem)
        if not partner and hb_order.customer_name:
            partner = ResPartner.search([('name', '=ilike', hb_order.customer_name)], limit=1)

        # ── Şehir/İl eşleştirme ──
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
            partner_name = hb_order.customer_name or 'Bilinmeyen Müşteri'
            vals = {
                'name': partner_name,
                'phone': hb_order.customer_phone,
                'email': '' if store.skip_customer_email else hb_order.customer_email,
                'country_id': self.env.ref('base.tr').id,
                'state_id': state_id,
                'city': city_name,
                'street': hb_order.shipping_address,
            }
            if ref_val:
                vals['ref'] = ref_val
            if is_real_tax:
                vals['vat'] = tax_no
                vals['company_type'] = 'company' if len(tax_no) == 10 else 'person'
            partner = ResPartner.create(vals)
        else:
            update_vals = {}
            # İsim güncelle — eski "Adsız" kayıtlarını düzelt
            if hb_order.customer_name and (not partner.name or partner.name in ('Adsız', 'Bilinmeyen Müşteri')):
                update_vals['name'] = hb_order.customer_name
            if ref_val and not partner.ref:
                update_vals['ref'] = ref_val
            if hb_order.shipping_address:
                update_vals['street'] = hb_order.shipping_address
            if state_id:
                update_vals['state_id'] = state_id
            if city_name:
                update_vals['city'] = city_name
            if is_real_tax and not partner.vat:
                update_vals['vat'] = tax_no
            if hb_order.customer_phone and not partner.phone:
                update_vals['phone'] = hb_order.customer_phone
            if hb_order.customer_email and not partner.email and not store.skip_customer_email:
                update_vals['email'] = hb_order.customer_email
            if update_vals:
                partner.write(update_vals)
                
        return partner

    # ═════════════════════════════════════════════════════════════
    # SATIŞ SİPARİŞİ OLUŞTURMA
    # ═════════════════════════════════════════════════════════════

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
                _logger.warning("HB Ürün bulunamadı: merchant_sku=%s, sku=%s, ürün adı=%s",
                               line.merchant_sku, line.sku, line.product_name)
                continue

            # HB unitPrice KDV DAHİL tutardır
            unit_price = line.merchant_unit_price if line.merchant_unit_price > 0 else line.price

            ol_vals = {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': unit_price,
                'name': f"[HB] {line.product_name}",
            }

            # KDV dahil vergi bul — yuvarlama farkı olmasın
            vat_rate = line.vat_rate
            if vat_rate > 0:
                if vat_rate not in tax_cache:
                    tax = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', vat_rate),
                        ('price_include', '=', True),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                    tax_cache[vat_rate] = tax
                include_tax = tax_cache[vat_rate]
                if include_tax:
                    ol_vals['tax_id'] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi bulunamadı — manuel dönüşüm
                    ol_vals['price_unit'] = unit_price / (1 + vat_rate / 100)
                    _logger.warning("HB: %%%d KDV dahil vergi bulunamadı, manuel dönüşüm", int(vat_rate))

            order_lines.append((0, 0, ol_vals))

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
        if hb_order.order_date:
            sale_vals['date_order'] = hb_order.order_date
        if warehouse_id:
            sale_vals['warehouse_id'] = warehouse_id

        sale_order = SaleOrder.create(sale_vals)
        if store.auto_confirm:
            sale_order.action_confirm()
        return sale_order

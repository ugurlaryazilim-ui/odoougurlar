import json
import logging
import pytz
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
IST = pytz.timezone('Europe/Istanbul')


class ShopifyOrderSync(models.Model):
    _inherit = 'shopify.order'

    # ─── Cron Entry Point ────────────────────────────────

    @api.model
    def _cron_sync_orders(self):
        """Cron tarafından çağrılır — aktif tüm store'ları senkronize eder."""
        stores = self.env['shopify.store'].search([
            ('active', '=', True),
            ('auto_sync', '=', True),
        ])
        for store in stores:
            try:
                self.sync_orders_for_store(store)
            except Exception as e:
                _logger.error("Shopify sipariş senkronizasyon hatası (%s): %s", store.name, e)

    @api.model
    def sync_orders_for_store(self, store):
        """Tek bir store için siparişleri senkronize et."""
        api = store.get_api()

        now_utc = fields.Datetime.now()
        start_date = now_utc - timedelta(days=store.order_day_range or 3)

        # ISO 8601 format
        created_at_min = start_date.strftime('%Y-%m-%dT%H:%M:%S+00:00')

        financial_filter = 'paid' if store.sync_only_paid else None
        result = api.get_orders(
            created_at_min=created_at_min,
            financial_status=financial_filter,
        )
        if not result.get('success'):
            _logger.error("Shopify sipariş çekme hatası: %s", result.get('error'))
            return {'created': 0, 'updated': 0, 'errors': 1}

        orders_data = result.get('data', [])
        _logger.info("Shopify'dan %d sipariş çekildi (store=%s)", len(orders_data), store.name)

        created_count = 0
        updated_count = 0
        error_count = 0

        for order_json in orders_data:
            try:
                status = self._process_order_json(order_json, store)
                if status == 'created':
                    created_count += 1
                elif status == 'updated':
                    updated_count += 1
            except Exception as e:
                error_count += 1
                _logger.error("Shopify sipariş işleme hatası (order=%s): %s",
                              order_json.get('name', '?'), e, exc_info=True)

        store.sudo().write({'last_sync': fields.Datetime.now()})
        return {'created': created_count, 'updated': updated_count, 'errors': error_count}

    # ─── Process Single Order ────────────────────────────

    def _process_order_json(self, order_json, store):
        """Gelen tekil JSON'u işler, ShopifyOrder ve SaleOrder yaratır."""
        order_id = str(order_json.get('id', ''))
        if not order_id:
            return 'skipped'

        existing = self.search([('order_id', '=', order_id)], limit=1)

        financial_status = order_json.get('financial_status', '')
        fulfillment_status = order_json.get('fulfillment_status', '') or ''

        if existing:
            update_vals = {
                'financial_status': financial_status,
                'fulfillment_status': fulfillment_status,
            }
            # Kargo bilgisi sonradan gelebilir
            fulfillments = order_json.get('fulfillments', [])
            if fulfillments and not existing.cargo_tracking_number:
                ful = fulfillments[0]
                update_vals['cargo_tracking_number'] = ful.get('tracking_number', '')
                update_vals['cargo_provider'] = ful.get('tracking_company', '')
            existing.write(update_vals)
            return 'updated'

        # Sipariş tarihi dönüşümü (Shopify ISO 8601 → UTC)
        order_date = False
        created_at = order_json.get('created_at', '')
        if created_at:
            try:
                # Shopify: "2026-03-13T15:24:15+03:00"
                naive_str = created_at[:19].replace('T', ' ')
                naive_dt = datetime.strptime(naive_str, '%Y-%m-%d %H:%M:%S')
                turkey_dt = IST.localize(naive_dt)
                order_date = turkey_dt.astimezone(pytz.UTC).replace(tzinfo=None)
            except Exception:
                pass

        # Müşteri bilgileri
        customer = order_json.get('customer', {}) or {}
        shipping_addr = order_json.get('shipping_address', {}) or {}
        billing_addr = order_json.get('billing_address', {}) or {}

        customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        if not customer_name:
            customer_name = shipping_addr.get('name', '') or 'Shopify Müşteri'

        customer_email = customer.get('email', '') or order_json.get('email', '') or ''
        customer_phone = (
            customer.get('phone', '') or
            shipping_addr.get('phone', '') or
            order_json.get('phone', '') or ''
        )

        # ─── note_attributes'tan İl/İlçe bilgisi ────────
        note_attrs = order_json.get('note_attributes', []) or []
        note_il = ''
        note_ilce = ''
        for attr in note_attrs:
            attr_name = (attr.get('name', '') or '').strip()
            attr_value = (attr.get('value', '') or '').strip()
            if attr_name == 'İl':
                note_il = attr_value
            elif attr_name == 'İlçe':
                note_ilce = attr_value

        # Şehir bilgisi: önce note_attributes, sonra shipping_address
        shipping_city = note_il or shipping_addr.get('city', '') or ''
        shipping_district = note_ilce or ''

        # Kargo bilgisi
        fulfillments = order_json.get('fulfillments', [])
        tracking_number = ''
        tracking_company = store.default_cargo_company or 'DHL'
        if fulfillments:
            tracking_number = fulfillments[0].get('tracking_number', '') or ''
            tracking_company = fulfillments[0].get('tracking_company', '') or tracking_company

        # İndirim kodları
        discount_codes = order_json.get('discount_codes', [])
        discount_code_str = ', '.join(d.get('code', '') for d in discount_codes) if discount_codes else ''

        # ShopifyOrder oluştur
        shopify_order_vals = {
            'store_id': store.id,
            'order_id': order_id,
            'order_number': order_json.get('name', f'#{order_json.get("order_number", "")}'),
            'order_date': order_date,
            'order_status': 'open' if not order_json.get('cancelled_at') else 'cancelled',
            'financial_status': financial_status,
            'fulfillment_status': fulfillment_status,
            'customer_shopify_id': str(customer.get('id', '')),
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'shipping_address': json.dumps(shipping_addr, ensure_ascii=False) if shipping_addr else '',
            'billing_address': json.dumps(billing_addr, ensure_ascii=False) if billing_addr else '',
            'shipping_city': shipping_city,
            'shipping_district': shipping_district,
            'cargo_tracking_number': tracking_number,
            'cargo_provider': tracking_company,
            'total_price': float(order_json.get('total_price', 0)),
            'subtotal_price': float(order_json.get('subtotal_price', 0)),
            'total_tax': float(order_json.get('total_tax', 0)),
            'total_discount': float(order_json.get('total_discounts', 0)),
            'shipping_price': float(
                order_json.get('total_shipping_price_set', {})
                .get('shop_money', {}).get('amount', 0)),
            'currency': order_json.get('currency', 'TRY'),
            'taxes_included': order_json.get('taxes_included', True),
            'discount_codes': discount_code_str,
            'raw_data': json.dumps(order_json, ensure_ascii=False),
        }

        # Satır bilgileri
        line_vals_list = []
        for item in order_json.get('line_items', []):
            item_price = float(item.get('price', 0))

            # İndirim (line bazında discount_allocations)
            item_discount = sum(
                float(da.get('amount', 0))
                for da in item.get('discount_allocations', [])
            )

            # KDV oranı
            tax_rate = 0.0
            tax_lines = item.get('tax_lines', [])
            if tax_lines:
                tax_rate = float(tax_lines[0].get('rate', 0)) * 100  # 0.1 → 10

            # KDV dahil fiyat → KDV hariç hesaplama
            qty = int(item.get('quantity', 1))
            effective_price = item_price - (item_discount / qty if qty > 0 else 0)
            if order_json.get('taxes_included', True) and tax_rate > 0:
                price_tax_excluded = effective_price / (1 + tax_rate / 100)
            else:
                price_tax_excluded = effective_price

            line_vals_list.append((0, 0, {
                'line_item_id': str(item.get('id', '')),
                'product_shopify_id': str(item.get('product_id', '')),
                'variant_shopify_id': str(item.get('variant_id', '')),
                'sku': item.get('sku', '') or '',
                'product_name': item.get('title', '') or item.get('name', ''),
                'variant_title': item.get('variant_title', '') or '',
                'quantity': qty,
                'price': item_price,
                'price_tax_excluded': round(price_tax_excluded, 2),
                'total_discount': item_discount,
                'tax_rate': tax_rate,
                'fulfillment_status': item.get('fulfillment_status', '') or '',
            }))

        shopify_order_vals['line_ids'] = line_vals_list
        shopify_order = self.create(shopify_order_vals)

        # İptal edilen siparişleri atla
        if order_json.get('cancelled_at'):
            _logger.info("Shopify sipariş iptal edilmiş, Odoo sale.order oluşturulmadı: %s",
                         shopify_order.order_number)
            return 'created'

        # Odoo Sale Order oluştur
        try:
            sale_order = self._create_odoo_sale_order(shopify_order, order_json, store)
            shopify_order.write({'sale_order_id': sale_order.id})
            sale_order.write({'shopify_order_id': shopify_order.id})
            _logger.info("Shopify → Odoo sipariş oluşturuldu: %s → %s",
                         shopify_order.order_number, sale_order.name)
        except Exception as e:
            _logger.error("Odoo sale.order oluşturulamadı (Shopify %s): %s",
                          shopify_order.order_number, e, exc_info=True)

        return 'created'

    # ─── Create Odoo Sale Order ──────────────────────────

    def _create_odoo_sale_order(self, shopify_order, order_json, store):
        """Shopify siparişinden Odoo sale.order oluşturur."""
        partner = self._find_or_create_partner(order_json, store)

        # Depo / Warehouse — store ayarlarından al
        warehouse = store.warehouse_id or self.env['stock.warehouse'].search(
            [('code', '=', '002')], limit=1
        ) or self.env['stock.warehouse'].search([], limit=1)

        so_vals = {
            'partner_id': partner.id,
            'partner_shipping_id': partner.id,
            'partner_invoice_id': partner.id,
            'date_order': shopify_order.order_date or fields.Datetime.now(),
            'client_order_ref': shopify_order.order_number,
            'warehouse_id': warehouse.id if warehouse else False,
            'order_line': [],
        }

        # ─── Batch ürün arama (N+1 önleme) — idefix pattern ───
        Product = self.env['product.product'].sudo()
        skus = [line.sku for line in shopify_order.line_ids if line.sku]
        product_map = {}

        if skus:
            # 1. Barcode ile ara
            products = Product.search([('barcode', 'in', skus)])
            for p in products:
                if p.barcode:
                    product_map[p.barcode] = p

            # 2. nebim_barcode fallback
            missing = [s for s in skus if s not in product_map]
            if missing and 'nebim_barcode' in Product._fields:
                for sku in missing:
                    p = Product.search([('nebim_barcode', '=', sku)], limit=1)
                    if not p:
                        p = Product.search([('nebim_barcode', 'ilike', sku)], limit=1)
                    if p:
                        product_map[sku] = p

            # 3. default_code exact match
            still_missing = [s for s in skus if s not in product_map]
            if still_missing:
                products = Product.search([('default_code', 'in', still_missing)])
                for p in products:
                    if p.default_code:
                        product_map[p.default_code] = p

            # 4. Shopify SKU → Odoo İç Referans dönüşümü
            # Shopify: 24K91231000436 (birleşik)
            # Odoo:    24K91231-0004-36 (tireli)
            # Tireler çıkarıldığında eşleşir
            final_missing = [s for s in skus if s not in product_map]
            if final_missing:
                # İlk 8 karakter ürün kodu — bunla başlayan tüm varyantları çek
                prefix_set = set()
                for sku in final_missing:
                    if len(sku) >= 6:
                        prefix_set.add(sku[:6])  # İlk 6 karakter yeterli
                for prefix in prefix_set:
                    candidates = Product.search([
                        ('default_code', '=like', f'{prefix}%')
                    ])
                    for p in candidates:
                        if p.default_code:
                            # Tireyi kaldır ve karşılaştır
                            clean_code = p.default_code.replace('-', '').replace(' ', '')
                            for sku in final_missing:
                                clean_sku = sku.replace('-', '').replace(' ', '')
                                if clean_code == clean_sku and sku not in product_map:
                                    product_map[sku] = p
                                    _logger.info(
                                        "Shopify SKU eşleşti (tireli dönüşüm): %s → %s",
                                        sku, p.default_code)

        # Sipariş satırları
        for line in shopify_order.line_ids:
            product = product_map.get(line.sku)

            if not product:
                _logger.warning("Shopify ürün bulunamadı: SKU=%s, Ürün=%s",
                                line.sku, line.product_name)
                continue

            # KDV dahil fiyat geldiği için KDV hariç olarak yazıyoruz
            # Odoo'nun vergi motoru tekrar KDV ekleyecek
            so_vals['order_line'].append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': line.quantity,
                'price_unit': line.price_tax_excluded,
            }))

        if not so_vals['order_line']:
            _logger.error("Shopify %s: Eşleşen ürün bulunamadı! SKUs=%s",
                          shopify_order.order_number, skus)
            return False

        sale_order = self.env['sale.order'].sudo().create(so_vals)

        # Otomatik onayla
        if store.auto_confirm:
            try:
                sale_order.action_confirm()
                _logger.info("Shopify sipariş otomatik onaylandı: %s", sale_order.name)
            except Exception as e:
                _logger.warning("Shopify sipariş otomatik onaylanamadı: %s", e)

        return sale_order

    # ─── Partner (Müşteri) ───────────────────────────────

    def _find_or_create_partner(self, order_json, store):
        """Müşteriyi bul veya oluştur."""
        customer = order_json.get('customer', {}) or {}
        shipping = order_json.get('shipping_address', {}) or {}

        email = customer.get('email', '') or order_json.get('email', '') or ''
        phone = (
            customer.get('phone', '') or
            shipping.get('phone', '') or
            order_json.get('phone', '') or ''
        )
        first_name = shipping.get('first_name', '') or customer.get('first_name', '')
        last_name = shipping.get('last_name', '') or customer.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip() or 'Shopify Müşteri'

        # ─── note_attributes'tan İl/İlçe ────────────────
        note_attrs = order_json.get('note_attributes', []) or []
        note_il = ''
        note_ilce = ''
        for attr in note_attrs:
            attr_name = (attr.get('name', '') or '').strip()
            attr_value = (attr.get('value', '') or '').strip()
            if attr_name == 'İl':
                note_il = attr_value
            elif attr_name == 'İlçe':
                note_ilce = attr_value

        city = note_il or shipping.get('city', '') or ''

        # Önce email ile ara
        partner = False
        if email:
            partner = self.env['res.partner'].search([('email', '=', email)], limit=1)

        # Sonra telefon ile ara
        if not partner and phone:
            partner = self.env['res.partner'].search([('phone', '=', phone)], limit=1)

        if partner:
            return partner

        # Ülke
        country_tr = self.env.ref('base.tr', raise_if_not_found=False)
        country_code = shipping.get('country_code', 'TR')
        country = False
        if country_code == 'TR' and country_tr:
            country = country_tr
        else:
            country = self.env['res.country'].search(
                [('code', '=', country_code)], limit=1)

        # İl / State
        state = False
        if city and country:
            state = self.env['res.country.state'].search([
                ('country_id', '=', country.id),
                ('name', 'ilike', city),
            ], limit=1)

        address1 = shipping.get('address1', '') or ''
        address2 = shipping.get('address2', '') or ''
        street = f"{address1} {address2}".strip() if address1 else ''
        if note_ilce:
            street = f"{street} {note_ilce}".strip()

        partner_vals = {
            'name': full_name,
            'email': email,
            'phone': phone,
            'street': street,
            'city': city,
            'state_id': state.id if state else False,
            'country_id': country.id if country else False,
            'zip': shipping.get('zip', '') or '',
            'company_type': 'person',
            'customer_rank': 1,
        }

        partner = self.env['res.partner'].sudo().create(partner_vals)
        _logger.info("Shopify müşteri oluşturuldu: %s (email=%s, il=%s, ilce=%s)",
                     partner.name, email, city, note_ilce)
        return partner

    # ─── Product Matching ────────────────────────────────

    def _find_product_by_sku(self, sku):
        """SKU/barkod ile ürün bul."""
        if not sku:
            return False

        Product = self.env['product.product'].sudo()

        # 1. Barcode ile ara
        product = Product.search([('barcode', '=', sku)], limit=1)
        if product:
            return product

        # 2. nebim_barcode fallback
        if 'nebim_barcode' in Product._fields:
            product = Product.search([('nebim_barcode', '=', sku)], limit=1)
            if product:
                return product

        # 3. Default code ile ara
        product = Product.search([('default_code', '=', sku)], limit=1)
        if product:
            return product

        return False

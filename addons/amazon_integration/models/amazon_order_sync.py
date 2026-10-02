import json
import logging
from datetime import datetime, timedelta

import requests
from dateutil import parser as date_parser

from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from requests_auth_aws_sigv4 import AWSSigV4
except ImportError:
    AWSSigV4 = None

_logger = logging.getLogger(__name__)


class AmazonOrderSync(models.Model):
    _inherit = 'amazon.store'

    @api.private
    def _get_aws_auth(self):
        """AWS IAM Credentials provided ise STS AssumeRole işlemi yaparak AWSSigV4 nesnesi döner."""
        if not self.aws_access_key or not self.aws_secret_key:
            return None
        
        if not AWSSigV4:
            _logger.warning("requests_auth_aws_sigv4 paketi yüklü değil. AWS Auth devre dışı.")
            return None
            
        region_map = {
            'eu': 'eu-west-1',
            'na': 'us-east-1',
            'fe': 'us-west-2'
        }
        aws_region = region_map.get(self.region, 'us-east-1')
        
        try:
            if self.aws_role_arn and boto3:
                sts_client = boto3.client(
                    'sts',
                    aws_access_key_id=self.aws_access_key,
                    aws_secret_access_key=self.aws_secret_key,
                    region_name=aws_region
                )
                assumed_role = sts_client.assume_role(
                    RoleArn=self.aws_role_arn,
                    RoleSessionName="AmazonSPAPI"
                )
                creds = assumed_role['Credentials']
                return AWSSigV4(
                    'execute-api',
                    region=aws_region,
                    aws_access_key_id=creds['AccessKeyId'],
                    aws_secret_access_key=creds['SecretAccessKey'],
                    aws_session_token=creds['SessionToken']
                )
            else:
                return AWSSigV4(
                    'execute-api',
                    region=aws_region,
                    aws_access_key_id=self.aws_access_key,
                    aws_secret_access_key=self.aws_secret_key
                )
        except Exception as e:
            _logger.error("AWS Auth Error: %s", e)
            return None

    @api.private
    def _get_restricted_data_token(self, session, auth, base_url, amazon_order_id):
        """Amazon SP-API Restricted Data Token (RDT) alır.

        PII (Kişisel Bilgi) verilerine erişim için gereklidir.
        RDT olmadan ShippingAddress, BuyerInfo gibi alanlar BOŞ döner.

        Tokens API: POST /tokens/2021-03-01/restrictedDataToken
        Dönüş: RDT string veya None (hata durumunda).
        """
        endpoint = f"{base_url}/tokens/2021-03-01/restrictedDataToken"
        payload = {
            "restrictedResources": [
                {
                    "method": "GET",
                    "path": f"/orders/v0/orders/{amazon_order_id}",
                    "dataElements": ["buyerInfo", "shippingAddress"]
                },
                {
                    "method": "GET",
                    "path": f"/orders/v0/orders/{amazon_order_id}/address",
                },
                {
                    "method": "GET",
                    "path": f"/orders/v0/orders/{amazon_order_id}/buyerInfo",
                },
                {
                    "method": "GET",
                    "path": f"/orders/v0/orders/{amazon_order_id}/orderItems/buyerInfo",
                },
            ]
        }
        try:
            res = session.post(endpoint, auth=auth, json=payload, timeout=20)
            if res.status_code == 200:
                rdt = res.json().get('restrictedDataToken')
                if rdt:
                    _logger.debug(
                        "Amazon RDT alındı: %s (sipariş: %s)",
                        rdt[:20] + '...', amazon_order_id)
                    return rdt
                else:
                    _logger.warning(
                        "Amazon RDT yanıtında token yok: %s",
                        res.text[:200])
            elif res.status_code == 403:
                _logger.error(
                    "Amazon RDT 403 Forbidden — SP-API uygulamanızda "
                    "'Direct-to-Consumer Shipping' veya 'Tax Invoicing' "
                    "rolü aktif olmalı! Seller Central > Developer Console > "
                    "Uygulamanız > Data Access bölümünü kontrol edin. "
                    "Sipariş: %s | Yanıt: %s",
                    amazon_order_id, res.text[:300])
            else:
                _logger.warning(
                    "Amazon RDT HTTP %s (sipariş: %s): %s",
                    res.status_code, amazon_order_id, res.text[:300])
        except Exception as e:
            _logger.error("Amazon RDT fetch hatası (%s): %s", amazon_order_id, e)
        return None

    @api.model
    def cron_sync_amazon_orders(self):
        """Cron ile otomatik senkronizasyon."""
        try:
            stores = self.env['amazon.store'].search([
                ('active', '=', True),
                ('auto_sync', '=', True),
            ])
            for store in stores:
                try:
                    store.action_sync_orders()
                except Exception as e:
                    _logger.exception("Amazon %s senkronizasyon hatası: %s", store.name, e)
                if store.sync_financials:
                    try:
                        with self.env.cr.savepoint():
                            store._sync_financials()
                    except Exception as e:
                        _logger.exception("Amazon %s finans senkronizasyon hatası: %s", store.name, e)
        except Exception as e:
            _logger.exception("Amazon cron senkronizasyon hatası: %s", e)

    def action_fix_orphan_orders(self):
        """Picking'i olmayan Amazon siparişlerini düzelt.

        Mevcut sale.order'larda:
        1. Ürünsüz satırları tespit et → tiresiz eşleşme ile ürün bul
        2. Picking'i olmayan siparişleri tespit et → action_confirm tekrar çağır
        3. Fallback ürünü olan satırları düzelt → gerçek ürünü bul ve ata

        Bu metod Amazon Mağaza formundaki butondan çağrılır.
        """
        self.ensure_one()
        Product = self.env['product.product'].sudo()
        fallback_product = self._get_fallback_product()
        fallback_id = fallback_product.id if fallback_product else 0

        # Picking'i olmayan veya ürünsüz satırı olan Amazon siparişlerini bul
        orders = self.env['sale.order'].sudo().search([
            ('amazon_store_id', '=', self.id),
            ('state', 'in', ['sale', 'draft']),
        ])

        fixed_count = 0
        for order in orders:
            needs_fix = False
            lines_updated = 0

            for line in order.order_line:
                # Ürünsüz veya fallback ürünlü satırları tespit et
                if not line.product_id or (fallback_id and line.product_id.id == fallback_id):
                    # Satır adından SKU çıkarmayı dene
                    sku = ''
                    # Amazon sipariş kaydından SKU'yu al
                    if order.amazon_order_id and order.amazon_order_id.line_ids:
                        for amz_line in order.amazon_order_id.line_ids:
                            if amz_line.sku:
                                sku = amz_line.sku
                                break
                    if not sku:
                        # Satır adından (Title) çıkarma — genelde SKU name'de olmaz
                        continue

                    # Ürün eşleşmesini tekrar dene
                    if hasattr(Product, 'find_by_marketplace_barcode'):
                        product = Product.find_by_marketplace_barcode(sku)
                        if product and product.id != fallback_id:
                            line.sudo().write({'product_id': product.id})
                            lines_updated += 1
                            _logger.info(
                                "Amazon orphan fix: %s satırında SKU %s → %s eşleştirildi",
                                order.name, sku, product.display_name)
                            needs_fix = True

            # Picking yoksa ve sipariş onaylıysa → picking oluştur
            if order.state == 'sale' and not order.picking_ids:
                try:
                    order._action_launch_stock_rule()
                    _logger.info(
                        "Amazon orphan fix: %s için picking oluşturuldu",
                        order.name)
                    needs_fix = True
                except Exception as e:
                    _logger.warning(
                        "Amazon orphan fix: %s picking oluşturulamadı: %s",
                        order.name, e)

            # Draft sipariş → onayla (picking oluşması için)
            # Ürün ataması yapıldıysa (lines_updated > 0) veya
            # mevcut satırlarında zaten product_id varsa (fallback ürün dahil)
            if order.state == 'draft':
                has_any_product = any(
                    l.product_id
                    for l in order.order_line
                )
                if has_any_product:
                    try:
                        order.action_confirm()
                        _logger.info(
                            "Amazon orphan fix: %s onaylandı (picking oluşacak)",
                            order.name)
                        needs_fix = True
                    except Exception as e:
                        _logger.warning(
                            "Amazon orphan fix: %s onaylanamadı: %s",
                            order.name, e)

            if needs_fix:
                fixed_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Amazon Orphan Fix'),
                'message': f"{fixed_count} sipariş düzeltildi.",
                'type': 'success' if fixed_count else 'info',
                'sticky': False,
            },
        }

    def action_sync_orders(self):
        self.ensure_one()
        sync_log = self.env['amazon.sync.log'].create({
            'store_id': self.id,
            'sync_type': 'order'
        })
        
        try:
            access_token = self.generate_access_token()
            
            # Connection pooling — tek session ile tüm istekler
            session = requests.Session()
            session.headers.update({
                'x-amz-access-token': access_token,
                'User-Agent': 'OdooUgurlar/1.0',
                'Content-Type': 'application/json'
            })
            
            auth = self._get_aws_auth()
            
            base_url = self.get_api_endpoint()
            days = self.order_day_range if self.order_day_range else 14
            created_after = (datetime.utcnow() - timedelta(days=days)).isoformat() + 'Z'
            
            endpoint = f"{base_url}/orders/v0/orders"
            params = {
                'MarketplaceIds': self.marketplace_id,
                'CreatedAfter': created_after,
                'OrderStatuses': 'Unshipped,PartiallyShipped,Shipped,Canceled',
                'MaxResultsPerPage': 50
            }
            
            total_fetched = 0
            success_count = 0
            error_count = 0
            log_msgs = []
            
            while True:
                response = session.get(endpoint, auth=auth, params=params, timeout=30)
                if response.status_code != 200:
                    err = f"API Hatası HTTP {response.status_code}: {response.text}"
                    _logger.error(err)
                    sync_log.mark_error(err)
                    return
                    
                data = response.json()
                payload = data.get('payload', {})
                orders = payload.get('Orders', [])
                
                if not orders:
                    break
                    
                start_dt = datetime.utcnow() - timedelta(days=days)
                for order in orders:
                    # Client-side tarih filtresi
                    purchase_date = order.get('PurchaseDate')
                    if purchase_date:
                        try:
                            order_dt = date_parser.parse(purchase_date).replace(tzinfo=None)
                            if order_dt < start_dt:
                                continue
                        except Exception:
                            pass

                    try:
                        with self.env.cr.savepoint():
                            p, s, e, m = self._process_single_order(order, session, auth, base_url)
                            total_fetched += p
                            success_count += s
                            error_count += e
                            log_msgs.extend(m)
                    except Exception as ex:
                        error_count += 1
                        log_msgs.append(f"Order Parse Error ({order.get('AmazonOrderId')}): {ex}")
                
                next_token = payload.get('NextToken')
                if not next_token:
                    break
                
                params = {
                    'MarketplaceIds': self.marketplace_id,
                    'NextToken': next_token
                }
            
            self.write({'last_sync': fields.Datetime.now()})
            details_txt = "\n".join(log_msgs) if log_msgs else "Tüm kayıtlar sorunsuz aktarıldı."
            sync_log.mark_done(total_fetched, success_count, error_count, details_txt)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Senkronizasyon Başarılı'),
                    'message': f"{success_count} sipariş işlendi.",
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            sync_log.mark_error(str(e))
            raise UserError(str(e))

    def _refetch_single_amazon_order(self, amazon_order_id):
        """Amazon'dan tek bir siparişi ve müşteri detaylarını yenile.

        RDT kullanarak PII bilgilerini de çeker.
        """
        self.ensure_one()
        access_token = self.generate_access_token()
        session = requests.Session()
        session.headers.update({
            'x-amz-access-token': access_token,
            'User-Agent': 'OdooUgurlar/1.0',
            'Content-Type': 'application/json'
        })
        auth = self._get_aws_auth()
        base_url = self.get_api_endpoint()

        # RDT al — PII bilgileri (ad, adres, telefon) için gerekli
        rdt = self._get_restricted_data_token(session, auth, base_url, amazon_order_id)

        # RDT varsa header'da kullan
        headers = {}
        if rdt:
            headers['x-amz-access-token'] = rdt

        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}"
        res = session.get(endpoint, auth=auth, headers=headers, timeout=20)
        if res.status_code != 200:
            raise UserError(_(
                "Amazon sipariş bilgisi alınamadı (HTTP %s): %s") % (
                res.status_code, res.text))

        order_data = res.json().get('payload', {})
        self._process_single_order(order_data, session, auth, base_url, force_update=True)

    @api.private
    def _get_fallback_product(self):
        """Varsayılan Amazon fallback ürününü getirir, yoksa veritabanı kısıtlamalarına uyarak dinamik oluşturur."""
        # 1. default_code = 'AMAZON-UNKNOWN' ile arama
        Product = self.env['product.product'].sudo()
        product = Product.search([('default_code', '=', 'AMAZON-UNKNOWN')], limit=1)
        if product:
            return product

        # 2. XML ref'ler ile arama (önceden eklenmişse)
        tmpl = self.env.ref('amazon_integration.product_template_amazon_unknown', raise_if_not_found=False)
        if tmpl:
            product = tmpl.product_variant_id or Product.search([('product_tmpl_id', '=', tmpl.id)], limit=1)
            if product:
                return product

        old_ref = self.env.ref('amazon_integration.product_amazon_unknown', raise_if_not_found=False)
        if old_ref and old_ref._name == 'product.product':
            return old_ref

        # 3. Güvenli şekilde ORM / SQL ile dinamik oluşturma
        try:
            tmpl_vals = {
                'name': 'Amazon Ürünü (Eşleştirilmemiş)',
                'default_code': 'AMAZON-UNKNOWN',
                'type': 'consu',
                'is_storable': True,
                'sale_ok': True,
                'purchase_ok': False,
                'list_price': 0,
                'standard_price': 0,
                'tracking': 'none',
            }
            tmpl = self.env['product.template'].sudo().create(tmpl_vals)
            return tmpl.product_variant_id or Product.search([('product_tmpl_id', '=', tmpl.id)], limit=1)
        except Exception as e:
            _logger.error("Amazon fallback ürün ORM hatası: %s", e)
            try:
                # Raw SQL fallback — veritabanındaki özel kısıtlamaları bypass etme
                self.env.cr.execute("SELECT id FROM product_product WHERE default_code = 'AMAZON-UNKNOWN' LIMIT 1")
                res = self.env.cr.fetchone()
                if res:
                    return Product.browse(res[0])

                name_val = json.dumps({"tr_TR": "Amazon Ürünü (Eşleştirilmemiş)", "en_US": "Amazon Ürünü (Eşleştirilmemiş)"})
                self.env.cr.execute("""
                    INSERT INTO product_template (name, type, is_storable, sale_ok, purchase_ok, list_price, standard_price, tracking, create_date, write_date, create_uid, write_uid, active)
                    VALUES (%s, 'consu', true, true, false, 0, 0, 'none', NOW(), NOW(), 1, 1, true)
                    RETURNING id
                """, (name_val,))
                tmpl_id = self.env.cr.fetchone()[0]

                self.env.cr.execute("""
                    INSERT INTO product_product (product_tmpl_id, default_code, active, create_date, write_date, create_uid, write_uid)
                    VALUES (%s, 'AMAZON-UNKNOWN', true, NOW(), NOW(), 1, 1)
                    RETURNING id
                """, (tmpl_id,))
                prod_id = self.env.cr.fetchone()[0]
                return Product.browse(prod_id)
            except Exception as sql_e:
                _logger.error("Amazon fallback ürün SQL hatası: %s", sql_e)
                # Son çare: Sistemde mevcut herhangi bir storable ürünü döndür
                return Product.search([('type', '=', 'consu')], limit=1)

    @api.private
    def _prepare_sale_order_lines(self, items_val, product_map, amazon_order_id, msgs,
                                  session=None, auth=None, base_url=None):
        """Odoo Sale Order satırlarını KDV DAHİL tutar esasına göre hazırlar.

        Amazon fiyatları KDV DAHİL (price_include=True) fiyattır.
        Odoo varsayılan vergisi KDV HARIÇ ise, Odoo üzerine tekrar KDV ekleyecektir.
        Bunu önlemek için price_include=True olan vergi aranır, bulunamazsa birim fiyat
        KDV Hariç tutara çevrilerek yazılır. Böylece Genel Toplam Amazon ile birebir tutar.

        Ürün Eşleşme Sırası:
            1. SellerSKU ile arama (barcode, nebim_barcode, default_code, tiresiz eşleşme)
            2. ASIN → Catalog Items API → EAN/UPC → barkod ile arama
            3. Fallback ürün: 'Amazon Ürünü (Eşleştirilmemiş)'
        """
        order_lines = []
        _tax_cache = {}
        line_fields = self.env['sale.order.line']._fields
        # Odoo 19: tax_ids (eski sürümlerde tax_id) — bilinmeyen alan create'te ValueError verir
        tax_field = 'tax_ids' if 'tax_ids' in line_fields else ('tax_id' if 'tax_id' in line_fields else False)
        _ean_cache = {}  # ASIN → EAN cache (aynı siparişte aynı ASIN'i tekrar çekme)

        for item in items_val:
            sku = item.get('SellerSKU')
            asin = item.get('ASIN', '')
            qty = float(item.get('QuantityOrdered', 1))
            item_price = float(item.get('ItemPrice', {}).get('Amount', 0.0))
            item_tax = float(item.get('ItemTax', {}).get('Amount', 0.0))
            # Satıcı/Amazon promosyonu ItemPrice'tan düşülmez, ayrı gelir → müşterinin ödediği tutar
            promotion = float((item.get('PromotionDiscount') or {}).get('Amount', 0.0) or 0.0)

            # ─── ADIM 1: SellerSKU ile ürün ara (tiresiz eşleşme dahil) ───
            product = product_map.get(sku)
            if not product and sku:
                # Batch'te bulunamadı, tek tek dene (fallback — Trendyol ile aynı mantık)
                Product = self.env['product.product'].sudo()
                if hasattr(Product, 'find_by_marketplace_barcode'):
                    product = Product.find_by_marketplace_barcode(sku)

            if product:
                _logger.info(
                    "Amazon SKU eşleşti: '%s' → %s (id:%d, code:%s) Sipariş: %s",
                    sku, product.display_name, product.id,
                    product.default_code, amazon_order_id)
            else:
                _logger.warning(
                    "Amazon ADIM-1 BAŞARISIZ: SellerSKU '%s' ile ürün bulunamadı. "
                    "ASIN: %s, Sipariş: %s, Title: %s",
                    sku, asin, amazon_order_id,
                    item.get('Title', '')[:80])

            # ─── ADIM 2: ASIN → Catalog API → EAN/UPC ile ara ───
            if not product and asin and session and auth and base_url:
                ean = _ean_cache.get(asin)
                if ean is None:
                    ean = self._fetch_catalog_ean(asin, session, auth, base_url)
                    _ean_cache[asin] = ean
                if ean:
                    Product = self.env['product.product'].sudo()
                    if hasattr(Product, 'find_by_marketplace_barcode'):
                        product = Product.find_by_marketplace_barcode(ean)
                    if product:
                        _logger.info(
                            "Amazon ASIN→EAN eşleşme başarılı: %s → EAN %s → %s (%s)",
                            asin, ean, product.display_name, product.default_code)
                    else:
                        _logger.warning(
                            "Amazon ADIM-2 BAŞARISIZ: ASIN %s → EAN '%s' bulundu ama "
                            "Odoo'da bu barkodla ürün yok. Sipariş: %s",
                            asin, ean, amazon_order_id)
                else:
                    _logger.warning(
                        "Amazon ADIM-2 BAŞARISIZ: ASIN %s için Catalog API'den "
                        "EAN/UPC alınamadı. Sipariş: %s",
                        asin, amazon_order_id)

            # ─── ADIM 3: Fallback ürünü ───
            if not product:
                # Ürün bulunamadı — varsayılan fallback ürünü kullan.
                # product_id OLMADAN satır oluşturulursa Odoo picking (teslimat)
                # oluşturmaz → sipariş toplama listesine GİREMEZ.
                fallback = self._get_fallback_product()
                if fallback:
                    product = fallback
                    msgs.append(
                        f"{amazon_order_id} siparişinde {sku} SKU'lu ürün "
                        f"Odoo'da bulunamadı — 'Amazon Ürünü (Eşleştirilmemiş)' ile oluşturuluyor."
                    )
                else:
                    # Fallback ürünü de bulunamadı — ürünsüz satır oluşturma!
                    # product_id olmayan satır picking oluşturmaz.
                    msgs.append(
                        f"{amazon_order_id} siparişinde {sku} SKU'lu ürün bulunamadı, "
                        f"fallback ürünü de yok — satır atlanıyor (picking oluşması için ürün gerekli)."
                    )
                    _logger.error(
                        "Amazon KRİTİK: SKU '%s', ASIN '%s' (Sipariş: %s) — "
                        "fallback ürünü de bulunamadı! Satır atlanıyor. "
                        "'AMAZON-UNKNOWN' kodlu ürün oluşturun.",
                        sku, asin, amazon_order_id,
                    )
                    continue  # Bu satırı atla — ürünsüz satır oluşturma
                _logger.warning(
                    "Amazon ADIM-3 FALLBACK: SKU '%s', ASIN '%s' (Sipariş: %s) — "
                    "eşleşme 3 adımda da başarısız, fallback ürünü kullanılıyor.",
                    sku, asin, amazon_order_id,
                )

            line_total = item_price - promotion if 0 < promotion < item_price else item_price
            unit_price_incl = line_total / qty if qty > 0 else line_total

            ol_vals = {
                'product_uom_qty': qty,
                'price_unit': unit_price_incl,
                'name': item.get('Title', sku or 'Amazon Ürünü'),
                'product_id': product.id,  # Her zaman ürün ataması yapılır
            }

            # ─── KDV Dahil Vergi Tespiti & Fiyat Ayarlaması ───
            vat_rate = 0.0
            if product:
                product_taxes = product.taxes_id.filtered(
                    lambda t: t.company_id.id in [self.company_id.id, self.env.company.id]
                )
                if item_tax > 0 and item_price > 0:
                    vat_rate = round((item_tax / item_price) * 100)
                elif product_taxes:
                    vat_rate = product_taxes[0].amount
            elif item_tax > 0 and item_price > 0:
                vat_rate = round((item_tax / item_price) * 100)

            if vat_rate > 0:
                if vat_rate not in _tax_cache:
                    tax = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', vat_rate),
                        ('price_include', '=', True),
                        ('company_id', 'in', [self.company_id.id, self.env.company.id]),
                    ], limit=1)
                    _tax_cache[vat_rate] = tax
                include_tax = _tax_cache[vat_rate]
                if include_tax and tax_field:
                    ol_vals[tax_field] = [(6, 0, [include_tax.id])]
                else:
                    # KDV dahil vergi bulunamadı — price_unit'i KDV Hariç tutara dönüştür
                    ol_vals['price_unit'] = unit_price_incl / (1.0 + (vat_rate / 100.0))
                    _logger.info(
                        "Amazon: %%%s KDV dahil vergi bulunamadı, birim fiyat KDV hariç (%s) olarak ayarlandı.",
                        vat_rate, ol_vals['price_unit']
                    )

            order_lines.append((0, 0, ol_vals))

        return order_lines

    @api.private
    def _process_single_order(self, order_data, session, auth, base_url, force_update=False):
        processed = 1
        created = 0
        failed = 0
        msgs = []
        
        amazon_order_id = order_data.get('AmazonOrderId')
        status = order_data.get('OrderStatus')
        
        # Odoo'da mevcut mu?
        existing_order = self.env['sale.order'].search([
            ('client_order_ref', '=', str(amazon_order_id)),
            ('amazon_store_id', '=', self.id)
        ], limit=1)

        amazon_order_rec = self.env['amazon.order'].search([
            ('amazon_order_number', '=', str(amazon_order_id)),
            ('store_id', '=', self.id)
        ], limit=1)

        # Müşteri veya adres bilgisi eksik mi, yoksa statü Pending'den çıktı mı?
        is_missing_pii = False
        if amazon_order_rec:
            if not amazon_order_rec.shipping_address or not amazon_order_rec.customer_email or amazon_order_rec.customer_name in ('', 'Amazon Müşterisi'):
                is_missing_pii = True
            if amazon_order_rec.order_status == 'Pending' and status != 'Pending':
                is_missing_pii = True

        # ─── İptal: Amazon'da iptal edilen sipariş Odoo'da da iptal edilir ───
        # İptal edilen siparişte Amazon kişisel veri vermez → PII/satır yenilemesine girilmez
        # (aksi halde her cron'da boş "Amazon Müşterisi" partner'ı oluşur).
        if existing_order and status == 'Canceled':
            self._cancel_amazon_sale_order(existing_order, amazon_order_rec, amazon_order_id)
            if amazon_order_rec and amazon_order_rec.order_status != status:
                amazon_order_rec.write({'order_status': status})
            return processed, 0, 0, msgs

        if existing_order and not force_update:
            partner_name = existing_order.partner_id.name if existing_order.partner_id else ''
            pii_missing = is_missing_pii or partner_name in ('', 'Amazon Müşterisi')

            # ─── KRİTİK: Draft sipariş + Pending olmayan durum = MUTLAKA onayla ───
            # Sipariş ilk geldiğinde Pending → draft bırakıldı. Cron tekrar çalıştığında
            # sipariş hâlâ draft ise picking oluşmamıştır → force_update ile onaylanır.
            if existing_order.state == 'draft' and status != 'Pending':
                force_update = True
                _logger.info(
                    "Amazon sipariş %s draft durumda ama statü '%s' — force_update ile onaylanacak.",
                    amazon_order_id, status)
            # Müşteri bilgisi eksik → yeniden çek. RDT alınamıyorsa her cron'da 5-6 istek
            # atmamak için aynı sipariş en fazla saatte bir denenir.
            elif pii_missing and status != 'Pending' and self._pii_retry_due(amazon_order_rec):
                force_update = True
            else:
                return processed, 0, 0, msgs

        # Canceled ise ve ERP'de yoksa alma
        if status == 'Canceled':
            return processed, 0, 0, msgs

        # Kişisel verisi temizlenmiş (saklama süresi dolmuş) sipariş yeniden doldurulmaz
        if amazon_order_rec and amazon_order_rec.pii_cleaned:
            return processed, 0, 0, msgs

        # ─── PENDING SİPARİŞ: API çağrıları yapmadan atla ───
        # Amazon, Pending siparişlerde PII vermez (ad, adres, telefon boş gelir).
        # GetOrders API'de OrderStatuses filtresi Pending'i zaten hariç tutar,
        # ama "Amazon'dan Bilgileri Yenile" butonu veya force_update ile
        # Pending sipariş buraya ulaşabilir → boşuna API çağrısı yapma.
        if status == 'Pending' and not existing_order:
            _logger.info(
                "Amazon sipariş %s Pending — PII mevcut değil, atlanıyor. "
                "Unshipped olduğunda otomatik işlenecek.",
                amazon_order_id)
            return processed, 0, 0, msgs

        # ─── PII (Adres ve Müşteri) Detaylarını Çek ───
        # Amazon SP-API PII verilerine erişim için Restricted Data Token (RDT) gerektirir.
        # RDT olmadan ShippingAddress ve BuyerInfo alanları BOŞ döner.
        buyer_info = dict(order_data.get('BuyerInfo') or {})
        shipping_address = dict(order_data.get('ShippingAddress') or {})

        # PII eksikse RDT al ve yeniden çek
        needs_pii = (
            not shipping_address or not shipping_address.get('Name')
            or not shipping_address.get('AddressLine1')
            or not buyer_info or not buyer_info.get('BuyerName')
        )
        rdt = None
        if needs_pii:
            rdt = self._get_restricted_data_token(session, auth, base_url, amazon_order_id)
            if rdt:
                _logger.info(
                    "Amazon PII için RDT alındı, adres/alıcı bilgisi çekiliyor: %s",
                    amazon_order_id)
            else:
                _logger.warning(
                    "Amazon RDT alınamadı — PII eksik kalacak: %s "
                    "(SP-API 'Direct-to-Consumer Shipping' rolü kontrol edin)",
                    amazon_order_id)

        if not shipping_address or not shipping_address.get('Name') or not shipping_address.get('AddressLine1'):
            fetched_address = self._fetch_order_address(
                amazon_order_id, session, auth, base_url, rdt=rdt)
            if fetched_address:
                shipping_address.update(fetched_address)

        if not buyer_info or not buyer_info.get('BuyerName') or not buyer_info.get('BuyerEmail'):
            fetched_buyer = self._fetch_order_buyer_info(
                amazon_order_id, session, auth, base_url, rdt=rdt)
            if fetched_buyer:
                buyer_info.update(fetched_buyer)

        # Müşteri Ad Soyad Tespiti: ShippingAddress.Name teslimat alıcısının tam adıdır (örn: "özgür karter").
        # BuyerInfo.BuyerName ise Amazon tarafından bazen sadece soyad (örn: "Karter") olarak verilebilir.
        buyer_name = shipping_address.get('Name') or buyer_info.get('BuyerName') or 'Amazon Müşterisi'
        
        # Müşteri Yarat / Güncelle — mevcut siparişte PII hâlâ gelmediyse partner'a dokunma
        # (her denemede yeni boş "Amazon Müşterisi" kaydı açılmasın)
        has_pii = buyer_name != 'Amazon Müşterisi' or bool(shipping_address.get('AddressLine1'))
        if existing_order and not has_pii:
            partner = existing_order.partner_id
        else:
            partner = self._get_or_create_partner(buyer_name, buyer_info, shipping_address)
        
        # Order Items'ları çek
        items_val = self._fetch_order_items(amazon_order_id, session, auth, base_url)
        if items_val is None:
            items_val = []

        # Raw JSON payload hazırlığı
        raw_data = {
            'Order': order_data,
            'BuyerInfo': buyer_info,
            'ShippingAddress': shipping_address,
            'OrderItems': items_val,
        }
        raw_json_str = json.dumps(raw_data, ensure_ascii=False, indent=2)

        total_order_amount = float(order_data.get('OrderTotal', {}).get('Amount', 0.0))

        # ─── amazon.order Kaydını Oluştur veya Güncelle ───
        amazon_order = self.env['amazon.order'].search([
            ('amazon_order_number', '=', str(amazon_order_id))
        ], limit=1)

        # Tarih dönüşümü
        order_date_raw = order_data.get('PurchaseDate')
        order_date = fields.Datetime.now()
        if order_date_raw:
            try:
                order_date = date_parser.parse(order_date_raw).replace(tzinfo=None)
            except Exception:
                order_date = fields.Datetime.now()

        amz_line_vals = []
        for item in items_val:
            amz_line_vals.append((0, 0, {
                'order_item_id': item.get('OrderItemId', ''),
                'sku': item.get('SellerSKU', ''),
                'asin': item.get('ASIN', ''),
                'product_name': item.get('Title', ''),
                'quantity': item.get('QuantityOrdered', 1),
                'price': float(item.get('ItemPrice', {}).get('Amount', 0.0)),
                'item_tax': float(item.get('ItemTax', {}).get('Amount', 0.0)),
            }))

        # ─── EasyShip Kargo Takip Kodu Çekimi ───
        easyship_tracking = ''
        easyship_status = order_data.get('EasyShipShipmentStatus', '')
        if status in ('Shipped', 'Unshipped') or easyship_status:
            easyship_tracking = self._fetch_easyship_tracking(
                amazon_order_id, session, auth, base_url
            )

        # Kargo takip: EasyShip tracking > Amazon Order ID fallback
        cargo_tracking = easyship_tracking or str(amazon_order_id)

        amz_order_vals = {
            'amazon_order_number': str(amazon_order_id),
            'store_id': self.id,
            'order_date': order_date,
            'order_status': status,
            'fulfillment_channel': order_data.get('FulfillmentChannel', 'MFN'),
            'customer_name': buyer_name,
            'customer_email': buyer_info.get('BuyerEmail', ''),
            'customer_phone': shipping_address.get('Phone', ''),
            'shipping_address': partner.street or shipping_address.get('AddressLine1', ''),
            'shipping_city': shipping_address.get('City', ''),
            'shipping_district': shipping_address.get('Municipality', '') or shipping_address.get('County', '') or shipping_address.get('StateOrRegion', ''),
            'postal_code': shipping_address.get('PostalCode', ''),
            'cargo_provider': 'MNGTR',
            'cargo_tracking_number': cargo_tracking,
            'easyship_tracking_id': easyship_tracking,
            'total_price': total_order_amount,
            'currency': order_data.get('OrderTotal', {}).get('CurrencyCode', 'TRY'),
            'raw_payload': raw_json_str,
        }

        if amazon_order:
            amazon_order.line_ids.unlink()
            amz_order_vals['line_ids'] = amz_line_vals
            amazon_order.write(amz_order_vals)
        else:
            amz_order_vals['line_ids'] = amz_line_vals
            amazon_order = self.env['amazon.order'].create(amz_order_vals)

        # Batch ürün arama
        Product = self.env['product.product'].sudo()
        all_skus = [item.get('SellerSKU') for item in items_val if item.get('SellerSKU')]
        product_map = Product.batch_find_by_marketplace_barcodes(all_skus) if all_skus else {}

        # Mevcut sipariş güncelleniyorsa partner, amazon_order ve fiyatları tazele
        if existing_order:
            old_partner_name = existing_order.partner_id.name if existing_order.partner_id else ''
            existing_order.sudo().write({
                'partner_id': partner.id,
                'partner_invoice_id': partner.id,
                'partner_shipping_id': partner.id,
                'amazon_order_id': amazon_order.id,
                'amazon_store_id': self.id,
            })
            amazon_order.write({'sale_order_id': existing_order.id})

            # ─── PII Güncelleme: Picking'lerdeki müşteri bilgisini de güncelle ───
            # Sipariş Pending→Unshipped geçişinde müşteri bilgisi gelir.
            # Picking'lerin partner_id'si de güncellenmeli ki toplama listesinde
            # "Amazon Müşterisi" yerine gerçek müşteri adı görünsün.
            if old_partner_name in ('', 'Amazon Müşterisi') and partner.name not in ('', 'Amazon Müşterisi'):
                _logger.info(
                    "Amazon PII güncellendi: %s → müşteri '%s' → '%s'",
                    amazon_order_id, old_partner_name, partner.name)
                for picking in existing_order.picking_ids:
                    if picking.state not in ('done', 'cancel'):
                        picking.sudo().write({'partner_id': partner.id})

            # Satırlar yalnızca TASLAK siparişte yeniden kurulur. Odoo onaylı siparişte satır
            # silmeye izin vermez (UserError) — eskiden tutar tutmayınca her cron'da hata alınıyordu.
            if items_val and existing_order.state in ('draft', 'sent'):
                new_lines = self._prepare_sale_order_lines(
                    items_val, product_map, amazon_order_id, msgs,
                    session=session, auth=auth, base_url=base_url)
                if new_lines:
                    existing_order.order_line.sudo().unlink()
                    existing_order.sudo().write({'order_line': new_lines})

            # ─── Draft sipariş → Onayla (Picking oluşması için) ───
            # Sipariş ilk geldiğinde Pending olmuş olabilir ve draft bırakılmış olabilir.
            # Artık tüm draft siparişler (Pending dahil) onaylanır → picking oluşur.
            if existing_order.state == 'draft' and status not in ('Pending', 'Canceled'):
                _logger.info(
                    "Amazon sipariş %s draft→onay geçişi: action_confirm çağrılıyor. Statü: %s, Kanal: %s",
                    amazon_order_id, status, order_data.get('FulfillmentChannel', 'N/A')
                )
                existing_order.action_confirm()
                # ─── Picking debug logu ───
                if existing_order.picking_ids:
                    for p in existing_order.picking_ids:
                        _logger.info(
                            "Amazon picking (force): %s | state=%s | type=%s (id:%d) | "
                            "wh=%s | batch=%s | create=%s | Sipariş: %s",
                            p.name, p.state,
                            p.picking_type_id.display_name, p.picking_type_id.id,
                            p.picking_type_id.warehouse_id.name if p.picking_type_id.warehouse_id else 'N/A',
                            p.batch_id.name if p.batch_id else 'YOK',
                            p.create_date, amazon_order_id)
                else:
                    _logger.warning(
                        "Amazon sipariş %s (force) onaylandı ama picking OLUŞMADI! "
                        "Kanal: %s | Satır ürünleri: %s",
                        amazon_order_id,
                        order_data.get('FulfillmentChannel', 'N/A'),
                        [(l.product_id.display_name, l.product_id.type, l.product_id.id)
                         for l in existing_order.order_line if l.product_id])

            return processed, 0, 0, msgs

        # ─── Odoo Siparişi Oluştur (Sadece Unshipped/Shipped) ───
        if not items_val:
            return processed, 0, 1, [f"{amazon_order_id} ürün detayları alınamadı, atlandı."]

        order_lines = self._prepare_sale_order_lines(
            items_val, product_map, amazon_order_id, msgs,
            session=session, auth=auth, base_url=base_url)
        if not order_lines:
            return processed, 0, 1, [f"{amazon_order_id} hiçbir ürün eşleştirilemedi, sipariş oluşturulmadı."]

        sale_order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
            'date_order': order_date,
            'client_order_ref': amazon_order_id,
            'amazon_store_id': self.id,
            'amazon_order_id': amazon_order.id,
            'warehouse_id': self.default_warehouse_id.id,
            'pricelist_id': self.default_pricelist_id.id if self.default_pricelist_id else False,
            'order_line': order_lines,
        })

        amazon_order.write({'sale_order_id': sale_order.id})

        # ─── Sipariş Onaylama (Picking Oluşturma) ───
        # Sadece Unshipped/Shipped siparişler buraya ulaşır (Pending yukarıda filtrelendi).
        # Bu noktada PII mevcut → müşteri bilgisi doğru → onaylanabilir.
        if status != 'Canceled':
            sale_order.action_confirm()
            # ─── Picking debug logu ───
            if sale_order.picking_ids:
                for p in sale_order.picking_ids:
                    _logger.info(
                        "Amazon picking oluştu: %s | state=%s | type=%s (id:%d) | "
                        "wh=%s | batch=%s | create=%s | Sipariş: %s | Kanal: %s | Müşteri: %s",
                        p.name, p.state,
                        p.picking_type_id.display_name, p.picking_type_id.id,
                        p.picking_type_id.warehouse_id.name if p.picking_type_id.warehouse_id else 'N/A',
                        p.batch_id.name if p.batch_id else 'YOK',
                        p.create_date, amazon_order_id,
                        order_data.get('FulfillmentChannel', 'N/A'),
                        partner.name)
            else:
                _logger.warning(
                    "Amazon sipariş %s onaylandı ama picking OLUŞMADI! "
                    "Kanal: %s | Satır ürünleri: %s",
                    amazon_order_id,
                    order_data.get('FulfillmentChannel', 'N/A'),
                    [(l.product_id.display_name, l.product_id.type, l.product_id.id)
                     for l in sale_order.order_line if l.product_id])
        else:
            _logger.info(
                "Amazon sipariş %s Canceled durumunda — onaylanmıyor.",
                amazon_order_id
            )

        created = 1
        return processed, created, failed, msgs

    @api.private
    def _fetch_easyship_tracking(self, amazon_order_id, session, auth, base_url):
        """Amazon EasyShip API'den gerçek kargo takip kodunu çeker (örn: ZA8156127).
        
        Endpoint: GET /easyShip/2022-03-23/package
        Bu endpoint 'Direct-to-Consumer Shipping' rolü gerektirir.
        Başarısız olursa boş string döner ve fallback olarak Amazon Order ID kullanılır.
        """
        endpoint = f"{base_url}/easyShip/2022-03-23/package"
        params = {
            'amazonOrderId': amazon_order_id,
            'marketplaceId': self.marketplace_id,
        }
        try:
            res = session.get(endpoint, auth=auth, params=params, timeout=20)
            if res.status_code == 200:
                payload = res.json().get('payload', {}) or res.json()
                # trackingDetails.trackingId formatı
                tracking_details = payload.get('trackingDetails', {})
                tracking_id = tracking_details.get('trackingId', '')
                if tracking_id:
                    _logger.info(
                        "Amazon EasyShip tracking çekildi: %s → %s",
                        amazon_order_id, tracking_id
                    )
                    return tracking_id
                # Alternatif response yapısı: scheduledPackageId altında olabilir
                packages = payload.get('packages', [])
                if packages:
                    for pkg in packages:
                        tid = (pkg.get('trackingDetails', {}) or {}).get('trackingId', '')
                        if tid:
                            _logger.info(
                                "Amazon EasyShip tracking (packages) çekildi: %s → %s",
                                amazon_order_id, tid
                            )
                            return tid
            elif res.status_code == 403:
                _logger.warning(
                    "Amazon EasyShip API 403 Forbidden (%s) — 'Direct-to-Consumer Shipping' rolü kontrol edin.",
                    amazon_order_id
                )
            elif res.status_code == 404:
                _logger.info(
                    "Amazon EasyShip paketi bulunamadı (%s) — sipariş henüz zamanlanmamış olabilir.",
                    amazon_order_id
                )
            else:
                _logger.warning(
                    "Amazon EasyShip API HTTP %s (%s): %s",
                    res.status_code, amazon_order_id, res.text[:500]
                )
        except Exception as e:
            _logger.error("Amazon EasyShip fetch hatası (%s): %s", amazon_order_id, e)
        return ''

    @api.private
    def _fetch_order_address(self, amazon_order_id, session, auth, base_url, rdt=None):
        """Sipariş teslimat adresini çeker. RDT (Restricted Data Token) gerektirir.

        RDT olmadan Amazon boş yanıt döner (PII koruması).
        """
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/address"
        try:
            # RDT varsa header'a ekle (LWA token yerine)
            headers = {}
            if rdt:
                headers['x-amz-access-token'] = rdt

            res = session.get(endpoint, auth=auth, headers=headers, timeout=20)
            if res.status_code == 200:
                address = res.json().get('payload', {}).get('ShippingAddress', {})
                if address and address.get('Name'):
                    _logger.info(
                        "Amazon adres bilgisi alındı: %s → %s (%s)",
                        amazon_order_id, address.get('Name', '?'), address.get('City', '?'))
                else:
                    _logger.info(
                        "Amazon adres yanıtı boş (Pending olabilir): %s | RDT: %s",
                        amazon_order_id, 'Var' if rdt else 'YOK')
                return address
            elif res.status_code == 403:
                _logger.error(
                    "Amazon Address API 403 Forbidden (%s) — "
                    "RDT: %s | SP-API 'Direct-to-Consumer Shipping' rolü kontrol edin. "
                    "Yanıt: %s",
                    amazon_order_id, 'Var' if rdt else 'YOK', res.text[:200])
            else:
                _logger.warning(
                    "Amazon Address API HTTP %s (%s): %s",
                    res.status_code, amazon_order_id, res.text[:200])
        except Exception as e:
            _logger.error("Amazon Address fetch hatası (%s): %s", amazon_order_id, e)
        return {}

    @api.private
    def _fetch_order_buyer_info(self, amazon_order_id, session, auth, base_url, rdt=None):
        """Alıcı bilgilerini çeker. RDT (Restricted Data Token) gerektirir.

        RDT olmadan Amazon boş yanıt döner (PII koruması).
        """
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/buyerInfo"
        try:
            headers = {}
            if rdt:
                headers['x-amz-access-token'] = rdt

            res = session.get(endpoint, auth=auth, headers=headers, timeout=20)
            if res.status_code == 200:
                buyer = res.json().get('payload', {})
                if buyer and (buyer.get('BuyerName') or buyer.get('BuyerEmail')):
                    _logger.info(
                        "Amazon alıcı bilgisi alındı: %s → %s",
                        amazon_order_id, buyer.get('BuyerName', '?'))
                else:
                    _logger.info(
                        "Amazon alıcı yanıtı boş (Pending olabilir): %s | RDT: %s",
                        amazon_order_id, 'Var' if rdt else 'YOK')
                return buyer
            elif res.status_code == 403:
                _logger.error(
                    "Amazon BuyerInfo API 403 Forbidden (%s) — "
                    "RDT: %s | SP-API 'Direct-to-Consumer Shipping' rolü kontrol edin. "
                    "Yanıt: %s",
                    amazon_order_id, 'Var' if rdt else 'YOK', res.text[:200])
            else:
                _logger.warning(
                    "Amazon BuyerInfo API HTTP %s (%s): %s",
                    res.status_code, amazon_order_id, res.text[:200])
        except Exception as e:
            _logger.error("Amazon BuyerInfo fetch hatası (%s): %s", amazon_order_id, e)
        return {}

    @api.private
    def _resolve_country_state(self, country_code, city_name):
        """Ülke ve İl (res.country.state) nesnesini çözer."""
        code = (country_code or 'TR').upper()
        country = self.env['res.country'].sudo().search([('code', '=', code)], limit=1)
        state_id = False
        if country and city_name and country.code == 'TR':
            search_city = city_name.strip()
            if search_city.upper() in ('MERSIN', 'MERSİN'):
                search_city = 'İçel'
            state = self.env['res.country.state'].sudo().search([
                ('country_id', '=', country.id),
                ('name', '=ilike', search_city)
            ], limit=1)
            if not state and search_city == 'İçel':
                state = self.env['res.country.state'].sudo().search([
                    ('country_id', '=', country.id),
                    ('name', '=ilike', 'Mersin')
                ], limit=1)
            if state:
                state_id = state.id
        return country, state_id

    @api.private
    def _get_or_create_partner(self, name, buyer_info, address_info):
        ResPartner = self.env['res.partner'].sudo()
        email = buyer_info.get('BuyerEmail', '')
        phone = address_info.get('Phone', '')

        country_code = address_info.get('CountryCode', 'TR') or 'TR'
        amazon_city = address_info.get('City', '')  # İl (örn: "izmir")
        amazon_district = address_info.get('Municipality', '')  # İlçe (örn: "karşıyaka")
        amazon_county = address_info.get('County', '') or address_info.get('StateOrRegion', '')  # Mahalle (örn: "Aksoy mah.")

        country, state_id = self._resolve_country_state(country_code, amazon_city)

        # İlçe (city): Municipality öncelikli, yoksa County, yoksa amazon_city
        district_name = amazon_district or amazon_county or amazon_city

        # Açık adres: AddressLine1 + AddressLine2 + Mahalle
        street_parts = []
        if address_info.get('AddressLine1') and address_info.get('AddressLine1') != 'null':
            street_parts.append(address_info.get('AddressLine1').strip())
        if address_info.get('AddressLine2') and address_info.get('AddressLine2') != 'null':
            street_parts.append(address_info.get('AddressLine2').strip())
        if amazon_county and amazon_county != amazon_district and amazon_county != amazon_city:
            street_parts.append(amazon_county.strip())
        
        street = ' '.join(street_parts).strip()

        # Eşleşme: Amazon alıcı e-postası (alıcıya özel, maskeli adres) veya aynı isim + aynı ilçe.
        # Yalnız isim/telefonla eşleştirme başka bir müşterinin/tedarikçinin kartını ezebiliyordu.
        top = [('parent_id', '=', False)]
        partner = False
        if email and '@' in email:
            partner = ResPartner.search(top + [('email', '=ilike', email)], limit=1)
        if not partner and name and name != 'Amazon Müşterisi' and district_name:
            partner = ResPartner.search(top + [
                ('name', '=ilike', name), ('city', '=ilike', district_name),
            ], limit=1)

        vals = {
            'name': name if name else 'Amazon Müşterisi',
            'email': email or '',
            'phone': phone or '',
            'city': district_name or '',
            'street': street or '',
            'zip': address_info.get('PostalCode', ''),
            'country_id': country.id if country else False,
            'state_id': state_id if state_id else False,
            'customer_rank': 1,
        }

        if partner:
            # Boş gelen alanlar mevcut bilgiyi silmesin; ad yalnızca daha tam ise değişsin
            update_vals = {k: v for k, v in vals.items() if v and k not in ('name', 'customer_rank')}
            if name and name != 'Amazon Müşterisi':
                if partner.name == 'Amazon Müşterisi' or len(name.split()) > len((partner.name or '').split()):
                    update_vals['name'] = name
            if update_vals:
                partner.write(update_vals)
        else:
            partner = ResPartner.create(vals)

        return partner

    @api.private
    def _fetch_order_items(self, amazon_order_id, session, auth, base_url):
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/orderItems"
        try:
            res = session.get(endpoint, auth=auth, timeout=20)
            if res.status_code == 200:
                return res.json().get('payload', {}).get('OrderItems', [])
        except Exception as e:
            _logger.error("Amazon OrderItems fetch hatası (%s): %s", amazon_order_id, e)
        return None

    @api.private
    def _fetch_catalog_ean(self, asin, session, auth, base_url):
        """ASIN ile Amazon Catalog Items API'den EAN/UPC barkodu çeker.

        Endpoint: GET /catalog/2022-04-01/items/{asin}
        Params: marketplaceIds, includedData=identifiers
        Gereksinim: SP-API uygulamasında 'Product Listing' rolü aktif olmalı.

        Döndürür: EAN/UPC string veya boş string.
        """
        marketplace_id = self.marketplace_id or 'A33AVAJ2PDY3EV'
        endpoint = f"{base_url}/catalog/2022-04-01/items/{asin}"
        params = {
            'marketplaceIds': marketplace_id,
            'includedData': 'identifiers',
        }
        try:
            res = session.get(endpoint, auth=auth, params=params, timeout=20)
            if res.status_code == 200:
                data = res.json()
                # identifiers → [{marketplaceId, identifiers: [{identifierType, identifier}]}]
                for marketplace in data.get('identifiers', []):
                    for ident in marketplace.get('identifiers', []):
                        id_type = ident.get('identifierType', '').upper()
                        id_val = ident.get('identifier', '').strip()
                        if id_type in ('EAN', 'UPC', 'GTIN') and id_val:
                            _logger.info(
                                "Amazon Catalog: ASIN %s → %s: %s",
                                asin, id_type, id_val)
                            return id_val
                _logger.info(
                    "Amazon Catalog: ASIN %s için EAN/UPC bulunamadı.",
                    asin)
            elif res.status_code == 403:
                _logger.warning(
                    "Amazon Catalog API 403 — 'Product Listing' rolü aktif olmayabilir.")
            else:
                _logger.warning(
                    "Amazon Catalog API hatası ASIN %s: HTTP %s",
                    asin, res.status_code)
        except Exception as e:
            _logger.error("Amazon Catalog API fetch hatası (ASIN %s): %s", asin, e)
        return ''

    # ─── Yardımcılar ─────────────────────────────────────────

    @api.private
    def _build_session(self):
        """LWA token'lı requests oturumu + (varsa) AWS imzası ve endpoint."""
        self.ensure_one()
        session = requests.Session()
        session.headers.update({
            'x-amz-access-token': self.generate_access_token(),
            'User-Agent': 'OdooUgurlar/1.0',
            'Content-Type': 'application/json'
        })
        return session, self._get_aws_auth(), self.get_api_endpoint()

    @api.model
    def _pii_retry_due(self, amazon_order_rec):
        """Müşteri bilgisi eksik sipariş yeniden çekilmeli mi? (saatte en fazla bir deneme)"""
        if not amazon_order_rec:
            return True
        if amazon_order_rec.pii_cleaned:
            return False
        last = amazon_order_rec.write_date
        return not last or last < fields.Datetime.now() - timedelta(hours=1)

    @api.model
    def _cancel_blocker(self, so):
        """Otomatik iptali engelleyen durum (sevk edilmiş / faturası kesilmiş) — yoksa False."""
        if so.picking_ids.filtered(lambda p: p.state == 'done'):
            return 'sevk edildiği'
        if so.invoice_ids.filtered(lambda m: m.state == 'posted'):
            return 'faturası kesildiği'
        return False

    @api.private
    def _cancel_amazon_sale_order(self, so, amazon_order_rec, amazon_order_id):
        """Amazon'da iptal edilen siparişi Odoo'da iptal eder.

        Sevk edilmiş / faturası kesilmiş siparişe dokunulmaz, chatter'a bir kez uyarı yazılır.
        _action_cancel kullanılır: action_cancel kilitli (locked) siparişte UserError veriyor;
        Nebim silme kancası (odoougurlar) _action_cancel üzerinde olduğu için o da çalışır.
        """
        if so.state == 'cancel':
            return
        blocker = self._cancel_blocker(so)
        if blocker:
            msg = (f"Amazon siparişi {amazon_order_id} iptal edildi ancak {so.name} {blocker} "
                   f"için otomatik iptal edilmedi; elle kontrol edin.")
            if not amazon_order_rec or amazon_order_rec.error_message != msg:
                if amazon_order_rec:
                    amazon_order_rec.error_message = msg
                so.message_post(body=msg)
                _logger.warning(msg)
            return
        try:
            with self.env.cr.savepoint():
                so.sudo()._action_cancel()
            so.message_post(body=f"Amazon siparişi {amazon_order_id} iptal edildiği için iptal edildi.")
            _logger.info("Amazon — Odoo sipariş iptal edildi: %s (%s)", so.name, amazon_order_id)
        except Exception as e:
            _logger.warning("Amazon — sipariş iptal hatası %s (%s): %s", so.name, amazon_order_id, e)

    # ─── Finans (Finances API v0) ────────────────────────────

    def action_sync_financials(self):
        self.ensure_one()
        res = self._sync_financials()
        msg = (f"{res['queried']} sipariş sorgulandı.\nYeni işlem: {res['created']}\n"
               f"Güncellenen: {res['updated']}")
        if res['errors']:
            msg += f"\nSorgulanamayan: {len(res['errors'])}\n" + '\n'.join(res['errors'][:5])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Amazon Finansal Senkronizasyon'),
                'message': msg,
                'type': 'warning' if res['errors'] else 'success',
                'sticky': bool(res['errors']),
            }
        }

    @api.private
    def _sync_financials(self, limit=25):
        """Kargolanmış siparişlerin finans olaylarını (komisyon, kesinti, iade) sipariş bazında çeker.

        GET /finances/v0/orders/{orderId}/financialEvents — rate 0.5/sn, burst 30. Son 48 saatin
        siparişleri henüz finans olayına düşmemiş olabilir. Her sipariş günde en fazla bir kez sorgulanır,
        her çalışmada en fazla `limit` sipariş (burst sınırının altında).
        """
        self.ensure_one()
        result = {'queried': 0, 'created': 0, 'updated': 0, 'errors': []}
        now = fields.Datetime.now()
        orders = self.env['amazon.order'].search([
            ('store_id', '=', self.id),
            ('order_status', 'in', ['Shipped', 'PartiallyShipped']),
            ('order_date', '>=', now - timedelta(days=self.financial_day_range or 30)),
            ('order_date', '<=', now - timedelta(hours=48)),
            '|', ('finance_checked_at', '=', False),
            ('finance_checked_at', '<', now - timedelta(days=1)),
        ], order='order_date desc', limit=limit)
        if not orders:
            return result

        session, auth, base_url = self._build_session()
        Event = self.env['amazon.finance.event']
        for order in orders:
            endpoint = f"{base_url}/finances/v0/orders/{order.amazon_order_number}/financialEvents"
            params = {'MaxResultsPerPage': 100}
            status_code = 0
            error = None
            while True:
                try:
                    res = session.get(endpoint, auth=auth, params=params, timeout=30)
                except requests.RequestException as e:
                    error = str(e)
                    break
                status_code = res.status_code
                if status_code != 200:
                    error = f"HTTP {status_code} {res.text[:150]}"
                    break
                payload = res.json().get('payload') or {}
                created, updated = Event._upsert_from_payload(self, order, payload.get('FinancialEvents') or {})
                result['created'] += created
                result['updated'] += updated
                next_token = payload.get('NextToken')
                if not next_token:
                    break
                params = {'MaxResultsPerPage': 100, 'NextToken': next_token}
            result['queried'] += 1
            if error:
                result['errors'].append(f"{order.amazon_order_number}: {error}")
                _logger.warning("Amazon finans %s sorgulanamadı: %s", order.amazon_order_number, error)
                # 429 (kota) / 401-403 (yetki) → bu çalışmayı bitir, sonraki cron'da devam
                if status_code in (401, 403, 429):
                    break
                continue
            order.write({'finance_checked_at': now})

        self.write({'last_financial_sync': now})
        _logger.info("Amazon finans [%s]: %d sipariş, %d yeni, %d güncellenen, %d hata",
                     self.name, result['queried'], result['created'], result['updated'], len(result['errors']))
        return result

    # ─── Kişisel Veri Temizliği (Amazon DPP) ─────────────────

    @api.model
    def _mask_name(self, name):
        return ' '.join(f"{part[0]}***" for part in (name or '').split()) or False

    @api.model
    def cron_amazon_pii_cleanup(self):
        """Saklama süresi dolan amazon.order kayıtlarındaki kişisel verileri temizler.

        Yalnızca 'Kişisel Verileri Otomatik Temizle' açık mağazalar. Süre sipariş tarihinden sayılır ve
        sipariş çekme aralığından kısa olamaz (temizlenen veri cron'da tekrar çekilmesin).
        Odoo satış siparişi / müşteri kartı / fatura yasal saklama zorunluluğu nedeniyle değişmez.
        """
        AmazonOrder = self.env['amazon.order']
        for store in self.search([('pii_cleanup_enabled', '=', True)]):
            days = max(store.pii_retention_days or 30, (store.order_day_range or 14) + 1)
            orders = AmazonOrder.search([
                ('store_id', '=', store.id),
                ('pii_cleaned', '=', False),
                ('order_status', 'in', ['Shipped', 'Canceled']),
                ('order_date', '<', fields.Datetime.now() - timedelta(days=days)),
            ], limit=500)
            for order in orders:
                raw = order.raw_payload
                if raw:
                    try:
                        data = json.loads(raw)
                        for key in ('BuyerInfo', 'ShippingAddress'):
                            data.pop(key, None)
                            if isinstance(data.get('Order'), dict):
                                data['Order'].pop(key, None)
                        raw = json.dumps(data, ensure_ascii=False, indent=2)
                    except (ValueError, TypeError, AttributeError):
                        raw = False
                order.write({
                    'customer_name': self._mask_name(order.customer_name),
                    'customer_email': False,
                    'customer_phone': False,
                    'shipping_address': False,
                    'postal_code': False,
                    'raw_payload': raw,
                    'pii_cleaned': True,
                })
            if orders:
                _logger.info("Amazon [%s]: %d siparişin kişisel verisi temizlendi (>%d gün).",
                             store.name, len(orders), days)


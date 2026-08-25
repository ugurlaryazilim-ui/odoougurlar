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
        except Exception as e:
            _logger.exception("Amazon cron senkronizasyon hatası: %s", e)

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
        """Amazon'dan tek bir siparişi ve müşteri detaylarını yenile."""
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

        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}"
        res = session.get(endpoint, auth=auth, timeout=20)
        if res.status_code != 200:
            raise UserError(_("Amazon sipariş bilgisi alınamadı (HTTP %s): %s") % (res.status_code, res.text))

        order_data = res.json().get('payload', {})
        self._process_single_order(order_data, session, auth, base_url, force_update=True)

    @api.private
    def _prepare_sale_order_lines(self, items_val, product_map, amazon_order_id, msgs):
        """Odoo Sale Order satırlarını KDV DAHİL tutar esasına göre hazırlar.

        Amazon fiyatları KDV DAHİL (price_include=True) fiyattır.
        Odoo varsayılan vergisi KDV HARIÇ ise, Odoo üzerine tekrar KDV ekleyecektir.
        Bunu önlemek için price_include=True olan vergi aranır, bulunamazsa birim fiyat
        KDV Hariç tutara çevrilerek yazılır. Böylece Genel Toplam Amazon ile birebir tutar.
        """
        order_lines = []
        _tax_cache = {}

        for item in items_val:
            sku = item.get('SellerSKU')
            qty = float(item.get('QuantityOrdered', 1))
            item_price = float(item.get('ItemPrice', {}).get('Amount', 0.0))
            item_tax = float(item.get('ItemTax', {}).get('Amount', 0.0))

            product = product_map.get(sku)
            if not product and sku:
                # Batch'te bulunamadı, tek tek dene (fallback — Trendyol ile aynı mantık)
                Product = self.env['product.product'].sudo()
                if hasattr(Product, 'find_by_marketplace_barcode'):
                    product = Product.find_by_marketplace_barcode(sku)
            if not product:
                msgs.append(f"{amazon_order_id} siparişinde {sku} SKU'lu ürün Odoo'da bulunamadı — ürünsüz satır oluşturuluyor.")
                _logger.warning("Amazon ürün bulunamadı: %s (Sipariş: %s) — satır ürünsüz oluşturulacak.", sku, amazon_order_id)

            unit_price_incl = item_price / qty if qty > 0 else item_price

            ol_vals = {
                'product_uom_qty': qty,
                'price_unit': unit_price_incl,
                'name': item.get('Title', sku or 'Amazon Ürünü'),
            }
            if product:
                ol_vals['product_id'] = product.id

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
                if include_tax:
                    ol_vals['tax_id'] = [(6, 0, [include_tax.id])]
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

        # İptal durumu kontrolü
        if existing_order and not force_update:
            if existing_order.state not in ['done', 'cancel']:
                if status == 'Canceled' and existing_order.state != 'cancel':
                    existing_order.action_cancel()
            
            total_order_amount = float(order_data.get('OrderTotal', {}).get('Amount', 0.0))
            partner_name = existing_order.partner_id.name if existing_order.partner_id else ''

            # Müşteri bilgisi eksikse, statü Pending'den çıktıysa veya fiyat tutmuyorsa güncellemeyi zorla
            if is_missing_pii or partner_name in ('', 'Amazon Müşterisi') or \
               (total_order_amount > 0 and abs(existing_order.amount_total - total_order_amount) > 0.01):
                force_update = True
            else:
                return processed, 0, 0, msgs

        # Canceled ise ve ERP'de yoksa alma
        if status == 'Canceled' and not existing_order:
            return processed, 0, 0, msgs

        # ─── PII (Adres ve Müşteri) Detaylarını Çek ───
        buyer_info = dict(order_data.get('BuyerInfo') or {})
        shipping_address = dict(order_data.get('ShippingAddress') or {})
        
        if not shipping_address or not shipping_address.get('Name') or not shipping_address.get('AddressLine1'):
            fetched_address = self._fetch_order_address(amazon_order_id, session, auth, base_url)
            if fetched_address:
                shipping_address.update(fetched_address)

        if not buyer_info or not buyer_info.get('BuyerName') or not buyer_info.get('BuyerEmail'):
            fetched_buyer = self._fetch_order_buyer_info(amazon_order_id, session, auth, base_url)
            if fetched_buyer:
                buyer_info.update(fetched_buyer)

        # Müşteri Ad Soyad Tespiti: ShippingAddress.Name teslimat alıcısının tam adıdır (örn: "özgür karter").
        # BuyerInfo.BuyerName ise Amazon tarafından bazen sadece soyad (örn: "Karter") olarak verilebilir.
        buyer_name = shipping_address.get('Name') or buyer_info.get('BuyerName') or 'Amazon Müşterisi'
        
        # Müşteri Yarat / Güncelle
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
            existing_order.sudo().write({
                'partner_id': partner.id,
                'partner_invoice_id': partner.id,
                'partner_shipping_id': partner.id,
                'amazon_order_id': amazon_order.id,
                'amazon_store_id': self.id,
            })
            amazon_order.write({'sale_order_id': existing_order.id})

            # Fiyat ve KDV düzeltmesi (eğer tutar Amazon ile tutmuyorsa veya force_update ise)
            if items_val and (abs(existing_order.amount_total - total_order_amount) > 0.01 or force_update):
                new_lines = self._prepare_sale_order_lines(items_val, product_map, amazon_order_id, msgs)
                if new_lines:
                    existing_order.order_line.sudo().unlink()
                    existing_order.sudo().write({'order_line': new_lines})

            # ─── Pending→Unshipped/Shipped geçişi: Sipariş hâlâ draft ise onayla ───
            # Sipariş ilk geldiğinde Pending idi ve action_confirm yapılmadı.
            # Şimdi PII tamamlandı ve sipariş draft durumunda → onayla (Nebim'e de gider)
            if existing_order.state == 'draft' and status not in ('Pending', 'Canceled'):
                if order_data.get('FulfillmentChannel') == 'MFN':
                    _logger.info(
                        "Amazon sipariş %s Pending→%s geçişi: PII tamamlandı, action_confirm çağrılıyor.",
                        amazon_order_id, status
                    )
                    existing_order.action_confirm()

            return processed, 0, 0, msgs

        # ─── Odoo Siparişi Oluştur ───
        if not items_val:
            return processed, 0, 1, [f"{amazon_order_id} ürün detayları alınamadı, atlandı."]

        order_lines = self._prepare_sale_order_lines(items_val, product_map, amazon_order_id, msgs)
        if not order_lines:
            return processed, 0, 1, [f"{amazon_order_id} hiçbir ürün eşleştirilemedi, sipariş oluşturulmadı."]

        sale_order = self.env['sale.order'].create({
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
        
        # ─── Pending Sipariş → Onaylama ───
        # Pending siparişlerde PII yok → action_confirm YAPMA (Nebim'e yanlış bilgi gider)
        # Unshipped/Shipped siparişlerde PII mevcut → action_confirm YAP
        if order_data.get('FulfillmentChannel') == 'MFN' and status != 'Pending':
            sale_order.action_confirm()
        elif status == 'Pending':
            _logger.info(
                "Amazon sipariş %s Pending durumunda — draft olarak bırakılıyor (PII henüz mevcut değil).",
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
    def _fetch_order_address(self, amazon_order_id, session, auth, base_url):
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/address"
        try:
            res = session.get(endpoint, auth=auth, timeout=20)
            if res.status_code == 200:
                return res.json().get('payload', {}).get('ShippingAddress', {})
        except Exception as e:
            _logger.error("Amazon Address fetch hatası (%s): %s", amazon_order_id, e)
        return {}

    @api.private
    def _fetch_order_buyer_info(self, amazon_order_id, session, auth, base_url):
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/buyerInfo"
        try:
            res = session.get(endpoint, auth=auth, timeout=20)
            if res.status_code == 200:
                return res.json().get('payload', {})
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

        partner = False
        if email and email != 'Amazon Müşterisi':
            partner = ResPartner.search([('email', '=', email)], limit=1)
        if not partner and phone:
            partner = ResPartner.search([('phone', '=', phone)], limit=1)
        if not partner and name and name != 'Amazon Müşterisi':
            partner = ResPartner.search([('name', '=ilike', name)], limit=1)

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
            if name and name != 'Amazon Müşterisi':
                if partner.name == 'Amazon Müşterisi' or len(name.split()) > len((partner.name or '').split()):
                    vals['name'] = name
            partner.write(vals)
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

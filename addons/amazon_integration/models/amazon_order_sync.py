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
                    
                for order in orders:
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
            
    @api.private
    def _process_single_order(self, order_data, session, auth, base_url):
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
        
        if existing_order:
            if existing_order.state not in ['done', 'cancel']:
                if status == 'Canceled' and existing_order.state != 'cancel':
                    existing_order.action_cancel()
            return processed, 0, 0, msgs

        # Canceled ise ve ERP'de yoksa alma
        if status == 'Canceled':
            return processed, 0, 0, msgs

        buyer_info = order_data.get('BuyerInfo', {})
        shipping_address = order_data.get('ShippingAddress', {})
        
        buyer_name = buyer_info.get('BuyerName') or shipping_address.get('Name') or 'Amazon Müşterisi'
        
        # Müşteri Yarat/Bul
        partner = self._get_or_create_partner(buyer_name, buyer_info, shipping_address)
        
        # Order Items'ları çek (session ile — connection pooling)
        items_val = self._fetch_order_items(amazon_order_id, session, auth, base_url)
        if not items_val:
            return processed, 0, 1, [f"{amazon_order_id} ürün detayları alınamadı, atlandı."]

        # Batch ürün arama — N+1 önleme
        Product = self.env['product.product'].sudo()
        all_skus = [item.get('SellerSKU') for item in items_val if item.get('SellerSKU')]
        product_map = {}
        if all_skus:
            # default_code ile toplu arama
            products = Product.search([('default_code', 'in', all_skus)])
            for p in products:
                if p.default_code:
                    product_map[p.default_code] = p
            # barcode fallback
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

        order_lines = []
        for item in items_val:
            sku = item.get('SellerSKU')
            qty = item.get('QuantityOrdered', 1)
            item_price = item.get('ItemPrice', {}).get('Amount', '0.0')
            
            product = product_map.get(sku)
            if not product:
                # Ürün bulunamazsa loglayıp devam et — rastgele ürün atama TEHLİKELİ
                msgs.append(f"{amazon_order_id} siparişinde {sku} SKU'lu ürün Odoo'da BULUNAMADI. Satır atlandı.")
                _logger.warning("Amazon ürün bulunamadı: %s (Sipariş: %s)", sku, amazon_order_id)
                continue
            
            unit_price = float(item_price) / float(qty) if qty > 0 else float(item_price)
                    
            order_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'price_unit': unit_price,
                'name': item.get('Title', product.name)
            }))

        if not order_lines:
            return processed, 0, 1, [f"{amazon_order_id} hiçbir ürün eşleştirilemedi, sipariş oluşturulmadı."]

        # Tarih dönüşümü — tzinfo=None (False DEĞİL!)
        order_date_raw = order_data.get('PurchaseDate')
        order_date = fields.Datetime.now()
        if order_date_raw:
            try:
                order_date = date_parser.parse(order_date_raw).replace(tzinfo=None)
            except Exception:
                order_date = fields.Datetime.now()
        
        sale_order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
            'date_order': order_date,
            'client_order_ref': amazon_order_id,
            'amazon_store_id': self.id,
            'warehouse_id': self.default_warehouse_id.id,
            'pricelist_id': self.default_pricelist_id.id if self.default_pricelist_id else False,
            'order_line': order_lines,
        })
        
        # MFN (satıcı kargosu) ise otomatik onayla
        if order_data.get('FulfillmentChannel') == 'MFN':
            sale_order.action_confirm()

        created = 1
        return processed, created, failed, msgs

    @api.private
    def _get_or_create_partner(self, name, buyer_info, address_info):
        ResPartner = self.env['res.partner']
        email = buyer_info.get('BuyerEmail', '')
        phone = address_info.get('Phone', '')
        city = address_info.get('City', '')
        
        # Müşteri eşleştirme — önce email, sonra phone, sonra name
        partner = False
        if email:
            partner = ResPartner.search([('email', '=', email)], limit=1)
        if not partner and phone:
            partner = ResPartner.search([('phone', '=', phone)], limit=1)
        if not partner:
            partner = ResPartner.search([('name', '=ilike', name)], limit=1)
            
        if not partner:
            partner = ResPartner.create({
                'name': name,
                'email': email,
                'phone': phone,
                'city': city,
                'street': address_info.get('AddressLine1', ''),
                'street2': address_info.get('AddressLine2', ''),
                'zip': address_info.get('PostalCode', ''),
                'customer_rank': 1,
            })
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

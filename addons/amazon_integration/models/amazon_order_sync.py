from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import requests
import json
import logging
from dateutil import parser
import boto3
from urllib.parse import urlparse
try:
    from requests_auth_aws_sigv4 import AWSSigV4
except ImportError:
    AWSSigV4 = None

_logger = logging.getLogger(__name__)

class AmazonStore(models.Model):
    _inherit = 'amazon.store'

    def _get_aws_auth(self):
        """AWS IAM Credentials provided ise STS AssumeRole işlemi yaparak AWSSigV4 nesnesi döner."""
        if not self.aws_access_key or not self.aws_secret_key:
            return None
            
        region_map = {
            'eu': 'eu-west-1',
            'na': 'us-east-1',
            'fe': 'us-west-2'
        }
        aws_region = region_map.get(self.region, 'us-east-1')
        
        try:
            if self.aws_role_arn:
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
            _logger.error(f"AWS Auth Error: {e}")
            return None

    def action_sync_orders(self):
        self.ensure_one()
        sync_log = self.env['amazon.sync.log'].create({
            'store_id': self.id,
            'sync_type': 'order'
        })
        
        try:
            access_token = self.generate_access_token()
            headers = {
                'x-amz-access-token': access_token,
                'User-Agent': 'OdooUgurlar/1.0',
                'Content-Type': 'application/json'
            }
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
                response = requests.get(endpoint, headers=headers, auth=auth, params=params, timeout=30)
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
                        p, s, e, m = self._process_single_order(order, headers, auth, base_url)
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
                    'title': 'Senkronizasyon Başarılı',
                    'message': f"{success_count} sipariş işlendi.",
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            sync_log.mark_error(str(e))
            raise UserError(str(e))
            
    def _process_single_order(self, order_data, headers, auth, base_url):
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
            # Sadece durumu veya kargo takip numarasını güncelle vb. (Örnek)
            if existing_order.state not in ['done', 'cancel']:
                if status == 'Canceled' and existing_order.state != 'cancel':
                    existing_order.action_cancel()
            return processed, 0, 0, msgs

        # Canceled ise ve ERP'de yoksa almana gerek yok (Opsiyonel)
        if status == 'Canceled':
            return processed, 0, 0, msgs

        # Siparişin detaylı verisi Odoo'ya işleniyor.
        buyer_info = order_data.get('BuyerInfo', {})
        shipping_address = order_data.get('ShippingAddress', {})
        
        buyer_name = buyer_info.get('BuyerName') or shipping_address.get('Name') or 'Amazon Müşterisi'
        
        # Müşteri Yarat/Bul
        partner = self._get_or_create_partner(buyer_name, buyer_info, shipping_address)
        
        # Order Items'ları çek (Ayrı API isteği gerektirir)
        items_val = self._fetch_order_items(amazon_order_id, headers, auth, base_url)
        if not items_val:
            return processed, 0, 1, [f"{amazon_order_id} ürün detayları alınamadı, atlandı."]
            
        order_lines = []
        for item in items_val:
            sku = item.get('SellerSKU')
            asin = item.get('ASIN')
            qty = item.get('QuantityOrdered', 1)
            item_price = item.get('ItemPrice', {}).get('Amount', '0.0')
            
            # Ürünü Odoo'da Bul
            product = self.env['product.product'].search([('default_code', '=', sku)], limit=1)
            if not product:
                # ASIN ile yedek bulma stratejisi eklenebilir veya dummy ürün atılabilir.
                msgs.append(f"{amazon_order_id} siparişinde {sku} SKU'lu ürün Odoo'da BULUNAMADI. Placeholder atandı.")
                product = self.env.ref('amazon_integration.product_amazon_dummy', raise_if_not_found=False)
                if not product:
                    product = self.env['product.product'].search([], limit=1) # Fallback
            
            unit_price = float(item_price) / float(qty) if qty > 0 else float(item_price)
                    
            order_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'price_unit': unit_price,
                'name': item.get('Title', product.name)
            }))
            
        order_date_raw = order_data.get('PurchaseDate')
        order_date = parser.parse(order_date_raw).replace(tzinfo=False) if order_date_raw else fields.Datetime.now()
        
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
        
        # Eğer satıcı tarafından direkt kargolanacaksa
        if order_data.get('FulfillmentChannel') == 'MFN':
            sale_order.action_confirm()

        created = 1
        return processed, created, failed, msgs
        
    def _get_or_create_partner(self, name, buyer_info, address_info):
        phone = address_info.get('Phone', '')
        city = address_info.get('City', '')
        email = buyer_info.get('BuyerEmail', f"{name.replace(' ', '').lower()}@amazon.local")
        
        domain = [('email', '=', email)]
        if phone:
            domain = ['|', ('phone', '=', phone)] + domain
            
        partner = self.env['res.partner'].search(domain, limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
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

    def _fetch_order_items(self, amazon_order_id, headers, auth, base_url):
        endpoint = f"{base_url}/orders/v0/orders/{amazon_order_id}/orderItems"
        res = requests.get(endpoint, headers=headers, auth=auth, timeout=20)
        if res.status_code == 200:
            return res.json().get('payload', {}).get('OrderItems', [])
        return None

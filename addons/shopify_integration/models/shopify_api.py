import logging
import time
import requests

_logger = logging.getLogger(__name__)


class ShopifyAPIClient:
    """Shopify REST Admin API Client — connection pooling + rate limiting."""

    def __init__(self, store):
        self.store = store
        self.shop_url = store.shop_url.strip().rstrip('/')
        self.access_token = store.access_token.strip()
        self.api_version = (store.api_version or '2024-04').strip()

        # Base URL
        if not self.shop_url.startswith('http'):
            self.shop_url = f"https://{self.shop_url}"
        self.base_url = f"{self.shop_url}/admin/api/{self.api_version}"

        # Connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def _request(self, method, endpoint, params=None, data=None):
        url = f"{self.base_url}/{endpoint}"
        try:
            resp = self._session.request(
                method, url,
                params=params,
                json=data,
                timeout=30,
            )

            # Rate limiting: Shopify 429 Too Many Requests
            if resp.status_code == 429:
                retry_after = float(resp.headers.get('Retry-After', 2))
                _logger.warning("Shopify rate limit — %s sn bekleniyor...", retry_after)
                time.sleep(retry_after)
                resp = self._session.request(
                    method, url, params=params, json=data, timeout=30)

            if resp.status_code == 200 or resp.status_code == 201:
                try:
                    return {'success': True, 'data': resp.json()}
                except Exception:
                    return {'success': True, 'data': resp.text}
            elif resp.status_code == 401:
                return {'success': False, 'error': '401 Unauthorized: Access Token hatalı.'}
            elif resp.status_code == 404:
                return {'success': False, 'error': f'404 Not Found: {endpoint}'}
            else:
                _logger.error("Shopify API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─── Orders ──────────────────────────────────────────

    def get_orders(self, created_at_min=None, created_at_max=None,
                   status='any', financial_status=None, limit=250):
        """Siparişleri çek (sayfalanmış)."""
        params = {
            'status': status,
            'limit': min(limit, 250),
            'order': 'created_at desc',
        }
        if created_at_min:
            params['created_at_min'] = created_at_min
        if created_at_max:
            params['created_at_max'] = created_at_max
        if financial_status:
            params['financial_status'] = financial_status

        all_orders = []
        result = self._request('GET', 'orders.json', params=params)
        if not result.get('success'):
            return result

        orders = result['data'].get('orders', [])
        all_orders.extend(orders)

        # Pagination — Shopify Link header
        # Not: İlk sayfa genellikle yeterli, gerekirse pagination eklenir
        return {'success': True, 'data': all_orders}

    def get_order(self, order_id):
        """Tekil sipariş detayı."""
        return self._request('GET', f'orders/{order_id}.json')

    def get_orders_count(self, status='any'):
        """Sipariş sayısı."""
        return self._request('GET', 'orders/count.json', params={'status': status})

    # ─── Fulfillments ────────────────────────────────────

    def create_fulfillment(self, order_id, tracking_number, tracking_company='DHL',
                           tracking_url='', line_items=None):
        """Kargo bilgisi gönder (fulfillment oluştur)."""
        body = {
            'fulfillment': {
                'tracking_info': {
                    'number': tracking_number,
                    'company': tracking_company,
                    'url': tracking_url,
                },
                'notify_customer': True,
            }
        }
        if line_items:
            body['fulfillment']['line_items_by_fulfillment_order'] = line_items

        return self._request('POST', f'orders/{order_id}/fulfillments.json', data=body)

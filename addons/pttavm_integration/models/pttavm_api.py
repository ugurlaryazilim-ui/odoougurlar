import base64
import logging
import time
import uuid
from datetime import datetime

import requests

_logger = logging.getLogger(__name__)

PTTAVM_INTEGRATION_API_URL = 'https://integration-api.pttavm.com/api/v1'
PTTAVM_SHIPMENT_API_URL = 'https://shipment.pttavm.com/api/v1'
PTTAVM_MAX_WINDOW_DAYS = 40  # /orders/search en fazla 40 günlük aralık kabul eder

_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 2


class PttavmAPIClient:
    """Pttavm REST API Client — connection pooling ile."""

    def __init__(self, store):
        self.store = store
        self.api_key = store.api_key
        self.access_token = store.access_token
        self.cargo_username = store.cargo_username
        self.cargo_password = store.cargo_password

        # Connection pooling — TCP bağlantıları yeniden kullanılır
        self._session = requests.Session()
        self._session.headers.update({
            'Api-Key': self.api_key or '',
            'Access-Token': self.access_token or '',
            'Content-Type': 'application/json',
        })

        # Shipment API session (Basic Auth)
        self._shipment_session = requests.Session()
        if self.cargo_username and self.cargo_password:
            credentials = f"{self.cargo_username}:{self.cargo_password}"
            encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
            self._shipment_session.headers.update({
                'Authorization': f'Basic {encoded}',
                'Content-Type': 'application/json',
                # PttAVM kargo Postman koleksiyonundaki sabit başlık
                'Integration-Key': 'pttavm',
            })

    def _send(self, session, method, url, label, **kwargs):
        """İsteği gönderir; 429 / 5xx yanıtlarda kısa beklemeyle yeniden dener. Tüm 2xx başarılıdır."""
        resp = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = session.request(method, url, timeout=45, **kwargs)
            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES:
                    time.sleep(2 * (attempt + 1))
                    continue
                return {'success': False, 'error': 'Bağlantı zaman aşımı'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                _logger.info("%s %s → %s, yeniden denenecek", label, url, resp.status_code)
                time.sleep(2 * (attempt + 1))
                continue
            break

        _logger.debug("%s %s %s → %s", label, method, url, resp.status_code)
        if 200 <= resp.status_code < 300:
            try:
                return {'success': True, 'data': resp.json()}
            except Exception:
                return {'success': True, 'data': resp.text}
        _logger.error("%s Hata: %s %s", label, resp.status_code, resp.text[:500])
        return {'success': False, 'status': resp.status_code,
                'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}

    def _request(self, method, endpoint, params=None, data=None):
        """Integration API Request"""
        if not self.api_key or not self.access_token:
            return {'success': False, 'error': 'Yetkilendirme (Api-Key, Access-Token) boş olamaz.'}
        # Correlation ID zorunlu ve her istekte farklı olmalı
        self._session.headers['X-Correlation-Id'] = str(uuid.uuid4())
        return self._send(self._session, method, f"{PTTAVM_INTEGRATION_API_URL}{endpoint}",
                          'Pttavm API', params=params, json=data)

    def _shipment_request(self, method, endpoint, data=None):
        """Shipment API Request (Basic Auth)"""
        if not self.cargo_username or not self.cargo_password:
            return {'success': False, 'error': 'Kargo Username ve Password boş olamaz.'}
        return self._send(self._shipment_session, method, f"{PTTAVM_SHIPMENT_API_URL}{endpoint}",
                          'Pttavm Shipment API', json=data)

    def get_orders(self, start_date=None, end_date=None, active_only=False):
        """Siparişleri çek. (Max 40 gün, sayfalama yok)"""
        params = {
            'isActiveOrders': 'true' if active_only else 'false'
        }

        if start_date:
            if isinstance(start_date, datetime):
                params['startDate'] = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                params['startDate'] = start_date

        if end_date:
            if isinstance(end_date, datetime):
                params['endDate'] = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                params['endDate'] = end_date

        _logger.debug("PttAVM API isteği: /orders/search params=%s", params)
        return self._request('GET', '/orders/search', params=params)

    def get_order_detail(self, order_id):
        """Tek siparişin detayını çek. (orderId = siparisNo)"""
        _logger.debug("PttAVM API isteği: /orders/%s", order_id)
        return self._request('GET', f'/orders/{order_id}')

    def send_invoice(self, order_id, line_item_ids, pdf_base64=None, url=None):
        """Fatura gönderimi (PDF/HTML içerik veya link). URL verilirse öncelikli kullanılır."""
        data = {
            "lineItemId": line_item_ids,
            "content": pdf_base64,
            "url": url
        }
        return self._request('POST', f'/orders/{order_id}/invoice', data=data)

    # ─── Shipment API ────────────────────────────────────────────────────────

    def get_warehouse(self):
        """Mağazaya ait depo bilgisini alma."""
        return self._shipment_request('POST', '/get-warehouse')

    def create_barcode(self, order_id, warehouse_id):
        """Sipariş için barkod oluştur (asenkron — sonuç barcode-status ile sorgulanır)."""
        data = {
            "orders": [
                {
                    "order_id": order_id,
                    "warehouse_id": warehouse_id
                }
            ]
        }
        return self._shipment_request('POST', '/create-barcode', data=data)

    def get_barcode_status(self, tracking_id):
        """Barkod oluşturma talebinin durumu: completed / pending / error."""
        data = {
            "tracking_id": tracking_id
        }
        return self._shipment_request('POST', '/barcode-status', data=data)

    def update_no_shipping_order(self, order_id):
        """Dijital ürünler için siparişi teslim edildi durumuna çeker."""
        data = {
            "order_id": order_id
        }
        return self._shipment_request('POST', '/update-no-shipping-order', data=data)

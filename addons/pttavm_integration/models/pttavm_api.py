import base64
import json
import logging
import requests
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

PTTAVM_INTEGRATION_API_URL = 'https://integration-api.pttavm.com/api/v1'
PTTAVM_SHIPMENT_API_URL = 'https://shipment.pttavm.com/api/v1'


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
            })

    def _request(self, method, endpoint, params=None, data=None):
        """Integration API Request"""
        if not self.api_key or not self.access_token:
            return {'success': False, 'error': 'Yetkilendirme (Api-Key, Access-Token) boş olamaz.'}

        url = f"{PTTAVM_INTEGRATION_API_URL}{endpoint}"
        # Correlation ID her istekte farklı olmalı
        self._session.headers['X-Correlation-Id'] = 'odoo-' + datetime.now().strftime('%Y%m%d%H%M%S%f')

        try:
            resp = self._session.request(
                method, url,
                params=params,
                json=data,
                timeout=45,
            )
            if resp.status_code == 200:
                try:
                    return {'success': True, 'data': resp.json()}
                except Exception:
                    return {'success': True, 'data': resp.text}
            else:
                _logger.error("Pttavm API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _shipment_request(self, method, endpoint, data=None):
        """Shipment API Request (Basic Auth)"""
        if not self.cargo_username or not self.cargo_password:
            return {'success': False, 'error': 'Kargo Username ve Password boş olamaz.'}

        url = f"{PTTAVM_SHIPMENT_API_URL}{endpoint}"

        try:
            resp = self._shipment_session.request(
                method, url,
                json=data,
                timeout=45,
            )
            if resp.status_code == 200:
                try:
                    return {'success': True, 'data': resp.json()}
                except Exception:
                    return {'success': True, 'data': resp.text}
            else:
                _logger.error("Pttavm Shipment API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_orders(self, start_date=None, end_date=None):
        """Siparişleri çek. (Max 40 gün)"""
        params = {
            'isActiveOrders': 'false'
        }
        
        if start_date:
            if isinstance(start_date, datetime):
                params['startDate'] = start_date.strftime('%Y-%m-%d')
            else:
                params['startDate'] = start_date
        
        if end_date:
            if isinstance(end_date, datetime):
                params['endDate'] = end_date.strftime('%Y-%m-%d')
            else:
                params['endDate'] = end_date

        return self._request('GET', '/orders/search', params=params)

    def send_invoice(self, order_id, line_item_ids, pdf_base64=None, url=None):
        """PDF Fatura Gönderimi."""
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
        """Sipariş için barkod oluştur."""
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
        """Barkod durumunu kontrol eder."""
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

import logging
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)

N11_API_URL = 'https://api.n11.com'


class N11APIClient:
    """N11 REST API Client — connection pooling ile."""

    def __init__(self, store):
        self.store = store
        self.app_key = store.n11_app_key
        self.app_secret = store.n11_app_secret

        # Connection pooling — TCP bağlantıları yeniden kullanılır
        self._session = requests.Session()
        self._session.headers.update({
            'appkey': self.app_key or '',
            'appsecret': self.app_secret or '',
            'Content-Type': 'application/json',
        })

    def _request(self, method, endpoint, params=None, data=None):
        """API Request over Headers Auth"""
        if not self.app_key or not self.app_secret:
            return {'success': False, 'error': 'App Key ve App Secret boş olamaz.'}

        url = f"{N11_API_URL}{endpoint}"

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
                _logger.error("N11 API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_shipment_packages(self, start_date=None, end_date=None, status=None, page=0, size=100):
        """Siparişleri çek."""
        params = {
            'page': page,
            'size': size
        }
        
        if start_date:
            if isinstance(start_date, datetime):
                params['startDate'] = int(start_date.timestamp() * 1000)
            else:
                params['startDate'] = int(start_date)
        
        if end_date:
            if isinstance(end_date, datetime):
                params['endDate'] = int(end_date.timestamp() * 1000)
            else:
                params['endDate'] = int(end_date)
                
        if status:
            params['status'] = status

        return self._request('GET', '/rest/delivery/v1/shipmentPackages', params=params)

    # ─── Shipment & Other APIs ────────────────────────────────────────────────────────
    
    def update_order_status_to_picking(self, line_ids):
        """Siparişleri Onaylandı (Picking) statüsüne alır."""
        data = {
            "lines": [{"lineId": line_id} for line_id in line_ids],
            "status": "Picking"
        }
        return self._request('PUT', '/rest/order/v1/update', data=data)

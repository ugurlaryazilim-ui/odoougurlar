import base64
import logging
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)

FLO_API_URL = 'https://api.flo.com.tr/v1'


class FloAPIClient:
    """Flo REST API Client — connection pooling ile."""

    def __init__(self, store):
        self.store = store
        self.username = store.flo_username
        self.password = store.flo_password
        self.seller_id = store.flo_seller_id

        # Connection pooling — TCP bağlantıları yeniden kullanılır
        credentials = f"{self.username}:{self.password}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

        self._session = requests.Session()
        self._session.headers.update({
            'Authorization': f'Basic {encoded}',
            'Content-Type': 'application/json',
        })

    def _request(self, method, endpoint, params=None, data=None):
        """API Request over Basic Auth"""
        if not self.username or not self.password:
            return {'success': False, 'error': 'Kullanıcı Adı ve Şifre boş olamaz.'}

        url = f"{FLO_API_URL}{endpoint}"

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
                _logger.error("Flo API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_orders(self, start_date=None, end_date=None, page=1, size=100):
        """Siparişleri çek."""
        params = {
            'page': page,
            'size': size
        }
        
        if start_date:
            if isinstance(start_date, datetime):
                params['startDate'] = int(start_date.timestamp())
            else:
                params['startDate'] = int(start_date)
        
        if end_date:
            if isinstance(end_date, datetime):
                params['endDate'] = int(end_date.timestamp())
            else:
                params['endDate'] = int(end_date)

        return self._request('GET', '/orders', params=params)

    def update_package(self, increment_id):
        """Update package."""
        data = {"increment_id": str(increment_id)}
        return self._request('POST', '/shipment/update-package', data=data)

    def change_cargo_company(self, increment_id, new_shipping_method_id):
        """Kargo firmasını değiştir."""
        data = {
            "increment_id": str(increment_id),
            "new_shipping_method_id": new_shipping_method_id
        }
        return self._request('POST', '/shipment/change-cargo-company', data=data)
        
    def get_cargo_companies(self):
        """Sistemdeki kargo firmalarını çek."""
        return self._request('GET', '/shipment/cargo-company/')

    def get_payment_agreements(self, start_date, end_date):
        """Finansal mutabakat verileri — FLO henüz bu servisi sunmuyorsa boş döner."""
        _logger.warning("Flo get_payment_agreements: Bu servis henüz FLO API'de desteklenmiyor olabilir.")
        params = {}
        if start_date:
            params['startDate'] = int(start_date.timestamp()) if isinstance(start_date, datetime) else int(start_date)
        if end_date:
            params['endDate'] = int(end_date.timestamp()) if isinstance(end_date, datetime) else int(end_date)
        return self._request('GET', '/payment-agreements', params=params)

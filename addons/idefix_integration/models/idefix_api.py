import base64
import logging
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)

IDEFIX_API_URL = 'https://merchantapi.idefix.com/oms'


class IdefixAPIClient:
    """Idefix REST API Client — connection pooling ile."""

    def __init__(self, store):
        self.store = store
        self.client_id = store.client_id
        self.client_secret = store.client_secret
        self.vendor_id = store.vendor_id

        # Connection pooling — TCP bağlantıları yeniden kullanılır
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

        self._session = requests.Session()
        self._session.headers.update({
            'X-API-KEY': encoded,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def _request(self, method, endpoint, params=None, data=None):
        if not self.vendor_id:
            return {'success': False, 'error': 'Satıcı ID (Vendor ID) tanımlanmamış.'}

        url = f"{IDEFIX_API_URL}/{self.vendor_id}{endpoint}"

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
            elif resp.status_code == 401:
                return {'success': False, 'error': '401 Unauthorized: API Key veya Secret hatalı (VENDOR_TOKEN_NOT_EXIST).'}
            else:
                _logger.error("Idefix API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_orders(self, start_date=None, end_date=None, page=1, limit=50):
        """Siparişleri çek."""
        params = {
            'limit': limit,
            'page': page
        }
        
        if start_date:
            if isinstance(start_date, datetime):
                params['startDate'] = start_date.strftime('%Y/%m/%d %H:%M:%S')
            else:
                params['startDate'] = start_date
        
        if end_date:
            if isinstance(end_date, datetime):
                params['endDate'] = end_date.strftime('%Y/%m/%d %H:%M:%S')
            else:
                params['endDate'] = end_date

        return self._request('GET', '/list', params=params)

    def update_tracking_number(self, shipment_id, tracking_number, tracking_url):
        """Kargo takip bilgisi gönder."""
        body = {
            "trackingNumber": tracking_number,
            "trackingUrl": tracking_url
        }
        return self._request('POST', f'/{shipment_id}/update-tracking-number', data=body)

    def update_shipment_status(self, shipment_id, status="invoiced", invoice_number=""):
        """Sipariş Durumunu Güncelleme (picking veya invoiced)"""
        body = {
            "status": status
        }
        if invoice_number:
            body["invoiceNumber"] = invoice_number
        return self._request('POST', f'/{shipment_id}/update-shipment-status', data=body)

    def get_refunds(self, start_date, end_date):
        """İade taleplerini listele"""
        params = {
            "startDate": start_date.strftime('%Y/%m/%d %H:%M:%S') if isinstance(start_date, datetime) else start_date,
            "endDate": end_date.strftime('%Y/%m/%d %H:%M:%S') if isinstance(end_date, datetime) else end_date
        }
        return self._request('GET', '/claim-list', params=params)

    def get_payment_agreements(self, start_date, end_date):
        """Finansal mutabakat verileri — Idefix henüz bu servisi sunmuyorsa boş döner."""
        _logger.warning("Idefix get_payment_agreements: Bu servis henüz Idefix API'de desteklenmiyor olabilir.")
        params = {
            "startDate": start_date.strftime('%Y/%m/%d %H:%M:%S') if isinstance(start_date, datetime) else start_date,
            "endDate": end_date.strftime('%Y/%m/%d %H:%M:%S') if isinstance(end_date, datetime) else end_date
        }
        return self._request('GET', '/payment-agreements', params=params)

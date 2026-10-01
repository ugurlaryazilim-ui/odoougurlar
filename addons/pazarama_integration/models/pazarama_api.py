import base64
import logging
import time
from datetime import datetime, timedelta

import requests

_logger = logging.getLogger(__name__)

PAZARAMA_AUTH_URL = 'https://isortagimgiris.pazarama.com/connect/token'
PAZARAMA_API_URL = 'https://isortagimapi.pazarama.com'
PAZARAMA_MAX_WINDOW_DAYS = 30  # getOrdersForApi: başlangıç-bitiş en fazla 1 ay

_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 2


def _fmt_minute(value):
    return value.strftime('%Y-%m-%dT%H:%M') if isinstance(value, datetime) else value


class PazaramaAPIClient:
    """Pazarama REST API Client — connection pooling ile."""

    def __init__(self, store):
        self.store = store
        self.client_id = store.client_id
        self.client_secret = store.client_secret
        self._token = None

        # Connection pooling — TCP bağlantıları yeniden kullanılır
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
        })

    def get_access_token(self, force=False):
        """Token alma veya var olan geçerli tokenı kullanma (ömrü 1 saat)."""
        from odoo import fields
        now = fields.Datetime.now()
        if self._token and not force:
            return self._token

        # Geçerli token varsa onu kullan
        if not force and self.store.access_token and self.store.token_expiry and self.store.token_expiry > now:
            self._token = self.store.access_token
            return self._token

        # Yeni token iste
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {encoded}',
        }
        data = {
            'grant_type': 'client_credentials',
            'scope': 'merchantgatewayapi.fullaccess'
        }

        try:
            resp = requests.post(PAZARAMA_AUTH_URL, headers=headers, data=data, timeout=30)
        except Exception as e:
            _logger.error("Pazarama Token İstek Hatası: %s", str(e))
            self.token_error = str(e)
            return None
        try:
            result = resp.json()
        except ValueError:
            result = {}
        data_obj = result.get('data') if isinstance(result.get('data'), dict) else {}
        access_token = data_obj.get('accessToken') or result.get('access_token')
        if resp.status_code != 200 or not access_token:
            _logger.error("Pazarama Token Hatası: %s %s", resp.status_code, resp.text[:500])
            self.token_error = f"Token alınamadı (HTTP {resp.status_code}): {resp.text[:200]}"
            return None
        expires_in = int(data_obj.get('expiresIn') or result.get('expires_in') or 3600)
        self._token = access_token
        # Ayrı cursor ile saklanır: cron işlemi mağaza satırını kilitlemesin
        self.store._save_token(access_token, now + timedelta(seconds=expires_in - 60))
        return access_token

    def _request(self, method, endpoint, params=None, data=None):
        token = self.get_access_token()
        if not token:
            return {'success': False, 'error': getattr(self, 'token_error', None) or 'Yetkilendirme (Token) başarısız.'}

        url = endpoint if endpoint.startswith('http') else f"{PAZARAMA_API_URL}{endpoint}"
        self._session.headers['Authorization'] = f'Bearer {token}'

        resp = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = self._session.request(method, url, params=params, json=data, timeout=45)
            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES:
                    time.sleep(2 * (attempt + 1))
                    continue
                return {'success': False, 'error': 'Bağlantı zaman aşımı'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                _logger.info("Pazarama API %s → %s, yeniden denenecek", endpoint, resp.status_code)
                time.sleep(2 * (attempt + 1))
                continue
            break

        if resp.status_code == 401:
            # Token süresi dolmuş / iptal edilmiş olabilir — sonraki istekte yenilensin
            self._token = None
            self.store._save_token(False, False)
        if not 200 <= resp.status_code < 300:
            _logger.error("Pazarama API Hata: %s %s %s", endpoint, resp.status_code, resp.text[:500])
            return {'success': False, 'status': resp.status_code,
                    'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        try:
            body = resp.json()
        except ValueError:
            return {'success': True, 'data': resp.text}
        # Pazarama zarfı: {data, success, messageCode, message, userMessage}
        if isinstance(body, dict) and body.get('success') is False:
            msg = body.get('userMessage') or body.get('message') or body.get('messageCode') or 'İşlem başarısız'
            _logger.warning("Pazarama API başarısız yanıt: %s %s", endpoint, msg)
            return {'success': False, 'error': str(msg), 'data': body}
        return {'success': True, 'data': body}

    def get_orders(self, start_date=None, end_date=None, page=1, size=100, order_number=None):
        """Siparişleri çek (tarih aralığı en fazla 1 ay; bitiş tarihi hariçtir)."""
        body = {
            'pageSize': min(size, 500),
            'pageNumber': page
        }
        if start_date:
            body['startDate'] = _fmt_minute(start_date)
        if end_date:
            body['endDate'] = _fmt_minute(end_date)
        if order_number:
            body['orderNumber'] = int(order_number) if str(order_number).isdigit() else order_number
        return self._request('POST', '/order/getOrdersForApi', data=body)

    def update_item_status(self, order_number, order_item_id, status):
        """Tek kalemin durumunu güncelle (ör. 12 = Siparişiniz Hazırlanıyor)."""
        body = {
            "orderNumber": int(order_number) if str(order_number).isdigit() else order_number,
            "item": {"orderItemId": order_item_id, "status": status},
        }
        return self._request('PUT', '/order/updateOrderStatus', data=body)

    def update_tracking_number(self, order_number, order_item_id, tracking_number, cargo_company_id, tracking_url=""):
        """Kargo takip bilgisi gönder."""
        body = {
            "orderNumber": int(order_number) if str(order_number).isdigit() else order_number,
            "item": {
                "orderItemId": order_item_id,
                "status": 5,  # Kargoya Verildi
                "deliveryType": 1,  # Cargo
                "shippingTrackingNumber": tracking_number,
                "trackingUrl": tracking_url,
                "cargoCompanyId": cargo_company_id
            }
        }
        return self._request('PUT', '/order/updateOrderStatus', data=body)

    def send_invoice_link(self, order_id, invoice_link):
        """Fatura linkini siparişin tamamına ekler (POST /order/invoice-link)."""
        body = {
            "invoiceLink": invoice_link,
            "orderid": order_id,
            "deliveryCompanyId": None,
            "trackingNumber": None,
        }
        return self._request('POST', '/order/invoice-link', data=body)

    def get_payment_agreements(self, start_date, end_date):
        """Muhasebe ve Finans Servisi (tarihler TR saati)."""
        body = {
            "startDate": start_date.strftime('%Y-%m-%dT%H:%M:%S.000') if isinstance(start_date, datetime) else start_date,
            "endDate": end_date.strftime('%Y-%m-%dT%H:%M:%S.999') if isinstance(end_date, datetime) else end_date,
            "allowanceStartDate": None,
            "allowanceEndDate": None,
            "orderId": None
        }
        return self._request('POST', '/order/paymentAgreement', data=body)

    def get_refunds(self, start_date, end_date, page_number=1, page_size=100, refund_status=None):
        """İade taleplerini listele"""
        body = {
            "pageSize": page_size,
            "pageNumber": page_number,
            "refundStatus": refund_status,
            "requestStartDate": start_date.strftime('%Y-%m-%d') if isinstance(start_date, datetime) else start_date,
            "requestEndDate": end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime) else end_date
        }
        return self._request('POST', '/order/getRefund', data=body)

    def update_refund_status(self, refund_id, status_code, reject_type=0):
        """İade Durumu Güncelleme"""
        body = {
            "refundId": refund_id,
            "status": status_code
        }
        if reject_type > 0:
            body["RefundRejectType"] = reject_type
        return self._request('POST', '/order/updateRefund', data=body)

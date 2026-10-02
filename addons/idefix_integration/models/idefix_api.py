import base64
import logging
import time
from datetime import datetime

import requests

_logger = logging.getLogger(__name__)

IDEFIX_API_URL = 'https://merchantapi.idefix.com/oms'

_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 2
_DATE_FMT = '%Y/%m/%d %H:%M:%S'  # Idefix tarih parametresi formatı (Türkiye saati)


def _fmt_date(value):
    return value.strftime(_DATE_FMT) if isinstance(value, datetime) else value


class IdefixAPIClient:
    """Idefix OMS REST API Client — connection pooling ile.

    Kimlik: X-API-KEY = base64(ApiKey:ApiSecret). Uç noktaların çoğu /oms/{vendorId}/... altındadır."""

    def __init__(self, store):
        # API bilgileri yalnızca sistem yöneticisi grubuna açık — okuma sudo ile yapılır
        store = store.sudo()
        self.store = store
        self.vendor_id = (store.vendor_id or '').strip()

        credentials = f"{store.client_id}:{store.client_secret}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

        self._session = requests.Session()
        self._session.headers.update({
            'X-API-KEY': encoded,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    @staticmethod
    def _error_text(resp):
        try:
            body = resp.json()
        except ValueError:
            return resp.text[:300]
        if isinstance(body, dict):
            msg = body.get('message') or body.get('error') or body.get('errors') or body.get('detail')
            if msg:
                return str(msg)[:300]
        return str(body)[:300]

    def _request(self, method, endpoint, params=None, data=None, vendor=True):
        if vendor and not self.vendor_id:
            return {'success': False, 'error': 'Satıcı ID (Vendor ID) tanımlanmamış.'}
        url = f"{IDEFIX_API_URL}/{self.vendor_id}{endpoint}" if vendor else f"{IDEFIX_API_URL}{endpoint}"

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
                # 429: Retry-After (saniye) kadar beklenir
                try:
                    wait = float(resp.headers.get('Retry-After') or 0)
                except ValueError:
                    wait = 0
                wait = min(max(wait, 2 * (attempt + 1)), 10)
                _logger.info("Idefix API %s → %s, %.1f sn sonra yeniden denenecek", endpoint, resp.status_code, wait)
                time.sleep(wait)
                continue
            break

        if resp.status_code == 401:
            return {'success': False, 'status': 401,
                    'error': '401 Unauthorized: API Key / Secret hatalı (VENDOR_TOKEN_NOT_EXIST).'}
        if not 200 <= resp.status_code < 300:
            _logger.error("Idefix API Hata: %s %s %s", endpoint, resp.status_code, resp.text[:500])
            return {'success': False, 'status': resp.status_code,
                    'error': f"HTTP {resp.status_code}: {self._error_text(resp)}"}
        if not resp.content:
            return {'success': True, 'data': {}}
        try:
            return {'success': True, 'data': resp.json()}
        except ValueError:
            return {'success': True, 'data': resp.text}

    # ─── Sevkiyatlar (shipment) ──────────────────────────────

    def get_orders(self, start_date=None, end_date=None, page=1, limit=50, ids=None, order_number=None):
        """Sevkiyat listesi (list). Tarihler Türkiye saatidir."""
        params = {'page': page, 'limit': limit}
        if ids:
            params['ids'] = ','.join(str(i) for i in ids)
        if order_number:
            params['orderNumber'] = order_number
        if start_date:
            params['startDate'] = _fmt_date(start_date)
        if end_date:
            params['endDate'] = _fmt_date(end_date)
        return self._request('GET', '/list', params=params)

    def update_shipment_status(self, shipment_id, status, invoice_number=''):
        """'picking' (artık müşteri iptal edemez) veya 'invoiced' (faturalandı)."""
        body = {'status': status}
        if invoice_number:
            body['invoiceNumber'] = invoice_number
        return self._request('POST', f'/{shipment_id}/update-shipment-status', data=body)

    def send_invoice_link(self, shipment_id, invoice_link):
        return self._request('POST', f'/{shipment_id}/invoice-link', data={'invoiceLink': invoice_link})

    def update_tracking_number(self, shipment_id, tracking_number, tracking_url):
        """Satıcının kendi kargo anlaşmasıyla gönderim — sipariş platform anlaşmasından çıkar."""
        body = {'trackingNumber': tracking_number, 'trackingUrl': tracking_url}
        return self._request('POST', f'/{shipment_id}/update-tracking-number', data=body)

    def update_box_info(self, shipment_id, box_quantity, desi):
        body = {'boxQuantity': box_quantity, 'desi': desi}
        return self._request('POST', f'/{shipment_id}/update-box-info', data=body)

    def get_noship_reasons(self):
        return self._request('GET', '/reasons/noship')

    def mark_unsupplied(self, shipment_id, items):
        """items: [{'id': item_id, 'reasonId': reason_id}]"""
        return self._request('POST', f'/{shipment_id}/unsupplied', data={'items': items})

    # ─── İadeler (claim) ─────────────────────────────────────

    def get_claims(self, start_date=None, end_date=None, page=1, limit=50, ids=None, order_number=None):
        params = {'page': page, 'limit': limit}
        if ids:
            params['ids'] = ','.join(str(i) for i in ids)
        if order_number:
            params['orderNumber'] = order_number
        if start_date:
            params['startDate'] = _fmt_date(start_date)
        if end_date:
            params['endDate'] = _fmt_date(end_date)
        return self._request('GET', '/claim-list', params=params)

    def approve_claim(self, claim_id, claim_line_ids):
        body = {'claimLineIds': [str(i) for i in claim_line_ids]}
        return self._request('POST', f'/{claim_id}/claim-approve', data=body)

    def get_claim_decline_reasons(self):
        # Bu uç noktada vendorId yoktur
        return self._request('GET', '/claim-decline-reasons', vendor=False)

    def decline_claim(self, claim_id, claim_lines):
        """claim_lines: [{'id', 'claimDeclineReasonId', 'description', 'images'}]"""
        return self._request('POST', f'/{claim_id}/claim-decline-request', data={'claimLines': claim_lines})

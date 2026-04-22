# -*- coding: utf-8 -*-
import base64
import json
import logging
import requests
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

IDEFIX_API_URL = 'https://merchantapi.idefix.com/oms'

class IdefixAPIClient:
    """Idefix REST API Client."""

    def __init__(self, store, env):
        self.store = store
        self.env = env
        self.client_id = store.client_id # This acts as API_KEY
        self.client_secret = store.client_secret # API_SECRET
        self.vendor_id = store.vendor_id

    def get_headers(self):
        """Token oluşturma: VENDOR TOKEN = base64_encode(ApiKEY:ApiSecret)"""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        return {
            'X-API-KEY': encoded,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _request(self, method, endpoint, params=None, data=None):
        if not self.vendor_id:
            return {'success': False, 'error': 'Satıcı ID (Vendor ID) tanımlanmamış.'}

        url = f"{IDEFIX_API_URL}/{self.vendor_id}{endpoint}"
        headers = self.get_headers()

        try:
            resp = requests.request(
                method, url,
                headers=headers,
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


class IdefixAPIModel(models.AbstractModel):
    """IdefixAPI nesnesini oluşturacak Odoo Factory"""
    _name = 'idefix.api'
    _description = 'Idefix API Factory'

    def create_api(self, store):
        return IdefixAPIClient(store, self.env)

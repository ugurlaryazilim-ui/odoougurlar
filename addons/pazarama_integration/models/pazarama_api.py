# -*- coding: utf-8 -*-
import base64
import json
import logging
import requests
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PAZARAMA_AUTH_URL = 'https://isortagimgiris.pazarama.com/connect/token'
PAZARAMA_API_URL = 'https://isortagimapi.pazarama.com'


class PazaramaAPIClient:
    """Pazarama REST API Client."""

    def __init__(self, store, env):
        self.store = store
        self.env = env
        self.client_id = store.client_id
        self.client_secret = store.client_secret

    def get_access_token(self):
        """Token alma veya var olan geçerli tokenı kullanma."""
        now = fields.Datetime.now()
        
        # Geçerli token varsa onu kullan
        if self.store.access_token and self.store.token_expiry and self.store.token_expiry > now:
            return self.store.access_token

        # Yeni token iste
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        # Form Auth
        # clientId ve clientSecret basic auth olarak gonderilecek
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers['Authorization'] = f'Basic {encoded}'
        
        data = {
            'grant_type': 'client_credentials',
            'scope': 'merchantgatewayapi.fullaccess'
        }

        try:
            resp = requests.post(PAZARAMA_AUTH_URL, headers=headers, data=data, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success') and 'data' in result:
                    data_obj = result.get('data')
                    access_token = data_obj.get('accessToken')
                    expires_in = data_obj.get('expiresIn', 3600)  # Gelen değer genelde saniye
                    
                    # Databasede güncelle
                    expiry_dt = now + timedelta(seconds=expires_in - 60) # 1 dk erken bitsin
                    self.store.sudo().write({
                        'access_token': access_token,
                        'token_expiry': expiry_dt
                    })
                    # Yeni aldığın an return etmeden önce commit edebiliriz ki bir sonraki hata durumunda tekrar uğraşmasın
                    self.env.cr.commit()
                    return access_token
                else:
                    _logger.error("Pazarama Token Hatası (Bağarısız Model): %s %s", resp.status_code, resp.text)
                    return None
            else:
                _logger.error("Pazarama Token Hatası: %s %s", resp.status_code, resp.text)
                return None
        except Exception as e:
            _logger.error("Pazarama Token İstek Hatası: %s", str(e))
            return None

    def _request(self, method, endpoint, params=None, data=None):
        token = self.get_access_token()
        if not token:
            return {'success': False, 'error': 'Yetkilendirme (Token) başarısız.'}

        url = f"{PAZARAMA_API_URL}{endpoint}"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

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
            else:
                _logger.error("Pazarama API Hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_orders(self, start_date=None, end_date=None, page=1, size=500):
        """Siparişleri çek."""
        body = {
            'pageSize': min(size, 500),
            'pageNumber': page
        }
        
        if start_date:
            if isinstance(start_date, datetime):
                body['startDate'] = start_date.strftime('%Y-%m-%dT%H:%M')
            else:
                body['startDate'] = start_date
        
        if end_date:
            if isinstance(end_date, datetime):
                body['endDate'] = end_date.strftime('%Y-%m-%dT%H:%M')
            else:
                body['endDate'] = end_date

        return self._request('POST', '/order/getOrdersForApi', data=body)

    def update_tracking_number(self, order_number, order_item_id, tracking_number, cargo_company_id, tracking_url=""):
        """Kargo takip bilgisi gönder."""
        body = {
            "orderNumber": order_number,
            "item": {
                "orderItemId": order_item_id,
                "status": 5, # Kargoya Verildi
                "deliveryType": 1, # Cargo
                "shippingTrackingNumber": tracking_number,
                "trackingUrl": tracking_url,
                "cargoCompanyId": cargo_company_id
            }
        }
        return self._request('PUT', '/order/updateOrderStatus', data=body)

    def update_bulk_order_status(self, order_number, status_code=11):
        """Toplu Sipariş Durumunu Güncelleme"""
        body = {
            "orderNumber": order_number,
            "status": status_code
        }
        return self._request('PUT', '/order/updateOrderStatusList', data=body)

    def get_payment_agreements(self, start_date, end_date):
        """Muhasebe ve Finans Servisi."""
        body = {
            "startDate": start_date.strftime('%Y-%m-%dT00:00:01.000Z') if isinstance(start_date, datetime) else start_date,
            "endDate": end_date.strftime('%Y-%m-%dT23:59:59.000Z') if isinstance(end_date, datetime) else end_date,
            "allowanceDate": None,
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
        # status code -> 2: Onayla, 3: Reddet
        body = {
            "refundId": refund_id,
            "status": status_code
        }
        if reject_type > 0:
            body["RefundRejectType"] = reject_type
        return self._request('POST', '/order/updateRefund', data=body)


class PazaramaAPIModel(models.AbstractModel):
    """PazaramaAPI nesnesini oluşturacak Odoo Factory"""
    _name = 'pazarama.api'
    _description = 'Pazarama API Factory'

    def create_api(self, store):
        return PazaramaAPIClient(store, self.env)

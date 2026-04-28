
import base64
import json
import logging
import requests
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TRENDYOL_PROD_URL = 'https://apigw.trendyol.com/integration'
TRENDYOL_STAGE_URL = 'https://stageapigw.trendyol.com/integration'


class TrendyolAPI:
    """Trendyol REST API Client."""

    def __init__(self, api_key, api_secret, seller_id, is_prod=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.seller_id = seller_id
        self.base_url = TRENDYOL_PROD_URL if is_prod else TRENDYOL_STAGE_URL
        # Connection pooling — TCP bağlantıları yeniden kullanılır
        self._session = requests.Session()
        credentials = f"{api_key}:{api_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._session.headers.update({
            'Authorization': f'Basic {encoded}',
            'Content-Type': 'application/json',
            'User-Agent': f'{seller_id} - OdooIntegration',
        })

    def _get_headers(self):
        return self._session.headers

    def _request(self, method, endpoint, params=None, data=None):
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self._session.request(
                method, url,
                params=params,
                json=data,
                timeout=30,
            )
            _logger.info("Trendyol API %s %s → %s", method, url, resp.status_code)
            if resp.status_code == 200:
                try:
                    return {'success': True, 'data': resp.json()}
                except Exception:
                    return {'success': True, 'data': resp.text}
            else:
                _logger.error("Trendyol API hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Bağlantı zaman aşımı'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Bağlantı hatası'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def test_connection(self):
        """Basit bağlantı testi — son 1 siparişi çek."""
        return self._request('GET', f'/order/sellers/{self.seller_id}/orders', params={'size': 1})

    def get_orders(self, status=None, start_date=None, end_date=None, page=0, size=50, order_number=None):
        """Sipariş paketlerini çek."""
        params = {
            'page': page,
            'size': min(size, 200),
            'orderByField': 'PackageLastModifiedDate',
            'orderByDirection': 'DESC',
        }
        if status:
            params['status'] = status
        if start_date:
            # Timestamp milliseconds GMT+3
            params['startDate'] = int(start_date.timestamp() * 1000)
        if end_date:
            params['endDate'] = int(end_date.timestamp() * 1000)
        if order_number:
            params['orderNumber'] = order_number

        return self._request('GET', f'/order/sellers/{self.seller_id}/orders', params=params)

    def update_package_status(self, package_id, status, lines, invoice_number=None):
        """Paket statüsünü güncelle (Picking / Invoiced)."""
        data = {
            'lines': lines,
            'params': {},
            'status': status,
        }
        if invoice_number and status == 'Invoiced':
            data['params']['invoiceNumber'] = invoice_number

        return self._request(
            'PUT',
            f'/order/sellers/{self.seller_id}/shipment-packages/{package_id}',
            data=data,
        )

    def unsupply_package(self, package_id, lines, reason_id=500):
        """Tedarik edememe bildirimi."""
        data = {'lines': lines, 'reasonId': reason_id}
        return self._request(
            'PUT',
            f'/order/sellers/{self.seller_id}/shipment-packages/{package_id}/items/unsupplied',
            data=data,
        )

    def update_tracking_number(self, shipment_package_id, tracking_number, cargo_provider_id=None):
        """Kargo takip numarasını Trendyol'a gönder."""
        data = {
            'trackingNumber': tracking_number,
        }
        if cargo_provider_id:
            data['cargoProviderId'] = cargo_provider_id

        return self._request(
            'PUT',
            f'/order/sellers/{self.seller_id}/shipment-packages/{shipment_package_id}/cargo-tracking-info',
            data=data,
        )

    def update_package_to_shipped(self, package_id, tracking_number, cargo_provider_id=None,
                                   package_count=1, desi=1.0):
        """Paketi kargoya verildi olarak güncelle."""
        data = {
            'trackingNumber': tracking_number,
        }
        if cargo_provider_id:
            data['cargoProviderId'] = cargo_provider_id
        if package_count:
            data['params'] = {
                'boxQuantity': package_count,
            }

        return self._request(
            'PUT',
            f'/order/sellers/{self.seller_id}/shipment-packages/{package_id}',
            data={'status': 'Shipped', **data},
        )

    # ═══════════════════════════════════════════════════════
    # FİNANSAL API
    # ═══════════════════════════════════════════════════════

    def get_settlements(self, start_date, end_date, transaction_type=None,
                        transaction_types=None, page=0, size=500):
        """Settlements (Satış/İade/İndirim/Komisyon) verisi çek.
        Not: startDate-endDate arası max 15 gün!
        """
        params = {
            'startDate': int(start_date.timestamp() * 1000),
            'endDate': int(end_date.timestamp() * 1000),
            'page': page,
            'size': min(size, 1000),
        }
        if transaction_types:
            params['transactionTypes'] = ','.join(transaction_types)
        elif transaction_type:
            params['transactionType'] = transaction_type

        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/settlements',
            params=params,
        )

    def get_other_financials(self, start_date, end_date, transaction_type=None,
                             transaction_types=None, transaction_sub_type=None,
                             page=0, size=500):
        """OtherFinancials (PlatformHizmetBedeli/Kargo/Ceza/Ödeme) verisi çek."""
        params = {
            'startDate': int(start_date.timestamp() * 1000),
            'endDate': int(end_date.timestamp() * 1000),
            'page': page,
            'size': min(size, 1000),
        }
        if transaction_types:
            params['transactionTypes'] = ','.join(transaction_types)
        elif transaction_type:
            params['transactionType'] = transaction_type
        if transaction_sub_type:
            params['transactionSubType'] = transaction_sub_type

        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/otherfinancials',
            params=params,
        )

    def get_cargo_invoice_items(self, invoice_serial_number, page=0, size=500):
        """Kargo faturası detayları — sipariş bazlı kargo bedelleri."""
        params = {'page': page, 'size': min(size, 500)}
        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/cargo-invoice/{invoice_serial_number}/items',
            params=params,
        )



import base64
import json
import logging
import requests
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TRENDYOL_PROD_URL = 'https://apigw.trendyol.com/integration'
TRENDYOL_STAGE_URL = 'https://stageapigw.trendyol.com/integration'


def ty_timestamp(dt_utc):
    """UTC naive datetime → Trendyol zaman damgası (ms, GMT+3).

    Trendyol sipariş servislerinde tarihler "GMT+3 epoch" olarak gider/gelir: TR yerel saat,
    UTC'ymiş gibi epoch'a çevrilmiş hali (gerçek epoch + 3 saat).
    """
    return int((dt_utc + timedelta(hours=3)).replace(tzinfo=timezone.utc).timestamp() * 1000)


def ty_epoch_ms(dt_utc):
    """UTC naive datetime → GERÇEK epoch (ms).

    Yalnız orderDate "GMT+3 epoch"tur; lastModifiedDate, packageHistories ve
    agreedDeliveryDate gerçek epoch'tur. Akış servisinin lastModified filtresi de
    gerçek epoch ister (+3 saat kaydırılırsa pencere ileride kalır ve akış boş döner).
    """
    return int(dt_utc.replace(tzinfo=timezone.utc).timestamp() * 1000)


def ty_datetime(ts_ms):
    """Trendyol GMT+3 zaman damgası (ms) → UTC naive datetime (Odoo'nun beklediği)."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).replace(tzinfo=None) - timedelta(hours=3)


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
            # Doküman: yazılım firmanın kendisine aitse "SatıcıId - SelfIntegration"
            'User-Agent': f'{seller_id} - SelfIntegration',
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
            # Başarılı istekler DEBUG: her senkronda onlarca satır log'u boğuyordu; hatalar aşağıda loglanır
            _logger.debug("Trendyol API %s %s → %s", method, url, resp.status_code)
            if resp.status_code == 200:
                try:
                    return {'success': True, 'data': resp.json()}
                except Exception:
                    return {'success': True, 'data': resp.text}
            else:
                _logger.error("Trendyol API hata: %s %s", resp.status_code, resp.text[:500])
                return {'success': False, 'status': resp.status_code,
                        'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Bağlantı zaman aşımı'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Bağlantı hatası'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def test_connection(self):
        """Basit bağlantı testi — son 1 siparişi çek."""
        return self._request('GET', f'/order/sellers/{self.seller_id}/v2/orders', params={'size': 1})

    def get_orders(self, status=None, start_date=None, end_date=None, page=0, size=50, order_number=None):
        """Sipariş paketlerini çek (v2 — eski /orders 15 Ekim 2026'da kapanıyor).

        start_date / end_date: UTC naive datetime. Aralık en fazla 14 gün olabilir.
        """
        params = {
            'page': page,
            'size': min(size, 200),
            'orderByField': 'PackageLastModifiedDate',
            'orderByDirection': 'DESC',
        }
        if status:
            params['status'] = status
        if start_date:
            params['startDate'] = ty_timestamp(start_date)
        if end_date:
            params['endDate'] = ty_timestamp(end_date)
        if order_number:
            params['orderNumber'] = order_number

        return self._request('GET', f'/order/sellers/{self.seller_id}/v2/orders', params=params)

    def get_orders_stream(self, modified_start, modified_end, next_cursor=None, size=200):
        """Son güncellenme tarihine göre TÜM statülerdeki paketler (cursor tabanlı akış).

        Trendyol'un periyodik senkron için önerdiği servis. Aralık en fazla 14 gün;
        filtreler aynı akış boyunca değiştirilmemelidir (değişirse 400).
        """
        params = {
            'lastModifiedStartDate': ty_epoch_ms(modified_start),
            'lastModifiedEndDate': ty_epoch_ms(modified_end),
            'size': min(size, 200),
        }
        if next_cursor:
            params['nextCursor'] = next_cursor
        return self._request('GET', f'/order/sellers/{self.seller_id}/orders/stream', params=params)

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

    # ═══════════════════════════════════════════════════════
    # FİNANSAL API
    # ═══════════════════════════════════════════════════════

    def get_settlements(self, start_date=None, end_date=None, transaction_type=None,
                        transaction_types=None, page=0, size=500, payment_order_id=None):
        """Settlements (Satış/İade/İndirim/Komisyon) verisi çek.
        Not: startDate-endDate arası max 15 gün! paymentOrderId verilirse tarih gerekmez.
        """
        params = {
            'page': page,
            'size': 1000 if size >= 1000 else 500,  # yalnız 500 / 1000 kabul edilir
        }
        if payment_order_id:
            params['paymentOrderId'] = payment_order_id
        else:
            params['startDate'] = int(start_date.timestamp() * 1000)
            params['endDate'] = int(end_date.timestamp() * 1000)
        if transaction_types:
            params['transactionTypes'] = ','.join(transaction_types)
        elif transaction_type:
            params['transactionType'] = transaction_type

        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/settlements',
            params=params,
        )

    def get_other_financials(self, start_date=None, end_date=None, transaction_type=None,
                             transaction_types=None, transaction_sub_type=None,
                             page=0, size=500, payment_order_id=None):
        """OtherFinancials (PlatformHizmetBedeli/Kargo/Ceza/Ödeme/Stopaj) verisi çek."""
        params = {
            'page': page,
            'size': 1000 if size >= 1000 else 500,
        }
        if payment_order_id:
            params['paymentOrderId'] = payment_order_id
        else:
            params['startDate'] = int(start_date.timestamp() * 1000)
            params['endDate'] = int(end_date.timestamp() * 1000)
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

    def get_payment_orders(self, page=0, size=10):
        """Ödenmiş (PAID) hakediş ödeme emirleri — sayfa başına en fazla 10 kayıt."""
        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/payment-order',
            params={'page': page, 'size': min(size, 10)},
        )

    def get_cargo_invoice_items(self, invoice_serial_number, page=0, size=500):
        """Kargo faturası detayları — sipariş bazlı kargo bedelleri."""
        params = {'page': page, 'size': min(size, 500)}
        return self._request(
            'GET',
            f'/finance/che/sellers/{self.seller_id}/cargo-invoice/{invoice_serial_number}/items',
            params=params,
        )

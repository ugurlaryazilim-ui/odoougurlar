import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import requests

_logger = logging.getLogger(__name__)

N11_API_URL = 'https://api.n11.com'
N11_RETURN_SOAP_URL = 'https://api.n11.com/ws/returnService/'
N11_PAGE_SIZE = 100          # shipmentPackages için n11 üst sınırı
N11_MAX_WINDOW_DAYS = 15     # n11 tek sorguda en fazla 15 günlük veri döner
_RETRY_STATUSES = (429, 500, 502, 503, 504)


def n11_ms(dt):
    """Odoo naive UTC datetime → n11 epoch milisaniye.

    n11 tarihleri gerçek epoch'tur (ör. agreedDeliveryDate = TR saatiyle 23:59:59.999);
    Trendyol'daki gibi +3 saat kaydırma yoktur."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def n11_datetime(value):
    """n11 epoch (ms; eski kayıtlarda saniye olabilir) → Odoo naive UTC datetime."""
    if value in (None, '', 0, '0'):
        return False
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return False
    if ts > 10 ** 11:  # milisaniye
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _xml_to_dict(elem):
    """Namespace'siz basit XML → dict/list dönüşümü (tekrarlayan etiketler listeye döner)."""
    children = list(elem)
    if not children:
        return (elem.text or '').strip()
    out = {}
    for child in children:
        key = _local(child.tag)
        val = _xml_to_dict(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


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
            'User-Agent': 'Ugurlar-Odoo-N11',
        })

    def _request(self, method, endpoint, params=None, data=None):
        """API Request over Headers Auth (429 / 5xx'te kısa bekleyip iki kez daha dener)."""
        if not self.app_key or not self.app_secret:
            return {'success': False, 'error': 'App Key ve App Secret boş olamaz.'}

        url = f"{N11_API_URL}{endpoint}"
        for attempt in range(3):
            try:
                resp = self._session.request(method, url, params=params, json=data, timeout=45)
            except requests.RequestException as e:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                return {'success': False, 'error': str(e)}

            if 200 <= resp.status_code < 300:
                try:
                    return {'success': True, 'data': resp.json()}
                except ValueError:
                    return {'success': True, 'data': resp.text}
            if resp.status_code in _RETRY_STATUSES and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            _logger.error("N11 API Hata: %s %s %s", resp.status_code, endpoint, resp.text[:500])
            return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}",
                    'status_code': resp.status_code}
        return {'success': False, 'error': 'N11 API yanıt vermedi'}

    def get_shipment_packages(self, start_date=None, end_date=None, status=None, page=0, size=N11_PAGE_SIZE,
                              order_number=None, package_ids=None, by_last_modified=False, direction=None):
        """Sipariş paketlerini çek.

        by_last_modified=True → tarih aralığı paketin lastModifiedDate'ine göre uygulanır
        (durum değişikliklerini yakalamak için). Aralık en fazla 15 gün olabilir."""
        params = {'page': page, 'size': min(int(size or N11_PAGE_SIZE), N11_PAGE_SIZE)}
        if order_number:
            params['orderNumber'] = order_number
        if package_ids:
            params['packageIds'] = package_ids
        if start_date:
            params['startDate'] = n11_ms(start_date) if isinstance(start_date, datetime) else int(start_date)
        if end_date:
            params['endDate'] = n11_ms(end_date) if isinstance(end_date, datetime) else int(end_date)
        if status:
            params['status'] = status
        if by_last_modified:
            params['orderByField'] = 'true'
        if direction:
            params['orderByDirection'] = direction
        return self._request('GET', '/rest/delivery/v1/shipmentPackages', params=params)

    def get_order_packages(self, order_number):
        """Bir siparişin tüm paketleri (bölünmüş paketler dahil). Liste ya da hata dict'i döner."""
        packages = []
        page = 0
        while True:
            res = self.get_shipment_packages(order_number=order_number, page=page)
            if not res.get('success'):
                return res
            data = res.get('data') or {}
            content = data if isinstance(data, list) else (data.get('content') or [])
            packages.extend(content)
            total_pages = data.get('totalPages', 1) if isinstance(data, dict) else 1
            page += 1
            if not content or page >= (total_pages or 1):
                break
        return {'success': True, 'data': packages}

    # ─── Shipment & Other APIs ────────────────────────────────────────────────────────

    def update_order_status_to_picking(self, line_ids):
        """Sipariş kalemlerini onaylar (Created → Picking).

        Dönen 'lines' sözlüğü: {lineId: (başarılı_mı, açıklama)}"""
        data = {
            "lines": [{"lineId": int(line_id)} for line_id in line_ids],
            "status": "Picking",
        }
        res = self._request('PUT', '/rest/order/v1/update', data=data)
        if not res.get('success'):
            return res
        results = {}
        body = res.get('data') or {}
        for item in (body.get('content') or []) if isinstance(body, dict) else []:
            ok = str(item.get('status') or '').upper() == 'SUCCESS'
            results[str(item.get('lineId'))] = (ok, item.get('reasons') or '')
        res['lines'] = results
        return res

    # ─── İade (SOAP ReturnService) ───────────────────────────────────────────────────

    def get_claim_returns(self, start_date, end_date, page=0, status='ALL'):
        """ClaimReturnList — iade talepleri. Tarihler date nesnesi (dd/MM/yyyy gönderilir).

        Dönüş: {'success', 'data': [claim dict], 'page_count'}"""
        if not self.app_key or not self.app_secret:
            return {'success': False, 'error': 'App Key ve App Secret boş olamaz.'}
        body = (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:sch="http://www.n11.com/ws/schemas"><soapenv:Header/><soapenv:Body>'
            '<sch:ClaimReturnListRequest>'
            f'<auth><appKey>{escape(self.app_key)}</appKey><appSecret>{escape(self.app_secret)}</appSecret></auth>'
            f'<searchData><status>{escape(status)}</status>'
            f'<period><startDate>{start_date:%d/%m/%Y}</startDate><endDate>{end_date:%d/%m/%Y}</endDate></period>'
            '</searchData>'
            f'<pagingData><currentPage>{int(page)}</currentPage></pagingData>'
            '</sch:ClaimReturnListRequest></soapenv:Body></soapenv:Envelope>'
        )
        try:
            resp = requests.post(N11_RETURN_SOAP_URL, data=body.encode('utf-8'), timeout=60, headers={
                'Content-Type': 'text/xml; charset=utf-8', 'User-Agent': 'Ugurlar-Odoo-N11'})
        except requests.RequestException as e:
            return {'success': False, 'error': str(e)}
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:300]}"}

        response = next((el for el in root.iter() if _local(el.tag) == 'ClaimReturnListResponse'), None)
        if response is None:
            fault = next((el for el in root.iter() if _local(el.tag) == 'faultstring'), None)
            return {'success': False, 'error': (fault.text if fault is not None else resp.text[:300])}
        data = _xml_to_dict(response)
        result = data.get('result') or {}
        if isinstance(result, dict) and str(result.get('status', '')).lower() not in ('success', ''):
            return {'success': False, 'error': f"{result.get('errorCode', '')} {result.get('errorMessage', '')}".strip()}
        claims = (data.get('claimReturnList') or {})
        claims = claims.get('claimReturn', []) if isinstance(claims, dict) else []
        if isinstance(claims, dict):
            claims = [claims]
        paging = data.get('pagingData') or {}
        try:
            page_count = int(paging.get('pageCount') or 1)
        except (TypeError, ValueError):
            page_count = 1
        return {'success': True, 'data': claims, 'page_count': page_count}

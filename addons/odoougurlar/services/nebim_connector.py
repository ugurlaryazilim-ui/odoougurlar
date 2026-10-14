import logging
import json
import re
import time

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Nebim oturum anahtarı URL'de taşınır: (S(<SessionID>)). Log'a ve kullanıcıya görünen hata
# alanlarına (sipariş/fatura yanıtı, sync log) düşmesin.
_SESSION_RE = re.compile(r'\(S\([^)]*\)\)')


def _mask(text):
    """URL / hata metnindeki Nebim oturum anahtarını gizler."""
    return _SESSION_RE.sub('(S(***))', str(text))


# Veri değiştiren SP'ler: yanıt alınamasa da Nebim'de çalışmış olabilir, yeniden gönderilmez
_NON_IDEMPOTENT_SPS = ('sp_GetNextExportFileNumber', 'sp_DeleteOrder')


def _request_not_delivered(exc):
    """İstek Nebim'e hiç ulaşmadı mı? (yalnız o zaman yeniden göndermek güvenli)

    Okuma zaman aşımı, bağlantının yanıt ortasında kopması veya HTTP 5xx'te Nebim belgeyi
    kaydetmiş olabilir: aynı siparişi / faturayı ikinci kez göndermek mükerrer belge demek.
    """
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = repr(exc)
        return any(k in text for k in ('NewConnectionError', 'Connection refused',
                                       'Name or service not known', 'Failed to establish'))
    return False


def _session_rejected(exc):
    """Nebim oturumu reddetti mi? (süresi dolmuş SessionID: belge işlenmemiştir)"""
    resp = getattr(exc, 'response', None)
    if resp is None or resp.status_code < 400:
        return False
    body = (resp.text or '')[:2000].lower()
    return 'session' in body and any(k in body for k in ('expired', 'invalid', 'not found', 'timeout',
                                                         'geçersiz', 'süresi'))


def _http_error_detail(exc):
    """HTTP hatasında Nebim'in kendi mesajını (gövde) da göster; oturum anahtarı maskeli."""
    resp = getattr(exc, 'response', None)
    body = ''
    if resp is not None:
        try:
            data = resp.json()
            if isinstance(data, dict):
                body = data.get('ExceptionMessage') or data.get('Message') or ''
        except Exception:
            body = (resp.text or '')[:300]
    return _mask(f'{exc} {body}'.strip())

# Timeout for HTTP requests (seconds)
CONNECT_TIMEOUT = 8       # Connect/login — kısa tutulmalı
DATA_TIMEOUT = 300         # Veri gönder/al — tüm ürünleri çekmek uzun sürer
MAX_RETRIES = 2            # 2 deneme yeterli (toplam maks ~25s)

# Session token cache: (token, expiry_timestamp)
_session_cache = {'token': None, 'expires': 0}
SESSION_TTL = 300  # 5 dakika

# HTTP connection pooling — TCP bağlantıları yeniden kullanılır
_http_session = requests.Session()
_http_session.headers.update({'Content-Type': 'application/json'})


class NebimConnector(models.AbstractModel):
    """
    Nebim V3 IntegratorService API bağlantı katmanı.
    
    URL Yapısı (Postman ile doğrulanmış):
      Connect : POST {base}/IntegratorService/Connect
      RunProc : POST {base}/(S({SessionID}))/IntegratorService/RunProc
    
    Örnek:
      Connect  = http://192.168.0.225:9091/IntegratorService/Connect
      RunProc  = http://192.168.0.225:9091/(S(aaj1b0mzmp84mo))/IntegratorService/RunProc
    """
    _name = 'odoougurlar.nebim.connector'
    _description = 'Nebim V3 API Connector'

    @api.private
    def _get_config(self):
        """Nebim bağlantı ayarlarını ir.config_parameter'dan okur."""
        ICP = self.env['ir.config_parameter'].sudo()
        config = {
            'url': ICP.get_param('odoougurlar.nebim_url', ''),
            'database': ICP.get_param('odoougurlar.nebim_database', 'UGURLAR'),
            'user_group': ICP.get_param('odoougurlar.nebim_user_group', 'ADM'),
            'username': ICP.get_param('odoougurlar.nebim_username', 'INT2'),
            'password': ICP.get_param('odoougurlar.nebim_password', ''),
            'model_type': int(ICP.get_param('odoougurlar.nebim_model_type', '1')),
        }
        if not config['url']:
            raise UserError('Nebim API URL yapılandırılmamış! Ayarlar > Nebim bölümünden URL girin.')
        return config

    @api.private
    def _get_sp_name(self, key):
        """Stored procedure adını ayarlardan okur."""
        ICP = self.env['ir.config_parameter'].sudo()
        defaults = {
            'item_details': 'sp_GetItemDetails_Hamurlabs',
            'inventory': 'sp_GetInventory_Hamurlabs',
            'item_attribute': 'sp_GetItemAttributeType_Hamurlabs',
            'customer': 'sp_GetCustomer_Hamurlabs',
            'country': 'sp_GetCountry_Hamurlabs',
            'district': 'sp_GetDistrict_Hamurlabs',
            'vendor': 'sp_GetVendorInfo_Hamurlabs',
            'warehouse': 'sp_GetWarehouseInfo_Hamurlabs',
        }
        param_name = f'odoougurlar.nebim_sp_{key}'
        return ICP.get_param(param_name, defaults.get(key, ''))

    @api.private
    def _get_root_url(self, url):
        """
        URL'den root kısmını alır (IntegratorService öncesi).
        
        Örnek:
            http://192.168.0.225:9091/IntegratorService
            → http://192.168.0.225:9091
        """
        url = url.rstrip('/')
        if '/IntegratorService' in url:
            return url.split('/IntegratorService')[0]
        parts = url.rsplit('/', 1)
        return parts[0] if len(parts) == 2 else url

    @api.private
    def _connect(self, force=False):
        """
        Nebim IntegratorService'e bağlanır ve session token döner.
        Token cache'lenir (5dk TTL); force=True ile zorunlu yenileme.
        
        URL: POST {base_url}/Connect
        
        Returns:
            str: SessionID
        """
        global _session_cache

        # Cached token varsa ve süresi dolmamışsa kullan
        if not force and _session_cache['token'] and time.time() < _session_cache['expires']:
            return _session_cache['token']

        config = self._get_config()
        url = f"{config['url'].rstrip('/')}/Connect"
        payload = {
            'ModelType': config['model_type'],
            'DatabaseName': config['database'],
            'UserGroupCode': config['user_group'],
            'UserName': config['username'],
            'Password': config['password'],
        }

        _logger.info("Nebim bağlantısı kuruluyor: %s", url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = _http_session.post(url, json=payload, timeout=CONNECT_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()

                # Nebim yanıtından SessionID'yi çıkar
                if isinstance(data, dict):
                    token = data.get('SessionID') or data.get('Token') or data.get('sessionID', '')
                elif isinstance(data, str):
                    token = data
                else:
                    token = str(data)

                if not token:
                    raise UserError('Nebim bağlantısı başarılı ama SessionID alınamadı!')

                _logger.info("Nebim bağlantısı başarılı (deneme %d/%d)", attempt, MAX_RETRIES)

                # Token'ı cache'le
                _session_cache['token'] = token
                _session_cache['expires'] = time.time() + SESSION_TTL
                return token

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim bağlantı hatası (deneme %d/%d): %s",
                    attempt, MAX_RETRIES, _mask(e)
                )
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s
                else:
                    raise Exception(f'Nebim bağlantı hatası ({MAX_RETRIES} deneme sonrası): {_mask(e)}')

    @api.private
    def _build_session_url(self, token, endpoint):
        """
        SessionID ile doğru Nebim URL'ini oluşturur.
        
        ASP.NET cookieless session formatı: (S({SessionID}))
        
        Örnek:
            token    = aaj1b0mzmp84modbfmyona
            endpoint = RunProc
            → http://192.168.0.225:9091/(S(aaj1b0mzmp84modbfmyona))/IntegratorService/RunProc
        """
        config = self._get_config()
        root_url = self._get_root_url(config['url'])
        return f"{root_url}/(S({token}))/IntegratorService/{endpoint}"

    def run_proc(self, proc_name, params=None):
        """
        Nebim üzerinde stored procedure çalıştırır.
        
        URL: POST {root}/(S({SessionID}))/IntegratorService/RunProc
        Body: { ProcName, Parameters: [{Name, Value}] }
        """
        token = self._connect()
        url = self._build_session_url(token, 'RunProc')

        payload = {'ProcName': proc_name}
        if params:
            payload['Parameters'] = params

        headers = {}

        _logger.info("Nebim SP çalıştırılıyor: %s → %s", proc_name, _mask(url))
        idempotent = not str(proc_name).startswith(_NON_IDEMPOTENT_SPS)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = _http_session.post(
                    url, json=payload, headers=headers, timeout=(CONNECT_TIMEOUT, DATA_TIMEOUT)
                )
                resp.raise_for_status()
                result = resp.json()
                _logger.info(
                    "Nebim SP başarılı: %s - %d kayıt",
                    proc_name,
                    len(result) if isinstance(result, list) else 1
                )
                return result

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim SP hatası (deneme %d/%d): %s - %s",
                    attempt, MAX_RETRIES, proc_name, _http_error_detail(e)
                )
                retry = idempotent or _request_not_delivered(e) or _session_rejected(e)
                if attempt < MAX_RETRIES and retry:
                    # Session expire olmuş olabilir → yenile
                    token = self._connect(force=True)
                    url = self._build_session_url(token, 'RunProc')
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Nebim SP çalıştırma hatası ({proc_name}): {_http_error_detail(e)}')

    def post_data(self, endpoint, payload):
        """
        Nebim'e veri gönderir (fatura, müşteri vb.).
        
        URL: POST {root}/(S({SessionID}))/IntegratorService/{endpoint}
        """
        token = self._connect()
        url = self._build_session_url(token, endpoint)

        headers = {}

        _logger.info("Nebim'e veri gönderiliyor: %s → %s", endpoint, _mask(url))

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = _http_session.post(
                    url, json=payload, headers=headers, timeout=(CONNECT_TIMEOUT, DATA_TIMEOUT)
                )
                resp.raise_for_status()
                result = resp.json()
                _logger.info("Nebim veri gönderimi başarılı: %s", endpoint)
                return result

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim veri gönderim hatası (deneme %d/%d): %s",
                    attempt, MAX_RETRIES, _http_error_detail(e)
                )
                # Yalnız istek Nebim'e ulaşmadıysa / oturum reddedildiyse yeniden gönder:
                # okuma zaman aşımında belge kaydedilmiş olabilir (mükerrer sipariş / e-fatura)
                if attempt < MAX_RETRIES and (_request_not_delivered(e) or _session_rejected(e)):
                    token = self._connect(force=True)
                    url = self._build_session_url(token, endpoint)
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Nebim veri gönderim hatası ({endpoint}): {_http_error_detail(e)}')

    def delete_data(self, payload):
        """
        Nebim'den kayıt siler (sipariş, fatura vb.).
        
        ÖNEMLİ: HTTP DELETE metodu kullanılır (POST DEĞİL!).
        POST ile "Object deleted successfully" sahte yanıt döner ama silmez.
        HTTP DELETE ile gerçek silme işlemi yapılır.
        
        URL: DELETE {root}/(S({SessionID}))/IntegratorService/Delete
        
        Payload örneği (sipariş silme):
            {
                "ModelType": 13,
                "InternalDescription": "#2066",
                "DocumentNumber": "#2066",
                "OfficeCode": "M",
                "StoreCode": "002",
                "WarehouseCode": "002",
                "CurrAccCode": "1-4-168457",
                "CustomerCode": "1-4-168457"
            }
        """
        token = self._connect()
        url = self._build_session_url(token, 'Delete')

        _logger.info("Nebim'den siliniyor: HTTP DELETE → %s | Belge: %s", _mask(url), payload.get('DocumentNumber', ''))

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # ÖNEMLİ: HTTP DELETE metodu — POST sahte success döner!
                resp = _http_session.delete(
                    url, json=payload, timeout=30
                )
                
                # Yanıt parse
                try:
                    result = resp.json()
                except Exception:
                    result = {'raw': resp.text, 'status_code': resp.status_code}
                
                _logger.info("Nebim Delete yanıtı: HTTP %d | Body: %s", 
                           resp.status_code, json.dumps(result, ensure_ascii=False)[:300])

                # HTTP hata kontrolü
                if resp.status_code >= 400:
                    error_body = resp.text[:500]
                    _logger.error("Nebim Delete HTTP %d: %s", resp.status_code, error_body)
                    raise Exception(f"Nebim Delete HTTP {resp.status_code}: {error_body}")
                
                # Nebim kendi hata mesajını döndürebilir
                if isinstance(result, dict) and result.get('ExceptionMessage'):
                    raise Exception(f"Nebim Delete Hatası: {result['ExceptionMessage']}")
                
                _logger.info("Nebim silme başarılı: %s (HTTP %d)", 
                           payload.get('DocumentNumber', ''), resp.status_code)
                return result

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim silme hatası (deneme %d/%d): %s",
                    attempt, MAX_RETRIES, _mask(e)
                )
                if attempt < MAX_RETRIES and (_request_not_delivered(e) or _session_rejected(e)):
                    token = self._connect(force=True)
                    url = self._build_session_url(token, 'Delete')
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Nebim silme hatası (Delete): {_mask(e)}')



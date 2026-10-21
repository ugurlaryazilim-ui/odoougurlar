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


class NebimTimeoutError(Exception):
    """Nebim ucu yanıt vermedi (okuma / bağlantı zaman aşımı) ya da zincir süre bütçesi doldu.

    DIKKAT: `except Exception` ile yutulan işlem sıradaki çağrıya geçer ve asılı uçta her çağrı
    tam timeout kadar bekler. İş hatalarını yutan işlemciler bu istisnayı yeniden fırlatmalıdır
    (`except NebimTimeoutError: raise`); zinciri başlatan kod ilk zaman aşımında kalan aşamaları atlar.
    """


def chain_timeout(env, exc):
    """True: `exc` zaman aşımı VE çağıran süre bütçeli bir zincirde (context `nebim_deadline`) -> yutmayıp
    yeniden fırlat. NEDEN: cron yolu (deadline yok) eski yutma davranışını korur."""
    return isinstance(exc, NebimTimeoutError) and env.context.get('nebim_deadline') is not None


# Veri değiştiren (YAZMA) SP'ler: yanıt alınamasa da Nebim'de çalışmış olabilir; yeniden gönderilmez ve
# zincir süre bütçesiyle kısaltılmaz. Yeni yazma SP'si eklenirse buraya yazılmalı (ad tahmini yapılmaz).
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
# NEDEN: Depo telefonları JSON-RPC ile bekler ve HTTP worker sayısı sınırlı (10); Nebim asılı kalınca
# 300 sn x 2 deneme bir worker'ı ~10 dk tutuyordu. Varsayılan (cron / toplu içe aktarma) 300 sn, 2 deneme kalır;
# etkileşimli çağıran `timeout=` / `retries=` verir ya da `with_context(nebim_timeout=..., nebim_retries=0)` ile
# zincire yayar. Not: timeout yalnız ÇAĞRI BAŞINA okuma süresidir; zincirde birden çok çağrı olduğundan
# toplam süre `nebim_deadline` context'i ile ayrıca sınırlanır (aşağıda).
INTERACTIVE_TIMEOUT = 15   # Mağaza / depo ekranı okuma uçları (yeniden deneme yok)
WRITE_CHAIN_TIMEOUT = 60   # Paketleme cari / sipariş / fatura zinciri: çağrı başına (HTTP isteği içinde)
# NEDEN: çağrı başına timeout zincirin toplamını sınırlamaz (cari 5 + sipariş 1 + fatura 1-2 çağrı =
# asılı Nebim'de ~7 x 60 sn worker). Zinciri başlatan kod `nebim_deadline` (time.monotonic mutlak zamanı)
# context'ini verir; OKUMA çağrısının timeout'u kalan süreyle kısalır, süre bitince ağa çıkılmaz. YAZMA
# (Post, _NON_IDEMPOTENT_SPS) kısaltılmaz: ya tam timeout ile başlar ya hiç başlamaz (bkz. _timeouts).
# Context yoksa (cron / toplu içe aktarma) davranış değişmez.
MIN_CALL_BUDGET = 0.2      # kalan süre bundan azsa ağ çağrısı başlatılmaz

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
    def _connect(self, force=False, retries=None):
        """
        Nebim IntegratorService'e bağlanır ve session token döner.
        Token cache'lenir (5dk TTL); force=True ile zorunlu yenileme.
        retries: ilk denemeden sonraki ek deneme sayısı (None = context `nebim_retries`, o da yoksa varsayılan;
        0 = yeniden deneme yok).

        URL: POST {base_url}/Connect

        Returns:
            str: SessionID
        """
        global _session_cache
        max_attempts = self._max_attempts(retries)

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

        for attempt in range(1, max_attempts + 1):
            connect_timeout = self._timeouts(CONNECT_TIMEOUT, 'Connect')[1]
            try:
                resp = _http_session.post(url, json=payload, timeout=connect_timeout)
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

                _logger.info("Nebim bağlantısı başarılı (deneme %d/%d)", attempt, max_attempts)

                # Token'ı cache'le
                _session_cache['token'] = token
                _session_cache['expires'] = time.time() + SESSION_TTL
                return token

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim bağlantı hatası (deneme %d/%d): %s",
                    attempt, max_attempts, _mask(e)
                )
                if attempt < max_attempts:
                    time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s
                else:
                    raise self._failure(e, f'Nebim bağlantı hatası ({max_attempts} deneme sonrası): {_mask(e)}')

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

    @api.private
    def _max_attempts(self, retries):
        """Azami deneme: açık `retries` > context `nebim_retries` > MAX_RETRIES (ek deneme sayısı; 0 = tek deneme)."""
        if retries is None:
            retries = self.env.context.get('nebim_retries')
        return MAX_RETRIES if retries is None else retries + 1

    @api.private
    def _timeouts(self, read_timeout, what, write=False):
        """(bağlantı, okuma) zaman aşımı; context `nebim_deadline` varsa OKUMA kalan süreyle kısaltılır.
        Süre yetmiyorsa ağ çağrısı yapmadan NebimTimeoutError.

        write=True (belge / kayıt oluşturan çağrı): kısaltılmaz; kalan süre `read_timeout`'tan azsa hiç başlamaz.
        DIKKAT: kısaltılmış süreyle başlayan yazmada Nebim belgeyi kaydedip yanıtı yetiştiremezse
        nebim_sent / cari kodu yazılmaz ve tekrar denemede belge ikinci kez açılır (mükerrer fatura / cari, K-1).
        NEDEN (bedel): yazma bütçenin son `read_timeout` saniyesinde başlamaz (sipariş sonraki Tamamla / cron'a
        kalır); başlayan yazma tam süreyle biter, zincir toplamı en kötü deadline + CONNECT_TIMEOUT olur.

        DIKKAT: requests zaman aşımı TOPLAM değil, soket okuma başınadır; bayt bayt yanıtlayan bir uç
        bütçeyi aşabilir. Asılı (hiç yanıt vermeyen) uç için sınır tutar."""
        deadline = self.env.context.get('nebim_deadline')
        if deadline is None:
            return CONNECT_TIMEOUT, read_timeout
        left = deadline - time.monotonic()
        if left < (read_timeout if write else MIN_CALL_BUDGET):
            raise NebimTimeoutError(f'Nebim zincir süre bütçesi doldu, çağrı yapılmadı ({what})')
        if write:
            return CONNECT_TIMEOUT, read_timeout
        return min(CONNECT_TIMEOUT, left), min(read_timeout, left)

    @staticmethod
    def _failure(exc, message):
        """Ağ hatasının istisnası: zaman aşımı ayrı türde (zincir atlama kararı için)."""
        return (NebimTimeoutError if isinstance(exc, requests.exceptions.Timeout) else Exception)(message)

    @api.private
    def _call_policy(self, timeout, retries):
        """(okuma zaman aşımı, azami deneme) — açık parametre > context (`nebim_timeout` / `nebim_retries`) > varsayılan."""
        timeout = timeout or self.env.context.get('nebim_timeout') or DATA_TIMEOUT
        return timeout, self._max_attempts(retries)

    def run_proc(self, proc_name, params=None, timeout=None, retries=None):
        """
        Nebim üzerinde stored procedure çalıştırır.

        URL: POST {root}/(S({SessionID}))/IntegratorService/RunProc
        Body: { ProcName, Parameters: [{Name, Value}] }

        timeout: okuma zaman aşımı sn (None = context `nebim_timeout`, o da yoksa 300).
        retries: ilk denemeden sonraki ek deneme sayısı (None = context `nebim_retries`, o da yoksa
        varsayılan 1; 0 = yeniden deneme yok).
        """
        timeout, max_attempts = self._call_policy(timeout, retries)
        # Yazma / okuma ayrımı açık listeden (_NON_IDEMPOTENT_SPS): yeniden deneme ve süre bütçesi aynı kaynaktan
        idempotent = not str(proc_name).startswith(_NON_IDEMPOTENT_SPS)
        if not idempotent:
            self._timeouts(timeout, proc_name, write=True)   # bütçe yetmiyorsa Connect'e de çıkma
        token = self._connect(retries=retries)
        url = self._build_session_url(token, 'RunProc')

        payload = {'ProcName': proc_name}
        if params:
            payload['Parameters'] = params

        headers = {}

        _logger.info("Nebim SP çalıştırılıyor: %s → %s", proc_name, _mask(url))

        for attempt in range(1, max_attempts + 1):
            call_timeouts = self._timeouts(timeout, proc_name, write=not idempotent)
            try:
                resp = _http_session.post(
                    url, json=payload, headers=headers, timeout=call_timeouts
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
                    attempt, max_attempts, proc_name, _http_error_detail(e)
                )
                retry = idempotent or _request_not_delivered(e) or _session_rejected(e)
                if attempt < max_attempts and retry:
                    # Session expire olmuş olabilir → yenile
                    token = self._connect(force=True, retries=retries)
                    url = self._build_session_url(token, 'RunProc')
                    time.sleep(2 ** attempt)
                else:
                    raise self._failure(e, f'Nebim SP çalıştırma hatası ({proc_name}): {_http_error_detail(e)}')

    def post_data(self, endpoint, payload, timeout=None, retries=None, write=True):
        """
        Nebim'e veri gönderir (fatura, müşteri vb.).

        URL: POST {root}/(S({SessionID}))/IntegratorService/{endpoint}

        timeout / retries: bkz. run_proc. Yazmada yeniden deneme zaten yalnız istek Nebim'e
        ulaşmadıysa / oturum reddedildiyse yapılır (okuma zaman aşımında asla).
        write: True = yeni belge / kayıt açar; süre bütçesiyle kısaltılmaz (bkz. _timeouts). False yalnız
        mevcut belgeyi güncelleyen (HeaderID'li) çağrı içindir: kesilse de belge çiftlenmez.
        """
        timeout, max_attempts = self._call_policy(timeout, retries)
        if write:
            self._timeouts(timeout, endpoint, write=True)   # bütçe yetmiyorsa Connect'e de çıkma
        token = self._connect(retries=retries)
        url = self._build_session_url(token, endpoint)

        headers = {}

        _logger.info("Nebim'e veri gönderiliyor: %s → %s", endpoint, _mask(url))

        for attempt in range(1, max_attempts + 1):
            call_timeouts = self._timeouts(timeout, endpoint, write=write)
            try:
                resp = _http_session.post(
                    url, json=payload, headers=headers, timeout=call_timeouts
                )
                resp.raise_for_status()
                result = resp.json()
                _logger.info("Nebim veri gönderimi başarılı: %s", endpoint)
                return result

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim veri gönderim hatası (deneme %d/%d): %s",
                    attempt, max_attempts, _http_error_detail(e)
                )
                # Yalnız istek Nebim'e ulaşmadıysa / oturum reddedildiyse yeniden gönder:
                # okuma zaman aşımında belge kaydedilmiş olabilir (mükerrer sipariş / e-fatura)
                if attempt < max_attempts and (_request_not_delivered(e) or _session_rejected(e)):
                    token = self._connect(force=True, retries=retries)
                    url = self._build_session_url(token, endpoint)
                    time.sleep(2 ** attempt)
                else:
                    raise self._failure(e, f'Nebim veri gönderim hatası ({endpoint}): {_http_error_detail(e)}')

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



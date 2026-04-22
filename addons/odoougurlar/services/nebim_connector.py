import logging
import json
import time

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
CONNECT_TIMEOUT = 8       # Connect/login — kısa tutulmalı
DATA_TIMEOUT = 300         # Veri gönder/al — tüm ürünleri çekmek uzun sürer
MAX_RETRIES = 2            # 2 deneme yeterli (toplam maks ~25s)

# Session token cache: (token, expiry_timestamp)
_session_cache = {'token': None, 'expires': 0}
SESSION_TTL = 300  # 5 dakika


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
                resp = requests.post(url, json=payload, timeout=CONNECT_TIMEOUT)
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

                _logger.info("Nebim bağlantısı başarılı (deneme %d/%d), SessionID: %s...",
                             attempt, MAX_RETRIES, str(token)[:20])

                # Token'ı cache'le
                _session_cache['token'] = token
                _session_cache['expires'] = time.time() + SESSION_TTL
                return token

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim bağlantı hatası (deneme %d/%d): %s",
                    attempt, MAX_RETRIES, str(e)
                )
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s
                else:
                    raise Exception(f'Nebim bağlantı hatası ({MAX_RETRIES} deneme sonrası): {str(e)}')

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

        headers = {
            'Content-Type': 'application/json',
        }

        _logger.info("Nebim SP çalıştırılıyor: %s → %s", proc_name, url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    url, json=payload, headers=headers, timeout=DATA_TIMEOUT
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
                    attempt, MAX_RETRIES, proc_name, str(e)
                )
                if attempt < MAX_RETRIES:
                    # Session expire olmuş olabilir → yenile
                    token = self._connect(force=True)
                    url = self._build_session_url(token, 'RunProc')
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Nebim SP çalıştırma hatası ({proc_name}): {str(e)}')

    def post_data(self, endpoint, payload):
        """
        Nebim'e veri gönderir (fatura, müşteri vb.).
        
        URL: POST {root}/(S({SessionID}))/IntegratorService/{endpoint}
        """
        token = self._connect()
        url = self._build_session_url(token, endpoint)

        headers = {
            'Content-Type': 'application/json',
        }

        _logger.info("Nebim'e veri gönderiliyor: %s → %s", endpoint, url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    url, json=payload, headers=headers, timeout=DATA_TIMEOUT
                )
                resp.raise_for_status()
                result = resp.json()
                _logger.info("Nebim veri gönderimi başarılı: %s", endpoint)
                return result

            except requests.exceptions.RequestException as e:
                _logger.warning(
                    "Nebim veri gönderim hatası (deneme %d/%d): %s",
                    attempt, MAX_RETRIES, str(e)
                )
                if attempt < MAX_RETRIES:
                    token = self._connect(force=True)
                    url = self._build_session_url(token, endpoint)
                    time.sleep(2 ** attempt)
                else:
                    raise Exception(f'Nebim veri gönderim hatası ({endpoint}): {str(e)}')

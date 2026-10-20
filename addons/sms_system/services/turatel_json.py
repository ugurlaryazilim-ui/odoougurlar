"""Turatel Platform JSON API istemcisi (platform.turatel.com/singlesms | /bulksms) — Odoo'dan bağımsız.

Bir istemci örneği = bir kimlik seti (userId + kullanıcı adı + şifre) + bir servis URL'si. Kimlik yalnız
``Auth/GetToken`` gövdesinde gider; diğer uçlar ``Authorization: Bearer`` ile çağrılır. Jeton süreç belleğindeki
modül önbelleğinde (kimlik seti + servis başına) tutulur; DB'ye, parametrelere ve loga yazılmaz.

Zarf: ``{isSuccess, errorCode, message, data}`` (anahtarlar büyük/küçük harf duyarsız okunur, ``errorCode`` string).
Hata sınıflaması ``TuratelError(retryable, uncertain)`` ile eski XML istemcisiyle aynıdır (tasarım §2.2, §5.2).
SendSms ve GetStatus satır alan adları belgesizdir: ayrıştırıcı toleranslıdır ve eşleme kuramazsa tahmin yürütmez.
"""
import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import namedtuple
from datetime import timezone

import pytz
import requests

from .turatel import TuratelError, classify_request_exception, mask_number

_logger = logging.getLogger(__name__)

TIMEOUT = (5, 15)          # (bağlanma, okuma) saniye
DEFAULT_VALIDITY = 1260    # dakika (eski XML'deki +21 saat)
MAX_TEXT_LENGTH = 402      # Turkcell concat sınırı (-467); uygulaması çağıranda (C4)
RAW_LIMIT = 2000           # provider_answer sınırı
ROW_RAW_LIMIT = 500
MESSAGE_LIMIT = 200        # Turatel hata mesajından hata metnine alınan en çok karakter
TZ = pytz.timezone('Europe/Istanbul')

AUTH_ERROR = 'Turatel kimlik hatası (kullanıcı adı/şifre/userId ya da jeton reddedildi)'
AUTH_CODES = {'-1'}
STATUS_EMPTY_CODES = {'-6'}   # durum uçlarında "kayıt yok" (C0, belgesiz)
# 301/307/308: hedef taşınmış, istek işlenmeden geri çevrildi (RFC 9110 §15.4). 302/303 işlenmiş olabilir.
REDIRECT_NOT_PROCESSED = frozenset({301, 307, 308})
TOKEN_TTL = 30 * 60        # sn; yanıtta süre yoksa jeton en çok bu kadar önbellekte kalır (Ö2)
TOKEN_MARGIN = 60          # sn; yanıttaki süreden düşülen pay (saat kayması, istek süresi)
TOKEN_MIN_TTL = 30         # sn

SendResult = namedtuple('SendResult', 'packet_id message_ids raw')
StatusRow = namedtuple('StatusRow', 'message_id client_id code raw')

# Uç başına gövde beyaz listesi (OpenAPI şeması; kimlik alanları yalnız GetToken'da)
_SCHEMA = {
    'Auth/GetToken': {'userId', 'username', 'password'},
    'Sms/GetUserAccounts': set(),
    'Sms/GetCredit': {'accountId'},
    'Sms/GetOriginator': {'accountId'},
    'Sms/SendSms': {'accountId', 'referenceId', 'originator', 'sendDate', 'validityPeriod', 'isCheckBlackList',
                    'isEncryptedParameter', 'messageText', 'packetName', 'allowDuplicateReceivers', 'ipAddress',
                    'receiverList', 'personalMessages', 'remoteUserIpAddress'},
    'Sms/GetStatus': {'accountId', 'packetId', 'messageIdList'},
    'Sms/GetStatusByTwoDates': {'accountId', 'startDate', 'endDate'},
}

# ── jeton önbelleği (süreç belleği): anahtar -> (jeton, geçerlilik sonu _clock() cinsinden) ──
_TOKEN_CACHE = {}
_TOKEN_LOCK = threading.Lock()


def clear_token_cache():
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def _clock():
    return time.monotonic()


def _token_lifetime(data):
    """Jetonun önbellekte kalacağı süre (sn): yanıtta sayısal expiresIn/expires_in/expires varsa ondan 60 sn
    eksiği (en az 30 sn, en çok TOKEN_TTL), yoksa TOKEN_TTL. Süre biçimi belgesiz; sayı değilse yok sayılır."""
    value = _ci(data, 'expiresIn', 'expires_in', 'expires')
    if isinstance(value, bool):
        return TOKEN_TTL
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return TOKEN_TTL
    if not math.isfinite(seconds) or seconds <= 0:
        return TOKEN_TTL
    return max(TOKEN_MIN_TTL, min(TOKEN_TTL, seconds - TOKEN_MARGIN))


# ── maskeleme ──
_LONG_DIGITS = re.compile(r'\d{10,}')


def mask_digits(text):
    """10+ haneli her rakam dizisini ``mask_number`` ile maskele (telefon numarası loga/alana girmesin)."""
    return _LONG_DIGITS.sub(lambda m: mask_number(m.group(0)), str(text or ''))


def safe_raw(obj, limit=RAW_LIMIT):
    """Saklanabilir ham yanıt: sıkıştırılmış JSON, uzun rakam dizileri maskeli, ``limit`` karakterle sınırlı."""
    try:
        text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(',', ':'),
                                                            default=str)
    except (TypeError, ValueError):
        text = str(obj)
    return mask_digits(text)[:limit]


# ── yardımcılar ──
def format_date(dt):
    """Turatel tarih biçimi ddMMyyHHmmss (İstanbul). Zaman dilimsiz ``dt`` UTC kabul edilir (Odoo kuralı)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).strftime('%d%m%y%H%M%S')


_GSM7_BASIC = set(
    '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?'
    '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà'
) | set('ıİşŞğĞçÇöÖüÜ')   # Türkçe harfler (Turatel: Türkçe GSM-7, 160 karakter)
_GSM7_EXTENDED = set('^{}\\[~]|€\f')


def json_segment_count(text):
    """JSON modunda tahmini parça: GSM-7 (+Türkçe) 160/153, aksi UCS-2 70/67 (UTF-16 birimi; emoji = 2)."""
    text = text or ''
    if all(ch in _GSM7_BASIC or ch in _GSM7_EXTENDED for ch in text):
        length = sum(2 if ch in _GSM7_EXTENDED else 1 for ch in text)
        single, multi = 160, 153
    else:
        length = len(text.encode('utf-16-le')) // 2
        single, multi = 70, 67
    if length <= single:
        return 1
    return math.ceil(length / multi)


DELIVERY_LABELS = {
    '103': 'SMS yetkisi yok',
    '114': 'Telefon kapalı veya kapsama dışı',
    '-104001': 'Genel kara listede',
    '-8000': 'İYS reddi (ticari izin yok)',
    '-467': 'Metin çok uzun (402 karakter, concat sınırı)',
    '-441': 'Başlık tanımsız',
}


def delivery_state(code):
    """İletim kodu → (durum, etiket). 0 iletildi; bilinen ret kodları iletilemedi; boş bekliyor; diğeri bilinmeyen."""
    key = '' if code is None else str(code).strip()
    if not key:
        return 'pending', 'yanıt bekleniyor'
    if key == '0':
        return 'delivered', 'iletildi'
    if key in DELIVERY_LABELS:
        return 'undelivered', DELIVERY_LABELS[key]
    return 'unknown', 'bilinmeyen (kod %s)' % key


# ── zarf / toleranslı okuma ──
def _ci(mapping, *names):
    """Sözlükten büyük/küçük harf duyarsız ilk bulunan anahtarın değeri."""
    if not isinstance(mapping, dict):
        return None
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _ci_has(mapping, name):
    return isinstance(mapping, dict) and any(str(k).lower() == name.lower() for k in mapping)


def _text(value):
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return value or None


def _first_list(data, keys):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = _ci(data, key)
        if isinstance(value, list):
            return value
    lists = [v for v in data.values() if isinstance(v, list)]
    return lists[0] if len(lists) == 1 else None


def _as_int(value, label):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise TuratelError('Turatel isteği hatalı: %s sayı olmalı' % label) from None


class _AuthFailed(Exception):
    """Sunucu jetonu/kimliği reddetti (-1 ya da HTTP 401); yalnız iç akışta kullanılır."""


class TuratelJsonClient:
    def __init__(self, base_url, user_id, username, password, timeout=TIMEOUT):
        self.base_url = (base_url or '').strip().rstrip('/')
        self.user_id = str(user_id or '').strip()
        self.username = (username or '').strip()
        self._password = password or ''
        self.timeout = timeout

    def __repr__(self):
        return '<TuratelJsonClient %s user=%s>' % (self.base_url, self.user_id)

    # ── jeton ──
    @property
    def _cache_key(self):
        digest = hashlib.sha256(self._password.encode('utf-8')).hexdigest()
        return (self.base_url.lower(), self.user_id, self.username, digest)

    def get_token(self, force=False):
        key = self._cache_key
        if not force:
            with _TOKEN_LOCK:
                cached = _TOKEN_CACHE.get(key)
            if cached and _clock() < cached[1]:
                return cached[0]
        if not (self.base_url and self.user_id and self.username and self._password):
            raise TuratelError('Turatel JSON kullanıcı bilgileri (userId, kullanıcı adı, şifre) eksik.')
        payload = {'userId': _as_int(self.user_id, 'userId'), 'username': self.username,
                   'password': self._password}
        try:
            data, _env = self._request('Auth/GetToken', payload, token=None, reading=True)
        except _AuthFailed:
            raise TuratelError(AUTH_ERROR) from None
        token = _text(_ci(data, 'accessToken', 'token'))
        if not token:
            raise TuratelError('Turatel jeton yanıtı tanımsız.', retryable=True)
        with _TOKEN_LOCK:
            _TOKEN_CACHE[key] = (token, _clock() + _token_lifetime(data))
        return token

    def _invalidate(self, token):
        """Önbellekteki jeton hâlâ reddedilen jetonsa sil (başka iş parçacığının yeni jetonu korunur)."""
        key = self._cache_key
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(key)
            if cached and cached[0] == token:
                del _TOKEN_CACHE[key]

    # ── taşıma ──
    def _post(self, endpoint, payload, token):
        extra = set(payload) - _SCHEMA[endpoint]
        if extra:
            raise ValueError('Turatel %s gövdesinde şema dışı alan: %s' % (endpoint, sorted(extra)))
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        # Yönlendirme izlenmez (G-C3): izlenseydi istek (jeton/şifre) başka adrese, POST da GET'e dönüşerek giderdi
        return requests.post('%s/%s' % (self.base_url, endpoint), json=payload, headers=headers,
                             timeout=self.timeout, allow_redirects=False)

    def _request(self, endpoint, payload, token, reading, empty_codes=()):
        """Tek POST; zarfı çöz ve ``data`` döndür. Kimlik reddi ``_AuthFailed``, diğer hatalar ``TuratelError``.

        reading=True: okuma ucu (ya da SendSms öncesi GetToken) — ağ/HTTP/JSON hataları yeniden denenebilir,
        asla belirsiz değil. reading=False (SendSms): istek gidip gitmediği bilinmeyen her durum belirsiz.
        """
        started = time.monotonic()
        try:
            response = self._post(endpoint, payload, token)
        except requests.RequestException as exc:
            error = classify_request_exception(exc)
            if reading and error.uncertain:
                error = TuratelError('Turatel yanıtı alınamadı (%s).' % exc.__class__.__name__, retryable=True)
            raise error from exc
        status = response.status_code
        if status == 401:
            self._log(endpoint, status, None, None, started)
            raise _AuthFailed()
        if status in REDIRECT_NOT_PROCESSED:
            # İşlenmeden geri çevrildi: SendSms için de belirsiz değil, yeniden denenebilir (adres yanlış olabilir)
            self._log(endpoint, status, None, None, started)
            raise TuratelError('Turatel HTTP %s yönlendirmesi döndü (izlenmedi); servis adresini kontrol edin.'
                               % status, retryable=True)
        if status != 200:
            self._log(endpoint, status, None, None, started)
            if reading:
                raise TuratelError('Turatel HTTP %s döndü.' % status, retryable=True)
            raise TuratelError('Turatel HTTP %s döndü; iletilip iletilmediği belirsiz.' % status, uncertain=True)
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        if not _ci_has(envelope, 'isSuccess'):
            self._log(endpoint, status, None, None, started)
            length = len(getattr(response, 'text', '') or '')
            if reading:
                raise TuratelError('Turatel yanıtı JSON değil (%d karakter).' % length, retryable=True)
            raise TuratelError('Turatel yanıtı JSON değil (%d karakter); iletilip iletilmediği belirsiz.' % length,
                               uncertain=True)
        success = _ci(envelope, 'isSuccess')
        success = success is True or str(success).strip().lower() == 'true'
        code = _text(_ci(envelope, 'errorCode'))
        self._log(endpoint, status, success, code, started)
        if success:
            return _ci(envelope, 'data'), envelope
        if code in AUTH_CODES:
            raise _AuthFailed()
        if code in empty_codes:
            return None, envelope
        raise self._error(code, _text(_ci(envelope, 'message')))

    @staticmethod
    def _error(code, message):
        if code == '-22':
            return TuratelError("Sunucu IP'si Turatel'de yetkili değil (-22)")
        if code == '-1000':
            return TuratelError('Hesap bu Turatel kullanıcısında tanımlı değil (-1000)')
        label = 'Turatel hatası %s' % (code or '(kodsuz)')
        if message:
            return TuratelError('%s: %s' % (label, mask_digits(message)[:MESSAGE_LIMIT]))
        return TuratelError(label)

    def _log(self, endpoint, status, success, code, started, extra=''):
        _logger.debug('Turatel JSON %s %s -> HTTP %s isSuccess=%s errorCode=%s (%.1f sn)%s', self.base_url.rsplit(
            '/', 1)[-1], endpoint, status, success, code, time.monotonic() - started, extra)

    def _call(self, endpoint, payload, reading=True, empty_codes=()):
        """Jetonla çağır; kimlik reddinde 1 yenileme + 1 tekrar (en çok 2 deneme), ikincisi kalıcı hata."""
        for attempt in (1, 2):
            # SendSms öncesi jeton hatası: SMS gitmedi → okuma gibi sınıflanır (yeniden denenebilir)
            token = self.get_token()
            try:
                return self._request(endpoint, payload, token, reading, empty_codes)
            except _AuthFailed:
                self._invalidate(token)
                if attempt == 2:
                    raise TuratelError(AUTH_ERROR) from None
        raise AssertionError('ulaşılamaz')

    # ── okuma uçları ──
    def get_user_accounts(self):
        data, _env = self._call('Sms/GetUserAccounts', {})
        accounts = _first_list(data, ('accounts', 'accountList')) or []
        out = []
        for item in accounts:
            account_id = _text(_ci(item, 'accountId'))
            if account_id:
                out.append({'accountId': account_id, 'accountName': _text(_ci(item, 'accountName')) or ''})
        return out

    def get_originators(self, account_id):
        payload = {'accountId': _as_int(account_id, 'accountId')}
        data, _env = self._call('Sms/GetOriginator', payload)
        items = _first_list(data, ('originatorList', 'originators')) or []
        return [str(x).strip() for x in items if _text(x)]

    def get_credit(self, account_id):
        payload = {'accountId': _as_int(account_id, 'accountId')}
        data, _env = self._call('Sms/GetCredit', payload)
        amount = _ci(data, 'amount', 'credit')
        try:
            return int(amount)
        except (TypeError, ValueError):
            raise TuratelError('Turatel kredi yanıtı tanımsız.', retryable=True) from None

    def get_status(self, account_id, packet_id=None, message_ids=None):
        payload = {'accountId': _as_int(account_id, 'accountId'),
                   'packetId': _as_int(packet_id, 'packetId') if packet_id not in (None, '') else None,
                   'messageIdList': [_as_int(m, 'messageId') for m in message_ids] if message_ids else None}
        data, _env = self._call('Sms/GetStatus', payload, empty_codes=STATUS_EMPTY_CODES)
        return self._status_rows(data)

    def get_status_between(self, account_id, start_dt, end_dt):
        payload = {'accountId': _as_int(account_id, 'accountId'),
                   'startDate': format_date(start_dt), 'endDate': format_date(end_dt)}
        data, _env = self._call('Sms/GetStatusByTwoDates', payload, empty_codes=STATUS_EMPTY_CODES)
        return self._status_rows(data)

    @staticmethod
    def _status_rows(data):
        rows = _first_list(data, ('statusList', 'messages', 'list', 'items', 'reports')) or []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            message_id = _text(_ci(row, 'messageId', 'msgId', 'id'))
            client_id = _text(_ci(row, 'clientId'))
            if not (message_id or client_id):
                continue
            code = _text(_ci(row, 'statusCode', 'status', 'deliveryStatus', 'code'))
            out.append(StatusRow(message_id, client_id, code, safe_raw(row, ROW_RAW_LIMIT)))
        return out

    # ── gönderim ──
    def send_sms(self, account_id, originator, message_text, receivers, *, client_ids, reference_id,
                 parameters=None, check_blacklist=False, validity_minutes=DEFAULT_VALIDITY, packet_name=None):
        receivers = [str(r).strip() for r in (receivers or [])]
        client_ids = [str(c) for c in (client_ids or [])]
        if not receivers:
            raise TuratelError('Turatel isteği hatalı: alıcı yok')
        if len(client_ids) != len(receivers) or len(set(client_ids)) != len(client_ids):
            raise TuratelError('Turatel isteği hatalı: her alıcının tekil bir clientId değeri olmalı')
        if parameters is not None and len(parameters) != len(receivers):
            raise TuratelError('Turatel isteği hatalı: parametre sayısı alıcı sayısına eşit değil')
        if not reference_id:
            raise TuratelError('Turatel isteği hatalı: referenceId boş')
        personal = []
        for i, client_id in enumerate(client_ids):
            item = {'clientId': client_id}
            if parameters is not None:
                item['parameter'] = [str(p) for p in (parameters[i] or [])]
            personal.append(item)
        payload = {
            'accountId': _as_int(account_id, 'accountId'),
            'referenceId': str(reference_id),
            'originator': originator,
            'sendDate': None,
            'validityPeriod': int(validity_minutes or DEFAULT_VALIDITY),
            'isCheckBlackList': bool(check_blacklist),
            'isEncryptedParameter': False,
            'messageText': message_text,
            'packetName': packet_name,
            'allowDuplicateReceivers': False,
            'ipAddress': None,
            'receiverList': receivers,
            'personalMessages': personal,
            'remoteUserIpAddress': None,
        }
        data, envelope = self._call('Sms/SendSms', payload, reading=False)
        packet_id = _text(_ci(data, 'packetId', 'packetID'))
        return SendResult(packet_id, self._map_message_ids(data, client_ids), safe_raw(envelope))

    @staticmethod
    def _map_message_ids(data, client_ids):
        """Mesaj kimliklerini clientId'ye eşle; kurulamazsa {} (tahmin yok, durum cron'u clientId ile eşler)."""
        items = _first_list(data, ('messageIdList', 'messageIds', 'messages', 'messageList', 'results', 'list',
                                   'items'))
        if not items:
            return {}
        if all(not isinstance(x, (dict, list)) for x in items):
            ids = [_text(x) for x in items]
            if len(ids) == len(client_ids) and all(ids):
                return dict(zip(client_ids, ids))
            return {}
        if not all(isinstance(x, dict) for x in items):
            return {}
        wanted = set(client_ids)
        if any(_text(_ci(x, 'clientId')) for x in items):
            out = {}
            for item in items:
                client_id, message_id = _text(_ci(item, 'clientId')), _text(_ci(item, 'messageId', 'msgId', 'id'))
                if client_id in wanted and message_id:
                    out[client_id] = message_id
            return out
        ids = [_text(_ci(x, 'messageId', 'msgId', 'id')) for x in items]
        if len(ids) == len(client_ids) and all(ids):
            return dict(zip(client_ids, ids))
        return {}

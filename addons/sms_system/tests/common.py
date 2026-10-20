"""sms_system test tabanı: HTTP taklidi, cron yamaları ve ortak yardımcılar.

Önemli (tasarım §10): Odoo'nun ağ engeli ``BlockedRequest`` bir ``requests.ConnectionError`` alt sınıfıdır.
Kodumuz ``ConnectionError``'ı "geçici hata" saydığı için gerçek bir ağ denemesi testi sessizce
geçici-hata yoluna sokardı. Bu yüzden:

* ``requests.post`` (turatel.py ve smartadm.py bunu kullanır) ``FakeNet.post`` ile değiştirilir;
* bilinmeyen adrese her çağrı ``AssertionError`` verir ve ``FakeNet.unexpected`` listesine yazılır
  (test bitiminde listenin boş olması denetlenir; kod AssertionError'ı yutsa bile test başarısız olur);
* TransactionCase'te ``requests.Session.send`` de ``AssertionError`` verir (HttpCase'te yamalanmaz:
  ``url_open`` aynı Session'ı kullanır).

``ir.cron._commit_progress`` TransactionCase'te commit yapamaz; yamalanır ve olay listesine yazılır.
"""
import importlib
import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import requests
from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, new_test_user

TURATEL_HOSTS = ('smsorigin.com', 'turatel.com')
SMARTADM_HOSTS = ('smartadm',)


class FakeResponse:
    def __init__(self, status_code=200, text='', payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.content = (text or '').encode('utf-8')
        self.headers = {}
        self.reason = ''

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError('HTTP %s' % self.status_code)

    def json(self):
        if self._payload is None:
            raise ValueError('JSON değil')
        return self._payload


def smart_ok(value=None):
    return FakeResponse(200, '', {'Status': 0, 'StatusCode': 0, 'SubStatusCode': 0, 'Value': value})


def smart_error(code, sub, value=None):
    return FakeResponse(200, '', {'Status': code, 'StatusCode': code, 'SubStatusCode': sub, 'Value': value})


class FakeNet:
    """Turatel (XML) ve SmartADM (JSON) taklidi; tüm çağrıları kaydeder."""

    def __init__(self):
        self.calls = []            # kabul edilen çağrılar
        self.unexpected = []       # bilinmeyen adrese denenen çağrılar
        self.events = []           # sıralı olaylar: ('post', 'turatel'|'smartadm'), ('commit', ...)
        self.turatel_script = []   # sıradaki Turatel sonuçları; boşsa "ID:<n>"
        self.turatel_hook = None   # çağrı anında çalışır: hook(call)
        self.iys = {}              # numara -> '1' (onay) | '0' (ret) | 'missing' (İYS'de yok)
        self.default_iys = '1'
        self.smart_session = None  # None ya da sonuç (hata taklidi)
        self.smart_query = None    # None ya da her /query için sonuç (callable ya da tek değer)
        self.query_cap = None      # bu kadar sorgudan sonra zaman aşımı ver (kırmızı koşuyu kısaltır)
        # İYS kişi kartı akışı: 'missing' numaraya Contact çağrılana kadar trigger/contactapiload -6/-601 döner.
        # smart_<uç>: None ya da o uç için sonuç (callable ya da tek değer); Contact sonrası numara `cards`a girer.
        self.cards = set()
        self.smart_contact = None
        self.smart_trigger = None
        self.smart_load = None
        self.smart_approve = None
        self._seq = 0
        self.tj = FakeTuratelJson(self)   # Turatel JSON API taklidi (platform.turatel.com)

    # ── sorgu yardımcıları ──
    @property
    def turatel_calls(self):
        return [c for c in self.calls if c['kind'] == 'turatel']

    @property
    def smartadm_calls(self):
        return [c for c in self.calls if c['kind'] == 'smartadm']

    @property
    def queried(self):
        return [c['number'] for c in self.smartadm_calls if c['path'] == 'query']

    @property
    def sent_numbers(self):
        out = []
        for call in self.turatel_calls:
            if call.get('command') == '0':
                out.extend(call['numbers'])
        return out

    # ── taklit ──
    @staticmethod
    def _kind(url):
        low = (url or '').lower()
        if any(h in low for h in SMARTADM_HOSTS):
            return 'smartadm'
        if any(h in low for h in TURATEL_HOSTS):
            return 'turatel'
        return None

    @staticmethod
    def _resolve(outcome, call):
        if callable(outcome):
            outcome = outcome(call)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, str):
            return FakeResponse(200, outcome)
        if isinstance(outcome, int):
            return FakeResponse(outcome, '')
        return outcome

    # ── JSON (platform.turatel.com) sorgu yardımcıları ──
    @property
    def json_calls(self):
        return [c for c in self.calls if c['kind'] == 'turatel_json']

    @property
    def json_sends(self):
        return [c for c in self.json_calls if c['endpoint'] == 'Sms/SendSms']

    @property
    def json_endpoints(self):
        return [c['endpoint'] for c in self.json_calls]

    def json_endpoint_calls(self, endpoint):
        return [c for c in self.json_calls if c['endpoint'] == endpoint]

    @property
    def json_sent_receivers(self):
        out = []
        for call in self.json_sends:
            out.extend(call['payload'].get('receiverList') or [])
        return out

    def post(self, url, data=None, **kwargs):
        if 'platform.turatel.com' in (url or '').lower():
            return self.tj.handle(url, data, kwargs)
        kind = self._kind(url)
        text = data.decode('utf-8') if isinstance(data, (bytes, bytearray)) else (data or '')
        call = {'kind': kind, 'url': url, 'body': text, 'timeout': kwargs.get('timeout'),
                'headers': kwargs.get('headers') or {}}
        if kind is None:
            self.unexpected.append(call)
            raise AssertionError('Gerçek ağ isteği denendi: %s' % url)
        if kind == 'turatel':
            match = re.search(r'<Numbers>(.*?)</Numbers>', text)
            call['numbers'] = [n for n in (match.group(1).split(',') if match else []) if n]
            match = re.search(r'<Command>(\d+)</Command>', text)
            call['command'] = match.group(1) if match else None
        else:
            call['path'] = url.rstrip('/').rsplit('/', 1)[-1]
            try:
                call['payload'] = json.loads(text) if text else {}
            except ValueError:
                call['payload'] = {}
            payload = call['payload'] or {}
            value = str(payload.get('Value') or (payload.get('CommunicationTools') or {}).get('Msisdn') or '')
            call['number'] = value[2:] if value.startswith('90') else value
        self.calls.append(call)
        self.events.append(('post', kind))
        if kind == 'turatel':
            return self._turatel(call)
        return self._smartadm(call)

    def _turatel(self, call):
        if self.turatel_hook:
            self.turatel_hook(call)
        self._seq += 1
        outcome = self.turatel_script.pop(0) if self.turatel_script else 'ID:%d' % (1000 + self._seq)
        return self._resolve(outcome, call)

    def smart_calls(self, path):
        return [c for c in self.smartadm_calls if c['path'].lower() == path.lower()]

    @property
    def smart_paths(self):
        return [c['path'].lower() for c in self.smartadm_calls]

    def _smart_missing(self, call):
        return self.iys.get(call['number'], self.default_iys) == 'missing' and call['number'] not in self.cards

    def _smartadm_flow(self, path, call):
        override = {'contact': self.smart_contact, 'trigger': self.smart_trigger,
                    'contactapiload': self.smart_load, 'approve': self.smart_approve}[path]
        if override is not None:
            outcome = self._resolve(override, call)
            if path == 'contact' and outcome.json().get('StatusCode') == 0:
                self.cards.add(call['number'])
            return outcome
        if path == 'contact':
            if call['number'] in self.cards:
                return smart_error(-6, -613)
            self.cards.add(call['number'])
            return smart_ok('CARD')
        if path in ('trigger', 'contactapiload') and self._smart_missing(call):
            return smart_error(-6, -601)
        return smart_ok('TRIG1' if path == 'trigger' else None)

    def _smartadm(self, call):
        path = call['path']
        if path.lower() in ('contact', 'trigger', 'contactapiload', 'approve'):
            return self._smartadm_flow(path.lower(), call)
        if path == 'session':
            if self.smart_session is not None:
                return self._resolve(self.smart_session, call)
            return smart_ok('SESS')
        if path == 'query':
            if self.query_cap is not None and len(self.queried) > self.query_cap:
                return self._resolve(requests.exceptions.ConnectTimeout(), call)
            if self.smart_query is not None:
                return self._resolve(self.smart_query, call)
            status = self.iys.get(call['number'], self.default_iys)
            if status == 'missing':
                if call['number'] in self.cards:   # kart açıldı ama henüz izni yok
                    return smart_ok([{'Authorization': {}}])
                return smart_error(-6, -601)
            return smart_ok([{'Authorization': {'Etk': {'Msisdn': {'Sms': status}}}}])
        if path == 'report2':
            return FakeResponse(200, '', {'Status': 0, 'StatusCode': 0, 'SubStatusCode': 0, 'Value': [],
                                          'MaxPage': 0})
        raise AssertionError('Beklenmeyen SmartADM ucu: %s' % path)


# ───────────────────────────── Turatel JSON API taklidi (C) ─────────────────────────────
# Zarf, GetToken/GetUserAccounts/GetOriginator/GetCredit/-1000/-6 yanıtları GERÇEKTİR (turatel-ornek-yanitlar.md).
# VARSAYIM (belgesiz; C0 yalnız okuma uçlarını denedi): SendSms yanıtı data={'packetId', 'messageIdList'} (sayı listesi,
# receiverList sırasıyla) ya da send_shape='objects' ile data={'packetId', 'messages': [{messageId, clientId}]};
# GetStatus/GetStatusByTwoDates satırı {messageId, clientId, packetId, statusCode, status}; data={'statusList': [...]}
# (ya da status_shape='list' ile çıplak liste). Gerçek alan adları geçiş adımı 3'te doğrulanır (02-tasarim R1).
JSON_BODY_SCHEMA = {   # OpenAPI şemasındaki alanlar, kimlik alanları (userId/username/password) HARİÇ (§5.2: Bearer ile taşınır)
    'Auth/GetToken': {'userId', 'username', 'password'},
    'Sms/GetUserAccounts': set(),
    'Sms/GetCredit': {'accountId'},
    'Sms/GetOriginator': {'accountId'},
    'Sms/SendSms': {'accountId', 'referenceId', 'originator', 'sendDate', 'validityPeriod', 'isCheckBlackList',
                    'isEncryptedParameter', 'messageText', 'packetName', 'allowDuplicateReceivers', 'ipAddress',
                    'receiverList', 'personalMessages', 'remoteUserIpAddress'},
    'Sms/GetStatus': {'accountId', 'packetId', 'messageIdList'},
    'Sms/GetStatusByTwoDates': {'accountId', 'startDate', 'endDate'},
    # Kullanıcı kararı (20.10, Turatel cevabı 4): onay zorunlu hesapta SendSms sonrası paket onayı. Yanıt belgesiz.
    'Sms/ConfirmSms': {'accountId', 'packetId'},
}
CREDENTIAL_KEYS = {'userId', 'username', 'password'}


BULK_SINGLE_RECEIVER_MESSAGE = 'Bulk SMS mode requires more than one valid receiver.'


def json_ok(data=None):
    return {'isSuccess': True, 'errorCode': None, 'message': None, 'data': data}


def json_err(code, message=None):
    return {'isSuccess': False, 'errorCode': str(code), 'message': message, 'data': None}


def tail10(number):
    """Numaranın son 10 hanesi (Turatel'e 5XXXXXXXXX ya da 905XXXXXXXXX gidebilir; sağlayıcı biçimi test dışı)."""
    return re.sub(r'\D', '', str(number or ''))[-10:]


class FakeTuratelJson:
    """platform.turatel.com/{singlesms,bulksms} taklidi: kimlik setleri, jetonlar, hesap yetkisi, durum satırları."""

    def __init__(self, net):
        self.net = net
        self.violations = []          # istek sözleşmesi ihlalleri (KK-C4, C25); teardown'da boş olmalı
        self.users = {                # kullanıcı adı -> kimlik seti
            'info_user': {'password': 'info_pw', 'user_id': '20219', 'accounts': [9254]},
            'com_user': {'password': 'com_pw', 'user_id': '20219', 'accounts': [65672]},
        }
        self.originators = {9254: ['UGURLARGRUP', 'TESTBASLIK'], 65672: ['UGURLARGRUP', 'TESTBASLIK']}
        self.credits = {9254: 90680, 65672: 5000}
        self.script = {}              # uç -> [sonuç | None]; sıradaki çağrı için (None = normal davran)
        self.hook = None              # hook(call): çağrı anında çalışır
        self.send_shape = 'ids'       # 'ids' | 'objects'
        self.status_shape = 'dict'    # 'dict' | 'list'
        self.status_empty = False     # True: durum uçları errorCode "-6" döndürür (gerçek C0 yanıtı)
        self.filter_dates = False     # True: durum satırları yalnız `when` penceredeyse döner
        self.default_code = 0         # yeni mesajın iletim kodu
        self.messages = {}            # messageId -> kayıt (gönderilen)
        self.status_windows = []      # (accountId, startDate, endDate) çağrıları
        self.tokens = {}              # jeton -> kullanıcı adı
        self.tokens_issued = []       # GetToken ile verilen (kullanıcı adı, jeton)
        self.confirmed = []           # ConfirmSms ile onaylanan (accountId, packetId)
        self._ids = 0
        self._packets = 4000

    # ── kurulum yardımcıları ──
    def add_script(self, endpoint, *outcomes):
        self.script.setdefault(endpoint, []).extend(outcomes)

    def expire_tokens(self, username=None):
        """Jetonları geçersiz kıl: sıradaki yetkili istek `-1` alır (jeton süresi doldu)."""
        for token, user in list(self.tokens.items()):
            if username is None or user == username:
                del self.tokens[token]

    def set_code(self, message_id, code):
        """Senaryo kısayolu: 0 → teslim edildi (status 1 + deliveryDate); diğer kod → `reason` (operatör/ret kodu)."""
        msg = self.messages[int(message_id)]
        msg['code'] = code
        msg.pop('status_row', None)

    def set_status(self, message_id, status, reason='', delivery_date=''):
        """Ham GetStatus alanları (canlı veri biçimi): status int, reason ve deliveryDate (ddMMyyHHmmss) metin."""
        self.messages[int(message_id)]['status_row'] = (status, reason, delivery_date)

    @staticmethod
    def status_fields(msg):
        if msg.get('status_row') is not None:
            return msg['status_row']
        if str(msg.get('code')) == '0':
            return 1, '', datetime.now().strftime('%d%m%y%H%M%S')
        return 2, str(msg['code']), ''

    def message_by_client(self, client_id):
        for msg in self.messages.values():
            if msg['client_id'] == client_id:
                return msg
        return None

    # ── sorgu yardımcıları ──
    def calls_to(self, endpoint, service=None):
        return [c for c in self.net.json_calls if c['endpoint'] == endpoint
                and (service is None or c['service'] == service)]

    # ── taklit ──
    def _violate(self, call, text):
        self.violations.append('%s: %s' % (call['endpoint'], text))

    def _check_contract(self, call):
        endpoint, payload, headers = call['endpoint'], call['payload'], call['headers']
        if not isinstance(payload, dict):
            return self._violate(call, 'gövde JSON nesnesi değil')
        if (headers.get('content-type') or '').split(';')[0].strip().lower() != 'application/json':
            self._violate(call, 'Content-Type application/json değil')
        if call['timeout'] is None:
            self._violate(call, 'zaman aşımı verilmemiş')
        if call['allow_redirects'] is not False:
            self._violate(call, 'yönlendirme izlenmemeli (allow_redirects=False, G-C3)')
        if endpoint == 'Sms/AbortSms':
            self._violate(call, 'çağrılmamalı (KK-C25)')
            return
        if endpoint == 'Sms/ConfirmSms' and not all(isinstance(payload.get(k), int) and not isinstance(
                payload.get(k), bool) for k in ('accountId', 'packetId')):
            self._violate(call, 'accountId/packetId sayı olmalı (int32/int64)')
        allowed = JSON_BODY_SCHEMA.get(endpoint)
        if allowed is None:
            self._violate(call, 'tasarımda olmayan uç')
            return
        extra = set(payload) - allowed
        if extra:
            self._violate(call, 'şemada/tasarımda olmayan ya da yasak alan: %s' % sorted(extra))
        if endpoint != 'Auth/GetToken':
            if not (headers.get('authorization') or '').startswith('Bearer '):
                self._violate(call, 'Authorization: Bearer başlığı yok')
            if CREDENTIAL_KEYS & set(payload):
                self._violate(call, 'gövdede kimlik alanı var')
        for key in ('ipAddress', 'remoteUserIpAddress', 'sendDate'):
            if payload.get(key) not in (None, ''):
                self._violate(call, '%s boş olmalı: %r' % (key, payload.get(key)))
        if endpoint == 'Sms/SendSms':
            if payload.get('isEncryptedParameter') not in (False, None):
                self._violate(call, 'isEncryptedParameter false olmalı')
            if payload.get('allowDuplicateReceivers') not in (False, None):
                self._violate(call, 'allowDuplicateReceivers false olmalı')

    @staticmethod
    def _response(outcome):
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, dict):
            return FakeResponse(200, json.dumps(outcome), outcome)
        if isinstance(outcome, str):
            return FakeResponse(200, outcome)
        if isinstance(outcome, int):
            return FakeResponse(outcome, '')
        return outcome

    def handle(self, url, data, kwargs):
        match = re.search(r'/(singlesms|bulksms)/(Auth/GetToken|Sms/[A-Za-z]+)/?$', url or '', re.I)
        if not match:
            self.net.unexpected.append({'kind': 'turatel_json', 'url': url})
            raise AssertionError('Bilinmeyen Turatel JSON adresi: %s' % url)
        payload = kwargs.get('json')
        if payload is None and data:
            try:
                payload = json.loads(data.decode('utf-8') if isinstance(data, (bytes, bytearray)) else data)
            except ValueError:
                payload = None
        headers = {str(k).lower(): v for k, v in (kwargs.get('headers') or {}).items()}
        bearer = (headers.get('authorization') or '')
        bearer = bearer[7:] if bearer.startswith('Bearer ') else None
        call = {'kind': 'turatel_json', 'url': url, 'service': match.group(1).lower(), 'endpoint': match.group(2),
                'payload': payload, 'headers': headers, 'timeout': kwargs.get('timeout'), 'bearer': bearer,
                'allow_redirects': kwargs.get('allow_redirects', True),
                'body': json.dumps(payload) if payload is not None else '', 'user': None}
        self.net.calls.append(call)
        self.net.events.append(('post', 'turatel_json'))
        self._check_contract(call)
        if self.hook:
            self.hook(call)
        queue = self.script.get(call['endpoint'])
        if queue:
            outcome = queue.pop(0)
            if callable(outcome):
                outcome = outcome(call)
            if outcome is not None:
                return self._response(outcome)
        return self._response(self._normal(call))

    # ── normal davranış ──
    def _next_id(self):
        self._ids += 1
        return 70000 + self._ids

    def _normal(self, call):
        endpoint, payload = call['endpoint'], call['payload'] or {}
        if endpoint == 'Auth/GetToken':
            user = self.users.get(payload.get('username'))
            if (not user or user['password'] != payload.get('password')
                    or str(user['user_id']) != str(payload.get('userId'))):
                return json_err(-1, 'Invalid credentials')
            token = 'TOK-%s-%d' % (payload['username'], len(self.tokens_issued) + 1)
            self.tokens[token] = payload['username']
            self.tokens_issued.append((payload['username'], token))
            return json_ok({'accessToken': token})
        username = self.tokens.get(call['bearer'])
        if not username:
            return json_err(-1, 'Unauthorized')
        user = self.users[username]
        call['user'] = username
        if endpoint == 'Sms/GetUserAccounts':
            return json_ok({'accounts': [{'accountId': a, 'accountName': 'hesap_%d' % a} for a in user['accounts']]})
        account = payload.get('accountId')
        try:
            account = int(account)
        except (TypeError, ValueError):
            return json_err(-2, 'accountId gerekli')
        if account not in user['accounts']:
            return json_err(-1000, 'Account not found in user info.')
        if endpoint == 'Sms/GetOriginator':
            return json_ok({'originatorList': list(self.originators.get(account, []))})
        if endpoint == 'Sms/GetCredit':
            return json_ok({'amount': self.credits.get(account, 0)})
        if endpoint == 'Sms/SendSms':
            return self._send(call, account)
        if endpoint in ('Sms/GetStatus', 'Sms/GetStatusByTwoDates'):
            return self._status(call, account)
        if endpoint == 'Sms/ConfirmSms':
            return self._confirm(call, account)
        return json_err(-99, 'Bilinmeyen uç')

    def _confirm(self, call, account):
        """VARSAYIM (belgesiz): bu hesabın paketi onaylanır, zarf data'sı boş; bilinmeyen paket hata."""
        packet = call['payload'].get('packetId')
        if not any(m['packet_id'] == packet and m['account'] == account for m in self.messages.values()):
            return json_err(-99, 'Packet not found')
        self.confirmed.append((account, packet))
        return json_ok(None)

    def _send(self, call, account):
        payload = call['payload']
        receivers = payload.get('receiverList') or []
        personal = payload.get('personalMessages') or []
        if call['service'] == 'bulksms' and len(receivers) < 2:
            # GERÇEK canlı yanıt (reklam hesabı 65672, isCheckBlackList true/false): bulksms tek alıcıyı reddeder
            return json_err(-1000, BULK_SINGLE_RECEIVER_MESSAGE)
        self._packets += 1
        packet = self._packets
        ids, objects = [], []
        for i, number in enumerate(receivers):
            mid = self._next_id()
            client_id = personal[i].get('clientId') if i < len(personal) and isinstance(personal[i], dict) else None
            self.messages[mid] = {'message_id': mid, 'client_id': client_id, 'number': number, 'account': account,
                                  'packet_id': packet, 'reference_id': payload.get('referenceId'),
                                  'user': call['user'], 'code': self.default_code, 'when': datetime.now()}
            ids.append(mid)
            objects.append({'messageId': mid, 'clientId': client_id, 'receiver': number})
        if self.send_shape == 'objects':
            return json_ok({'packetId': packet, 'messages': objects})
        return json_ok({'packetId': packet, 'messageIdList': ids})

    @staticmethod
    def _parse_date(text):
        return datetime.strptime(text, '%d%m%y%H%M%S')

    def _status(self, call, account):
        payload = call['payload']
        if call['endpoint'] == 'Sms/GetStatusByTwoDates':
            self.status_windows.append((account, payload.get('startDate'), payload.get('endDate')))
        if self.status_empty:
            return json_err(-6, None)
        rows = []
        for msg in self.messages.values():
            if msg['account'] != account:
                continue
            if call['endpoint'] == 'Sms/GetStatus':
                wanted = payload.get('messageIdList') or []
                if payload.get('packetId') is not None and msg['packet_id'] != payload['packetId']:
                    continue
                if wanted and msg['message_id'] not in wanted:
                    continue
            elif self.filter_dates:
                start, end = self._parse_date(payload['startDate']), self._parse_date(payload['endDate'])
                if not start <= msg['when'] <= end:
                    continue
            status, reason, delivery_date = self.status_fields(msg)
            # Canlı satır biçimi: status = paket/teslim aşaması, reason = operatör kodu, deliveryDate = teslim zamanı
            rows.append({'messageId': msg['message_id'], 'clientId': msg['client_id'], 'packetId': msg['packet_id'],
                         'receiver': '+90' + tail10(msg['number']), 'messageSize': 1, 'personalParameter': '[]',
                         'status': status, 'deliveryDate': delivery_date, 'reason': reason})
        return json_ok(rows if self.status_shape == 'list' else {'statusList': rows})


class SmsFakes:
    """TransactionCase/HttpCase karışımı: ağ taklidi, cron yamaları, ayar yardımcıları."""

    block_session = True   # HttpCase'te False

    def setup_fakes(self):
        self.net = FakeNet()
        self.events = self.net.events
        self.startPatcher(patch('requests.post', self.net.post))
        if self.block_session:
            def blocked_send(session, request, **kwargs):
                self.net.unexpected.append({'kind': None, 'url': getattr(request, 'url', '?')})
                raise AssertionError('requests.Session.send çağrıldı (gerçek ağ): %s' % getattr(request, 'url', '?'))
            self.startPatcher(patch.object(requests.Session, 'send', blocked_send))

        events = self.events

        def fake_commit_progress(cron, processed=0, *, remaining=None, deactivate=False):
            cron.env.flush_all()   # gerçek commit de önce flush eder
            events.append(('commit', processed, remaining))
            return 1000.0

        self.startPatcher(patch.object(self.env.registry['ir.cron'], '_commit_progress', fake_commit_progress))
        # İYS sorguları arası 0.15 sn bekleme testi yavaşlatmasın (monotonic gerçek kalır)
        self.startPatcher(patch('odoo.addons.sms_system.models.sms_iys.time',
                                SimpleNamespace(monotonic=time.monotonic, sleep=lambda seconds: None)))
        self.addCleanup(self._assert_no_real_network)
        self.addCleanup(self._assert_json_contract)

    def _assert_no_real_network(self):
        self.assertEqual(self.net.unexpected, [], 'Test gerçek ağ isteği denedi')

    def _assert_json_contract(self):
        """KK-C4/C25 her JSON isteğinde otomatik denetlenir (şema dışı alan, gövdede kimlik, ConfirmSms vb.)."""
        self.assertEqual(self.net.tj.violations, [], 'Turatel JSON istek sözleşmesi ihlali')

    # ── ayarlar ──
    @property
    def icp(self):
        return self.env['ir.config_parameter'].sudo()

    def configure_sms(self, test_mode='False', originator='TESTBASLIK', iys=False):
        self.icp.set_param('sms_system.turatel_channel_code', 'CH1')
        self.icp.set_param('sms_system.turatel_username', 'user1')
        self.icp.set_param('sms_system.turatel_password', 'pass1')
        self.icp.set_param('sms_system.turatel_originator', originator)
        self.icp.set_param('sms_system.test_mode', test_mode)
        self.icp.set_param('sms_system.user_daily_limit', '50')
        self.icp.set_param('sms_system.daily_limit', '0')
        # KK-C26: ticari SMS için ret metni zorunlu; testlerin varsayılan ret metni
        self.icp.set_param('sms_system.optout_text', 'Ret icin RET yazip 3030a gonderin. Mersis 0123456789012345')
        if iys:
            self.icp.set_param('sms_system.iys_enabled', 'True')
            self.icp.set_param('sms_system.iys_customer_code', 'CUST')
            self.icp.set_param('sms_system.iys_username', 'iysuser')
            self.icp.set_param('sms_system.iys_password', 'iyspass')
        else:
            self.icp.set_param('sms_system.iys_enabled', 'False')

    def set_param(self, key, value):
        """value None → parametreyi sil (yokluğunu taklit et)."""
        if value is None:
            self.icp.search([('key', '=', 'sms_system.' + key)]).unlink()
        else:
            self.icp.set_param('sms_system.' + key, value)

    # ── JSON modu (C) ──
    JSON_SINGLE_URL = 'https://platform.turatel.com/singlesms'
    JSON_BULK_URL = 'https://platform.turatel.com/bulksms'

    def json_api(self):
        """services/turatel_json.py; henüz yoksa ARAYÜZ YOK (import hatası değil, anlaşılır başarısızlık)."""
        try:
            return importlib.import_module('odoo.addons.sms_system.services.turatel_json')
        except ImportError:
            self.fail('ARAYÜZ YOK: sms_system/services/turatel_json.py (tasarım §5.2) bulunamadı')

    def json_client(self, which='info', service='single', **kw):
        """Taklit sunucuya karşı doğrudan istemci (Odoo kaydı gerektirmez)."""
        api = self.json_api()
        api.clear_token_cache()
        self.addCleanup(api.clear_token_cache)
        user = {'info': ('20219', 'info_user', 'info_pw'), 'com': ('20219', 'com_user', 'com_pw')}[which]
        base = self.JSON_SINGLE_URL if service == 'single' else self.JSON_BULK_URL
        return api.TuratelJsonClient(base, *user, **kw)

    def configure_json(self, commercial=True, test_mode='False', iys=False, originator='TESTBASLIK'):
        """API modu json, iki kimlik seti dolu (varsayılan). commercial=False: reklam seti tamamen boş."""
        api = self.json_api()
        api.clear_token_cache()
        self.addCleanup(api.clear_token_cache)
        self.configure_sms(test_mode=test_mode, iys=iys, originator=originator)
        values = {
            'api_mode': 'json', 'turatel_single_url': self.JSON_SINGLE_URL, 'turatel_bulk_url': self.JSON_BULK_URL,
            'turatel_validity_minutes': '1260',
            'turatel_json_info_user_id': '20219', 'turatel_json_info_username': 'info_user',
            'turatel_json_info_password': 'info_pw', 'turatel_account_info': '9254',
        }
        com = {'turatel_json_com_user_id': '20219', 'turatel_json_com_username': 'com_user',
               'turatel_json_com_password': 'com_pw', 'turatel_account_commercial': '65672'}
        for key, value in values.items():
            self.set_param(key, value)
        for key, value in com.items():
            self.set_param(key, value if commercial else None)

    def db8(self):
        return (self.icp.get_param('database.uuid') or '')[:8]

    def client_id_of(self, message):
        return '%s-m%d' % (self.db8(), message.id)

    @contextmanager
    def capture_logs(self, name='odoo.addons.sms_system'):
        """sms_system loglarını DEBUG'dan itibaren topla; geri döner: biçimlendirilmiş satır listesi."""
        lines = []
        formatter = logging.Formatter('%(levelname)s %(name)s %(message)s')

        class Collector(logging.Handler):
            def emit(self, record):
                lines.append(formatter.format(record))

        logger = logging.getLogger(name)
        handler, old_level = Collector(level=logging.DEBUG), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            yield lines
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)


    # ── kayıt yardımcıları ──
    @property
    def Message(self):
        return self.env['sms.system.message']

    def require_state(self, state):
        """Henüz var olmayan durumlar için anlaşılır başarısızlık (import/sözdizimi hatası değil)."""
        values = [key for key, _label in self.Message._fields['state'].selection]
        if state not in values:
            self.fail("ARAYÜZ YOK: sms.system.message.state içinde '%s' yok (seçenekler: %s)" % (state, values))

    def make_message(self, number='5321234567', state='error', retry_count=0, **vals):
        self.require_state(state)
        base = {'number': number, 'body': 'Test mesajı', 'originator': 'TESTBASLIK', 'state': state,
                'retry_count': retry_count}
        base.update(vals)
        return self.Message.sudo().create(base)

    def set_write_date(self, records, minutes_ago):
        """write_date'i SQL ile geriye al (ORM write_date'i her zaman 'şimdi' yapar)."""
        self.env.flush_all()
        when = fields.Datetime.now() - timedelta(minutes=minutes_ago)
        self.env.cr.execute('UPDATE %s SET write_date = %%s WHERE id IN %%s' % records._table,
                            (when, tuple(records.ids)))
        records.invalidate_recordset()

    def set_create_date(self, records, minutes_ago):
        self.env.flush_all()
        when = fields.Datetime.now() - timedelta(minutes=minutes_ago)
        self.env.cr.execute('UPDATE %s SET create_date = %%s WHERE id IN %%s' % records._table,
                            (when, tuple(records.ids)))
        records.invalidate_recordset()

    def db_state(self, message, flush=True):
        """Mesajın veritabanındaki durumu (önbelleği atlar). flush=False: yalnız flush edilmiş/commit
        edilmiş değeri görür (sağlayıcı çağrısı anındaki "başka transaction'ın gördüğü" durumu taklit eder)."""
        if flush:
            self.env.flush_all()
        self.env.cr.execute('SELECT state FROM sms_system_message WHERE id = %s', (message.id,))
        return self.env.cr.fetchone()[0]


class SmsTestCase(SmsFakes, TransactionCase):
    """Ağ ve cron yamalı TransactionCase; varsayılan: canlı mod (test modu kapalı), başlık dolu, İYS kapalı."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = new_test_user(cls.env, login='sms_t_plain', groups='base.group_user')
        cls.admin_user = new_test_user(cls.env, login='sms_t_admin', groups='base.group_user,base.group_system')
        cls.sms_manager = new_test_user(cls.env, login='sms_t_mgr', groups='base.group_user,sms_system.group_sms_manager')

    def setUp(self):
        super().setUp()
        self.setup_fakes()
        self.configure_sms()


class SmsHttpCase(SmsFakes, HttpCase):
    """HttpCase varyantı (RPC testleri); yalnız requests.post yamalanır."""

    block_session = False
    PW = 'Sms-Test-Pw-12345'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_user = new_test_user(cls.env, login='sms_h_plain', password=cls.PW, groups='base.group_user')
        cls.sms_manager = new_test_user(cls.env, login='sms_h_mgr', password=cls.PW,
                                        groups='base.group_user,sms_system.group_sms_manager')

    def setUp(self):
        super().setUp()
        self.setup_fakes()
        self.configure_sms()

    def call_kw(self, model, method, args=None, kwargs=None):
        payload = {'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                   'params': {'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}}
        response = self.url_open('/web/dataset/call_kw/%s/%s' % (model, method), data=json.dumps(payload),
                                 headers={'Content-Type': 'application/json'}, timeout=30)
        self.assertLess(response.status_code, 500)
        try:
            return response.json()
        except ValueError:
            return {'error': {'message': 'JSON değil', 'status': response.status_code}}

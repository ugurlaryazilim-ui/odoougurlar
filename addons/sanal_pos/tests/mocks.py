# -*- coding: utf-8 -*-
"""Paratika HTTP taklidi (Odoo'dan bağımsız, saf Python + requests).

Taklit ``requests.Session.send`` seviyesinde yapılır: ``requests.post``,
``Session.post`` ve ``Session.request`` hangisi kullanılırsa kullanılsın
Paratika'ya giden istek yakalanır. Böylece testler geliştiricinin HTTP
kütüphanesi kullanım biçimine bağlanmaz. Yalnız adı ``paratika`` geçen
sunucular taklit edilir; localhost istekleri (HttpCase) ve diğer dış
istekler Odoo'nun kendi işleyicisine devredilir (dış istek zaten engellidir).
"""
import itertools
import json
from collections import defaultdict, deque
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

TEST_URL_PREFIX = 'https://test.paratika.com.tr/paratika/api/v2'
LIVE_URL_PREFIX = 'https://vpos.paratika.com.tr/paratika/api/v2'


class RawResponse:
    """JSON olmayan / özel HTTP yanıtı (ör. 500 sayfası)."""

    def __init__(self, status=200, text='', content_type='text/html'):
        self.status = status
        self.text = text
        self.content_type = content_type


class Call:
    """Taklide gelen tek bir Paratika çağrısı."""

    def __init__(self, action, params, request, kw, probe):
        self.action = action
        self.params = params                      # düz sözlük (ilk değerler)
        self.url = request.url
        self.method = request.method
        self.headers = dict(request.headers or {})
        body = request.body
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.raw_body = body or b''               # gönderilen baytlar
        self.timeout = kw.get('timeout')
        self.probe = probe                        # çağrı anındaki DB/commit özeti

    @property
    def body_text(self):
        return self.raw_body.decode('ascii', errors='replace')

    @property
    def content_type(self):
        for key, value in self.headers.items():
            if key.lower() == 'content-type':
                return value
        return ''


def parse_body(body):
    if body is None:
        return {}
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    parsed = parse_qs(body, keep_blank_values=True, encoding='utf-8')
    return {key: values[0] for key, values in parsed.items()}


def ok_body(**extra):
    body = {'responseCode': '00', 'responseMsg': 'Success'}
    body.update(extra)
    return body


def err_body(code, message='Hata', **extra):
    body = {'responseCode': '99', 'responseMsg': message,
            'errorCode': code, 'errorMsg': message}
    body.update(extra)
    return body


def tran(status='AP', ttype='SALE', amount='9000.00', ref='T1',
         currency='TRY', installments=1, last4='1234', **extra):
    """QUERYTRANSACTION ``transactionList`` öğesi.

    Zaman alanı bilerek yok: Paratika'nın biçimi belgelenmemiş; sağlayıcı
    alanın yokluğunu tolere etmelidir (ödeme zamanı o zaman 'şimdi' olur).
    """
    item = {
        'pgTranId': ref,
        'transactionStatus': status,
        'transactionType': ttype,
        'amount': amount,
        'currency': currency,
        'installmentCount': installments,
        'panLast4': last4,
    }
    item.update(extra)
    return item


def qt_body(*transactions):
    return ok_body(
        transactionCount=len(transactions),
        totalTransactionCount=len(transactions),
        transactionList=list(transactions),
    )


def timeout_exc():
    return requests.exceptions.ReadTimeout('read timed out')


def connection_exc():
    return requests.exceptions.ConnectionError('connection refused')


class ParatikaMock:
    """Sıralı yanıt kuyruklu Paratika taklidi."""

    def __init__(self):
        self.calls = []
        self.unexpected = []
        self.probe = None
        self._queues = defaultdict(deque)
        self._defaults = {}
        self._token_seq = itertools.count(1)
        self._ref_seq = itertools.count(1)
        self._install_defaults()

    # -- yapılandırma ---------------------------------------------------
    def _install_defaults(self):
        self.default('PAYBYLINKPAYMENT', lambda p: ok_body(
            sessionToken='TOK-%03d' % next(self._token_seq)))
        self.default('PAYBYLINKPAYMENTRESEND', lambda p: ok_body())
        self.default('PAYBYLINKPAYMENTCANCEL', lambda p: ok_body())
        self.default('QUERYPAYBYLINKPAYMENT', lambda p: ok_body(payByLinkPaymentList=[]))
        self.default('QUERYTRANSACTION', lambda p: qt_body())
        self.default('VOID', lambda p: ok_body(
            pgTranId='V-%03d' % next(self._ref_seq), merchantPaymentId=p.get('MERCHANTPAYMENTID')))
        self.default('REFUND', lambda p: ok_body(
            pgTranId='R-%03d' % next(self._ref_seq), merchantPaymentId=p.get('MERCHANTPAYMENTID')))

    def queue(self, action, *responses):
        """Sıradaki çağrılar için yanıt (dict | RawResponse | Exception | callable)."""
        self._queues[action].extend(responses)

    def default(self, action, response):
        """Kuyruk boşken kullanılan kalıcı yanıt."""
        self._defaults[action] = response

    # -- gözlem ----------------------------------------------------------
    def calls_for(self, *actions):
        return [c for c in self.calls if c.action in actions]

    def count(self, *actions):
        if not actions:
            return len(self.calls)
        return len(self.calls_for(*actions))

    @property
    def actions(self):
        return [c.action for c in self.calls]

    def last(self, action):
        found = self.calls_for(action)
        return found[-1] if found else None

    # -- işleyici ----------------------------------------------------------
    def handle(self, request, kw):
        params = parse_body(request.body)
        action = params.get('ACTION', '')
        probe = self.probe() if self.probe else None
        self.calls.append(Call(action, params, request, kw, probe))

        if self._queues[action]:
            response = self._queues[action].popleft()
        elif action in self._defaults:
            response = self._defaults[action]
        else:
            self.unexpected.append(action)
            response = err_body('ERR99999', 'taklitte tanimsiz action: %s' % action)

        if callable(response) and not isinstance(response, (BaseException, type)):
            response = response(params)
        if isinstance(response, type) and issubclass(response, BaseException):
            response = response()
        if isinstance(response, BaseException):
            raise response
        return self._build(request, response)

    @staticmethod
    def _build(request, payload):
        resp = requests.Response()
        resp.request = request
        resp.url = request.url
        resp.encoding = 'utf-8'
        if isinstance(payload, RawResponse):
            resp.status_code = payload.status
            resp.headers['Content-Type'] = payload.content_type
            resp._content = payload.text.encode('utf-8')
        else:
            resp.status_code = 200
            resp.reason = 'OK'
            resp.headers['Content-Type'] = 'application/json;charset=UTF-8'
            resp._content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return resp


def make_send_patch(mock):
    """``requests.Session.send`` yamasını döndürür (başlatma/durdurma çağırana ait)."""
    original = requests.Session.send

    def fake_send(session, request, **kw):
        host = urlsplit(request.url).hostname or ''
        if 'paratika' in host:
            return mock.handle(request, kw)
        return original(session, request, **kw)

    return patch.object(requests.Session, 'send', fake_send)

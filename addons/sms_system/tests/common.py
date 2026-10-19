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
import json
import re
import time
from datetime import timedelta
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
        self._seq = 0

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

    def post(self, url, data=None, **kwargs):
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
            value = str((call['payload'] or {}).get('Value') or '')
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

    def _smartadm(self, call):
        path = call['path']
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
                return smart_error(-6, -601)
            return smart_ok([{'Authorization': {'Etk': {'Msisdn': {'Sms': status}}}}])
        if path == 'report2':
            return FakeResponse(200, '', {'Status': 0, 'StatusCode': 0, 'SubStatusCode': 0, 'Value': [],
                                          'MaxPage': 0})
        raise AssertionError('Beklenmeyen SmartADM ucu: %s' % path)


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

    def _assert_no_real_network(self):
        self.assertEqual(self.net.unexpected, [], 'Test gerçek ağ isteği denedi')

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

"""KK-A15/A16 (sınıflandırma), KK-A23 (eski XML istemcisi), KK-A25 (maske) ve ağ engeli meta testi."""
import requests
from odoo.tests.common import tagged
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError

from odoo.addons.sms_system.services import turatel
from odoo.addons.sms_system.services.turatel import (
    TuratelClient, TuratelError, normalize_number, prepare_text, segment_count)

from .common import FakeResponse, SmsTestCase


def _client():
    return TuratelClient('CH1', 'user1', 'pass1')


def _dns_error():
    dns = NewConnectionError(None, 'Failed to resolve host (Name or service not known)')
    return requests.exceptions.ConnectionError(MaxRetryError(None, '/xml/process.aspx', reason=dns))


def _reset_error():
    return requests.exceptions.ConnectionError(
        ProtocolError('Connection aborted.', ConnectionResetError('Connection reset by peer')))


@tagged('post_install', '-at_install')
class TestTuratelClient(SmsTestCase):

    # ── KK-A23: ağ engeli (meta) ──
    def test_kk_a23_gercek_ag_istegi_assertion_error_verir(self):
        """Taklit dışı adres: AssertionError (ConnectionError değil) ve kayıt düşer."""
        with self.assertRaises(AssertionError):
            requests.post('https://example.invalid/x', data=b'x', timeout=1)
        self.assertEqual(len(self.net.unexpected), 1)
        self.net.unexpected.clear()   # bu test kasıtlı denedi; sonda temizlik denetimi geçsin

    def test_kk_a23_session_send_engelli(self):
        with self.assertRaises(AssertionError):
            requests.Session().get('https://example.invalid/y', timeout=1)
        self.net.unexpected.clear()

    # ── KK-A23: normalize_number ──
    def test_kk_a23_normalize_number(self):
        cases = {
            '05321234567': '5321234567',
            '+90 532 123 45 67': '5321234567',
            '905321234567': '5321234567',
            '5321234567': '5321234567',
            '(0532) 123-45-67': '5321234567',
            '4321234567': None,        # 5 ile başlamıyor
            '532123456': None,         # 9 hane
            '53212345678': None,       # 11 hane, 0'sız
            '0212 123 45 67': None,    # sabit hat
            '': None,
            None: None,
            'abc': None,
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_number(raw), expected, repr(raw))

    # ── KK-A23: prepare_text / segment_count ──
    def test_kk_a23_prepare_text_turkce_type2(self):
        self.assertEqual(prepare_text('  Merhaba dünya  ')[1], '1')
        self.assertEqual(prepare_text('Merhaba dünya')[0], 'Merhaba dünya')
        self.assertEqual(prepare_text('Işık Şimdi')[1], '2')
        self.assertEqual(prepare_text('Işık Şimdi', ascii_mode=True), ('Isik Simdi', '1'))

    def test_kk_a23_segment_siniri(self):
        self.assertEqual(segment_count('a' * 160, '1'), 1)
        self.assertEqual(segment_count('a' * 161, '1'), 2)
        self.assertEqual(segment_count('a' * 306, '1'), 2)
        self.assertEqual(segment_count('a' * 307, '1'), 3)
        self.assertEqual(segment_count('ş' * 155, '2'), 1)
        self.assertEqual(segment_count('ş' * 156, '2'), 2)
        self.assertEqual(segment_count('ş' * 299, '2'), 3)

    # ── KK-A23: eski XML üretimi ──
    def test_kk_a23_xml_kacis_ve_cdata(self):
        client = TuratelClient('C<1>', 'u&ser', 'p"w>')
        xml = client.build_send_xml(['5321234567'], 'a ]]> b & <c>', 'BA&SLIK')
        self.assertIn('<ChannelCode>C&lt;1&gt;</ChannelCode>', xml)
        self.assertIn('<UserName>u&amp;ser</UserName>', xml)
        self.assertIn('<Originator>BA&amp;SLIK</Originator>', xml)
        self.assertIn('<![CDATA[a ]]]]><![CDATA[> b & <c>]]>', xml)
        self.assertIn('<Numbers>5321234567</Numbers>', xml)
        self.assertEqual(xml.count('<Command>0</Command>'), 1)

    def test_kk_a23_xml_cok_numara_virgullu(self):
        xml = _client().build_send_xml(['5321234567', '5329999999'], 'x', 'ORG')
        self.assertIn('<Numbers>5321234567,5329999999</Numbers>', xml)

    # ── KK-A23: cevap ayrıştırma ──
    def test_kk_a23_basarili_cevap_id(self):
        self.net.turatel_script = ['ID:98765']
        msg_id, answer = _client().send(['5321234567'], 'x', 'ORG')
        self.assertEqual(msg_id, '98765')
        self.assertEqual(answer, 'ID:98765')
        self.assertEqual(self.net.turatel_calls[0]['numbers'], ['5321234567'])

    def test_kk_a23_hata_kodlari(self):
        for code, hint in (('20', 'XML'), ('30', 'şifre'), ('40', 'Originator'), ('50', 'kredi'),
                           ('51', 'Numara'), ('70', 'parametre'), ('85', 'Mükerrer')):
            self.net.turatel_script = [code]
            with self.assertRaises(TuratelError) as ctx:
                _client().send(['5321234567'], 'x', 'ORG')
            self.assertIn(hint, str(ctx.exception), code)
            self.assertFalse(ctx.exception.retryable, code)
            self.assertFalse(getattr(ctx.exception, 'uncertain', False), code)

    def test_kk_a23_bilinmeyen_kod_yeniden_denenmez(self):
        self.net.turatel_script = ['99']
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertFalse(ctx.exception.retryable)

    # ── KK-A15: kesin gitmeyen hatalar → geçici (retryable) ──
    def test_kk_a15_connect_timeout_retryable(self):
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(ctx.exception.retryable)
        self.assertFalse(getattr(ctx.exception, 'uncertain', False))

    def test_kk_a15_dns_hatasi_retryable(self):
        self.net.turatel_script = [_dns_error()]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(ctx.exception.retryable, 'DNS/NewConnectionError isteğin gitmediği kesin: geçici')
        self.assertFalse(getattr(ctx.exception, 'uncertain', False))

    # ── KK-A16: gidip gitmediği belli olmayanlar → uncertain ──
    def test_kk_a16_read_timeout_uncertain(self):
        self.net.turatel_script = [requests.exceptions.ReadTimeout()]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(getattr(ctx.exception, 'uncertain', False), 'ReadTimeout belirsiz sayılmalı')
        self.assertFalse(ctx.exception.retryable)

    def test_kk_a16_http_503_uncertain(self):
        self.net.turatel_script = [FakeResponse(503, 'Service Unavailable')]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(getattr(ctx.exception, 'uncertain', False), 'HTTP 5xx belirsiz sayılmalı')
        self.assertFalse(ctx.exception.retryable)

    def test_kk_a16_http_200_disi_uncertain(self):
        self.net.turatel_script = [FakeResponse(404, 'x')]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(getattr(ctx.exception, 'uncertain', False), 'HTTP 200 dışı belirsiz sayılmalı')

    def test_kk_a16_baglanti_kopmasi_uncertain(self):
        self.net.turatel_script = [_reset_error()]
        with self.assertRaises(TuratelError) as ctx:
            _client().send(['5321234567'], 'x', 'ORG')
        self.assertTrue(getattr(ctx.exception, 'uncertain', False), 'Bağlantı kurulduktan sonra kopma belirsiz')
        self.assertFalse(ctx.exception.retryable)

    # ── KK-A25: mask_number ──
    def test_kk_a25_mask_number(self):
        mask = getattr(turatel, 'mask_number', None)
        if mask is None:
            self.fail('ARAYÜZ YOK: services.turatel.mask_number')
        for raw in ('05321234567', '5321234567', '+90 532 123 45 67', '905321234567'):
            self.assertEqual(mask(raw), '532*****67', raw)

    def test_kk_a25_mask_number_gecersiz_girdi(self):
        mask = getattr(turatel, 'mask_number', None)
        if mask is None:
            self.fail('ARAYÜZ YOK: services.turatel.mask_number')
        out = mask('1234567')
        self.assertNotIn('12345', out)
        self.assertTrue(out.endswith('67'))
        self.assertEqual(mask(''), mask(None))

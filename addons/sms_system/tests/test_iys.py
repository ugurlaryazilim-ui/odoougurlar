"""KK-A25 (numara maskesi: SmartADM hata/log) ve refresh_contacts 'retryable' anahtarı (S-7)."""
from odoo.tests.common import tagged

from odoo.addons.sms_system.services.smartadm import SmartAdmClient, SmartAdmError

from .common import FakeResponse, SmsTestCase, smart_error


def _client():
    return SmartAdmClient('CUST', 'iysuser', 'iyspass')


@tagged('post_install', '-at_install')
class TestIysMasking(SmsTestCase):

    # ── KK-A25 ──
    def test_kk_a25_gecersiz_numara_istisna_metni_maskeli(self):
        for fn in ('query', 'trigger'):
            with self.subTest(uc=fn):
                with self.assertRaises(SmartAdmError) as ctx:
                    getattr(_client(), fn)('05321234567')   # 11 hane: SmartADM biçimine uymaz
                text = str(ctx.exception)
                self.assertNotIn('5321234567', text, 'istisna metni numaranın tamamını içeriyor')
                self.assertIn('532*****67', text)
        self.assertEqual(self.net.calls, [], 'geçersiz numara için istek atılmamalı')

    def test_kk_a25_contact_api_load_istisna_metni_maskeli(self):
        from datetime import datetime
        with self.assertRaises(SmartAdmError) as ctx:
            _client().contact_api_load('05321234567', True, datetime.now(), 'HS_WEB')
        self.assertNotIn('5321234567', str(ctx.exception))
        self.assertIn('532*****67', str(ctx.exception))

    def test_kk_a25_sunucu_numara_hatasi_metinde_ve_logda_tam_numara_yok(self):
        self.configure_sms(iys=True)
        lst = self.env['sms.system.list'].create({'name': 'L'})
        contact = self.env['sms.system.contact'].create({'mobile': '5321234567', 'list_ids': [(6, 0, lst.ids)]})
        self.net.smart_query = smart_error(-3, -114)   # telefon numarası biçimi geçersiz
        with self.assertLogs('odoo.addons.sms_system', level='WARNING') as logs:
            stats = self.env['sms.system.iys'].refresh_contacts(contact)
        self.assertEqual(stats['stopped'], 'error')
        joined = '\n'.join(logs.output) + '\n' + str(stats.get('error'))
        self.assertNotIn('5321234567', joined, 'log/istisna metni numaranın tamamını içeriyor')
        with self.assertRaises(SmartAdmError) as ctx:
            _client().query('5321234567')
        self.assertNotIn('5321234567', str(ctx.exception))

    def test_kk_a25_sunucu_hatasi_numara_hatasi_maskeli_gorunur(self):
        """Numara bilgisi hata metnine giriyorsa yalnız maskeli biçimde (ilk 3 + son 2) olmalı."""
        self.net.smart_session = None
        self.net.smart_query = smart_error(-3, -114)
        with self.assertRaises(SmartAdmError) as ctx:
            _client().query('5321234567')
        text = str(ctx.exception)
        self.assertNotIn('5321234567', text)
        self.assertNotIn('1234567', text)


@tagged('post_install', '-at_install')
class TestRefreshRetryable(SmsTestCase):

    def _contacts(self, count):
        lst = self.env['sms.system.list'].create({'name': 'L'})
        return self.env['sms.system.contact'].create(
            [{'mobile': '53210000%02d' % i, 'list_ids': [(6, 0, lst.ids)]} for i in range(count)])

    def setUp(self):
        super().setUp()
        self.configure_sms(iys=True)

    def _refresh(self, contacts):
        return self.env['sms.system.iys'].refresh_contacts(contacts)

    def test_retryable_kalici_hatada_false(self):
        self.net.smart_session = smart_error(-1, -1)   # yanlış şifre
        stats = self._refresh(self._contacts(3))
        self.assertEqual(stats['stopped'], 'error')
        self.assertIn('retryable', stats)
        self.assertIs(stats['retryable'], False)

    def test_retryable_gecici_hatada_true(self):
        self.net.smart_query = FakeResponse(503, 'x')
        stats = self._refresh(self._contacts(5))
        self.assertEqual(stats['stopped'], 'error')
        self.assertIn('retryable', stats)
        self.assertIs(stats['retryable'], True)

    def test_sorgu_hatasi_olmadan_tamamlanan_tur_degismez(self):
        stats = self._refresh(self._contacts(3))
        self.assertEqual((stats['done'], stats['approved'], stats['stopped']), (3, 3, None))
        self.assertEqual(self.net.queried, ['5321000000', '5321000001', '5321000002'])

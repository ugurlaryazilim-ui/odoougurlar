"""A4: hata sınıflaması ayrıntıları (kabul testlerine ek birim testleri): bayrak kuralı, zaman aşımı çifti,
bilinmeyen bağlantı hatası, paket yolu ve "Belirsiz" filtresi."""
import requests
from odoo.tests.common import tagged
from urllib3.exceptions import MaxRetryError, NewConnectionError

from odoo.addons.sms_system.services.turatel import TIMEOUT, TuratelClient, TuratelError

from .common import SmsTestCase

MAX_RETRY = 3


def _send_error(test, outcome):
    test.net.turatel_script = [outcome]
    with test.assertRaises(TuratelError) as ctx:
        TuratelClient('CH1', 'user1', 'pass1').send(['5321234567'], 'x', 'ORG')
    return ctx.exception


@tagged('post_install', '-at_install')
class TestErrorClassification(SmsTestCase):

    def test_iki_bayrak_ayni_anda_true_olamaz(self):
        with self.assertRaises(ValueError):
            TuratelError('x', retryable=True, uncertain=True)
        for flags in ({}, {'retryable': True}, {'uncertain': True}):
            error = TuratelError('x', **flags)
            self.assertEqual((error.retryable, error.uncertain),
                             (flags.get('retryable', False), flags.get('uncertain', False)))

    def test_zaman_asimi_baglanma_5_okuma_15(self):
        self.assertEqual(TIMEOUT, (5, 15))
        self.net.turatel_script = ['ID:1']
        TuratelClient('CH1', 'user1', 'pass1').send(['5321234567'], 'x', 'ORG')
        self.assertEqual(self.net.turatel_calls[0]['timeout'], (5, 15))

    def test_baglanti_reddedildi_gecici(self):
        refused = NewConnectionError(None, 'Failed to establish a new connection: [Errno 111] Connection refused')
        error = _send_error(self, requests.exceptions.ConnectionError(
            MaxRetryError(None, '/xml/process.aspx', reason=refused)))
        self.assertEqual((error.retryable, error.uncertain), (True, False))

    def test_nedeni_bilinmeyen_baglanti_hatasi_belirsiz(self):
        """Emin olunamayan durumda yeniden gönderme yok: belirsiz."""
        error = _send_error(self, requests.exceptions.ConnectionError('bilinmeyen'))
        self.assertEqual((error.retryable, error.uncertain), (False, True))

    def test_gecersiz_adres_kalici_hata(self):
        for exc in (requests.exceptions.MissingSchema('adres yok'), requests.exceptions.InvalidURL('bozuk')):
            with self.subTest(exc=exc.__class__.__name__):
                error = _send_error(self, exc)
                self.assertEqual((error.retryable, error.uncertain), (False, False))

    def test_hata_metninde_numara_ve_sir_yok(self):
        error = _send_error(self, requests.exceptions.ReadTimeout('5321234567 pass1 user1'))
        self.assertNotIn('5321234567', str(error))
        self.assertNotIn('pass1', str(error))

    # ── paket yolu (kampanya kuyruğu) ──
    def _pack(self, state='queued', **vals):
        return (self.make_message(state=state, **vals) | self.make_message(state=state, number='5329999999', **vals))

    def test_paket_read_timeout_belirsiz_ve_max_retry(self):
        pack = self._pack()
        self.net.turatel_script = [requests.exceptions.ReadTimeout()]
        cfg = self.Message._settings()
        pack._deliver_pack(cfg, self.Message._client(cfg))
        self.assertEqual(pack.mapped('state'), ['uncertain', 'uncertain'])
        self.assertEqual(pack.mapped('retry_count'), [MAX_RETRY, MAX_RETRY])
        self.assertTrue(all(pack.mapped('error')))

    def test_paket_baglanti_kurulamadi_error_kalir(self):
        pack = self._pack()
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()]
        cfg = self.Message._settings()
        pack._deliver_pack(cfg, self.Message._client(cfg))
        self.assertEqual(pack.mapped('state'), ['error', 'error'])

    def test_paket_baslik_yoksa_error_ve_max_retry(self):
        pack = self._pack(originator=False)
        cfg = self.Message._settings()
        pack._deliver_pack(cfg, self.Message._client(cfg))
        self.assertEqual(pack.mapped('state'), ['error', 'error'])
        self.assertEqual(pack.mapped('retry_count'), [MAX_RETRY, MAX_RETRY])
        self.assertEqual(self.net.calls, [])

    # ── görünüm ──
    def test_belirsiz_filtresi_yalniz_belirsizleri_getirir(self):
        uncertain = self.make_message(state='uncertain', retry_count=MAX_RETRY)
        self.make_message(state='error', number='5329999999')
        arch = self.Message.get_view(view_type='search')['arch']
        self.assertIn('name="uncertain"', arch)
        self.assertEqual(self.Message.search([('state', '=', 'uncertain')]), uncertain)

    def test_belirsiz_durum_secimde_var(self):
        self.assertIn(('uncertain', 'Belirsiz'), self.Message._fields['state'].selection)

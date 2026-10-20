"""KK-A23 (devam): eski XML istemcisinin güvenlik ağı — rapor/kredi XML'i, tarih penceresi, eksik kimlik, cevap biçimleri.

Ağ yalnız ``tests/common.py`` taklidiyle; gerçek istek denenirse test başarısız olur.
"""
from datetime import datetime

import pytz
from odoo.tests.common import tagged

from odoo.addons.sms_system.services.turatel import TuratelClient, TuratelError

from .common import SmsTestCase


@tagged('post_install', '-at_install')
class TestTuratelLegacy(SmsTestCase):

    def test_kk_a23_gonderim_tarih_penceresi_21_saat(self):
        now = pytz.timezone('Europe/Istanbul').localize(datetime(2026, 10, 19, 14, 5))
        xml = TuratelClient('CH1', 'u', 'p').build_send_xml(['5321234567'], 'x', 'ORG', now=now)
        self.assertIn('<SDate>191020261405</SDate>', xml)
        self.assertIn('<EDate>201020261105</EDate>', xml)

    def test_kk_a23_rapor_ve_kredi_xml_komutlari(self):
        client = TuratelClient('CH1', 'u', 'p')
        report = client.build_report_xml('12<3')
        self.assertIn('<Command>3</Command>', report)
        self.assertIn('<MsgID>12&lt;3</MsgID>', report)
        credit = client.build_credit_xml()
        self.assertIn('<Command>6</Command>', credit)
        self.assertNotIn('<MsgID>', credit)

    def test_kk_a23_eksik_kimlik_ag_cagrisi_yapmaz(self):
        for args in (('', 'u', 'p'), ('CH1', '', 'p'), ('CH1', 'u', '')):
            with self.assertRaises(TuratelError) as ctx:
                TuratelClient(*args).send(['5321234567'], 'x', 'ORG')
            self.assertFalse(ctx.exception.retryable)
        self.assertEqual(self.net.calls, [])

    def test_kk_a23_id_cevabi_kucuk_harf_ve_bosluk(self):
        self.net.turatel_script = ['  id: 555 \n']
        msg_id, _answer = TuratelClient('CH1', 'u', 'p').send(['5321234567'], 'x', 'ORG')
        self.assertEqual(msg_id, '555')

    def test_kk_a23_istek_turkce_metin_type_2_ile_gider(self):
        self.net.turatel_script = ['ID:1']
        TuratelClient('CH1', 'u', 'p').send(['5321234567'], 'Işık', 'ORG', sms_type='2')
        body = self.net.turatel_calls[0]['body']
        self.assertIn('<Type>2</Type>', body)
        self.assertIn('Işık', body)

    def test_kk_a23_rapor_ve_kredi_ham_cevap_dondurur(self):
        self.net.turatel_script = ['3 teslim edildi', '1234']
        client = TuratelClient('CH1', 'u', 'p')
        self.assertEqual(client.report('9'), '3 teslim edildi')
        self.assertEqual(client.credit(), '1234')

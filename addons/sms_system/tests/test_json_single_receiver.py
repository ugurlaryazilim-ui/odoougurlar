"""Tek alıcılı paket (canlıda kanıtlanan hata): bulksms 2'den az alıcıyı -1000 ile reddeder.

Ticari kampanya tek alıcıya (ya da son paketi tek kişiye) kalınca paket singlesms'e, aynı kimlik setiyle gider;
ConfirmSms ve durum sorgusu provider_service + hesapla aynı servisi/seti seçer. -1000'in Turatel mesajı hata
metninde görünür (eskiden her -1000 "hesap tanımlı değil" diye çevriliyordu).
"""
from datetime import timedelta
from unittest.mock import patch

import requests
from odoo import fields
from odoo.tests.common import tagged

from ..services.turatel import TuratelError
from .common import BULK_SINGLE_RECEIVER_MESSAGE, SmsTestCase, json_err
from .test_json_routing import JsonModelMixin

PACK_SIZE_PATH = 'odoo.addons.sms_system.models.sms_campaign.PACK_SIZE'


@tagged('post_install', '-at_install')
class TestSingleReceiverPack(JsonModelMixin, SmsTestCase):

    def commercial(self, names, body='Sabit reklam metni'):
        self.configure_json(iys=True)
        return self.make_json_campaign(names=names, message_type='commercial', body=body)

    def assert_commercial_single(self, call):
        self.assertEqual(call['service'], 'singlesms')
        self.assertEqual((call['user'], int(call['payload']['accountId'])), ('com_user', 65672))
        self.assertIs(call['payload']['isCheckBlackList'], True)

    # ── (a) ticari tek alıcı ──
    def test_ticari_tek_alicili_kampanya_singlesms_reklam_seti(self):
        msgs = self.launch(self.commercial(('Ayşe',)))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs.state, 'sent', msgs.error)
        self.assertEqual(len(self.net.json_sends), 1)
        call = self.net.json_sends[0]
        self.assert_commercial_single(call)
        self.assertEqual(call['payload']['messageText'], msgs.body)
        self.assertEqual((msgs.provider_service, str(msgs.provider_account_id)), ('single', '65672'))
        self.assertEqual(msgs.delivery_state, 'pending')
        self.assertTrue(msgs.provider_msg_id and msgs.provider_packet_id)

    def test_tek_alicili_kisisellestirilmis_kampanya_son_metin_parametresiz(self):
        msgs = self.launch(self.commercial(('Ayşe',), body='Merhaba {ad}'))
        self.assertEqual(msgs.state, 'sent', msgs.error)
        call = self.net.json_sends[0]
        self.assertEqual(call['service'], 'singlesms')
        self.assertTrue(msgs.body.startswith('Merhaba Ayşe'), msgs.body)   # ticari: ret metni sonda
        self.assertEqual(call['payload']['messageText'], msgs.body, '{1} şablonu değil, kaydın son metni')
        self.assertNotIn('{1}', call['payload']['messageText'])
        for item in call['payload']['personalMessages']:
            self.assertNotIn('parameter', item)

    # ── (b) 2 alıcı bulksms'te kalır ──
    def test_iki_alicili_kampanya_bulksms_te_kalir(self):
        msgs = self.launch(self.commercial(('Ayşe', 'Can')))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual([c['service'] for c in self.net.json_sends], ['bulksms'])
        self.assertEqual({(m.provider_service, str(m.provider_account_id)) for m in msgs}, {('bulk', '65672')})

    # ── (c) son paket tek kalırsa ──
    def test_son_paket_tek_kalirsa_singlesms_e_gider(self):
        with patch(PACK_SIZE_PATH, 2):
            msgs = self.launch(self.commercial(('Ayşe', 'Can', 'Mehmet')))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual([c['service'] for c in self.net.json_sends], ['bulksms', 'singlesms'])
        self.assert_commercial_single(self.net.json_sends[1])
        self.assertEqual([m.provider_service for m in msgs], ['bulk', 'bulk', 'single'])
        self.assertEqual(len({m.provider_packet_id for m in msgs}), 2, 'İki ayrı paket')

    # ── (d) bilgilendirme tek alıcı ──
    def test_bilgilendirme_tek_alicili_kampanya_bilgi_seti_singlesms(self):
        msgs = self.launch(self.make_json_campaign(names=('Ayşe',), message_type='info', body='Duyuru'))
        self.assertEqual(msgs.state, 'sent', msgs.error)
        call = self.net.json_sends[0]
        self.assertEqual((call['service'], call['user'], int(call['payload']['accountId'])),
                         ('singlesms', 'info_user', 9254))
        self.assertIs(call['payload']['isCheckBlackList'], False)
        self.assertEqual((msgs.provider_service, str(msgs.provider_account_id)), ('single', '9254'))

    # ── ConfirmSms: tek alıcılı reklam paketi singlesms + reklam seti ──
    def test_tek_alicili_ticari_paket_singlesms_ve_reklam_setiyle_onaylanir(self):
        msgs = self.launch(self.commercial(('Ayşe',)))
        self.refresh_all(msgs)
        confirms = self.net.tj.calls_to('Sms/ConfirmSms')
        self.assertEqual(len(confirms), 1)
        self.assertEqual((confirms[0]['service'], confirms[0]['user'], confirms[0]['payload']['accountId']),
                         ('singlesms', 'com_user', 65672))
        self.assertEqual(confirms[0]['payload']['packetId'], int(msgs.provider_packet_id))
        self.assertFalse(msgs.delivery_code, 'Onay tamam: confirm_pending kalmamalı')

    # ── (f) durum sorgusu ──
    def test_tek_alicili_ticari_kayit_durumu_singlesms_ve_reklam_setiyle_sorgulanir(self):
        msgs = self.launch(self.commercial(('Ayşe',)))
        before = len(self.net.json_calls)
        msgs.action_fetch_report()
        self.refresh_all(msgs)
        status = [c for c in self.net.json_calls[before:] if c['endpoint'] == 'Sms/GetStatus']
        self.assertEqual(len(status), 1)
        self.assertEqual((status[0]['service'], status[0]['user'], status[0]['payload']['accountId']),
                         ('singlesms', 'com_user', 65672))
        self.assertEqual(msgs.delivery_state, 'delivered')

    def test_durum_cron_tek_alicili_ticari_kaydi_reklam_setiyle_sorgular(self):
        msgs = self.launch(self.commercial(('Ayşe',)))
        msgs.sudo().write({'sent_at': fields.Datetime.now() - timedelta(hours=1)})
        before = len(self.net.json_calls)
        self.cron_status()
        self.refresh_all(msgs)
        status = [c for c in self.net.json_calls[before:] if c['endpoint'].startswith('Sms/GetStatus')]
        self.assertTrue(status)
        self.assertEqual({(c['service'], c['user']) for c in status}, {('singlesms', 'com_user')})
        self.assertEqual(msgs.delivery_state, 'delivered')

    # ── hata eşlemesi mevcut paket yoluyla aynı ──
    def test_tek_alicili_paket_belirsiz_hata_single_baglamiyla_belirsiz_kalir(self):
        self.net.tj.add_script('Sms/SendSms', requests.ReadTimeout('okuma'))
        msgs = self.launch(self.commercial(('Ayşe',)))
        self.assertEqual(msgs.state, 'uncertain')
        self.assertEqual((msgs.provider_service, str(msgs.provider_account_id)), ('single', '65672'))
        self.assertEqual(len(self.net.json_sends), 1, 'Belirsiz paket tekrar gönderilmez')

    def test_tek_alicili_paket_kalici_hata_kayda_yazilir(self):
        self.net.tj.add_script('Sms/SendSms', json_err(-441, 'Originator not defined'))
        msgs = self.launch(self.commercial(('Ayşe',)))
        self.assertEqual(msgs.state, 'error')
        self.assertIn('-441', msgs.error)
        self.assertEqual(len(self.net.json_sends), 1)

    # ── (e) -1000: Turatel mesajı hata metninde görünür ──
    def test_bulksms_tek_alici_gercek_1000_mesaji_hata_metninde(self):
        client = self.json_client('com', service='bulk')
        with self.assertRaises(TuratelError) as ctx:
            client.send_sms(65672, 'TESTBASLIK', 'Kampanya', ['5321234567'], client_ids=['c1'], reference_id='R',
                            check_blacklist=True)
        text = str(ctx.exception)
        self.assertIn('-1000', text)
        self.assertIn(BULK_SINGLE_RECEIVER_MESSAGE, text)
        self.assertNotIn('tanımlı değil', text, 'Yanlış yönlendiren hesap metni olmamalı')
        self.assertFalse(ctx.exception.uncertain)

    def test_1000_hesap_yok_mesaji_turkce_aciklama_korunur(self):
        client = self.json_client('info', service='single')
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(65672)   # bilgi kullanıcısı reklam hesabını görmez: 'Account not found in user info.'
        self.assertIn('Hesap bu Turatel kullanıcısında tanımlı değil (-1000)', str(ctx.exception))

    def test_1000_mesaji_bossa_eski_metin_ve_rakamlar_maskelenir(self):
        client = self.json_client('info', service='single')
        self.net.tj.add_script('Sms/GetCredit', json_err(-1000, None), json_err(-1000, 'Hata 905321234567 numara'))
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(9254)
        self.assertIn('Hesap bu Turatel kullanıcısında tanımlı değil (-1000)', str(ctx.exception))
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(9254)
        self.assertIn('Turatel hatası -1000: Hata', str(ctx.exception))
        self.assertNotIn('905321234567', str(ctx.exception))

    def test_kampanya_kaydinda_turatel_1000_mesaji_gorunur(self):
        """Turatel yine de -1000 dönerse (ör. tek geçerli alıcı) kullanıcı gerçek mesajı görür."""
        self.net.tj.add_script('Sms/SendSms', json_err(-1000, BULK_SINGLE_RECEIVER_MESSAGE))
        msgs = self.launch(self.commercial(('Ayşe',)))
        self.assertEqual(msgs.state, 'error')
        self.assertIn(BULK_SINGLE_RECEIVER_MESSAGE, msgs.error)

"""Turatel ConfirmSms (kullanıcı kararı 20.10; Turatel cevabı 4): onay zorunlu hesapta SendSms sonrası paket onayı.

Gönderim başarısından ve commit'ten sonra paket başına bir ConfirmSms; hata SMS kaydını bozmaz (delivery_code
'confirm_pending'), "SMS: İletim durumu" cron'u 24 saat yeniden dener. Confirm hiçbir yoldan SendSms'i tekrarlamaz.
"""
from unittest.mock import patch

import requests
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from ..services.turatel import TuratelError
from .common import json_err, SmsTestCase
from .test_delivery_status import StatusMixin
from .test_json_routing import NUMBER

CONFIRM = 'Sms/ConfirmSms'


class ConfirmMixin(StatusMixin):

    def confirms(self, service=None):
        return self.net.tj.calls_to(CONFIRM, service)

    def require_confirm(self):
        if not hasattr(self.json_api().TuratelJsonClient, 'confirm_sms'):
            self.fail('ARAYÜZ YOK: TuratelJsonClient.confirm_sms')

    def send_with_failing_confirm(self, outcome=None):
        self.net.tj.add_script(CONFIRM, outcome or json_err(-5, 'Paket onaylanamadi 5321234567'))
        msg = self.Message.send_sms(NUMBER, 'Onay hatası')
        self.refresh_all(msg)
        return msg

    def assert_pending_confirm(self, msg):
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(msg.delivery_code, 'confirm_pending')
        self.assertEqual(msg.delivery_state, 'pending')


@tagged('post_install', '-at_install')
class TestConfirmSmsClient(ConfirmMixin, SmsTestCase):

    def setUp(self):
        super().setUp()
        self.require_confirm()

    def test_confirm_govdesi_hesap_ve_paket_sayi_bearer(self):
        client = self.json_client('info', 'bulk')
        result = client.send_sms('9254', 'TESTBASLIK', 'Metin', ['5321234567'], client_ids=['c1'], reference_id='r1')
        raw = client.confirm_sms('9254', result.packet_id)
        call = self.confirms()[-1]
        self.assertEqual(call['payload'], {'accountId': 9254, 'packetId': int(result.packet_id)})
        self.assertEqual(call['service'], 'bulksms')
        self.assertEqual(call['user'], 'info_user')
        self.assertIsInstance(raw, str)
        self.assertEqual(self.net.tj.confirmed, [(9254, int(result.packet_id))])

    def test_confirm_hatasi_hic_belirsiz_degil(self):
        client = self.json_client('info', 'single')
        for outcome in (requests.ReadTimeout('okuma'), requests.ConnectionError('koptu'), 500, 'html',
                        json_err(-5, 'Hata 5321234567')):
            with self.subTest(sonuc=repr(outcome)):
                self.net.tj.add_script(CONFIRM, outcome)
                with self.assertRaises(TuratelError) as ctx:
                    client.confirm_sms('9254', '4001')
                self.assertFalse(ctx.exception.uncertain, 'ConfirmSms SMS göndermez; belirsiz sayılmaz')
                self.assertNotIn('5321234567', str(ctx.exception))

    def test_bos_paket_agdan_once_hata(self):
        client = self.json_client('info', 'single')
        with self.assertRaises(TuratelError):
            client.confirm_sms('9254', None)
        self.assertEqual(self.net.json_calls, [])

    def test_jeton_suresi_dolunca_bir_kez_yenilenir(self):
        client = self.json_client('info', 'single')
        result = client.send_sms('9254', 'TESTBASLIK', 'Metin', ['5321234567'], client_ids=['c1'], reference_id='r1')
        self.net.tj.expire_tokens()
        client.confirm_sms('9254', result.packet_id)
        self.assertEqual(len(self.confirms()), 2, 'Kimlik reddinde 1 yenileme + 1 tekrar')
        self.assertEqual(len(self.net.json_sends), 1)


@tagged('post_install', '-at_install')
class TestConfirmSmsFlow(ConfirmMixin, SmsTestCase):

    def setUp(self):
        super().setUp()
        self.require_confirm()

    # ── başarılı onay ──
    def test_tekli_senkron_gonderimde_paket_onaylanir(self):
        msg = self.Message.send_sms(NUMBER, 'Merhaba')
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent', msg.error)
        confirms = self.confirms()
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0]['payload'], {'accountId': 9254, 'packetId': int(msg.provider_packet_id)})
        self.assertEqual((confirms[0]['service'], confirms[0]['user']), ('singlesms', 'info_user'))
        self.assertFalse(msg.delivery_code, 'Başarılı onayda kod temiz')
        self.assertEqual(msg.delivery_state, 'pending')
        self.assertEqual(len(self.net.json_sends), 1)
        endpoints = [e for e in self.net.json_endpoints if e != 'Auth/GetToken']
        self.assertEqual(endpoints, ['Sms/SendSms', CONFIRM], 'Onay gönderimden SONRA')

    def test_kuyruk_yolunda_onay_commit_sonrasi(self):
        msg = self.Message.send_sms(NUMBER, 'Kuyruk', queue=True)
        seen = []

        def on_call(call):
            if call['endpoint'] == CONFIRM:
                # flush yok: yalnız commit edilmiş (flush edilmiş) değer görünür
                self.env.cr.execute('SELECT state, delivery_code, provider_packet_id FROM sms_system_message '
                                    'WHERE id = %s', (msg.id,))
                seen.append(self.env.cr.fetchone())
        self.net.tj.hook = on_call
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:2], ('sent', 'confirm_pending'), 'Onaydan önce sent + paket commit edilmeli')
        self.assertTrue(seen[0][2])
        self.assertFalse(msg.delivery_code)
        self.assertEqual(self.events[-1][0], 'commit', 'Onay sonucu da commit edilir')

    def test_kampanya_paketinde_paket_basina_tek_onay(self):
        camp = self.make_json_campaign(names=('Ayşe', 'Mehmet', 'Can'), body='Merhaba {ad}')
        seen = []

        def on_call(call):
            if call['endpoint'] == CONFIRM:
                self.env.cr.execute('SELECT count(*) FROM sms_system_message WHERE campaign_id = %s '
                                    "AND state = 'sent' AND delivery_code = 'confirm_pending'", (camp.id,))
                seen.append(self.env.cr.fetchone()[0])
        self.net.tj.hook = on_call
        msgs = self.launch(camp)
        self.refresh_all(*msgs)
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(len(self.sends('bulksms')), 1)
        confirms = self.confirms()
        self.assertEqual(len(confirms), 1, 'Paket başına tek ConfirmSms')
        self.assertEqual(confirms[0]['payload']['packetId'], int(msgs[0].provider_packet_id))
        self.assertEqual(confirms[0]['service'], 'bulksms')
        self.assertEqual(seen, [3], 'Onaydan önce paket sent + commit')
        self.assertEqual(set(msgs.mapped('delivery_code')), {False})

    def test_ticari_kampanya_reklam_setiyle_onaylanir(self):
        self.configure_json(iys=True)
        msgs = self.launch(self.make_json_campaign(message_type='commercial', body='Sabit metin'))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        confirms = self.confirms()
        self.assertEqual(len(confirms), 1)
        self.assertEqual((confirms[0]['user'], confirms[0]['payload']['accountId']), ('com_user', 65672))

    def test_kampanya_deneme_gonderimi_onaylanir(self):
        camp = self.make_json_campaign(body='Deneme {ad}')
        self.sms_manager.partner_id.phone = NUMBER
        camp.with_user(self.sms_manager).action_send_test_to_me()
        self.assertEqual(len(self.confirms('singlesms')), 1)

    # ── hata: kayıt bozulmaz ──
    def test_onay_hatasi_kaydi_bozmaz_istisna_yok(self):
        for outcome in (json_err(-5, 'Paket onaylanamadi 5321234567'), requests.ReadTimeout('okuma'), 503,
                        requests.ConnectTimeout('baglanti')):
            with self.subTest(sonuc=repr(outcome)):
                before = len(self.net.json_sends)
                msg = self.send_with_failing_confirm(outcome)
                self.assert_pending_confirm(msg)
                self.assertEqual(len(self.net.json_sends), before + 1, 'Onay hatası SendSms tekrarlatmaz')
                self.assertIn('ConfirmSms', msg.delivery_report or '')
                self.assertNotIn('5321234567', msg.delivery_report or '')
                self.assertEqual(msg.delivery_label, 'Turatel onayı bekleniyor')
                self.assertFalse(msg.error)

    def test_onay_hatasi_kuyruk_ve_kampanyada_da_yutulur(self):
        self.net.tj.add_script(CONFIRM, requests.ReadTimeout('a'), requests.ReadTimeout('b'))
        single = self.Message.send_sms(NUMBER, 'Kuyruk', queue=True)
        self.Message._cron_send_queued()
        msgs = self.launch(self.make_json_campaign(body='Sabit metin'))
        self.refresh_all(single, *msgs)
        for msg in single | msgs:
            self.assert_pending_confirm(msg)
        self.assertEqual(len(self.net.json_sends), 2)

    def test_onay_yazimi_hatasi_da_yutulur(self):
        """Yardımcının içindeki yazım hatası (savepoint) dışarı sızmaz; SMS kaydı 'sent' kalır."""
        msg = self.send_with_failing_confirm()
        orig_write = type(self.Message).write

        def failing_write(records, vals):
            if 'delivery_report' in vals:
                raise ValueError('yazılamadı')
            return orig_write(records, vals)
        with patch.object(type(self.Message), 'write', failing_write):
            msg.sudo()._confirm_sent_packets(msg._settings())
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(msg.delivery_code, 'confirm_pending')

    # ── cron yeniden denemesi ──
    def test_cron_yeniden_dener_ve_temizler(self):
        msg = self.send_with_failing_confirm()
        self.net.tj.status_empty = True
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(len(self.confirms()), 2)
        self.assertFalse(msg.delivery_code)
        self.assertEqual(msg.delivery_state, 'pending')
        self.cron_status()
        self.assertEqual(len(self.confirms()), 2, 'Onaylanan paket yeniden onaylanmaz')
        self.assertEqual(len(self.net.json_sends), 1, 'Cron SendSms çağırmaz')

    def test_cron_24_saatten_eski_kaydi_denemez(self):
        old = self.make_tracked(hours_ago=25, message_id='991001', provider_packet_id='4990',
                                delivery_code='confirm_pending')
        young = self.make_tracked(hours_ago=23, message_id='991002', provider_packet_id='4991',
                                  delivery_code='confirm_pending', number='05321234568')
        self.net.tj.status_empty = True
        self.cron_status()
        packets = [c['payload']['packetId'] for c in self.confirms()]
        self.assertEqual(packets, [4991])
        self.refresh_all(old, young)
        self.assertEqual(old.delivery_code, 'confirm_pending')
        self.assertEqual(young.delivery_code, 'confirm_pending', 'Taklitte paket yok: hata, kayıt bekler')
        self.assertIn('ConfirmSms', young.delivery_report or '')

    def test_cron_paket_basina_bir_onay_ve_commit(self):
        a = self.make_tracked(message_id='991011', provider_packet_id='4995', delivery_code='confirm_pending')
        b = self.make_tracked(message_id='991012', provider_packet_id='4995', delivery_code='confirm_pending',
                              number='05321234568')
        self.net.tj.status_empty = True
        self.cron_status()
        self.assertEqual([c['payload']['packetId'] for c in self.confirms()], [4995])
        self.assertTrue(any(e[0] == 'commit' and e[1] == 2 for e in self.events), 'Paket sonrası commit(2)')
        self.refresh_all(a, b)

    def test_cron_hata_tek_uyari_satiri(self):
        for i in range(3):
            self.make_tracked(message_id='99102%d' % i, provider_packet_id='496%d' % i,
                              delivery_code='confirm_pending', number='0532123456%d' % i)
        self.net.tj.status_empty = True
        with self.capture_logs() as logs:
            self.cron_status()
        lines = [line for line in self.warnings(logs) if 'ConfirmSms' in line]
        self.assertEqual(len(lines), 1, lines)
        self.assertNotIn('Bearer', ''.join(lines))

    def test_durumu_sorgula_once_onaylar(self):
        msg = self.send_with_failing_confirm()
        self.net.tj.set_code(msg.provider_msg_id, 0)
        before = len(self.net.json_calls)
        msg.action_fetch_report()
        endpoints = [c['endpoint'] for c in self.net.json_calls[before:] if c['endpoint'] != 'Auth/GetToken']
        self.assertEqual(endpoints, [CONFIRM, 'Sms/GetStatus'])
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')
        self.assertEqual(len(self.net.json_sends), 1)

    def test_durum_satiri_bekleyen_onayi_ezmez_nihai_kod_ezer(self):
        msg = self.make_tracked(message_id='991031', provider_packet_id='4970', delivery_code='confirm_pending')
        Row = self.json_api().StatusRow
        msg._apply_status_rows([Row('991031', None, '777', '{}')])
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('unknown', 'confirm_pending'))
        msg._apply_status_rows([Row('991031', None, '0', '{}')])
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('delivered', '0'))

    # ── ayar, legacy, test modu ──
    def test_ayar_kapali_onay_cagrilmaz(self):
        self.configure_json(iys=True)
        self.set_param('turatel_confirm_info', 'False')
        msg = self.Message.send_sms(NUMBER, 'Kapalı')
        info = self.launch(self.make_json_campaign(body='Sabit metin'))
        self.refresh_all(msg, *info)
        self.assertEqual(self.confirms(), [])
        self.assertFalse(msg.delivery_code)
        self.assertEqual(set(info.mapped('delivery_code')), {False})
        pending = self.make_tracked(message_id='991041', provider_packet_id='4980', delivery_code='confirm_pending',
                                    number='05321234569')
        self.net.tj.status_empty = True
        self.cron_status()
        self.assertEqual(self.confirms(), [], 'Ayar kapalıyken cron da onaylamaz')
        # Reklam seti ayarı bağımsız
        com = self.launch(self.make_json_campaign(message_type='commercial', body='Sabit metin'))
        self.assertEqual([c['user'] for c in self.confirms()], ['com_user'])
        self.refresh_all(pending, *com)
        self.assertEqual(pending.delivery_code, 'confirm_pending')

    def test_ayar_yoksa_acik_yalniz_tam_false_kapatir(self):
        for value, expected in ((None, True), ('', True), ('True', True), ('0', True), ('False', False)):
            with self.subTest(deger=value):
                self.set_param('turatel_confirm_commercial', value)
                self.assertIs(self.Message._settings()['confirm']['commercial'], expected)

    def test_legacy_modda_onay_yok(self):
        pending = self.make_tracked(message_id='991051', provider_packet_id='4981', delivery_code='confirm_pending')
        self.set_param('api_mode', 'legacy_xml')
        self.Message.send_sms(NUMBER, 'Eski')
        self.launch(self.make_json_campaign(body='Sabit metin'))
        self.cron_status()
        self.assertEqual(self.net.json_calls, [])
        self.refresh_all(pending)
        self.assertEqual(pending.delivery_code, 'confirm_pending')

    def test_test_modunda_yalniz_test_numarasi_onaylanir(self):
        self.configure_json(test_mode='True')
        self.set_param('test_numbers', '05321234568')
        blocked = self.Message.send_sms(NUMBER, 'Engel')
        self.assertEqual(blocked.state, 'test')
        self.assertEqual(self.net.json_calls, [])
        allowed = self.Message.send_sms('05321234568', 'Serbest')
        self.assertEqual(allowed.state, 'sent', allowed.error)
        self.assertEqual(len(self.confirms()), 1)

    def test_onay_sendsms_i_hicbir_yoldan_tekrarlamaz(self):
        self.net.tj.add_script(CONFIRM, *([json_err(-5, 'x')] * 6))
        self.net.tj.status_empty = True   # iletildi kodu onay beklemeyi bitirirdi
        msg = self.Message.send_sms(NUMBER, 'Tek')
        self.cron_status()
        self.cron_status()
        msg.action_fetch_report()
        self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.json_sends), 1)
        self.assertEqual(len(self.confirms()), 4, 'gönderim + 2 cron + Durumu Sorgula')
        self.refresh_all(msg)
        self.assert_pending_confirm(msg)

    # ── etiketler ──
    def test_etiketler(self):
        labels = dict(self.Message._fields['delivery_state'].selection)
        self.assertEqual(labels['pending'], 'Yanıt bekleniyor')
        msg = self.make_tracked(message_id='991061', delivery_code='confirm_pending')
        self.assertEqual(msg.delivery_label, 'Turatel onayı bekleniyor')


@tagged('post_install', '-at_install')
class TestConfirmSmsSettings(ConfirmMixin, SmsTestCase):

    def settings(self, user=None):
        rec = self.env['res.config.settings'].create({})
        return rec.with_user(user) if user else rec

    def test_ayarlar_varsayilan_acik_ve_kolon_yok(self):
        fields_ = self.env['res.config.settings']._fields
        for name in ('sms_confirm_info', 'sms_confirm_commercial'):
            self.assertIn(name, fields_)
            self.assertFalse(fields_[name].store, 'Geçici tabloya kolon eklenmemeli (deploy penceresi)')
        rec = self.settings()
        self.assertTrue(rec.sms_confirm_info)
        self.assertTrue(rec.sms_confirm_commercial)

    def test_yonetici_dugmesi_ayari_degistirir(self):
        rec = self.settings()
        rec.with_context(sms_confirm_set='info').action_sms_toggle_confirm()
        self.assertEqual(self.icp.get_param('sms_system.turatel_confirm_info'), 'False')
        self.assertIsNot(self.icp.get_param('sms_system.turatel_confirm_commercial'), 'False')
        rec.invalidate_recordset()
        self.assertFalse(rec.sms_confirm_info)
        rec.with_context(sms_confirm_set='info').action_sms_toggle_confirm()
        self.assertEqual(self.icp.get_param('sms_system.turatel_confirm_info'), 'True')
        with self.assertRaises(UserError):
            rec.with_context(sms_confirm_set='baska').action_sms_toggle_confirm()

    def test_yonetici_olmayan_degistiremez(self):
        rec = self.settings()
        for user in (self.sms_manager, self.plain_user):
            with self.subTest(kullanici=user.login):
                with self.assertRaises(AccessError):
                    rec.with_user(user).with_context(sms_confirm_set='commercial').action_sms_toggle_confirm()
        self.assertFalse(self.icp.get_param('sms_system.turatel_confirm_commercial'))

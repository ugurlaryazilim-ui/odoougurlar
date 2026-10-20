"""Turatel ConfirmSms (kullanıcı kararı 20.10; Turatel cevabı 4): onay zorunlu hesapta SendSms sonrası paket onayı.

Cron gönderimlerinde (kuyruk, kampanya) gönderim commit'inden sonra paket başına bir ConfirmSms; kullanıcı isteği
içindeki senkron gönderim onaylamaz, iletim durumu cron'unu tetikler. Geçici hata 'confirm_pending' bırakır (cron
yeniden dener), kalıcı hata 'confirm_failed' yapar; hiçbiri SMS kaydını bozmaz ve SendSms'i tekrarlamaz.
"""
import time
from unittest.mock import patch

import requests
from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from ..models import sms_message as sms_message_module
from ..services.turatel import TuratelError
from .common import json_err, SmsTestCase
from .test_delivery_status import StatusMixin
from .test_json_routing import NUMBER

CONFIRM = 'Sms/ConfirmSms'
STATUS_CRON = 'sms_system.cron_sms_delivery_status'


class ConfirmMixin(StatusMixin):

    def confirms(self, service=None):
        return self.net.tj.calls_to(CONFIRM, service)

    def confirmed_packets(self):
        return [c['payload']['packetId'] for c in self.confirms()]

    def require_confirm(self):
        if not hasattr(self.json_api().TuratelJsonClient, 'confirm_sms'):
            self.fail('ARAYÜZ YOK: TuratelJsonClient.confirm_sms')

    def status_triggers(self):
        cron = self.env.ref(STATUS_CRON)
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', cron.id)])

    def send_with_failing_confirm(self, outcome=None):
        """Kuyruk yolu (onay cron içinde, gönderim commit'inden sonra); varsayılan hata geçicidir."""
        self.net.tj.add_script(CONFIRM, outcome or requests.ReadTimeout('okuma 5321234567'))
        msg = self.Message.send_sms(NUMBER, 'Onay hatası', queue=True)
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        return msg

    def make_pending(self, i, hours_ago=1, known=True, **vals):
        """Onay bekleyen gönderilmiş kayıt; known: paket Turatel taklidinde var (onay başarılı olur)."""
        packet = 5000 + i
        msg = self.make_tracked(message_id=str(992000 + i), provider_packet_id=str(packet),
                                delivery_code='confirm_pending', number='0532123%04d' % i, hours_ago=hours_ago,
                                **vals)
        if known:
            self.net.tj.messages[992000 + i] = {
                'message_id': 992000 + i, 'client_id': self.client_id_of(msg), 'number': msg.number,
                'account': 9254, 'packet_id': packet, 'reference_id': None, 'user': 'info_user', 'code': 0,
                'when': fields.Datetime.now()}
        return msg

    def run_confirm_step(self, started=None):
        Message = self.Message.sudo()
        return Message._cron_confirm_pending(Message._settings(), time.monotonic() if started is None else started)

    def assert_pending_confirm(self, msg, code='confirm_pending'):
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(msg.delivery_code, code)
        self.assertEqual(msg.delivery_state, 'pending')


@tagged('post_install', '-at_install')
class TestConfirmSmsClient(ConfirmMixin, SmsTestCase):

    def setUp(self):
        super().setUp()
        self.require_confirm()

    def test_confirm_govdesi_hesap_ve_paket_sayi_bearer(self):
        client = self.json_client('info', 'bulk')
        result = client.send_sms('9254', 'TESTBASLIK', 'Metin', ['5321234567', '5321234568'], client_ids=['c1', 'c2'],
                                 reference_id='r1')   # bulksms en az 2 alıcı ister
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

    # ── senkron (istek içi) gönderim: onay istekte değil, cron tetiklenir ──
    def test_senkron_gonderimde_istekte_onay_yok_cron_tetiklenir_ve_onaylar(self):
        before = self.status_triggers()
        msg = self.Message.send_sms(NUMBER, 'Merhaba')
        self.refresh_all(msg)
        self.assertEqual(self.confirms(), [], 'İstek içinde (commit öncesi) ConfirmSms yok')
        self.assert_pending_confirm(msg)
        self.assertEqual(self.status_triggers(), before + 1, 'İletim durumu cron\'u hemen tetiklenir')
        self.net.tj.status_empty = True
        self.cron_status()
        self.refresh_all(msg)
        confirms = self.confirms()
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0]['payload'], {'accountId': 9254, 'packetId': int(msg.provider_packet_id)})
        self.assertEqual((confirms[0]['service'], confirms[0]['user']), ('singlesms', 'info_user'))
        self.assertFalse(msg.delivery_code, 'Başarılı onayda kod temiz')
        self.assertEqual(msg.delivery_state, 'pending')
        self.assertEqual(len(self.net.json_sends), 1)
        endpoints = [e for e in self.net.json_endpoints if e != 'Auth/GetToken']
        self.assertEqual(endpoints[:2], ['Sms/SendSms', CONFIRM], 'Onay gönderimden SONRA')

    def test_senkron_gonderim_onay_gerekmezse_tetik_yok(self):
        self.set_param('turatel_confirm_info', 'False')
        before = self.status_triggers()
        msg = self.Message.send_sms(NUMBER, 'Kapalı')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(self.status_triggers(), before)
        self.set_param('turatel_confirm_info', 'True')
        self.Message.send_sms('05321234568', 'Engelli', queue=True)
        self.assertEqual(self.status_triggers(), before, 'Kuyruk yolu kuyruk cron\'unu tetikler, durum cron\'unu değil')

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
        camp = self.make_json_campaign(names=('Ayşe', 'Mehmet', 'Can'), body='Merhaba')
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

    def test_kampanya_deneme_gonderimi_istekte_onaylanmaz_cron_onaylar(self):
        camp = self.make_json_campaign(body='Deneme {ad}')
        self.sms_manager.partner_id.phone = NUMBER
        before = self.status_triggers()
        camp.with_user(self.sms_manager).action_send_test_to_me()
        self.assertEqual(self.confirms(), [])
        self.assertEqual(self.status_triggers(), before + 1)
        self.net.tj.status_empty = True
        self.cron_status()
        self.assertEqual(len(self.confirms('singlesms')), 1)

    # ── hata: kayıt bozulmaz; geçici → bekler, kalıcı → başarısız ──
    def test_onay_hatasi_kaydi_bozmaz_gecici_bekler_kalici_basarisiz(self):
        for outcome, code, label in (
                (requests.ReadTimeout('okuma 5321234567'), 'confirm_pending', 'Turatel onayı bekleniyor'),
                (503, 'confirm_pending', 'Turatel onayı bekleniyor'),
                (requests.ConnectTimeout('baglanti'), 'confirm_pending', 'Turatel onayı bekleniyor'),
                (json_err(-5, 'Paket onaylanamadi 5321234567'), 'confirm_failed', 'Turatel onayı başarısız')):
            with self.subTest(sonuc=repr(outcome)):
                before = len(self.net.json_sends)
                msg = self.send_with_failing_confirm(outcome)
                self.assert_pending_confirm(msg, code)
                self.assertEqual(len(self.net.json_sends), before + 1, 'Onay hatası SendSms tekrarlatmaz')
                self.assertIn('ConfirmSms', msg.delivery_report or '')
                self.assertNotIn('5321234567', msg.delivery_report or '')
                self.assertEqual(msg.delivery_label, label)
                self.assertFalse(msg.error)

    def test_kimlik_seti_olmayan_hesap_kalici_hata(self):
        msg = self.make_pending(1, account='1111')
        self.run_confirm_step()
        self.refresh_all(msg)
        self.assertEqual(self.confirms(), [], 'Set yoksa ağ isteği yok')
        self.assert_pending_confirm(msg, 'confirm_failed')

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

    def test_ilgisiz_flush_hatasi_yutulmaz(self):
        """Onaydan önceki bekleyen yazımların flush hatası onay hatası sayılıp yutulmamalı."""
        msg = self.send_with_failing_confirm()
        with patch.object(type(self.env), 'flush_all', side_effect=RuntimeError('ilgisiz flush')):
            with self.assertRaisesRegex(RuntimeError, 'ilgisiz flush'):
                msg.sudo()._confirm_sent_packets(msg._settings())
        self.assertEqual(len(self.confirms()), 1, 'Flush hatasında ağ isteği yapılmaz')

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

    def test_kalici_hata_cronla_denenmez_durumu_sorgula_yeniden_dener(self):
        msg = self.send_with_failing_confirm(json_err(-5, 'Onay yetkisi yok'))
        self.assert_pending_confirm(msg, 'confirm_failed')
        self.net.tj.status_empty = True
        self.cron_status()
        self.cron_status()
        self.assertEqual(len(self.confirms()), 1, 'confirm_failed cron ile yeniden denenmez')
        msg.action_fetch_report()
        self.refresh_all(msg)
        self.assertEqual(len(self.confirms()), 2, '"Durumu Sorgula" başarısız onayı elle yeniden dener')
        self.assertFalse(msg.delivery_code)
        self.assertEqual(len(self.net.json_sends), 1)

    def test_cron_penceresi_24_saat_ve_gecerlilik_suresi(self):
        self.set_param('turatel_validity_minutes', '1440')
        old = self.make_pending(1, hours_ago=25)
        young = self.make_pending(2, hours_ago=23)
        self.run_confirm_step()
        self.assertEqual(self.confirmed_packets(), [5002])
        self.refresh_all(old, young)
        self.assertEqual(old.delivery_code, 'confirm_pending', 'Pencere dışı kayıt denenmez, işaret kalır')
        self.assertFalse(young.delivery_code)
        # Geçerlilik süresi 24 saatten kısaysa pencere geçerlilik süresidir (süresi dolan SMS onaylanmaz)
        self.set_param('turatel_validity_minutes', '60')
        expired = self.make_pending(3, hours_ago=2)
        fresh = self.make_pending(4, hours_ago=0.5)
        self.run_confirm_step()
        self.assertEqual(self.confirmed_packets(), [5002, 5004])
        self.refresh_all(expired, fresh)
        self.assertEqual(expired.delivery_code, 'confirm_pending')
        self.assertFalse(fresh.delivery_code)

    def test_cron_paket_basina_bir_onay_ve_commit(self):
        a = self.make_tracked(message_id='991011', provider_packet_id='4995', delivery_code='confirm_pending')
        b = self.make_tracked(message_id='991012', provider_packet_id='4995', delivery_code='confirm_pending',
                              number='05321234568')
        self.net.tj.status_empty = True
        self.cron_status()
        self.assertEqual([c['payload']['packetId'] for c in self.confirms()], [4995])
        self.assertTrue(any(e[0] == 'commit' and e[1] == 2 for e in self.events), 'Paket sonrası commit(2)')
        self.refresh_all(a, b)

    def test_cron_en_yeniden_baslar_ve_paket_tavanina_uyar(self):
        limit = sms_message_module.CONFIRM_MAX_PACKETS
        msgs = [self.make_pending(i) for i in range(limit + 2)]
        failed, stats = self.run_confirm_step()
        self.assertEqual(failed, [])
        expected = [5000 + i for i in reversed(range(limit + 2))][:limit]
        self.assertEqual(self.confirmed_packets(), expected, 'En yeni paket önce; çalışma başına tavan')
        self.assertEqual(stats['onay ertelendi'], 1)
        self.refresh_all(*msgs)
        self.assertEqual([m.delivery_code for m in msgs[:2]], ['confirm_pending'] * 2, 'En eskiler sonraki çalışmaya')
        self.run_confirm_step()
        self.assertEqual(self.confirmed_packets()[limit:], [5001, 5000])

    def test_cron_onay_suresi_tavani_durum_sorgusuna_yer_birakir(self):
        self.assertLess(sms_message_module.CONFIRM_TIME_BUDGET, sms_message_module.STATUS_TIME_BUDGET)
        self.make_pending(1)
        started = time.monotonic() - sms_message_module.CONFIRM_TIME_BUDGET - 1
        _failed, stats = self.run_confirm_step(started)
        self.assertEqual(self.confirms(), [])
        self.assertEqual(stats['onay ertelendi'], 1)

    def test_cron_art_arda_ayni_hata_onayi_keser(self):
        msgs = [self.make_pending(i) for i in range(5)]
        self.net.tj.add_script(CONFIRM, *[requests.ReadTimeout('okuma')] * 5)
        failed, stats = self.run_confirm_step()
        self.assertEqual(len(self.confirms()), 3, 'Art arda 3 aynı hata: bu çalışmada onay kesilir')
        self.assertEqual(len(failed), 3)
        self.assertEqual(stats['onay kesildi (art arda aynı hata)'], 1)
        self.refresh_all(*msgs)
        self.assertEqual({m.delivery_code for m in msgs}, {'confirm_pending'}, 'Geçici hata: hepsi bekler')

    def test_cron_farkli_hatalar_kesmez(self):
        for i in range(5):
            self.make_pending(i)
        self.net.tj.add_script(CONFIRM, requests.ReadTimeout('a'), 503, requests.ReadTimeout('b'), 503,
                               requests.ReadTimeout('c'))
        failed, stats = self.run_confirm_step()
        self.assertEqual(len(self.confirms()), 5)
        self.assertEqual(len(failed), 5)
        self.assertFalse(stats['onay kesildi (art arda aynı hata)'])

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

    def test_durum_satiri_onay_isaretini_ezmez_nihai_kod_ezer(self):
        Row = self.json_api().StatusRow
        for i, code in enumerate(('confirm_pending', 'confirm_failed')):
            with self.subTest(kod=code):
                mid = '99103%d' % i
                msg = self.make_tracked(message_id=mid, provider_packet_id='497%d' % i, delivery_code=code,
                                        number='0532123457%d' % i)
                msg._apply_status_rows([Row(mid, None, 'status:5', '{}')])
                self.refresh_all(msg)
                self.assertEqual((msg.delivery_state, msg.delivery_code), ('unknown', code))
                msg._apply_status_rows([Row(mid, None, 'status:1', '{}')])
                self.refresh_all(msg)
                self.assertEqual((msg.delivery_state, msg.delivery_code), ('delivered', 'status:1'))

    def test_uzlasan_belirsiz_kayit_paket_yoksa_onay_bilinmiyor_notu(self):
        Row = self.json_api().StatusRow
        bare = self.make_tracked(message_id='991071', state='uncertain', provider_packet_id=False)
        packed = self.make_tracked(message_id='991072', state='uncertain', provider_packet_id='4975',
                                   number='05321234568')
        (bare | packed)._apply_status_rows([Row('991071', None, 'status:2', '{}'), Row('991072', None, 'status:2', '{}')])
        self.refresh_all(bare, packed)
        self.assertEqual((bare.state, packed.state), ('sent', 'sent'))
        self.assertIn('onay durumu bilinmiyor', bare.delivery_report or '')
        self.assertNotIn('onay durumu bilinmiyor', packed.delivery_report or '')

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
        before = self.status_triggers()
        self.Message.send_sms(NUMBER, 'Eski')
        self.assertEqual(self.status_triggers(), before)
        self.launch(self.make_json_campaign(body='Sabit metin'))
        self.cron_status()
        self.assertEqual(self.net.json_calls, [])
        self.refresh_all(pending)
        self.assertEqual(pending.delivery_code, 'confirm_pending')

    def test_test_modunda_yalniz_test_numarasi_onaylanir(self):
        self.configure_json(test_mode='True')
        self.set_param('test_numbers', '05321234568')
        before = self.status_triggers()
        blocked = self.Message.send_sms(NUMBER, 'Engel')
        self.assertEqual(blocked.state, 'test')
        self.assertEqual(self.net.json_calls, [])
        self.assertEqual(self.status_triggers(), before, 'Gönderilmeyen kayıt için tetik yok')
        allowed = self.Message.send_sms('05321234568', 'Serbest')
        self.assertEqual(allowed.state, 'sent', allowed.error)
        self.assertEqual(self.confirms(), [])
        self.net.tj.status_empty = True
        self.cron_status()
        self.assertEqual(len(self.confirms()), 1)
        self.refresh_all(blocked)
        self.assertFalse(blocked.delivery_code)

    def test_onay_sendsms_i_hicbir_yoldan_tekrarlamaz(self):
        self.net.tj.add_script(CONFIRM, *[requests.ReadTimeout('x')] * 6)
        self.net.tj.status_empty = True   # iletildi kodu onay beklemeyi bitirirdi
        msg = self.Message.send_sms(NUMBER, 'Tek')
        self.cron_status()
        self.cron_status()
        msg.action_fetch_report()
        self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.json_sends), 1)
        self.assertEqual(len(self.confirms()), 3, '2 cron + Durumu Sorgula (senkron gönderim istekte onaylamaz)')
        self.refresh_all(msg)
        self.assert_pending_confirm(msg)

    # ── etiketler ──
    def test_etiketler(self):
        labels = dict(self.Message._fields['delivery_state'].selection)
        self.assertEqual(labels['pending'], 'Yanıt bekleniyor')
        msg = self.make_tracked(message_id='991061', delivery_code='confirm_pending')
        self.assertEqual(msg.delivery_label, 'Turatel onayı bekleniyor')
        msg.delivery_code = 'confirm_failed'
        self.assertEqual(msg.delivery_label, 'Turatel onayı başarısız')

    def test_arama_filtreleri(self):
        arch = self.env.ref('sms_system.view_sms_message_search').arch
        for name in ('confirm_pending', 'confirm_failed'):
            self.assertIn('name="%s"' % name, arch)


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

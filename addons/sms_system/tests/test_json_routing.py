"""KK-C8 (log/sır), C10..C15 (yönlendirme, alanlar, legacy, test modu), C17 (mükerrer), C29/C30 (reklam seti, jeton)."""
from unittest.mock import patch

import requests
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import json_err, json_ok, tail10, SmsTestCase
from .test_campaign import CampaignMixin

NUMBER = '05321234567'
RET_TEXT = 'Ret icin RET yazip 3030a gonderin. Mersis 0123456789012345'


class JsonModelMixin(CampaignMixin):

    _contact_seq = 0

    def setUp(self):
        super().setUp()
        self.configure_json()
        self.set_param('optout_text', RET_TEXT)

    def new_mobile(self):
        type(self)._contact_seq += 1
        return '5330%06d' % type(self)._contact_seq

    def make_json_campaign(self, names=('Ayşe', 'Mehmet', 'Can'), message_type='info', body='Merhaba {ad}',
                           state='draft', **vals):
        lst = self.make_list()
        fresh = self.ago(hours=1)
        for name in names:
            extra = {'iys_status': 'approved', 'iys_checked_at': fresh} if message_type == 'commercial' else {}
            self.make_contact(self.new_mobile(), lst, name=name, **extra)
        return self.make_campaign(lst, message_type, state=state, body=body, **vals)

    def launch(self, camp):
        camp.action_send()
        self.run_queue()
        return self.campaign_msgs(camp)

    def campaign_msgs(self, camp):
        return self.Message.search([('campaign_id', '=', camp.id)], order='id')

    def sends(self, service=None):
        return [c for c in self.net.json_sends if service is None or c['service'] == service]

    def sends_with(self, message):
        """Bu kaydı (clientId ile) içeren SendSms isteği sayısı."""
        cid = self.client_id_of(message)
        return len([c for c in self.net.json_sends
                    if cid in [p.get('clientId') for p in (c['payload'].get('personalMessages') or [])]])

    def cron_status(self):
        if not hasattr(self.Message, '_cron_fetch_delivery_status'):
            self.fail('ARAYÜZ YOK: sms.system.message._cron_fetch_delivery_status (tasarım §5.5)')
        return self.Message._cron_fetch_delivery_status()

    def refresh_all(self, *records):
        self.env.flush_all()
        for rec in records:
            rec.invalidate_recordset()


@tagged('post_install', '-at_install')
class TestJsonRouting(JsonModelMixin, SmsTestCase):

    # ── KK-C10: tekli yollar ──
    def assert_single_info(self, call):
        self.assertEqual(call['service'], 'singlesms')
        self.assertEqual(call['user'], 'info_user')
        self.assertEqual(int(call['payload']['accountId']), 9254)
        self.assertIs(call['payload']['isCheckBlackList'], False)

    def test_kk_c10_send_sms_senkron_singlesms_bilgi_hesabi(self):
        msg = self.Message.send_sms(NUMBER, 'Merhaba dünya')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(len(self.net.json_sends), 1)
        self.assert_single_info(self.net.json_sends[0])
        self.assertEqual(self.net.smartadm_calls, [])
        self.assertEqual(self.net.turatel_calls, [], 'Eski XML adresine istek gitmemeli')

    def test_kk_c10_kuyruk_yolu_singlesms(self):
        msg = self.Message.send_sms(NUMBER, 'Kuyruk', queue=True)
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(self.net.json_sends, [])
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(len(self.net.json_sends), 1)
        self.assert_single_info(self.net.json_sends[0])

    def test_kk_c10_tekli_yeniden_deneme_singlesms(self):
        msg = self.make_message(NUMBER, state='error', body='Tekrar', retry_count=1)
        msg.action_retry()
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assert_single_info(self.net.json_sends[0])

    def test_kk_c10_otomatik_yeniden_deneme_cron_singlesms(self):
        msg = self.make_message(NUMBER, state='error', body='Cron', retry_count=1)
        self.set_write_date(msg, 30)
        self.Message._cron_retry_failed()
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assert_single_info(self.net.json_sends[0])

    def test_kk_c10_kampanya_deneme_gonderimi_tekli_yol_bilgi_hesabi(self):
        camp = self.make_json_campaign(message_type='info', body='Deneme {ad}')
        self.sms_manager.partner_id.phone = NUMBER
        camp.with_user(self.sms_manager).action_send_test_to_me()
        self.assertEqual(len(self.net.json_sends), 1)
        self.assert_single_info(self.net.json_sends[0])
        self.assertEqual(self.net.smartadm_calls, [])

    def test_kk_c10_yeni_sms_sihirbazi_singlesms(self):
        wiz = self.env['sms.system.send.wizard'].with_user(self.sms_manager).create({'number': NUMBER, 'body': 'Elle'})
        wiz.action_send()
        self.assertEqual(len(self.net.json_sends), 1)
        self.assert_single_info(self.net.json_sends[0])

    def test_kk_c10_ticari_kampanya_ayari_tekli_gonderimi_degistirmez(self):
        """Reklam seti tanımsız olsa da tekli gönderim bilgi setiyle gider (KK-C29 kapsamı)."""
        self.configure_json(commercial=False)
        msg = self.Message.send_sms(NUMBER, 'Tekli')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assert_single_info(self.net.json_sends[0])

    # ── KK-C11: kampanya paketleri ──
    def test_kk_c11_bilgilendirme_kampanyasi_bulksms_bilgi_hesabi(self):
        for message_type in ('info', 'staff'):
            with self.subTest(tur=message_type):
                before = len(self.net.json_sends)
                camp = self.make_json_campaign(message_type=message_type)
                msgs = self.launch(camp)
                self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
                calls = self.net.json_sends[before:]
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['service'], 'bulksms')
                self.assertEqual(calls[0]['user'], 'info_user')
                self.assertEqual(int(calls[0]['payload']['accountId']), 9254)
                self.assertIs(calls[0]['payload']['isCheckBlackList'], False)

    def test_kk_c11_ticari_kampanya_bulksms_reklam_hesabi_kara_liste_true(self):
        self.configure_json(iys=True)
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}')
        msgs = self.launch(camp)
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(len(self.net.json_sends), 1)
        call = self.net.json_sends[0]
        self.assertEqual(call['service'], 'bulksms')
        self.assertEqual(call['user'], 'com_user', 'Reklam isteği reklam kimlik setiyle gitmeli')
        self.assertEqual(int(call['payload']['accountId']), 65672)
        self.assertIs(call['payload']['isCheckBlackList'], True)
        self.assertIn(RET_TEXT, call['payload']['messageText'], 'Ret metni eklenmeli')
        self.assertEqual(self.net.smartadm_calls, [], 'Taze onaylı numaralar için İYS sorgusu yok')

    # ── KK-C12: referenceId / kimlik eşlemesi ──
    def test_kk_c12_tekli_reference_id_alici_client_id_dir(self):
        msg = self.Message.send_sms(NUMBER, 'Ref')
        payload = self.net.json_sends[0]['payload']
        self.assertEqual(payload['referenceId'], self.client_id_of(msg))
        self.assertEqual([p['clientId'] for p in payload['personalMessages']], [self.client_id_of(msg)])
        self.assertRegex(self.client_id_of(msg), r'^.{8}-m\d+$')

    def test_kk_c12_uc_alicili_paket_kimlikleri_karismaz(self):
        camp = self.make_json_campaign()
        msgs = self.launch(camp)
        self.assertEqual(len(self.net.json_sends), 1)
        payload = self.net.json_sends[0]['payload']
        self.assertEqual(payload['referenceId'], '%s-p%d' % (self.db8(), msgs[0].id))
        self.assertEqual([tail10(n) for n in payload['receiverList']], [m.number[-10:] for m in msgs])
        self.assertEqual([p['clientId'] for p in payload['personalMessages']], [self.client_id_of(m) for m in msgs])
        fake = self.net.tj
        packet_ids = {str(fake.message_by_client(self.client_id_of(m))['packet_id']) for m in msgs}
        self.assertEqual(len(packet_ids), 1)
        message_ids = set()
        for msg in msgs:
            sent = fake.message_by_client(self.client_id_of(msg))
            self.assertEqual(tail10(sent['number']), msg.number[-10:])
            self.assertEqual(str(msg.provider_msg_id), str(sent['message_id']), 'Kayıt kendi mesaj kimliğini almalı')
            self.assertEqual(str(msg.provider_packet_id), str(sent['packet_id']))
            message_ids.add(msg.provider_msg_id)
        self.assertEqual(len(message_ids), 3)

    def test_kk_c12_yanit_ters_sirada_nesne_listesi_olsa_da_karismaz(self):
        """VARSAYIM: yanıt data.messages=[{messageId, clientId}] biçimindeyse clientId ile eşlenir."""
        fake = self.net.tj

        def reversed_objects(call):
            resp = fake._normal(call)
            ids = resp['data']['messageIdList']
            objs = [{'messageId': i, 'clientId': fake.messages[i]['client_id'], 'receiver': fake.messages[i]['number']}
                    for i in reversed(ids)]
            return json_ok({'packetId': resp['data']['packetId'], 'messages': objs})

        fake.add_script('Sms/SendSms', reversed_objects)
        msgs = self.launch(self.make_json_campaign())
        for msg in msgs:
            sent = fake.message_by_client(self.client_id_of(msg))
            self.assertEqual(str(msg.provider_msg_id), str(sent['message_id']))
            self.assertEqual(tail10(sent['number']), msg.number[-10:])

    def test_kk_c12_her_istekte_reference_id_benzersiz(self):
        self.Message.send_sms('05321234567', 'bir')
        self.Message.send_sms('05321234568', 'iki')
        self.launch(self.make_json_campaign())
        self.launch(self.make_json_campaign())
        refs = [c['payload']['referenceId'] for c in self.net.json_sends]
        self.assertEqual(len(refs), 4)
        self.assertEqual(len(set(refs)), 4)
        self.assertTrue(all(refs))

    # ── KK-C13: yeni alanlar ──
    def test_kk_c13_alanlar_ve_secenekler(self):
        fields_ = self.Message._fields
        for name in ('provider_packet_id', 'delivery_state', 'delivery_code', 'provider_service',
                     'provider_account_id'):
            self.assertIn(name, fields_, 'ARAYÜZ YOK: sms.system.message.%s' % name)
            self.assertTrue(fields_[name].store, name)
        self.assertEqual({k for k, _l in fields_['delivery_state'].selection},
                         {'pending', 'delivered', 'undelivered', 'unknown'})
        self.assertEqual({k for k, _l in fields_['provider_service'].selection}, {'legacy', 'single', 'bulk'})
        camp_fields = self.env['sms.system.campaign']._fields
        for name in ('delivered_count', 'undelivered_count'):
            self.assertIn(name, camp_fields, 'ARAYÜZ YOK: sms.system.campaign.%s' % name)

    def test_kk_c13_tekli_gonderimde_alanlar_yazilir(self):
        msg = self.Message.send_sms(NUMBER, 'Alan')
        sent = self.net.tj.message_by_client(self.client_id_of(msg))
        self.assertEqual(msg.provider_service, 'single')
        self.assertEqual(str(msg.provider_account_id), '9254')
        self.assertEqual(msg.delivery_state, 'pending')
        self.assertEqual(str(msg.provider_msg_id), str(sent['message_id']))
        self.assertEqual(str(msg.provider_packet_id), str(sent['packet_id']))

    def test_kk_c13_kampanyada_bulk_ve_reklam_hesabi_yazilir(self):
        self.configure_json(iys=True)
        info = self.launch(self.make_json_campaign(message_type='info'))
        com = self.launch(self.make_json_campaign(message_type='commercial'))
        for msg in info:
            self.assertEqual((msg.provider_service, str(msg.provider_account_id), msg.delivery_state),
                             ('bulk', '9254', 'pending'))
        for msg in com:
            self.assertEqual((msg.provider_service, str(msg.provider_account_id), msg.delivery_state),
                             ('bulk', '65672', 'pending'))

    def test_kk_c13_ham_yanit_en_cok_2000_karakter(self):
        fake = self.net.tj

        def huge(call):
            resp = fake._normal(call)
            resp['data']['padding'] = 'x' * 6000
            return resp

        fake.add_script('Sms/SendSms', huge)
        msg = self.Message.send_sms(NUMBER, 'Uzun yanıt')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertTrue(msg.provider_answer)
        self.assertLessEqual(len(msg.provider_answer), 2000)

    def test_kk_c13_legacy_modda_provider_msg_id_davranisi_korunur(self):
        self.set_param('api_mode', 'legacy_xml')
        msg = self.Message.send_sms(NUMBER, 'Eski')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertTrue(msg.provider_msg_id)
        self.assertEqual(msg.provider_service, 'legacy')
        self.assertFalse(msg.delivery_state, 'Eski modda iletim takibi yok')

    # ── KK-C14: legacy mod ──
    def test_kk_c14_legacy_modda_json_istegi_yok(self):
        self.set_param('api_mode', 'legacy_xml')
        self.Message.send_sms(NUMBER, 'Tekli')
        # Sabit gövde: legacy kişiselleştirme yapmaz, {ad} ile her ad ayrı paket olurdu (davranış değişmez)
        msgs = self.launch(self.make_json_campaign(body='Sabit metin'))
        self.assertEqual(self.net.json_calls, [])
        self.assertEqual(len(self.net.turatel_calls), 2)
        self.assertEqual(set(msgs.mapped('state')), {'sent'})

    def test_kk_c14_legacy_modda_ticari_kampanya_reklam_setinden_bagimsiz(self):
        self.set_param('api_mode', 'legacy_xml')
        self.configure_json(commercial=False, iys=True)
        self.set_param('api_mode', 'legacy_xml')
        msgs = self.launch(self.make_json_campaign(message_type='commercial', body='Sabit metin'))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(self.net.json_calls, [])
        self.assertEqual(len(self.net.turatel_calls), 1)

    def test_kk_c14_json_den_legacy_e_donus_sonraki_gonderim_xml_mevcut_kayit_ayni(self):
        old = self.Message.send_sms(NUMBER, 'Önce json')
        snapshot = (old.state, old.provider_msg_id, old.provider_packet_id, old.provider_service,
                    old.provider_account_id, old.delivery_state)
        self.set_param('api_mode', 'legacy_xml')
        new = self.Message.send_sms('05321234568', 'Sonra xml')
        self.assertEqual(new.state, 'sent', new.error)
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(len(self.net.json_sends), 1)
        self.refresh_all(old)
        self.assertEqual((old.state, old.provider_msg_id, old.provider_packet_id, old.provider_service,
                          old.provider_account_id, old.delivery_state), snapshot)

    def test_kk_c14_legacy_modda_durum_sorgusu_json_istegi_yapmaz(self):
        self.set_param('api_mode', 'legacy_xml')
        self.cron_status()
        self.assertEqual(self.net.json_calls, [])

    # ── KK-C15 (K2): test modu ──
    def test_kk_c15_test_modunda_sendsms_sifir_tum_yollar(self):
        self.configure_json(test_mode='True', iys=True)
        self.set_param('optout_text', RET_TEXT)
        single = self.Message.send_sms(NUMBER, 'Tekli')
        queued = self.Message.send_sms('05321234568', 'Kuyruk', queue=True)
        self.Message._cron_send_queued()
        info = self.launch(self.make_json_campaign(message_type='info'))
        com = self.launch(self.make_json_campaign(message_type='commercial'))
        self.refresh_all(single, queued)
        self.assertEqual(self.net.json_sends, [])
        self.assertEqual(single.state, 'test')
        self.assertEqual(queued.state, 'test')
        self.assertEqual(set(info.mapped('state')), {'test'})
        self.assertEqual(set(com.mapped('state')), {'test'})
        self.assertEqual([c['endpoint'] for c in self.net.json_calls if c['endpoint'] != 'Auth/GetToken'], [],
                         'SendSms dışında da çağrı yok: okuma çağrılarını yalnız KK-C3/C20 düğmeleri yapar')

    def test_kk_c15_test_modu_degerleri_yalniz_tam_false_kapatir(self):
        for value in ('True', None, '0', 'false', ''):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                msg = self.Message.send_sms(NUMBER, 'K2')
                self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.json_sends, [])

    # ── KK-C8: sızıntı yok ──
    def collect_all_text(self, logs, *messages):
        parts = list(logs)
        for msg in messages:
            msg.invalidate_recordset()
            parts += [msg.error or '', msg.provider_answer or '']
        return '\n'.join(parts)

    def assert_clean(self, text, numbers=()):
        for secret in ('info_pw', 'com_pw', 'Bearer', 'Authorization', 'authorization', 'TOK-', 'accessToken'):
            self.assertNotIn(secret, text, 'Sızıntı: %s' % secret)
        for number in numbers:
            self.assertNotIn(tail10(number), text, 'Telefon maskesiz: %s' % number)
        for body_key in ('receiverList', 'personalMessages', 'messageText'):
            self.assertNotIn(body_key, text, 'Tam istek gövdesi sızdı')

    def test_kk_c8_basarili_gonderimde_log_ve_alanlar_temiz(self):
        with self.capture_logs() as logs:
            msg = self.Message.send_sms(NUMBER, 'Gizli metin 123')
            self.launch(self.make_json_campaign())
        self.assert_clean(self.collect_all_text(logs, msg), [NUMBER])

    def test_kk_c8_hata_durumlarinda_log_ve_alanlar_temiz(self):
        numbers = ['05321234567', '05321234568', '05321234569']
        self.net.tj.add_script('Sms/SendSms', json_err(-5, 'Yetersiz kredi'),
                               requests.exceptions.ReadTimeout('zaman aşımı'), json_err(-22, 'Unauthorized IP Address'))
        with self.capture_logs() as logs:
            msgs = [self.Message.send_sms(n, 'Gizli metin') for n in numbers]
        self.assertEqual([m.state for m in msgs], ['error', 'uncertain', 'error'])
        self.assert_clean(self.collect_all_text(logs, *msgs), numbers)

    def test_kk_c8_kimlik_hatasi_sifre_icermez(self):
        self.set_param('turatel_json_info_password', 'COK-GIZLI-SIFRE')
        with self.capture_logs() as logs:
            msg = self.Message.send_sms(NUMBER, 'Kimlik')
        self.assertEqual(msg.state, 'error')
        self.assertIn('kimlik', (msg.error or '').lower())
        text = self.collect_all_text(logs, msg)
        self.assertNotIn('COK-GIZLI-SIFRE', text)
        self.assertNotIn('info_user', msg.error or '', 'Kullanıcı adı hata metnine yazılmamalı')


@tagged('post_install', '-at_install')
class TestJsonKnownAssumptions(JsonModelMixin, SmsTestCase):

    def test_kk_c12_c13_sendsms_yaniti_eslesmezse_kayitlar_sent_kalir_kimlik_bos(self):
        """Tasarım §5.2: eşleme kurulamazsa message_ids boş, kayıtlar sent; kimliği C5 cron'u clientId ile bulur."""
        fake = self.net.tj
        fake.add_script('Sms/SendSms', lambda call: json_ok({'packetId': 4999, 'unexpected': True}))
        msgs = self.launch(self.make_json_campaign())
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual({m.provider_msg_id for m in msgs}, {False})
        self.assertEqual({str(m.provider_packet_id) for m in msgs}, {'4999'})
        self.assertEqual({m.delivery_state for m in msgs}, {'pending'})


@tagged('post_install', '-at_install')
class TestJsonDuplicates(JsonModelMixin, SmsTestCase):

    # ── KK-C17 (K4) ──
    def test_kk_c17_sendsms_aninda_kayit_sending_ve_flush_edilmis(self):
        msg = self.Message.send_sms(NUMBER, 'K4 tekli kuyruk', queue=True)
        seen = []

        def hook(call):
            if call['endpoint'] == 'Sms/SendSms':
                seen.append(self.db_state(msg, flush=False))

        self.net.tj.hook = hook
        self.Message._cron_send_queued()
        self.assertEqual(seen, ['sending'], 'Sağlayıcı çağrısından önce sending yazılmış olmalı')

    def test_kk_c17_kampanya_paketi_sendsms_aninda_sending(self):
        camp = self.make_json_campaign()
        camp.action_send()
        msgs = self.campaign_msgs(camp)
        seen = []

        def hook(call):
            if call['endpoint'] == 'Sms/SendSms':
                seen.append({self.db_state(m, flush=False) for m in msgs})

        self.net.tj.hook = hook
        self.run_queue()
        self.assertEqual(seen, [{'sending'}])

    def test_kk_c17_es_zamanli_yollar_ayni_kaydi_ikinci_kez_gondermez(self):
        msg = self.Message.send_sms(NUMBER, 'K4 eşzamanlı', queue=True)
        state = {'nested': False}

        def hook(call):
            if call['endpoint'] == 'Sms/SendSms' and not state['nested']:
                state['nested'] = True
                # sağlayıcı yanıtı beklenirken başka yollar aynı kayda ulaşır
                self.Message._cron_send_queued()
                self.Message._cron_retry_failed()
                self.Campaign._cron_process_queue()
                self.Message.browse(msg.id).action_retry()

        self.net.tj.hook = hook
        self.Message._cron_send_queued()
        self.assertEqual(self.sends_with(msg), 1)

    def test_kk_c17_kampanya_kayitlari_es_zamanli_yollarda_bir_kez(self):
        camp = self.make_json_campaign()
        camp.action_send()
        msgs = self.campaign_msgs(camp)
        state = {'nested': False}

        def hook(call):
            if call['endpoint'] == 'Sms/SendSms' and not state['nested']:
                state['nested'] = True
                self.Campaign._cron_process_queue()
                self.Message._cron_send_queued()
                self.Message._cron_retry_failed()
                try:
                    camp.action_retry_errors()
                except UserError:
                    pass   # kuyrukta/gönderilirken: yeniden gönderilecek hatalı kayıt yok

        self.net.tj.hook = hook
        self.run_queue()
        for msg in msgs:
            self.assertEqual(self.sends_with(msg), 1, msg.number)

    def test_kk_c17_tamamlanmis_kayit_hicbir_yolla_tekrar_gonderilmez(self):
        msg = self.Message.send_sms(NUMBER, 'Bir kez')
        self.assertEqual(msg.state, 'sent')
        self.set_write_date(msg, 600)
        self.Message._cron_send_queued()
        self.Message._cron_retry_failed()
        self.Campaign._cron_process_queue()
        msg.action_retry()   # yalnız 'error' kayıtlar kuyruğa alınır; gönderilmiş kayıt atlanır
        self.Message._cron_send_queued()
        self.assertEqual(self.sends_with(msg), 1)

    def test_kk_c17_belirsiz_kayit_otomatik_yollarla_gonderilmez(self):
        self.net.tj.add_script('Sms/SendSms', requests.exceptions.ReadTimeout('okuma zaman aşımı'))
        msg = self.Message.send_sms(NUMBER, 'Belirsiz')
        self.assertEqual(msg.state, 'uncertain', msg.error)
        self.set_write_date(msg, 600)
        self.Message._cron_send_queued()
        self.Message._cron_retry_failed()
        self.Campaign._cron_process_queue()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain')
        self.assertEqual(self.sends_with(msg), 1)

    def test_kk_c17_kampanyada_belirsiz_paket_tekrar_gonderilmez(self):
        self.net.tj.add_script('Sms/SendSms', requests.exceptions.ReadTimeout('okuma zaman aşımı'))
        camp = self.make_json_campaign()
        msgs = self.launch(camp)
        self.assertEqual(set(msgs.mapped('state')), {'uncertain'})
        with self.assertRaises(UserError):
            camp.action_retry_errors()
        self.run_queue(2)
        self.assertEqual(len(self.net.json_sends), 1)


@tagged('post_install', '-at_install')
class TestJsonCommercialSet(JsonModelMixin, SmsTestCase):

    NO_COM = 'Reklam hesabı kimlik bilgileri (kullanıcı adı/şifre) tanımlı değil'

    def setUp(self):
        super().setUp()
        self.configure_json(commercial=False, iys=True)
        self.set_param('optout_text', RET_TEXT)

    # ── KK-C29 ──
    def test_kk_c29_ticari_kampanya_onayi_user_error(self):
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}')
        with self.assertRaises(UserError) as ctx:
            camp.action_confirm_send()
        self.assertIn(self.NO_COM, str(ctx.exception))
        with self.assertRaises(UserError) as ctx:
            camp.action_send()
        self.assertIn(self.NO_COM, str(ctx.exception))
        self.assertEqual(camp.state, 'draft')
        self.assertEqual(self.net.json_calls, [])

    def test_kk_c29_kuyruktaki_ticari_paket_kalici_hata_ve_istek_yok(self):
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}', state='sending')
        msgs = self.Message.sudo()
        for contact in self.Contact.search([('list_ids', 'in', camp.list_ids.ids)]):
            msgs |= self.campaign_message(camp, contact, state='queued', body='Indirim %s' % contact.name)
        bodies = msgs.mapped('body')
        self.run_queue(2)
        self.refresh_all(msgs)
        self.assertEqual(set(msgs.mapped('state')), {'error'})
        self.assertEqual(set(msgs.mapped('retry_count')), {3}, 'Kalıcı hata: retry_count = MAX')
        self.assertEqual(msgs.mapped('body'), bodies, 'Metin aynı kalmalı')
        for msg in msgs:
            self.assertIn('Reklam hesabı', msg.error or '')
        self.assertEqual(self.net.json_sends, [])
        self.assertEqual(self.net.json_calls, [], 'Bilgi setiyle de hiçbir istek yapılmamalı (GetToken dahil)')

    def test_kk_c29_hatali_ticari_kayitlar_otomatik_yeniden_denenmez(self):
        camp = self.make_json_campaign(message_type='commercial', state='sending')
        for contact in self.Contact.search([('list_ids', 'in', camp.list_ids.ids)]):
            self.campaign_message(camp, contact, state='queued')
        self.run_queue()
        self.Message._cron_retry_failed()
        self.run_queue()
        self.assertEqual(self.net.json_calls, [])

    def test_kk_c29_bilgilendirme_ve_personel_kampanyasi_ve_tekli_etkilenmez(self):
        for message_type in ('info', 'staff'):
            with self.subTest(tur=message_type):
                msgs = self.launch(self.make_json_campaign(message_type=message_type))
                self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        single = self.Message.send_sms(NUMBER, 'Tekli')
        self.assertEqual(single.state, 'sent', single.error)
        self.assertEqual({c['user'] for c in self.net.json_calls if c['endpoint'] == 'Sms/SendSms'}, {'info_user'})
        self.assertEqual(self.net.tj.calls_to('Auth/GetToken')[0]['payload']['username'], 'info_user')

    def test_kk_c29_client_secimi_reklam_seti_yoksa_kalici_hata(self):
        from odoo.addons.sms_system.services.turatel import TuratelError
        cfg = self.Message._settings()
        self.assertIsNone(cfg['json_creds']['commercial'])
        with self.assertRaises(TuratelError) as ctx:
            self.Message._client(cfg, service='bulk', purpose='commercial')
        self.assertFalse(ctx.exception.retryable)
        self.assertFalse(ctx.exception.uncertain)
        self.assertIn('Reklam hesabı', str(ctx.exception))
        self.assertEqual(self.net.json_calls, [])

    def test_kk_c29_legacy_mod_etkilenmez(self):
        self.set_param('api_mode', 'legacy_xml')
        camp = self.make_json_campaign(message_type='commercial')
        msgs = self.launch(camp)
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(self.net.json_calls, [])

    # ── KK-C30: jeton önbelleği set başına (model düzeyi) ──
    def test_kk_c30_bilgi_ve_ticari_gonderim_ayri_jeton_ve_kendi_kimligi(self):
        self.configure_json(commercial=True, iys=True)
        self.Message.send_sms(NUMBER, 'Bilgi')
        self.launch(self.make_json_campaign(message_type='commercial'))
        issued = [user for user, _token in self.net.tj.tokens_issued]
        self.assertEqual(sorted(issued), ['com_user', 'info_user'])
        by_service = {(c['service'], c['user']) for c in self.net.json_sends}
        self.assertEqual(by_service, {('singlesms', 'info_user'), ('bulksms', 'com_user')})
        com_tokens = {t for u, t in self.net.tj.tokens_issued if u == 'com_user'}
        self.assertEqual({c['bearer'] for c in self.net.json_sends if c['user'] == 'com_user'}, com_tokens)

    def test_kk_c30_bir_setin_jetonu_gecersizse_yalniz_o_set_yenilenir(self):
        self.configure_json(commercial=True, iys=True)
        self.Message.send_sms(NUMBER, 'Bilgi 1')
        self.launch(self.make_json_campaign(message_type='commercial'))
        issued_before = list(self.net.tj.tokens_issued)
        com_token = next(t for u, t in issued_before if u == 'com_user')
        self.net.tj.expire_tokens('info_user')
        msg = self.Message.send_sms('05321234568', 'Bilgi 2')
        self.assertEqual(msg.state, 'sent', msg.error)
        new = self.net.tj.tokens_issued[len(issued_before):]
        self.assertEqual([u for u, _t in new], ['info_user'], 'Yalnız bilgi seti jetonu yenilenmeli')
        self.launch(self.make_json_campaign(message_type='commercial'))
        self.assertEqual(len(self.net.tj.tokens_issued), len(issued_before) + 1, 'Reklam jetonu korunmalı')
        self.assertIn(com_token, self.net.tj.tokens)


@tagged('post_install', '-at_install')
class TestJsonRoutingFixedBody(JsonModelMixin, SmsTestCase):
    """C3 kanıtı sabit gövdeyle: {ad} kişiselleştirmesi (tek pakette {1} + parametre) C4'tür; buradaki
    kontroller C3'ün yönlendirme, kimlik eşleme ve mükerrer önleme sözleşmesini C4'ten bağımsız doğrular."""

    BODY = 'Sabit metin'

    def test_c3_uc_alicili_paket_tek_istek_kimlikler_karismaz(self):
        msgs = self.launch(self.make_json_campaign(body=self.BODY))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(len(self.net.json_sends), 1)
        call = self.net.json_sends[0]
        payload = call['payload']
        self.assertEqual((call['service'], call['user'], int(payload['accountId'])), ('bulksms', 'info_user', 9254))
        self.assertIs(payload['isCheckBlackList'], False)
        self.assertEqual(payload['referenceId'], '%s-p%d' % (self.db8(), msgs[0].id))
        self.assertEqual([tail10(n) for n in payload['receiverList']], [m.number[-10:] for m in msgs])
        self.assertEqual([p['clientId'] for p in payload['personalMessages']], [self.client_id_of(m) for m in msgs])
        fake = self.net.tj
        for msg in msgs:
            sent = fake.message_by_client(self.client_id_of(msg))
            self.assertEqual(tail10(sent['number']), msg.number[-10:])
            self.assertEqual(str(msg.provider_msg_id), str(sent['message_id']))
            self.assertEqual(str(msg.provider_packet_id), str(sent['packet_id']))
            self.assertEqual((msg.provider_service, msg.provider_account_id, msg.delivery_state),
                             ('bulk', '9254', 'pending'))
        self.assertEqual(len(set(msgs.mapped('provider_msg_id'))), 3)

    def test_c3_ticari_paket_reklam_seti_kara_liste_true(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        msgs = self.launch(self.make_json_campaign(message_type='commercial', body=self.BODY))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(len(self.net.json_sends), 1)
        call = self.net.json_sends[0]
        self.assertEqual((call['service'], call['user'], int(call['payload']['accountId'])),
                         ('bulksms', 'com_user', 65672))
        self.assertIs(call['payload']['isCheckBlackList'], True)
        self.assertEqual({m.provider_account_id for m in msgs}, {'65672'})

    def test_c3_paket_sendsms_aninda_sending(self):
        camp = self.make_json_campaign(body=self.BODY)
        camp.action_send()
        msgs = self.campaign_msgs(camp)
        seen = []

        def hook(call):
            if call['endpoint'] == 'Sms/SendSms':
                seen.append({self.db_state(m, flush=False) for m in msgs})

        self.net.tj.hook = hook
        self.run_queue()
        self.assertEqual(seen, [{'sending'}])

    def test_c3_reference_id_her_istekte_benzersiz(self):
        self.Message.send_sms('05321234567', 'bir')
        self.Message.send_sms('05321234568', 'iki')
        self.launch(self.make_json_campaign(body=self.BODY))
        self.launch(self.make_json_campaign(body=self.BODY))
        refs = [c['payload']['referenceId'] for c in self.net.json_sends]
        self.assertEqual(len(refs), 4)
        self.assertEqual(len(set(refs)), 4)

    def test_c3_kilitli_kampanya_kaydi_pakete_girmez(self):
        """Başka işlemin kilitlediği kayıt (SKIP LOCKED) bu çalışmada gönderilmez, kuyrukta kalır."""
        camp = self.make_json_campaign(body=self.BODY)
        camp.action_send()
        msgs = self.campaign_msgs(camp)
        busy = msgs[1]
        original = type(self.Message)._lock_for_send

        def lock(model, ids, states):
            return original(model, [i for i in ids if i != busy.id], states)

        with patch.object(type(self.Message), '_lock_for_send', lock):
            self.run_queue()
        self.refresh_all(*msgs)
        self.assertEqual(busy.state, 'queued')
        self.assertEqual(self.sends_with(busy), 0)
        self.assertEqual((msgs - busy).mapped('state'), ['sent', 'sent'])

    def test_c3_belirsiz_json_kaydi_servis_ve_hesap_tasir(self):
        """Belirsiz kayıt C5'te uzlaştırılabilsin: hangi servis/hesapla gönderildiği yazılır."""
        self.net.tj.add_script('Sms/SendSms', requests.exceptions.ReadTimeout('okuma zaman aşımı'))
        msg = self.Message.send_sms(NUMBER, 'Belirsiz')
        self.assertEqual((msg.state, msg.retry_count), ('uncertain', 3))
        self.assertEqual((msg.provider_service, msg.provider_account_id), ('single', '9254'))
        self.assertFalse(msg.delivery_state)

    def test_c3_ticari_reklam_seti_yoksa_hatali_kayit_yeniden_gonderilemez(self):
        self.configure_json(commercial=False, iys=True)
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial', body=self.BODY, state='sending')
        for contact in self.Contact.search([('list_ids', 'in', camp.list_ids.ids)]):
            self.campaign_message(camp, contact, state='error', body=self.BODY)
        with self.assertRaises(UserError) as ctx:
            camp.action_retry_errors()
        self.assertIn('Reklam hesabı kimlik bilgileri', str(ctx.exception))
        self.assertEqual(set(self.campaign_msgs(camp).mapped('state')), {'error'})
        self.assertEqual(self.net.json_calls, [])

    def test_c3_kampanya_iletim_sayaclari(self):
        msgs = self.launch(self.make_json_campaign(body=self.BODY))
        msgs[0].delivery_state = 'delivered'
        msgs[1].delivery_state = 'undelivered'
        camp = msgs[0].campaign_id
        camp.invalidate_recordset()
        self.assertEqual((camp.delivered_count, camp.undelivered_count), (1, 1))

    def test_c3_belirsiz_paket_tekrar_gonderilmez(self):
        self.net.tj.add_script('Sms/SendSms', requests.exceptions.ReadTimeout('okuma zaman aşımı'))
        camp = self.make_json_campaign(body=self.BODY)
        msgs = self.launch(camp)
        self.assertEqual(set(msgs.mapped('state')), {'uncertain'})
        self.assertEqual({(m.provider_service, m.provider_account_id) for m in msgs}, {('bulk', '9254')})
        with self.assertRaises(UserError):
            camp.action_retry_errors()
        self.run_queue(2)
        self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.json_sends), 1)

    def test_c3_yanit_eslesmezse_sent_kimlik_bos_paket_no_yazilir(self):
        self.net.tj.add_script('Sms/SendSms', lambda call: json_ok({'packetId': 4999, 'unexpected': True}))
        msgs = self.launch(self.make_json_campaign(body=self.BODY))
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual({m.provider_msg_id for m in msgs}, {False})
        self.assertEqual({m.provider_packet_id for m in msgs}, {'4999'})
        self.assertEqual({m.delivery_state for m in msgs}, {'pending'})

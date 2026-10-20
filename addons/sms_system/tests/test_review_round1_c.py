"""Düzeltme turu #1 (C), kıdemli kısım.

Ö1 (KK-C16): JSON bağlamı (servis + hesap) 'sending' ile aynı commit'te, SendSms'ten önce yazılır.
Ö2: jeton önbelleğinin süresi var. G-C2: taslak dışındaki kampanyanın içeriği değişmez.
G-C3: yönlendirme izlenmez, 3xx sınıflaması, ayarlarda https zorunlu. N5: reklam seti yokken gönderim döngüsü yok.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import SmsTestCase
from .test_json_routing import JsonModelMixin, NUMBER, RET_TEXT
from .test_json_settings import FULL, JsonSettingsMixin


class WorkerKilled(BaseException):
    """İşçinin SendSms sırasında ölmesi (zaman aşımı, bellek, yeniden başlatma): hiçbir except bloğu yakalamaz."""


@tagged('post_install', '-at_install')
class TestReviewO1ContextBeforeSend(JsonModelMixin, SmsTestCase):
    """Ö1: SendSms anında ölen işçinin kaydı takılı süpürmeyle belirsiz olur ve C5 onu yine bulur."""

    def db_context(self, msg):
        """Flush edilmemiş önbelleği değil, veritabanındakini (commit edilmiş durumu) okur."""
        self.env.cr.execute('SELECT state, provider_service, provider_account_id FROM sms_system_message '
                            'WHERE id = %s', (msg.id,))
        return self.env.cr.fetchone()

    def kill_on_send(self, records):
        """SendSms sağlayıcıya ulaşır (Turatel kaydeder), yanıt dönmeden işçi ölür. Döner: SendSms anı DB durumu."""
        fake, seen = self.net.tj, []

        def die(call):
            seen.extend(self.db_context(m) for m in records)
            fake._normal(call)
            raise WorkerKilled()

        fake.add_script('Sms/SendSms', die)
        return seen

    def survive(self, func):
        try:
            func()
        except WorkerKilled:
            pass
        else:
            self.fail('SendSms çağrılmadı')
        self.env.invalidate_all()   # ölümde son commit'ten sonrası yoktur (SendSms'e kadar yazım yapılmaz)

    def test_o1_tekli_kuyruk_sendsms_aninda_baglam_db_de(self):
        msg = self.Message.send_sms(NUMBER, 'Ö1 tekli', queue=True)
        seen = self.kill_on_send(msg)
        self.survive(self.Message._cron_send_queued)
        self.assertEqual(seen, [('sending', 'single', '9254')],
                         'Servis ve hesap, sending ile aynı commit içinde ve SendSms öncesi yazılmalı')

    def test_o1_tekli_olen_isci_kaydi_c5_ile_uzlasir(self):
        msg = self.Message.send_sms(NUMBER, 'Ö1 tekli', queue=True)
        self.kill_on_send(msg)
        self.survive(self.Message._cron_send_queued)
        self.set_write_date(msg, 20)
        self.Message._cron_send_queued()   # takılı süpürme: gönderiliyor -> belirsiz
        self.refresh_all(msg)
        self.assertEqual((msg.state, msg.provider_service, msg.provider_account_id), ('uncertain', 'single', '9254'))
        self.cron_status()
        self.refresh_all(msg)
        fake_msg = self.net.tj.message_by_client(self.client_id_of(msg))
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(str(msg.provider_msg_id), str(fake_msg['message_id']))
        self.assertEqual(self.sends_with(msg), 1, 'Uzlaşma yeniden gönderim yapmaz')

    def test_o1_tekli_olen_isci_kaydi_durumu_sorgula_ile_uzlasir(self):
        msg = self.Message.send_sms(NUMBER, 'Ö1 sorgula', queue=True)
        self.kill_on_send(msg)
        self.survive(self.Message._cron_send_queued)
        self.set_write_date(msg, 20)
        self.Message._cron_send_queued()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain')
        msg.action_fetch_report()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertTrue(msg.provider_msg_id)
        self.assertEqual(self.net.turatel_calls, [], 'XML rapor ucu çağrılmamalı')

    def test_o1_ticari_kampanya_paketi_olen_isci_reklam_hesabiyla_uzlasir(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial', body='Indirim')
        camp.action_send()
        self.run_queue_until_send(camp)
        msgs = self.campaign_msgs(camp)
        self.assertEqual(self.pack_seen, [('sending', 'bulk', '65672')] * len(msgs))
        self.set_write_date(msgs, 20)
        self.run_queue()   # takılı süpürme + kampanya bitişi
        self.refresh_all(camp, *msgs)
        self.assertEqual(set(msgs.mapped('state')), {'uncertain'})
        self.assertEqual(camp.state, 'done')
        self.cron_status()
        self.refresh_all(*msgs)
        self.assertEqual(set(msgs.mapped('state')), {'sent'}, msgs.mapped('error'))
        self.assertEqual(len({m.provider_msg_id for m in msgs}), len(msgs))
        statuses = [c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')]
        self.assertTrue(statuses)
        self.assertEqual({c['user'] for c in statuses}, {'com_user'})
        self.assertEqual(len(self.net.json_sends), 1)

    def run_queue_until_send(self, camp):
        """İlk çalışma kampanyayı başlatır ve paketi gönderirken işçi ölür."""
        def die(call):
            records = self.campaign_msgs(camp)
            self.pack_seen = [self.db_context(m) for m in records]
            self.net.tj._normal(call)
            raise WorkerKilled()

        self.pack_seen = None
        self.net.tj.add_script('Sms/SendSms', die)
        self.survive(self.Campaign._cron_process_queue)

    def test_o1_test_modunda_engellenen_kayit_baglam_almaz(self):
        self.configure_json(test_mode='True')
        self.set_param('test_numbers', '5329999999')
        blocked = self.make_message(NUMBER, state='queued')
        allowed = self.make_message('5329999999', state='queued')
        self.Message._cron_send_queued()
        self.refresh_all(blocked, allowed)
        self.assertEqual((blocked.state, blocked.provider_service, blocked.provider_account_id), ('test', False, False))
        self.assertEqual((allowed.state, allowed.provider_service), ('sent', 'single'), allowed.error)
        self.assertEqual(self.net.json_sent_receivers, ['5329999999'])

    def test_o1_legacy_modda_sending_baglami_yazilmaz(self):
        self.set_param('api_mode', 'legacy_xml')
        msg = self.make_message(NUMBER, state='queued')
        seen = []
        original = self.net._turatel

        def turatel(call):
            seen.append(self.db_context(msg))
            return original(call)

        with patch.object(self.net, '_turatel', turatel):
            self.Message._cron_send_queued()
        self.assertEqual(seen, [('sending', None, None)])
        self.refresh_all(msg)
        self.assertEqual((msg.state, msg.provider_service), ('sent', 'legacy'), msg.error)


@tagged('post_install', '-at_install')
class TestReviewO2TokenTtl(JsonModelMixin, SmsTestCase):
    """Ö2: jeton süresiz önbellekte kalmaz; süre dolunca yeni GetToken alınır."""

    def clock(self, api, start=1000.0):
        now = [start]
        self.startPatcher(patch.object(api, '_clock', lambda: now[0], create=True))
        return now

    def test_o2_sabit_sure_30_dk_sonra_yeni_jeton(self):
        api = self.json_api()
        client = self.json_client('info')
        now = self.clock(api)
        first = client.get_token()
        now[0] += 29 * 60
        self.assertEqual(client.get_token(), first, '30 dk dolmadan önbellek kullanılır')
        now[0] += 2 * 60
        second = client.get_token()
        self.assertNotEqual(second, first, '30 dk sonra yeni jeton alınmalı')
        self.assertEqual(len(self.net.tj.tokens_issued), 2)

    def test_o2_yanittaki_sure_kullanilir_bir_dk_pay_birakilir(self):
        api = self.json_api()
        fake = self.net.tj

        def short_lived(call):
            envelope = fake._normal(call)
            envelope['data']['expiresIn'] = 120
            return envelope

        fake.add_script('Auth/GetToken', short_lived, short_lived)
        client = self.json_client('info')
        now = self.clock(api)
        first = client.get_token()
        now[0] += 59
        self.assertEqual(client.get_token(), first)
        now[0] += 2
        self.assertNotEqual(client.get_token(), first, 'expiresIn - 60 sn dolunca yenilenmeli')
        self.assertEqual(len(fake.tokens_issued), 2)

    def test_o2_sure_bilgisi_sayi_degilse_sabit_sure(self):
        api = self.json_api()
        fake = self.net.tj

        def odd(call):
            envelope = fake._normal(call)
            envelope['data']['expiresIn'] = 'yarın'
            return envelope

        fake.add_script('Auth/GetToken', odd)
        client = self.json_client('info')
        now = self.clock(api)
        first = client.get_token()
        now[0] += 29 * 60
        self.assertEqual(client.get_token(), first)

    def test_o2_suresi_dolan_jetonla_gonderim_yeni_jeton_alir(self):
        api = self.json_api()
        now = self.clock(api)
        self.Message.send_sms(NUMBER, 'bir')
        now[0] += 31 * 60
        msg = self.Message.send_sms(NUMBER, 'iki')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(len(self.net.tj.tokens_issued), 2)
        self.assertEqual([c['bearer'] for c in self.net.json_sends],
                         [token for _user, token in self.net.tj.tokens_issued])


@tagged('post_install', '-at_install')
class TestReviewGC2CampaignLocked(JsonModelMixin, SmsTestCase):
    """G-C2: onaylanmış (taslak dışı) kampanyada metin/tür/liste/şablon değişmez; sistem yazımları etkilenmez."""

    def setUp(self):
        super().setUp()
        self.template = self.env['sms.system.template'].create({'name': 'Şablon', 'body': 'Şablon metni {ad}'})
        self.other_list = self.make_list('Diğer liste')

    def content_changes(self):
        return {
            'body': {'body': 'Yeni metin'},
            'message_type': {'message_type': 'commercial'},
            'list_ids_ekle': {'list_ids': [(4, self.other_list.id)]},
            'list_ids_degistir': {'list_ids': [(6, 0, self.other_list.ids)]},
            'template_id': {'template_id': self.template.id},
        }

    def test_gc2_taslak_disinda_icerik_degisikligi_reddedilir(self):
        for state in ('scheduled', 'sending', 'done', 'cancel'):
            camp = self.make_json_campaign(state=state)
            for label, vals in self.content_changes().items():
                with self.subTest(state=state, alan=label):
                    with self.assertRaises(UserError):
                        camp.write(vals)

    def test_gc2_taslakta_icerik_serbest(self):
        camp = self.make_json_campaign()
        for vals in self.content_changes().values():
            camp.write(vals)
        self.assertEqual((camp.body, camp.message_type, camp.template_id), ('Yeni metin', 'commercial', self.template))

    def test_gc2_sistem_yazimlari_ve_ayni_deger_serbest(self):
        camp = self.make_json_campaign(state='sending')
        camp.write({'state': 'done', 'finished_at': self.ago(minutes=1), 'skipped_count': 2})
        camp.write({'state': 'sending', 'finished_at': False})
        camp.write({'body': camp.body, 'message_type': camp.message_type, 'template_id': False,
                    'list_ids': [(6, 0, camp.list_ids.ids)]})
        self.assertEqual(camp.state, 'sending')

    def test_gc2_baslamis_kampanya_taslaga_alinamaz(self):
        for state in ('sending', 'done'):
            camp = self.make_json_campaign(state=state)
            with self.subTest(state=state), self.assertRaises(UserError):
                camp.write({'state': 'draft'})
        for state in ('scheduled', 'cancel'):
            camp = self.make_json_campaign(state=state)
            camp.action_draft()
            self.assertEqual(camp.state, 'draft')
            camp.write({'body': 'Düzeltildi'})

    def test_gc2_poc_onayli_ticari_kampanya_bilgilendirmeye_cevrilemez(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial', body='Indirim')
        camp.action_send()
        self.assertEqual(camp.state, 'scheduled')
        with self.assertRaises(UserError):
            camp.write({'message_type': 'info'})
        self.run_queue()
        sends = self.net.json_sends
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]['user'], 'com_user')
        self.assertEqual(int(sends[0]['payload']['accountId']), 65672)
        self.assertIs(sends[0]['payload']['isCheckBlackList'], True)

    def make_sent_campaign(self, state='sending', **vals):
        """Kampanyaya ait SMS kaydı olan (gönderimi başlamış) kampanya; yazımlar SMS yöneticisi olarak yapılır."""
        camp = self.make_json_campaign(state=state, **vals)
        self.make_message(state='queued', campaign_id=camp.id)
        return camp.with_user(self.sms_manager)

    def test_gc2b_poc_p2b_scheduled_taslak_icerik_zinciri_kapali(self):
        """PoC P2b: sending -> scheduled -> draft -> içerik -> sending. İlk adım zaten reddedilir."""
        self.configure_json(iys=True)
        camp = self.make_sent_campaign(message_type='commercial', body='Indirim {ad}')
        original = (camp.message_type, camp.body)
        with self.assertRaises(UserError):
            camp.write({'state': 'scheduled'})
        with self.assertRaises(UserError):
            camp.write({'state': 'draft'})
        with self.assertRaises(UserError):
            camp.write({'message_type': 'info', 'body': 'BAMBASKA METIN {ad}'})
        self.assertEqual((camp.state, camp.message_type, camp.body), ('sending',) + original)

    def test_gc2b_poc_p2c_cancel_taslak_icerik_zinciri_kapali(self):
        """PoC P2c: iptal -> taslak -> içerik. Kayıtlı kampanya 'cancel'/'draft'e geri alınamaz."""
        camp = self.make_sent_campaign(state='cancel', message_type='commercial', body='Indirim {ad}')
        with self.assertRaises(UserError):
            camp.write({'state': 'draft'})
        with self.assertRaises(UserError):
            camp.action_draft()
        with self.assertRaises(UserError):
            camp.write({'message_type': 'info', 'body': 'BAMBASKA METIN {ad}'})
        self.assertEqual((camp.state, camp.message_type), ('cancel', 'commercial'))

    def test_gc2b_kayitli_kampanyada_taslak_olsa_bile_icerik_kilitli(self):
        camp = self.make_sent_campaign(state='draft')
        for label, vals in self.content_changes().items():
            with self.subTest(alan=label), self.assertRaises(UserError):
                camp.write(vals)

    def test_gc2b_kayitli_kampanya_baska_duruma_geri_alinamaz(self):
        for target in ('draft', 'scheduled', 'cancel'):
            camp = self.make_sent_campaign(state='sending')
            with self.subTest(hedef=target), self.assertRaises(UserError):
                camp.write({'state': target})
            self.assertEqual(camp.state, 'sending')

    def test_gc2b_sistem_yazimlari_ve_meshru_akislar_calisir(self):
        # sudo (cron/sistem) geri almayı yapabilir; kayıtsız kampanyada kullanıcı akışları açık
        sent = self.make_json_campaign(state='scheduled')
        self.make_message(state='queued', campaign_id=sent.id)
        sent.sudo().write({'state': 'draft'})
        self.assertEqual(sent.state, 'draft')
        empty = self.make_json_campaign(state='scheduled').with_user(self.sms_manager)
        empty.action_draft()
        empty.write({'body': 'Düzeltildi'})
        self.assertEqual((empty.state, empty.body), ('draft', 'Düzeltildi'))
        empty.action_cancel()
        self.assertEqual(empty.state, 'cancel')
        empty.action_draft()
        copy = empty.copy()
        self.assertEqual(copy.state, 'draft')
        done = self.make_json_campaign(state='sending')
        self.make_message(state='sent', campaign_id=done.id)
        done = done.with_user(self.sms_manager)
        done.action_cancel()   # gönderilmiş kayıt varsa 'cancel' değil 'done'
        self.assertEqual(done.state, 'done')

    def test_gc2b_cron_planli_kampanyayi_taslaga_alabilir(self):
        self.configure_json(iys=True)   # ret metni yok: planlı ticari kampanya cron'da taslağa döner
        self.set_param('optout_text', '')
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}', state='scheduled',
                                       scheduled_at=self.ago(minutes=5))
        self.run_queue()
        self.assertEqual(camp.state, 'draft')

    def test_gc2c_poc_p2i_kuyruktaki_ticari_kayit_baska_kampanyaya_tasinamaz(self):
        """PoC P2i: bilgi kampanyasını doğrudan 'sending' yap, ticari kaydı ona taşı. İki adım da kapalı."""
        self.configure_json(iys=True)
        commercial = self.make_sent_campaign(message_type='commercial', body='Indirim {ad}')
        msg = commercial.sudo().message_ids_sms
        info = self.make_json_campaign(message_type='info', body='BAMBASKA {ad}').with_user(self.sms_manager)
        with self.assertRaises(UserError):
            info.write({'state': 'sending'})
        self.assertEqual(info.state, 'draft')
        with self.assertRaises(UserError):
            msg.with_user(self.sms_manager).write({'campaign_id': info.id})
        self.assertEqual(msg.campaign_id, commercial.sudo())

    def test_gc2c_kampanya_kullanici_yazimiyla_dogrudan_sending_olamaz(self):
        for state in ('draft', 'scheduled', 'done'):
            camp = self.make_json_campaign(state=state).with_user(self.sms_manager)
            with self.subTest(state=state), self.assertRaises(UserError):
                camp.write({'state': 'sending'})
            self.assertEqual(camp.state, state)

    def test_gc2c_mesaj_gonderim_icerigi_kullanici_yazimiyla_degismez(self):
        camp = self.make_json_campaign(state='sending')
        for state in ('queued', 'sending', 'sent', 'uncertain'):
            msg = self.make_message(state=state, campaign_id=camp.id, contact_id=False)
            as_manager = msg.with_user(self.sms_manager)
            for vals in ({'body': 'Başka'}, {'number': '5329998877'}, {'originator': 'BASKA'},
                         {'campaign_id': False}, {'campaign_id': self.make_json_campaign().id}):
                with self.subTest(state=state, vals=vals), self.assertRaises(UserError):
                    as_manager.write(vals)
            as_manager.write({'body': msg.body, 'campaign_id': camp.id})   # aynı değer serbest
            msg.sudo().write({'body': 'Sistem yazımı'})                    # sistem serbest

    def test_gc2c_meshru_akislar_etkilenmez(self):
        """Gönderim, yeniden deneme, onay akışı kullanıcı ortamında çalışmaya devam eder."""
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}').with_user(self.sms_manager)
        camp.action_send()   # draft -> scheduled -> cron _start: sending
        self.run_queue()
        self.assertEqual(camp.sudo().state, 'done')
        self.assertTrue(camp.sudo().message_ids_sms)
        info = self.make_json_campaign().with_user(self.sms_manager)
        info.action_send()
        self.assertEqual(info.sudo().state, 'sending')
        self.assertTrue(info.sudo().message_ids_sms)


@tagged('post_install', '-at_install')
class TestReviewGC3Redirects(JsonModelMixin, SmsTestCase):
    """G-C3: Turatel JSON istekleri yönlendirme izlemez; 3xx sınıflaması."""

    def test_gc3_istekler_allow_redirects_false(self):
        msg = self.Message.send_sms(NUMBER, 'Yönlendirme yok')
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertTrue(self.net.json_calls)
        self.assertEqual({c['allow_redirects'] for c in self.net.json_calls}, {False})

    def test_gc3_301_307_308_sendsms_islenmedi_yeniden_denenebilir(self):
        for status in (301, 307, 308):
            with self.subTest(status=status):
                self.net.tj.add_script('Sms/SendSms', status)
                msg = self.Message.send_sms(NUMBER, 'Kalıcı yönlendirme %s' % status)
                self.assertEqual((msg.state, msg.retry_count), ('error', 1), msg.error)
                self.assertIn(str(status), msg.error)
                self.assertIn('yönlendirme', msg.error)

    def test_gc3_302_303_sendsms_belirsiz(self):
        for status in (302, 303):
            with self.subTest(status=status):
                self.net.tj.add_script('Sms/SendSms', status)
                msg = self.Message.send_sms(NUMBER, 'Belirsiz yönlendirme %s' % status)
                self.assertEqual(msg.state, 'uncertain', msg.error)

    def test_gc3_okuma_ucunda_yonlendirme_yeniden_denenebilir(self):
        from odoo.addons.sms_system.services.turatel import TuratelError
        client = self.json_client('info')
        self.net.tj.add_script('Sms/GetCredit', 308)
        with self.assertRaises(TuratelError) as ctx:
            client.get_credit(9254)
        self.assertTrue(ctx.exception.retryable)
        self.assertFalse(ctx.exception.uncertain)


@tagged('post_install', '-at_install')
class TestReviewGC3Https(JsonSettingsMixin, SmsTestCase):
    """G-C3: JSON servis adresleri https olmalı; hata ayar kaydında, hiçbir parametre yazılmadan."""

    def test_gc3_http_adres_kaydedilemez_parametreler_degismez(self):
        self.save_screen(**FULL)
        for field, key in (('sms_single_url', 'turatel_single_url'), ('sms_bulk_url', 'turatel_bulk_url')):
            with self.subTest(alan=field):
                before = {k: self.param(k) for k in ('turatel_single_url', 'turatel_bulk_url',
                                                     'turatel_json_info_username')}
                bad = FULL[field].replace('https://', 'http://')
                try:
                    self.save_screen(**dict(FULL, sms_json_info_username='baska_user', **{field: bad}))
                except UserError as e:
                    self.assertIn('https://', str(e))
                else:
                    self.fail('http:// adres kaydedilmemeli: %s' % field)
                self.assertEqual({k: self.param(k) for k in before}, before)
                self.assertEqual(self.param(key), FULL[field])

    def test_gc3_https_buyuk_harf_ve_bos_adres_kabul(self):
        self.save_screen(**dict(FULL, sms_single_url='HTTPS://platform.turatel.com/singlesms', sms_bulk_url=''))
        self.assertEqual(self.param('turatel_single_url'), 'HTTPS://platform.turatel.com/singlesms')


@tagged('post_install', '-at_install')
class TestReviewN5NoCommercialSet(JsonModelMixin, SmsTestCase):
    """N5: reklam seti yokken kalıcı hata sonrası gönderim döngüsüne girilmez (İYS/Turatel çağrısı yok)."""

    def test_n5_kilitli_kayit_kalsa_da_iys_ve_turatel_cagrilmaz(self):
        self.configure_json(commercial=False, iys=True)
        self.set_param('optout_text', RET_TEXT)
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial', state='sending', body='Indirim')
        msgs = self.Message.sudo()
        for _i in range(3):
            # İYS'si hiç sorgulanmamış kişi: kapıya girilirse SmartADM sorgulanırdı
            contact = self.make_contact(self.new_mobile(), lst, iys_status='approved')
            msgs |= self.campaign_message(camp, contact, state='queued', body='Indirim')
        busy = msgs[1]
        original = type(self.Message)._lock_for_send

        def lock(model, ids, states):
            return original(model, [i for i in ids if i != busy.id], states)

        with patch.object(type(self.Message), '_lock_for_send', lock):
            self.run_queue()
        self.refresh_all(camp, *msgs)
        self.assertEqual(self.net.smartadm_calls, [], 'Reklam seti yokken İYS sorgusu yapılmamalı')
        self.assertEqual(self.net.json_calls, [])
        self.assertEqual(busy.state, 'queued')
        self.assertEqual(set((msgs - busy).mapped('state')), {'error'})
        self.assertEqual(camp.state, 'sending', 'Kuyrukta kayıt varken kampanya bitmez')
        self.run_queue()   # kilit kalktı: kalan kayıt da kalıcı hataya alınır, kampanya biter
        self.refresh_all(camp, *msgs)
        self.assertEqual(set(msgs.mapped('state')), {'error'})
        self.assertEqual(camp.state, 'done')
        self.assertEqual(self.net.smartadm_calls, [])
        self.assertEqual(self.net.json_calls, [])

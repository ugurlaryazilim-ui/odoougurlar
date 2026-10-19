"""Düzeltme turu #1 (C), kıdemli kısım.

Ö1 (KK-C16): JSON bağlamı (servis + hesap) 'sending' ile aynı commit'te, SendSms'ten önce yazılır.
Ö2: jeton önbelleğinin süresi var. G-C2: taslak dışındaki kampanyanın içeriği değişmez.
G-C3: yönlendirme izlenmez, 3xx sınıflaması, ayarlarda https zorunlu. N5: reklam seti yokken gönderim döngüsü yok.
"""
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import SmsTestCase
from .test_json_routing import JsonModelMixin, NUMBER, RET_TEXT


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
        camp = self.make_json_campaign(message_type='commercial', body='Indirim {ad}')
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
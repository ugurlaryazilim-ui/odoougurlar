"""KK-C7 (kod eşlemesi, model), C13 eki (hesap seti), C16 (belirsiz uzlaştırma), C18 (durum cron'u), C19 (görünümler)."""
from datetime import datetime, time as dtime, timedelta
from unittest.mock import patch

import requests
from lxml import etree
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user, tagged

from ..services.turatel_json import delivery_state as map_delivery_code
from .common import json_err, SmsTestCase
from .test_json_routing import JsonModelMixin, NUMBER

TRACK_FIELDS = ('provider_packet_id', 'delivery_state', 'delivery_code', 'provider_service', 'provider_account_id')


class StatusMixin(JsonModelMixin):

    def require_tracking(self):
        missing = [n for n in TRACK_FIELDS if n not in self.Message._fields]
        if missing:
            self.fail('ARAYÜZ YOK: sms.system.message alanları yok: %s' % ', '.join(missing))

    def make_tracked(self, number=NUMBER, hours_ago=1, service='single', account='9254', message_id='900001', **vals):
        self.require_tracking()
        base = {'state': 'sent', 'provider_service': service, 'provider_account_id': account,
                'delivery_state': 'pending', 'provider_msg_id': message_id,
                'sent_at': fields.Datetime.now() - timedelta(hours=hours_ago)}
        base.update(vals)
        return self.make_message(number, **base)

    def register_at_provider(self, msg, code=0, account=9254):
        """Sağlayıcının kaydı gördüğünü taklit et (mesajın clientId'si ile)."""
        fake = self.net.tj
        mid = int(msg.provider_msg_id or fake._next_id())
        fake.messages[mid] = {'message_id': mid, 'client_id': self.client_id_of(msg), 'number': msg.number,
                              'account': account, 'packet_id': 4001, 'reference_id': None, 'user': 'info_user',
                              'code': code, 'when': fields.Datetime.now()}
        return mid

    def local_day(self, dt):
        return (dt + timedelta(hours=3)).strftime('%d%m%y')   # Europe/Istanbul = UTC+3 (DST yok)

    def warnings(self, logs):
        return [line for line in logs if line.startswith(('WARNING', 'ERROR', 'CRITICAL'))]


@tagged('post_install', '-at_install')
class TestDeliveryCron(StatusMixin, SmsTestCase):

    # ── KK-C18: cron kaydı ──
    def test_kk_c18_cron_kaydi_15_dakika(self):
        cron = self.env.ref('sms_system.cron_sms_delivery_status', raise_if_not_found=False)
        self.assertTrue(cron, 'ARAYÜZ YOK: sms_system.cron_sms_delivery_status')
        self.assertEqual((cron.interval_number, cron.interval_type), (15, 'minutes'))
        self.assertTrue(cron.active)
        self.assertEqual(cron.model_id.model, 'sms.system.message')
        self.assertIn('_cron_fetch_delivery_status', cron.code)

    # ── KK-C18 + KK-C7 (model): durumlar güncellenir ──
    def test_kk_c18_iletim_durumlari_guncellenir_ve_kodlar_eslenir(self):
        # 0 = ulaştı (status 1 + deliveryDate); diğerleri `reason` kodu: bilinmeyen kod da iletilemedi sayılır
        codes = {0: 'delivered', 103: 'undelivered', 114: 'undelivered', -104001: 'undelivered',
                 -8000: 'undelivered', -467: 'undelivered', -441: 'undelivered', 777: 'undelivered'}
        msgs = {}
        for i, code in enumerate(codes):
            msg = self.Message.send_sms('0532123%04d' % (4000 + i), 'Durum %d' % i)
            self.assertEqual(msg.state, 'sent', msg.error)
            self.net.tj.set_code(msg.provider_msg_id, code)
            msgs[code] = msg
        self.cron_status()
        self.refresh_all(*msgs.values())
        for code, state in codes.items():
            msg = msgs[code]
            self.assertEqual(msg.delivery_state, state, 'kod %s' % code)
            self.assertEqual(str(msg.delivery_code), 'status:1' if code == 0 else str(code),
                             'reason kodu olduğu gibi, teslim status:1 olarak saklanmalı')
            self.assertEqual(msg.state, 'sent', 'Gönderim durumu değişmez')

    def test_kk_c18_hicbir_iletim_kodu_yeniden_gonderim_tetiklemez(self):
        msg = self.Message.send_sms(NUMBER, 'Tek sefer')
        self.net.tj.set_code(msg.provider_msg_id, 103)
        self.cron_status()
        self.Message._cron_retry_failed()
        self.Message._cron_send_queued()
        self.Campaign._cron_process_queue()
        self.assertEqual(self.sends_with(msg), 1)
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c18_sorgu_iki_tarih_ucuyla_servis_ve_hesap_setine_gore(self):
        self.configure_json(iys=True)
        single = self.Message.send_sms(NUMBER, 'Tekli')
        info = self.launch(self.make_json_campaign(message_type='info'))
        com = self.launch(self.make_json_campaign(message_type='commercial'))
        before = len(self.net.json_calls)
        self.cron_status()
        calls = [c for c in self.net.json_calls[before:] if c['endpoint'] == 'Sms/GetStatusByTwoDates']
        seen = {(c['service'], c['user'], int(c['payload']['accountId'])) for c in calls}
        self.assertEqual(seen, {('singlesms', 'info_user', 9254), ('bulksms', 'info_user', 9254),
                                ('bulksms', 'com_user', 65672)})
        self.assertEqual(len(calls), 3, 'Aynı (servis, hesap, gün) için tek sorgu')
        self.assertEqual([c for c in self.net.json_calls[before:] if c['endpoint'] == 'Sms/SendSms'], [])
        self.refresh_all(single, *info, *com)
        self.assertEqual({m.delivery_state for m in single | info | com}, {'delivered'})

    def test_kk_c18_gun_parcalari_istanbul_saatiyle_ve_parca_basina_commit(self):
        a = self.make_tracked('05321230001', hours_ago=30, message_id='910001')
        b = self.make_tracked('05321230002', hours_ago=2, message_id='910002')
        self.register_at_provider(a)
        self.register_at_provider(b)
        before_events = len(self.events)
        self.cron_status()
        windows = [w for w in self.net.tj.status_windows if w[0] == 9254]
        days = {self.local_day(m.sent_at) for m in (a, b)}
        self.assertEqual(len(days), 2)
        self.assertEqual({w[1][:6] for w in windows}, days)
        self.assertEqual(len(windows), 2, 'Her gün parçası için bir sorgu')
        for _acc, start, end in windows:
            self.assertEqual((len(start), start[6:], len(end), end[6:]), (12, '000000', 12, '235959'))
            self.assertEqual(start[:6], end[:6], 'Pencere tek takvim günü')
        commits = [e for e in self.events[before_events:] if e[0] == 'commit']
        self.assertGreaterEqual(len(commits), 2, 'İlerleme parça parça commit edilmeli')

    def test_kk_c18_eslesme_message_id_ile_client_id_olmasa_da(self):
        msg = self.make_tracked(message_id='920001')
        mid = self.register_at_provider(msg, code=0)
        self.net.tj.messages[mid]['client_id'] = None
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')

    def test_kk_c18_message_id_olmayan_kayit_client_id_ile_eslenir_ve_kimlik_yazilir(self):
        msg = self.make_tracked(message_id=False)
        mid = self.register_at_provider(msg, code=0)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')
        self.assertEqual(str(msg.provider_msg_id), str(mid))

    def test_kk_c18_48_saati_asan_bekleyen_bilinmeyen_olur(self):
        old = self.make_tracked('05321230003', hours_ago=49, message_id='930001')
        fresh = self.make_tracked('05321230004', hours_ago=47, message_id='930002')
        self.cron_status()
        self.refresh_all(old, fresh)
        self.assertEqual(old.delivery_state, 'unknown')
        self.assertEqual(old.state, 'sent')
        self.assertEqual(fresh.delivery_state, 'pending', '48 saat dolmadan beklemeye devam')

    def test_kk_c18_48_saati_asan_kayit_raporda_varsa_yine_sorgulanmaz_bilinmeyen_olur(self):
        """Pencere dışı: 48 saati aşıp kesin sonuç almayan kayıt 'bilinmeyen' olur."""
        old = self.make_tracked(hours_ago=60, message_id='930003')
        self.register_at_provider(old, code=0)
        self.cron_status()
        self.refresh_all(old)
        self.assertEqual(old.delivery_state, 'unknown')

    def test_kk_c18_aday_olmayan_kayitlar_degismez_ve_istek_yok(self):
        legacy = self.make_tracked('05321230005', service='legacy', delivery_state=False, message_id='940001')
        errored = self.make_message('05321230006', state='error')
        done = self.make_tracked('05321230007', delivery_state='delivered', message_id='940002', delivery_code='status:1')
        self.cron_status()
        self.assertEqual([c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')], [])
        self.refresh_all(legacy, errored, done)
        self.assertFalse(legacy.delivery_state)
        self.assertEqual(errored.state, 'error')
        self.assertEqual(done.delivery_state, 'delivered')

    def test_kk_c18_turatel_hatasinda_cron_cokmez_bir_kez_loglanir_sonraki_calisma_devam(self):
        msg = self.make_tracked(message_id='950001')
        self.register_at_provider(msg, code=0)
        self.net.tj.add_script('Sms/GetStatusByTwoDates', json_err(-5, 'Boom'))
        with self.capture_logs() as logs:
            self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'pending')
        hits = [line for line in self.warnings(logs) if 'Boom' in line or '-5' in line]
        self.assertEqual(len(hits), 1, 'Hata bir kez loglanmalı: %s' % hits)
        self.cron_status()   # sonraki çalışma: normal yanıt
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')

    def test_kk_c18_baglanti_hatalari_cron_cokertmez(self):
        msg = self.make_tracked(message_id='950002')
        self.register_at_provider(msg, code=0)
        for error in (requests.exceptions.ConnectTimeout('c'), requests.exceptions.ReadTimeout('r'), 500, 'html değil json',
                      json_err(-22, 'Unauthorized IP Address'), json_err(-1, 'x'), json_err(-1, 'x')):
            self.net.tj.add_script('Sms/GetStatusByTwoDates', error)
        for _i in range(5):
            self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'pending', 'Hatalarda kayıt değişmemeli')
        self.assertEqual(msg.state, 'sent')

    def test_kk_c18_eksik_hesap_seti_cift_atlanir_tek_uyari(self):
        a = self.make_tracked('05321230008', account='11111', message_id='960001')
        b = self.make_tracked('05321230009', account='11111', message_id='960002')
        with self.capture_logs() as logs:
            self.cron_status()
        self.refresh_all(a, b)
        self.assertEqual({a.delivery_state, b.delivery_state}, {'pending'})
        self.assertEqual([c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')], [])
        self.assertEqual(len(self.warnings(logs)), 1, 'Çalışma başına tek uyarı: %s' % self.warnings(logs))

    def test_kk_c18_minus_6_bos_sonuc_hata_logu_yok_kayit_degismez(self):
        msg = self.make_tracked(message_id='970001')
        self.net.tj.status_empty = True
        with self.capture_logs() as logs:
            self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'pending')
        self.assertEqual(self.warnings(logs), [], 'Hata/uyarı logu yazılmamalı')
        old = self.make_tracked('05321230010', hours_ago=49, message_id='970002')
        self.cron_status()
        self.refresh_all(old)
        self.assertEqual(old.delivery_state, 'unknown', '-6 ile boş kalan eski kayıt 48 saatte bilinmeyen olur')

    def test_kk_c18_durum_yaniti_cubuk_liste_biciminde_de_okunur(self):
        """VARSAYIM: GetStatus yanıtı data={'statusList': [...]} ya da çıplak liste (02-tasarim §5.2 toleranslı ayrıştırma)."""
        self.net.tj.status_shape = 'list'
        msg = self.make_tracked(message_id='980001')
        self.register_at_provider(msg, code=0)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')

    def test_kk_c18_loglarda_sir_ve_telefon_yok(self):
        msg = self.make_tracked(message_id='980002')
        self.register_at_provider(msg, code=0)
        self.net.tj.add_script('Sms/GetStatusByTwoDates', json_err(-5, 'Boom'))
        with self.capture_logs() as logs:
            self.cron_status()
            self.cron_status()
        text = '\n'.join(logs)
        for secret in ('info_pw', 'com_pw', 'Bearer', 'TOK-', NUMBER[-10:]):
            self.assertNotIn(secret, text)

    # ── KK-C16 ──
    def uncertain_message(self, reached_provider=True):
        fake = self.net.tj

        def send_then_timeout(call):
            if reached_provider:
                fake._normal(call)   # istek sağlayıcıya ulaştı, yanıt gelmedi
            return requests.exceptions.ReadTimeout('okuma zaman aşımı')

        fake.add_script('Sms/SendSms', send_then_timeout)
        msg = self.Message.send_sms(NUMBER, 'Belirsiz uzlaşma')
        self.assertEqual(msg.state, 'uncertain', msg.error)
        return msg

    def test_kk_c16_belirsiz_kayit_servis_ve_hesap_alanlarini_tasir(self):
        msg = self.uncertain_message()
        self.assertEqual(msg.provider_service, 'single')
        self.assertEqual(str(msg.provider_account_id), '9254')

    def test_kk_c16_belirsiz_kayit_raporda_bulunursa_sent_olur(self):
        msg = self.uncertain_message(reached_provider=True)
        self.set_write_date(msg, 20)
        self.cron_status()
        self.refresh_all(msg)
        fake_msg = self.net.tj.message_by_client(self.client_id_of(msg))
        self.assertEqual(msg.state, 'sent')
        self.assertEqual(str(msg.provider_msg_id), str(fake_msg['message_id']))
        self.assertEqual(msg.delivery_state, 'delivered')
        self.assertEqual(self.sends_with(msg), 1, 'Uzlaşma yeniden gönderim yapmaz')

    def test_kk_c16_uzlasan_kayitta_belirsiz_hata_metni_temizlenir(self):
        msg = self.uncertain_message(reached_provider=True)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'sent')
        self.assertFalse(msg.error, 'Gönderildi durumundaki kayıtta "belirsiz" hata metni kalmamalı')

    def test_kk_c16_belirsiz_kayit_raporda_yoksa_belirsiz_kalir_yeniden_gonderilmez(self):
        msg = self.uncertain_message(reached_provider=False)
        for _i in range(3):
            self.cron_status()
            self.Message._cron_retry_failed()
            self.Campaign._cron_process_queue()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain')
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c16_minus_6_ile_belirsiz_kayit_belirsiz_kalir(self):
        msg = self.uncertain_message(reached_provider=True)
        self.net.tj.status_empty = True
        with self.capture_logs() as logs:
            self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain')
        self.assertEqual(self.warnings(logs), [])

    def test_kk_c16_kampanya_paketi_belirsizse_hepsi_uzlasir(self):
        fake = self.net.tj
        fake.add_script('Sms/SendSms', lambda call: (fake._normal(call), requests.exceptions.ReadTimeout('r'))[1])
        camp = self.make_json_campaign()
        msgs = self.launch(camp)
        self.assertEqual(set(msgs.mapped('state')), {'uncertain'})
        self.cron_status()
        self.refresh_all(*msgs)
        self.assertEqual(set(msgs.mapped('state')), {'sent'})
        self.assertEqual({m.delivery_state for m in msgs}, {'delivered'})
        self.assertEqual(len({m.provider_msg_id for m in msgs}), 3)
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c16_eski_xml_belirsiz_kayitlari_cron_dokunmaz(self):
        self.set_param('api_mode', 'legacy_xml')
        msg = self.make_message(NUMBER, state='uncertain', provider_service='legacy')
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain')
        self.assertEqual(self.net.json_calls, [])


@tagged('post_install', '-at_install')
class TestDeliveryUi(StatusMixin, SmsTestCase):

    # ── KK-C19 ──
    def view_arch(self, model, view_type):
        return etree.fromstring(self.env[model].get_view(view_type=view_type)['arch'])

    def test_kk_c19_mesaj_arama_gorunumunde_iletim_filtreleri(self):
        arch = self.view_arch('sms.system.message', 'search')
        filters = {f.get('string'): f.get('domain') or '' for f in arch.iter('filter')}
        for label, state in (('İletildi', 'delivered'), ('İletilemedi', 'undelivered')):
            self.assertIn(label, filters, 'ARAYÜZ YOK: mesaj arama filtresi %r' % label)
            self.assertIn('delivery_state', filters[label])
            self.assertIn(state, filters[label])
        self.assertIn('Belirsiz', filters)

    def test_kk_c19_mesaj_formunda_iletim_alanlari_ve_durum_sorgula(self):
        arch = self.view_arch('sms.system.message', 'form')
        names = {f.get('name') for f in arch.iter('field')}
        for name in ('delivery_state', 'delivery_code'):
            self.assertIn(name, names, 'ARAYÜZ YOK: mesaj formunda %s' % name)
        buttons = {b.get('name'): b.get('string') for b in arch.iter('button')}
        self.assertIn('action_fetch_report', buttons)
        self.assertIn('Durumu Sorgula', ' '.join(filter(None, buttons.values())))

    def test_kk_c19_kampanya_formunda_iletildi_iletilemedi_sayaclari(self):
        names = {f.get('name') for f in self.view_arch('sms.system.campaign', 'form').iter('field')}
        self.assertIn('delivered_count', names)
        self.assertIn('undelivered_count', names)

    def test_kk_c19_kampanya_sayaclari_durum_cron_sonrasi(self):
        camp = self.make_json_campaign(names=('A', 'B', 'C', 'D'))
        msgs = self.launch(camp)
        self.net.tj.set_code(msgs[0].provider_msg_id, 0)
        self.net.tj.set_code(msgs[1].provider_msg_id, 0)
        self.net.tj.set_code(msgs[2].provider_msg_id, 103)
        self.net.tj.set_code(msgs[3].provider_msg_id, -441)
        self.cron_status()
        camp.invalidate_recordset()
        self.assertEqual((camp.delivered_count, camp.undelivered_count), (2, 2))

    def test_kk_c19_durumu_sorgula_json_modunda_getstatus_paket_ile(self):
        msg = self.Message.send_sms(NUMBER, 'Sorgula')
        self.net.tj.set_code(msg.provider_msg_id, 0)
        before = len(self.net.json_calls)
        msg.action_fetch_report()
        calls = [c for c in self.net.json_calls[before:] if c['endpoint'] == 'Sms/GetStatus']
        self.assertEqual(len(calls), 1)
        self.assertEqual(int(calls[0]['payload']['accountId']), 9254)
        self.assertEqual(calls[0]['user'], 'info_user')
        self.assertEqual(str(calls[0]['payload']['packetId']), str(msg.provider_packet_id))
        self.assertEqual(self.net.turatel_calls, [], 'XML rapor ucu çağrılmamalı')
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')

    def test_kk_c19_durumu_sorgula_paket_yoksa_gonderim_gunu_aralik_sorgusu(self):
        msg = self.make_tracked(message_id='990001', provider_packet_id=False)
        self.register_at_provider(msg, code=103)
        msg.action_fetch_report()
        self.assertTrue([c for c in self.net.json_calls if c['endpoint'] == 'Sms/GetStatusByTwoDates'])
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'undelivered')

    def test_kk_c19_durumu_sorgula_kayit_yoksa_bildirim_ve_kayit_degismez(self):
        msg = self.make_tracked(message_id='990002')
        self.net.tj.status_empty = True
        result = msg.action_fetch_report()
        params = (result or {}).get('params') or {}
        self.assertIn('henüz kayıt yok', str(params.get('message') or ''))
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'pending')

    def test_kk_c19_durumu_sorgula_kendi_hesap_setiyle(self):
        msg = self.make_tracked(service='bulk', account='65672', message_id='990003')
        self.register_at_provider(msg, code=0, account=65672)
        self.net.tj.messages[int(msg.provider_msg_id)]['user'] = 'com_user'
        msg.action_fetch_report()
        users = {c['user'] for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')}
        self.assertEqual(users, {'com_user'})
        self.assertEqual({c['service'] for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')},
                         {'bulksms'})

    def test_kk_c19_legacy_modda_durumu_sorgula_eski_rapor_ucu(self):
        self.set_param('api_mode', 'legacy_xml')
        msg = self.Message.send_sms(NUMBER, 'Eski')
        self.assertTrue(msg.provider_msg_id)
        before = len(self.net.calls)
        msg.action_fetch_report()
        new = self.net.calls[before:]
        self.assertTrue(new, 'Eski modda rapor sorgusu yapılmalı')
        self.assertEqual([c for c in new if c['kind'] == 'turatel_json'], [])


@tagged('post_install', '-at_install')
class TestDeliveryStatusExtra(StatusMixin, SmsTestCase):
    """C5 uygulama ayrıntıları: gece yarısı, süre bütçesi, yetki, açıklama, test modu, bilinmeyen yeniden sorgu."""

    def istanbul_today(self):
        return (fields.Datetime.now() + timedelta(hours=3)).date()

    def utc_at(self, day, hour, minute=0):
        """İstanbul günü + saat → UTC naive (UTC+3, DST yok)."""
        return datetime.combine(day, dtime(hour, minute)) - timedelta(hours=3)

    def make_uncertain(self, number=NUMBER):
        return self.make_tracked(number, state='uncertain', sent_at=False, delivery_state=False, message_id=False)

    def set_write_at(self, record, when):
        self.env.flush_all()
        self.env.cr.execute('UPDATE sms_system_message SET write_date = %s WHERE id = %s', (when, record.id))
        record.invalidate_recordset()

    def test_c5_belirsiz_kayit_gece_yarisini_asarsa_iki_gun_sorgulanir(self):
        yesterday = self.istanbul_today() - timedelta(days=1)
        msg = self.make_uncertain()
        self.set_write_at(msg, self.utc_at(yesterday, 0, 10))   # dün 00:10 İstanbul: istek önceki güne düşebilir
        self.cron_status()
        days = {w[1][:6] for w in self.net.tj.status_windows if w[0] == 9254}
        self.assertEqual(days, {(yesterday - timedelta(days=1)).strftime('%d%m%y'), yesterday.strftime('%d%m%y')})
        self.refresh_all(msg)
        self.assertEqual(msg.state, 'uncertain', 'Raporda yoksa belirsiz kalır')

    def test_c5_belirsiz_kayit_iki_parcada_eslesse_de_bir_kez_yazilir(self):
        yesterday = self.istanbul_today() - timedelta(days=1)
        unsure = self.make_uncertain('05321230011')
        self.set_write_at(unsure, self.utc_at(yesterday, 0, 10))
        other = self.make_tracked('05321230012', message_id='970001', sent_at=self.utc_at(yesterday, 12))
        self.register_at_provider(unsure, code=0)
        self.register_at_provider(other, code=0)
        written = []
        Model = self.env.registry['sms.system.message']
        original = Model.write

        def spy(records, vals):
            written.extend(records.ids)
            return original(records, vals)

        with patch.object(Model, 'write', spy):
            self.cron_status()
        self.refresh_all(unsure, other)
        self.assertEqual((unsure.state, unsure.delivery_state, other.delivery_state), ('sent', 'delivered', 'delivered'))
        self.assertEqual(written.count(unsure.id), 1)
        self.assertEqual(unsure.sent_at, self.utc_at(yesterday, 0, 10), 'Gönderim zamanı = belirsiz olduğu an')

    def test_c5_sure_butcesi_bitince_kalan_parcalar_sonraki_calismaya(self):
        a = self.make_tracked('05321230013', hours_ago=30, message_id='970002')
        b = self.make_tracked('05321230014', hours_ago=2, message_id='970003')
        self.register_at_provider(a)
        self.register_at_provider(b)
        with patch.object(self.env.registry['ir.cron'], '_commit_progress',
                          lambda cron, processed=0, **kw: 5.0):
            self.cron_status()
        self.assertEqual(len(self.net.tj.status_windows), 1, 'Süre azalınca ilk parçadan sonra durur')
        self.refresh_all(a, b)
        self.assertEqual((a.delivery_state, b.delivery_state), ('delivered', 'pending'), 'En eski gün önce')
        self.cron_status()
        self.refresh_all(b)
        self.assertEqual(b.delivery_state, 'delivered')

    def test_c5_durumu_sorgula_yonetici_olmayana_kapali_ag_cagrisi_yok(self):
        sms_user = new_test_user(self.env, login='sms_c5_user', groups='base.group_user,sms_system.group_sms_user')
        msg = self.make_tracked(message_id='970004', user_id=sms_user.id)   # kayıt kuralı okumaya izin verir
        self.register_at_provider(msg, code=0)
        for user in (self.plain_user, sms_user):
            with self.assertRaises(AccessError):
                msg.with_user(user).action_fetch_report()
        self.assertEqual(self.net.calls, [])
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'pending')

    def test_y1_durumu_sorgula_yalniz_gonderilmis_ya_da_belirsiz_kayitta(self):
        """Y1: hata kaydı servis/hesap taşısa da (Ö1) düğme gizli, sunucu metodu ağa gitmez."""
        err = self.make_tracked('05321230021', state='error', message_id=False, error='Kalıcı hata')
        self.assertEqual((err.provider_service, err.provider_account_id), ('single', '9254'))
        result = err.action_fetch_report()
        self.assertEqual(result['params']['type'], 'warning')
        self.assertEqual(self.net.calls, [], 'Hata kaydı için sağlayıcı sorgusu yapılmamalı')
        # sent/uncertain sorgulanır
        sent = self.make_tracked('05321230022')
        unsure = self.make_tracked('05321230023', state='uncertain', message_id=False)
        self.register_at_provider(sent, code=0)
        (sent | unsure | err).action_fetch_report()
        self.assertTrue([c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')])
        self.refresh_all(err)
        self.assertEqual(err.state, 'error')

    def test_y1_durumu_sorgula_dugmesi_hata_kaydinda_gizli(self):
        arch = etree.fromstring(self.env['sms.system.message'].get_view(view_type='form')['arch'])
        button = next(b for b in arch.iter('button') if b.get('name') == 'action_fetch_report')
        condition = button.get('invisible') or ''
        self.assertIn('state', condition)
        self.assertIn("'sent'", condition)
        self.assertIn("'uncertain'", condition)

    def test_c5_iletim_aciklamasi(self):
        delivered = self.make_tracked('05321230015', delivery_state='delivered', delivery_code='status:1')
        failed = self.make_tracked('05321230016', delivery_state='undelivered', delivery_code='103')
        odd = self.make_tracked('05321230017', delivery_state='unknown', delivery_code='status:777')
        fresh = self.make_tracked('05321230018')
        self.assertEqual(delivered.delivery_label, 'iletildi')
        self.assertEqual(failed.delivery_label, map_delivery_code('103')[1])
        self.assertNotEqual(failed.delivery_label, 'iletildi')
        self.assertIn('777', odd.delivery_label)
        self.assertFalse(fresh.delivery_label)

    def test_c5_test_modunda_gercekten_gonderilen_kayit_sorgulanir(self):
        self.set_param('test_mode', 'True')
        sent = self.make_tracked('05321230019', message_id='970005')
        self.register_at_provider(sent, code=0)
        simulated = self.make_message('05321230020', state='test', provider_service='single',
                                      provider_account_id='9254')
        self.register_at_provider(simulated, code=0)
        self.cron_status()
        self.refresh_all(sent, simulated)
        self.assertEqual(sent.delivery_state, 'delivered')
        self.assertEqual((simulated.state, simulated.delivery_state), ('test', False))

    def test_c5_bilinmeyen_status_sonraki_calismada_yeniden_sorgulanir(self):
        msg = self.make_tracked(message_id='970006')
        mid = self.register_at_provider(msg)
        self.net.tj.set_status(mid, 7)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('unknown', 'status:7'))
        self.assertIn('durum 7', msg.delivery_label)
        self.net.tj.set_code(mid, 0)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('delivered', 'status:1'))

    def test_c5_durumu_sorgula_eslesince_bildirim_ve_ham_satir(self):
        msg = self.make_tracked(message_id='970007', provider_packet_id=False)
        self.register_at_provider(msg, code=0)
        result = msg.action_fetch_report()
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('iletildi', result['params']['message'])
        self.refresh_all(msg)
        self.assertIn('970007', msg.delivery_report or '')


@tagged('post_install', '-at_install')
class TestLiveStatusMapping(StatusMixin, SmsTestCase):
    """Canlı veri: status 1 + deliveryDate = ulaştı; status 0/2 = bekliyor; reason = ret kodu; ham satır cron'da da yazılır."""

    DATE = '201026123000'

    def one_cycle(self, status, reason='', delivery_date='', **vals):
        msg = self.make_tracked(**vals)
        mid = self.register_at_provider(msg)
        self.net.tj.set_status(mid, status, reason, delivery_date)
        self.cron_status()
        self.refresh_all(msg)
        return msg

    def test_status_1_ve_teslim_tarihi_dolu_iletildi(self):
        msg = self.one_cycle(1, '', self.DATE)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('delivered', 'status:1'))
        self.assertEqual(msg.delivery_label, 'iletildi')

    def test_status_0_bekliyor_onay(self):
        msg = self.one_cycle(0)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('pending', 'status:0'))
        self.assertIn('onay', msg.delivery_label)

    def test_status_2_operatore_iletildi_rapor_bekleniyor(self):
        msg = self.one_cycle(2)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('pending', 'status:2'))
        self.assertIn('rapor bekleniyor', msg.delivery_label)

    def test_status_1_ama_teslim_tarihi_bos_bekliyor(self):
        msg = self.one_cycle(1, '', '')
        self.assertEqual(msg.delivery_state, 'pending')
        self.assertNotEqual(msg.delivery_code, 'status:1')

    def test_reason_114_iletilemedi(self):
        msg = self.one_cycle(2, '114')
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('undelivered', '114'))
        self.assertEqual(msg.delivery_label, map_delivery_code('114')[1])

    def test_reason_status_1_teslim_tarihi_olsa_da_iletilemedi_yazar(self):
        msg = self.one_cycle(1, '-8000', self.DATE)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('undelivered', '-8000'))

    def test_bilinmeyen_reason_iletilemedi_kod_x(self):
        msg = self.one_cycle(2, '4242')
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('undelivered', '4242'))
        self.assertEqual(msg.delivery_label, 'iletilemedi (kod 4242)')

    def test_reason_sifir_yok_sayilir(self):
        msg = self.one_cycle(1, '0', self.DATE)
        self.assertEqual(msg.delivery_state, 'delivered')

    def test_bilinmeyen_status_unknown_ve_ham_satir_kalir(self):
        msg = self.one_cycle(9)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('unknown', 'status:9'))
        self.assertIn('bilinmeyen (durum 9)', msg.delivery_label)
        self.assertIn('"status":9', msg.delivery_report)

    def test_cron_yolunda_ham_satir_maskeli_yazilir(self):
        msg = self.one_cycle(2, '', '')
        report = msg.delivery_report or ''
        self.assertIn('"status":2', report)
        self.assertIn('"reason":""', report)
        self.assertLessEqual(len(report), 500)
        self.assertNotIn(NUMBER[-10:], report, 'Telefon ham raporda maskeli olmalı')

    def test_pending_sonra_teslim_nihai_olur_ve_nihai_kayit_sorgulanmaz(self):
        msg = self.make_tracked(message_id='971001')
        mid = self.register_at_provider(msg)
        self.net.tj.set_status(mid, 0)
        self.cron_status()
        self.net.tj.set_status(mid, 2)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('pending', 'status:2'))
        self.net.tj.set_status(mid, 1, '', self.DATE)
        self.cron_status()
        self.refresh_all(msg)
        self.assertEqual(msg.delivery_state, 'delivered')
        before = len([c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')])
        self.cron_status()
        self.assertEqual(len([c for c in self.net.json_calls if c['endpoint'].startswith('Sms/GetStatus')]), before)

    def test_onay_isareti_bekleyen_status_ile_ezilmez_nihai_ezer(self):
        for status in (0, 2):
            with self.subTest(status=status):
                msg = self.make_tracked(message_id='972%03d' % status, delivery_code='confirm_pending',
                                        number='053212300%02d' % status)
                mid = self.register_at_provider(msg)
                self.net.tj.set_status(mid, status)
                self.cron_status()
                self.refresh_all(msg)
                self.assertEqual((msg.delivery_state, msg.delivery_code), ('pending', 'confirm_pending'))
                self.assertIn('"status":%d' % status, msg.delivery_report, 'Ham satır yine de yazılır')
                self.net.tj.set_status(mid, 1, '', self.DATE)
                self.cron_status()
                self.refresh_all(msg)
                self.assertEqual((msg.delivery_state, msg.delivery_code), ('delivered', 'status:1'))

    def test_onay_notu_ham_satirla_silinmez(self):
        msg = self.make_tracked(message_id='973001', delivery_code='confirm_failed',
                                delivery_report='ConfirmSms başarısız (örnek)')
        mid = self.register_at_provider(msg)
        self.net.tj.set_status(mid, 0)
        self.cron_status()
        self.refresh_all(msg)
        self.assertIn('ConfirmSms başarısız (örnek)', msg.delivery_report)
        self.assertIn('"status":0', msg.delivery_report)
        self.assertEqual(msg.delivery_code, 'confirm_failed')

    def test_eski_yanlis_delivered_kod_0_son_48_saatte_yeniden_sorgulanir_ve_duzelir(self):
        wrong = self.make_tracked('05321230031', message_id='974001', delivery_state='delivered', delivery_code='0')
        reached = self.make_tracked('05321230032', message_id='974002', delivery_state='delivered', delivery_code='0')
        too_old = self.make_tracked('05321230033', message_id='974003', hours_ago=60, delivery_state='delivered',
                                    delivery_code='0')
        self.net.tj.set_status(self.register_at_provider(wrong), 0)
        self.net.tj.set_status(self.register_at_provider(reached), 1, '', self.DATE)
        self.register_at_provider(too_old)
        self.cron_status()
        self.refresh_all(wrong, reached, too_old)
        self.assertEqual((wrong.delivery_state, wrong.delivery_code), ('pending', 'status:0'))
        self.assertEqual((reached.delivery_state, reached.delivery_code), ('delivered', 'status:1'))
        self.assertEqual((too_old.delivery_state, too_old.delivery_code), ('delivered', '0'), '48 saat dışı dokunulmaz')

    def test_eski_yanlis_delivered_kayit_reason_ile_iletilemediye_gecer(self):
        wrong = self.make_tracked('05321230034', message_id='974004', delivery_state='delivered', delivery_code='0')
        self.net.tj.set_status(self.register_at_provider(wrong), 2, '114')
        self.cron_status()
        self.refresh_all(wrong)
        self.assertEqual((wrong.delivery_state, wrong.delivery_code), ('undelivered', '114'))

    def test_durumu_sorgula_bekleyen_kayit_bildirimi(self):
        msg = self.make_tracked(message_id='975001', provider_packet_id=False)
        self.net.tj.set_status(self.register_at_provider(msg), 0)
        result = msg.action_fetch_report()
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('onay', result['params']['message'])
        self.refresh_all(msg)
        self.assertEqual((msg.delivery_state, msg.delivery_code), ('pending', 'status:0'))
        self.assertIn('"status":0', msg.delivery_report)

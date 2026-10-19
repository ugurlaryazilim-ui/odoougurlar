"""KK-C27: test modunda gerçek gönderilecek numaralar listesi (kontrollü canlı deneme)."""
import re

from odoo.exceptions import UserError
from odoo.tests.common import new_test_user, tagged

from .common import SmsTestCase
from .test_json_routing import JsonModelMixin, RET_TEXT

LISTED_A = '5321110001'
LISTED_B = '5321110002'
OTHER = '5321110003'
LISTED = '0%s, +90%s' % (LISTED_A, LISTED_B)   # kullanıcı farklı biçimlerde yazar


class TestNumbersMixin(JsonModelMixin):

    def listed(self, value=LISTED, mode='json', test_mode='True'):
        if mode == 'json':
            self.configure_json(test_mode=test_mode, iys=True)
        else:
            self.configure_sms(test_mode=test_mode, iys=True)
            self.set_param('api_mode', 'legacy_xml')
        self.set_param('optout_text', RET_TEXT)
        if value is None:
            self.set_param('test_numbers', None)
        else:
            self.set_param('test_numbers', value)

    def campaign_with(self, numbers, message_type='info'):
        lst = self.make_list()
        for i, number in enumerate(numbers):
            extra = {'iys_status': 'approved', 'iys_checked_at': self.ago(hours=1)} if message_type == 'commercial' else {}
            self.make_contact(number, lst, name='Kişi%d' % i, **extra)
        return self.make_campaign(lst, message_type, state='draft', body='Merhaba {ad}')

    def states_by_number(self, msgs):
        out = {}
        for m in msgs:
            out[re.sub(r'\D', '', m.number)[-10:]] = m.state
        return out


@tagged('post_install', '-at_install')
class TestTestNumbersSettings(TestNumbersMixin, SmsTestCase):

    def Settings(self):
        return self.env['res.config.settings']

    def require_field(self):
        if 'sms_test_numbers' not in self.Settings()._fields:
            self.fail('ARAYÜZ YOK: res.config.settings.sms_test_numbers')

    def save(self, value):
        self.require_field()
        self.Settings().create({'sms_test_numbers': value}).execute()

    def stored(self):
        raw = self.icp.get_param('sms_system.test_numbers') or ''
        return [x.strip() for x in raw.split(',') if x.strip()]

    def test_kk_c27_alan_vardir_ve_gercek_deger_ekrana_gelir(self):
        self.require_field()
        self.set_param('test_numbers', LISTED_A)
        self.assertEqual(self.Settings().default_get(['sms_test_numbers']).get('sms_test_numbers'), LISTED_A)

    def test_kk_c27_numaralar_normalize_edilip_saklanir(self):
        self.save(LISTED)
        self.assertEqual(self.stored(), [LISTED_A, LISTED_B])

    def test_kk_c27_bes_numara_kabul_edilir(self):
        numbers = ['532111000%d' % i for i in range(1, 6)]
        self.save(', '.join(numbers))
        self.assertEqual(self.stored(), numbers)

    def test_kk_c27_alti_numara_reddedilir_ve_eski_deger_korunur(self):
        self.save(LISTED_A)
        with self.assertRaises(UserError):
            self.save(', '.join('532111000%d' % i for i in range(1, 7)))
        self.assertEqual(self.stored(), [LISTED_A])

    def test_kk_c27_gecersiz_numara_kaydi_engeller(self):
        self.save(LISTED_A)
        for bad in ('12345', '0532 111', LISTED_A + ', abc', LISTED_A + ', 4321110002'):
            with self.subTest(deger=bad):
                with self.assertRaises(UserError):
                    self.save(bad)
                self.assertEqual(self.stored(), [LISTED_A], 'Hatalı kayıt hiçbir şey yazmamalı')

    def test_kk_c27_bos_liste_kabul_edilir_ve_listeyi_temizler(self):
        self.save(LISTED_A)
        self.save('')
        self.assertEqual(self.stored(), [])

    def test_kk_c27_yinelenen_numara_tek_sayilir(self):
        self.save('%s, 0%s, +90%s' % (LISTED_A, LISTED_A, LISTED_A))
        self.assertEqual(self.stored(), [LISTED_A])

    def test_g_c1_test_numaralari_yonetici_olmayana_gorunmez(self):
        # G-C1: numaralar çalışan telefonlarıdır (KVKK); RPC'ye açık default_get/get_values sızdırmamalı
        self.require_field()
        self.set_param('test_numbers', '%s,%s' % (LISTED_A, LISTED_B))
        self.assertEqual(self.Settings()._fields['sms_test_numbers'].groups, 'base.group_system')
        manager = new_test_user(self.env, login='sms_t_mgr_c1', groups='base.group_user,sms_system.group_sms_manager')
        for user in (self.plain_user, manager):
            res = self.Settings().with_user(user).default_get(['sms_test_numbers', 'sms_test_mode'])
            self.assertNotIn('sms_test_numbers', res)
            values = self.Settings().with_user(user).get_values()
            self.assertNotIn('sms_test_numbers', values)
            for number in (LISTED_A, LISTED_B):
                self.assertNotIn(number, repr(res) + repr(values))

    def test_g_c1_sistem_yoneticisi_test_numaralarini_gorur(self):
        self.require_field()
        self.set_param('test_numbers', LISTED_A)
        res = self.Settings().with_user(self.admin_user).default_get(['sms_test_numbers'])
        self.assertEqual(res.get('sms_test_numbers'), LISTED_A)

    def test_kk_c27_ayarlar_sozlugu_test_numaralarini_tasir(self):
        self.set_param('test_numbers', '%s,%s' % (LISTED_A, LISTED_B))
        numbers = self.Message._settings().get('test_numbers')
        self.assertEqual(sorted(numbers or []), [LISTED_A, LISTED_B])
        self.set_param('test_numbers', None)
        self.assertFalse(self.Message._settings().get('test_numbers'))

    def test_kk_c27_blocked_by_test_mode_anlami(self):
        if not hasattr(self.Message, '_blocked_by_test_mode'):
            self.fail('ARAYÜZ YOK: sms.system.message._blocked_by_test_mode(cfg, number) (tasarım §6)')
        on = {'test_mode': True, 'test_numbers': [LISTED_A]}
        off = {'test_mode': False, 'test_numbers': [LISTED_A]}
        empty = {'test_mode': True, 'test_numbers': []}
        self.assertFalse(self.Message._blocked_by_test_mode(on, LISTED_A))
        self.assertTrue(self.Message._blocked_by_test_mode(on, OTHER))
        self.assertFalse(self.Message._blocked_by_test_mode(off, OTHER))
        self.assertTrue(self.Message._blocked_by_test_mode(empty, LISTED_A), 'Liste boşsa KK-A27: hepsi test')


@tagged('post_install', '-at_install')
class TestTestNumbersSend(TestNumbersMixin, SmsTestCase):

    def run_modes(self):
        return ('json', 'legacy_xml')

    def test_kk_c27_tekli_gonderim_listedeki_gercek_digerleri_test_iki_modda(self):
        for mode in self.run_modes():
            with self.subTest(mode=mode):
                self.listed(mode='json' if mode == 'json' else 'legacy')
                n_before = len(self.net.json_sends) + len(self.net.turatel_calls)
                listed = self.Message.send_sms('0' + LISTED_A, 'Gerçek')
                other = self.Message.send_sms('0' + OTHER, 'Test')
                self.assertEqual(listed.state, 'sent', listed.error)
                self.assertEqual(other.state, 'test')
                self.assertEqual(len(self.net.json_sends) + len(self.net.turatel_calls) - n_before, 1,
                                 'Yalnız listedeki numara için istek')

    def test_kk_c27_liste_bos_hepsi_test_kk_a27(self):
        for mode in self.run_modes():
            with self.subTest(mode=mode):
                self.listed(value=None, mode='json' if mode == 'json' else 'legacy')
                n_before = len(self.net.json_sends) + len(self.net.turatel_calls)
                msg = self.Message.send_sms('0' + LISTED_A, 'Boş liste')
                self.assertEqual(msg.state, 'test')
                self.assertEqual(len(self.net.json_sends) + len(self.net.turatel_calls), n_before)
        self.listed(value='', mode='json')
        self.assertEqual(self.Message.send_sms('0' + LISTED_A, 'Boş metin').state, 'test')

    def test_kk_c27_test_modu_kapaliysa_liste_etkisiz_herkese_gider(self):
        self.listed(test_mode='False')
        msg = self.Message.send_sms('0' + OTHER, 'Açık')
        self.assertEqual(msg.state, 'sent', msg.error)

    def test_kk_c27_kuyruk_yolu_listedekini_gonderir_digerini_test_yapar(self):
        self.listed()
        listed = self.Message.send_sms('0' + LISTED_A, 'K1', queue=True)
        other = self.Message.send_sms('0' + OTHER, 'K2', queue=True)
        self.Message._cron_send_queued()
        self.refresh_all(listed, other)
        self.assertEqual(listed.state, 'sent', listed.error)
        self.assertEqual(other.state, 'test')
        self.assertEqual(len(self.net.json_sends), 1)

    def test_kk_c27_kampanya_json_yalniz_listedeki_alicilar_gonderilir(self):
        self.listed()
        camp = self.campaign_with([LISTED_A, OTHER, LISTED_B, '5321110004'])
        msgs = self.launch(camp)
        states = self.states_by_number(msgs)
        self.assertEqual(states, {LISTED_A: 'sent', LISTED_B: 'sent', OTHER: 'test', '5321110004': 'test'})
        self.assertEqual(len(self.net.json_sends), 1, 'Tek paket, yalnız listedeki 2 alıcı')
        payload = self.net.json_sends[0]['payload']
        self.assertEqual(len(payload['personalMessages']), 2)
        sent_ids = {p['clientId'] for p in payload['personalMessages']}
        self.assertEqual(sent_ids, {self.client_id_of(m) for m in msgs if m.state == 'sent'})

    def test_kk_c27_kampanya_hic_liste_alicisi_yoksa_istek_yok(self):
        self.listed()
        msgs = self.launch(self.campaign_with([OTHER, '5321110004']))
        self.assertEqual(set(msgs.mapped('state')), {'test'})
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c27_ticari_kampanya_da_ayni_kural(self):
        self.listed()
        msgs = self.launch(self.campaign_with([LISTED_A, OTHER], message_type='commercial'))
        self.assertEqual(self.states_by_number(msgs), {LISTED_A: 'sent', OTHER: 'test'})
        self.assertEqual([c['service'] for c in self.net.json_sends], ['bulksms'])
        self.assertEqual(len(self.net.json_sends[0]['payload']['personalMessages']), 1)

    def test_kk_c27_kampanya_eski_xml_modunda_yalniz_listedekiler(self):
        self.listed(mode='legacy')
        msgs = self.launch(self.campaign_with([LISTED_A, OTHER]))
        self.assertEqual(self.states_by_number(msgs), {LISTED_A: 'sent', OTHER: 'test'})
        self.assertEqual(self.net.json_sends, [])
        self.assertTrue(self.net.turatel_calls)

    def test_kk_c27_listedeki_test_alicisi_kampanya_sayaclarina_sent_olarak_yansir(self):
        self.listed()
        camp = self.campaign_with([LISTED_A, OTHER])
        self.launch(camp)
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'done')
        self.assertEqual(camp.sent_count, 2, 'Hem gerçek hem test alıcı işlenmiş sayılır')

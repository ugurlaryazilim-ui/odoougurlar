"""Düzeltme turu #1 (07-guvenlik-AB, 06-inceleme-AB, 05-test-raporu-AB) regresyon testleri.

G-1 (kaynak kayda erişim sağlayıcıdan önce; sağlayıcıdan sonra istisna yok), Ö-1 (eski belirsiz hata kayıtları
migration'la belirsiz), G-3/D-6 (action_retry yalnız yönetici), G-5 (SmartADM hata metni maskeli), D-4 (eski XML
tanımsız yanıt belirsiz), D-7/B-1 (negatif elle sınır reddedilir), D-8 (numaraya özgü İYS hatası kampanyayı
bekletmez).
"""
import importlib.util
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from odoo.addons.sms_system.services.smartadm import SmartAdmClient, SmartAdmError
from odoo.addons.sms_system.services.turatel import TuratelClient, TuratelError

from .common import SmsHttpCase, SmsTestCase, smart_error, smart_ok
from .test_campaign import CampaignMixin
from .test_settings import SettingsMixin

MAX_RETRY = 3


# ==== S1 G-1 ====
@tagged('post_install', '-at_install')
class TestG1RecordAccess(SmsTestCase):
    """Okuma yetkisi olup yazma yetkisi olmayan kayda SMS: sağlayıcıya hiç gidilmez (eskiden SMS gidiyor,
    message_post AccessError'ı kaydı geri alıyordu: günlük sınır ve iz atlatılıyordu)."""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': 'G1 Kişi'})
        as_plain = self.partner.with_user(self.plain_user)
        as_plain.check_access('read')   # ön koşul: okuyabilir
        with self.assertRaises(AccessError, msg='ön koşul: düz kullanıcı res.partner yazamamalı'):
            as_plain.check_access('write')

    def _wizard(self, res_model, res_id, number='05321234567'):
        return self.env['sms.system.send.wizard'].with_user(self.plain_user).create(
            {'number': number, 'body': 'Oltalama http://x', 'res_model': res_model, 'res_id': res_id})

    def test_g1_send_sms_yazilamayan_kayit_saglayiciya_gitmez(self):
        with self.assertRaises(AccessError):
            self.Message.with_user(self.plain_user).send_sms(
                '05321234567', 'Merhaba', record=self.partner.with_user(self.plain_user))
        self.assertEqual(self.net.turatel_calls, [], 'yetkisiz kayıt için sağlayıcı çağrıldı')

    def test_g1_sihirbaz_yolu_tekrarlarda_0_saglayici_cagrisi(self):
        self.set_param('user_daily_limit', '2')
        for i in range(5):
            wiz = self._wizard('res.partner', self.partner.id, '0532123456%d' % i)
            with self.assertRaises(AccessError):
                wiz.action_send()
        self.assertEqual(self.net.turatel_calls, [], 'sihirbaz yetkisiz kayıtla SMS gönderdi')

    def test_g1_okunamayan_kayit_da_reddedilir(self):
        lst = self.env['sms.system.list'].create({'name': 'L'})
        camp = self.env['sms.system.campaign'].create(
            {'name': 'K', 'message_type': 'info', 'list_ids': [(6, 0, lst.ids)], 'body': 'x'})
        with self.assertRaises(AccessError):
            self._wizard('sms.system.campaign', camp.id).action_send()
        self.assertEqual(self.net.turatel_calls, [])

    def test_g1_yetkili_kayitta_not_duser(self):
        msg = self.Message.with_user(self.admin_user).send_sms(
            '05321234567', 'Merhaba', record=self.partner.with_user(self.admin_user))
        self.assertEqual(msg.state, 'sent')
        bodies = ' '.join(self.partner.message_ids.mapped('body'))
        self.assertIn('SMS', bodies)

    def test_g1_not_yazimi_patlarsa_sms_kaydi_ve_sayac_kalir(self):
        def boom(record, **kwargs):
            raise AccessError('not yazılamadı')

        partner = self.partner.with_user(self.admin_user)
        with patch.object(self.env.registry['res.partner'], 'message_post', boom), \
                self.assertLogs('odoo.addons.sms_system', level='WARNING'):
            msg = self.Message.with_user(self.admin_user).with_context(sms_manual=True).send_sms(
                '05321234567', 'Merhaba', record=partner)
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(msg.state, 'sent')
        self.env.flush_all()
        self.env.cr.execute('SELECT state, manual FROM sms_system_message WHERE id = %s', (msg.id,))
        self.assertEqual(self.env.cr.fetchone(), ('sent', True), 'SMS kaydı (günlük sınır sayacı) kalmalı')


# ==== S2 Ö-1 ====
@tagged('post_install', '-at_install')
class TestO1LegacyUncertainMigration(CampaignMixin, SmsTestCase):
    """Eski kodun ReadTimeout/ConnectionError/HTTP hata metinleriyle 'error' yazdığı kayıtlar belirsiz olur."""

    LEGACY_UNCERTAIN = (
        'Turatel sunucusuna ulaşılamadı: ReadTimeout',
        'Turatel sunucusuna ulaşılamadı: ConnectionError',
        'Turatel sunucusuna ulaşılamadı: ChunkedEncodingError',
        'Turatel HTTP 503 döndü',
        'Turatel HTTP 500 döndü',
        'Turatel HTTP 404 döndü',
    )

    def _migrate(self):
        path = Path(__file__).resolve().parents[1] / 'migrations' / '19.0.1.7.0' / 'post-migrate.py'
        spec = importlib.util.spec_from_file_location('sms_post_migrate_1_7_0_o1', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.6.0')
        self.env.invalidate_all()

    def test_o1_eski_belirsiz_metinler_tekli_ve_kampanyada_belirsiz_olur(self):
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        singles, campaign_msgs = [], []
        for i, text in enumerate(self.LEGACY_UNCERTAIN):
            singles.append(self.make_message(number='53206000%02d' % i, state='error', retry_count=1, error=text))
            contact = self.make_contact('53207000%02d' % i, lst)
            campaign_msgs.append(self.campaign_message(camp, contact, error=text))
        not_sent = self.make_message(number='5320600099', state='error', retry_count=1,
                                     error='Turatel sunucusuna ulaşılamadı: ConnectTimeout')
        no_origin = self.make_message(number='5320600098', state='error', retry_count=0,
                                      error='Mesaj başlığı (Originator) ayarlanmamış.')
        new_text = self.make_message(number='5320600097', state='error', retry_count=1,
                                     error='Turatel HTTP 503 döndü; iletilip iletilmediği belirsiz.')
        icp_before = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        self._migrate()
        for msg in singles + campaign_msgs:
            self.assertEqual((msg.state, msg.retry_count), ('uncertain', MAX_RETRY), msg.error)
        self.assertEqual((not_sent.state, not_sent.retry_count), ('error', 1), 'ConnectTimeout kesin gitmedi')
        self.assertEqual((no_origin.state, no_origin.retry_count), ('error', MAX_RETRY),
                         'başlık eksik eski kayıt başlık girilince otomatik gitmemeli')
        self.assertEqual(new_text.state, 'error', 'yalnız eski metinler eşleşmeli')
        self._migrate()   # idempotent
        self.assertEqual(singles[0].state, 'uncertain')
        icp_after = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        self.assertEqual(icp_after, icp_before, 'migration ayarlara (test_mode) dokunmamalı')
        # hiçbir yol belirsizleri yeniden göndermez; yalnız kesin gitmemiş ConnectTimeout kaydı denenir
        new_text.write({'state': 'sent'})
        self.Message._cron_retry_failed()
        with self.assertRaisesRegex(UserError, 'belirsiz'):
            camp.action_retry_errors()   # kampanyada yalnız belirsizler var: hiçbiri kuyruğa alınmaz
        self.Campaign._cron_process_queue()
        self.assertEqual(self.net.sent_numbers, [not_sent.number])


# ==== S3 G-3 ====
@tagged('post_install', '-at_install')
class TestG3RetryGroup(SmsTestCase):

    def test_g3_duz_kullanici_action_retry_access_error(self):
        msg = self.make_message(state='error', retry_count=MAX_RETRY, user_id=self.plain_user.id)
        with self.assertRaises(AccessError):
            msg.with_user(self.plain_user).action_retry()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'error')

    def test_g3_sms_yoneticisi_kuyruga_alabilir(self):
        msg = self.make_message(state='error', retry_count=MAX_RETRY, user_id=self.plain_user.id)
        msg.with_user(self.sms_manager).action_retry()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'queued')


@tagged('post_install', '-at_install')
class TestG3RetryGroupRpc(SmsHttpCase):

    def test_g3_rpc_action_retry_reddedilir_ve_durum_degismez(self):
        msg = self.make_message(state='error', retry_count=MAX_RETRY, user_id=self.plain_user.id)
        self.authenticate(self.plain_user.login, self.PW)
        body = self.call_kw('sms.system.message', 'action_retry', [[msg.id]])
        self.assertIn('error', body, 'düz kullanıcı RPC ile yeniden gönderimi kuyruğa aldı')
        self.assertIn('AccessError', str(body['error']))
        self.env.invalidate_all()
        self.assertEqual(msg.state, 'error')


# ==== S4 G-5 ====
@tagged('post_install', '-at_install')
class TestG5SmartAdmUnknownErrorMasked(SmsTestCase):

    @staticmethod
    def _client():
        return SmartAdmClient('CUST', 'iysuser', 'iyspass')

    def test_g5_bilinmeyen_kod_value_numarasi_maskeli(self):
        self.net.smart_query = smart_error(-8, -801, 'Numara 905321234567 islenemedi')
        with self.assertRaises(SmartAdmError) as ctx:
            self._client().query('5321234567')
        text = str(ctx.exception)
        self.assertNotIn('5321234567', text)
        self.assertIn('532*****67', text)
        self.assertIn('islenemedi', text)

    def test_g5_kirpma_maskeden_sonra_kismi_numara_kalmaz(self):
        text = SmartAdmClient.error_text((-8, -801), 'x' * 112 + '905321234567')
        self.assertNotRegex(text, r'\d{6,}', 'kırpılan numaranın açık kısmı metinde kaldı')

    def test_g5_log_ve_kampanya_notunda_tam_numara_yok(self):
        self.configure_sms(iys=True)
        lst = self.env['sms.system.list'].create({'name': 'L'})
        contact = self.env['sms.system.contact'].create({'mobile': '5321234567', 'list_ids': [(6, 0, lst.ids)]})
        self.net.smart_query = smart_error(-8, -801, 'MSISDN 905321234567')
        with self.assertLogs('odoo.addons.sms_system', level='WARNING') as logs:
            stats = self.env['sms.system.iys'].refresh_contacts(contact)
        joined = '\n'.join(logs.output) + '\n' + str(stats.get('error'))
        self.assertNotIn('5321234567', joined)


# ==== S5 D-4 ====
@tagged('post_install', '-at_install')
class TestD4LegacyUndefinedAnswer(SmsTestCase):

    UNDEFINED = ('', '<html><body>Bakim</body></html>', 'Bilinmeyen cevap', 'ID')

    def test_d4_tanimsiz_yanit_belirsiz(self):
        for answer in self.UNDEFINED:
            with self.subTest(answer=answer):
                self.net.turatel_script = [answer]
                with self.assertRaises(TuratelError) as ctx:
                    TuratelClient('CH1', 'user1', 'pass1').send(['5321234567'], 'x', 'ORG')
                self.assertTrue(ctx.exception.uncertain, 'HTTP 200 + tanımsız yanıt belirsiz olmalı')
                self.assertFalse(ctx.exception.retryable)

    def test_d4_sayisal_kod_kalici_hata_kalir(self):
        for answer in ('99', '-1', '30'):
            with self.subTest(answer=answer):
                self.net.turatel_script = [answer]
                with self.assertRaises(TuratelError) as ctx:
                    TuratelClient('CH1', 'user1', 'pass1').send(['5321234567'], 'x', 'ORG')
                self.assertFalse(ctx.exception.uncertain)

    def test_d4_send_sms_tanimsiz_yanit_kaydi_belirsiz_ve_tekrar_gonderilmez(self):
        self.net.turatel_script = ['<html>502 Bad Gateway</html>']
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual((msg.state, msg.retry_count), ('uncertain', MAX_RETRY))
        msg.action_retry()
        self.Message._cron_retry_failed()
        self.assertEqual(len(self.net.turatel_calls), 1)


# ==== S6 D-7 ====
@tagged('post_install', '-at_install')
class TestD7NegativeUserLimit(SettingsMixin, SmsTestCase):

    def test_d7_negatif_sinir_reddedilir_ve_parametre_degismez(self):
        self.set_param('user_daily_limit', '30')
        with self.assertRaises(UserError):
            self.save_screen(sms_user_daily_limit=-5)
        self.assertEqual(self.param('user_daily_limit'), '30', 'negatif değer sınırı kaldırmamalı')

    def test_d7_sifir_hala_sinirsiz_kaydedilir(self):
        self.save_screen(sms_user_daily_limit=0)
        self.assertEqual(self.param('user_daily_limit'), '0')


# ==== S7 D-8 ====
@tagged('post_install', '-at_install')
class TestD8NumberSpecificIysError(CampaignMixin, SmsTestCase):
    """Tek numaranın kalıcı İYS hatası (biçim geçersiz) ticari kampanyayı süresiz bekletmez."""

    BAD = '5320800001'

    def setUp(self):
        super().setUp()
        self.configure_sms(iys=True)

        def query(call):
            if call['number'] == self.BAD:
                return smart_error(-3, -114)
            return smart_ok([{'Authorization': {'Etk': {'Msisdn': {'Sms': '1'}}}}])
        self.net.smart_query = query

    def test_d8_refresh_gecersiz_numarada_durmaz_kisi_isaretlenir(self):
        lst = self.make_list()
        contacts = (self.make_contact('5320800000', lst) | self.make_contact(self.BAD, lst)
                    | self.make_contact('5320800002', lst))
        stats = self.env['sms.system.iys'].refresh_contacts(contacts)
        self.assertIsNone(stats['stopped'])
        self.assertEqual(self.net.queried, ['5320800000', self.BAD, '5320800002'])
        bad = contacts.filtered(lambda c: c.mobile == self.BAD)
        self.assertEqual(bad.iys_status, 'unknown')
        self.assertTrue(bad.iys_checked_at, 'geçersiz numara tekrar tekrar sorgulanmamalı')
        self.assertEqual(set((contacts - bad).mapped('iys_status')), {'approved'})

    def _sending_campaign(self, bad_checked_at):
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial', state='sending')
        good = self.make_contact('5320800000', lst, iys_status='approved', iys_checked_at=self.ago(days=3))
        bad = self.make_contact(self.BAD, lst, iys_status='approved', iys_checked_at=bad_checked_at)
        msgs = {'good': self.campaign_message(camp, good, state='queued'),
                'bad': self.campaign_message(camp, bad, state='queued')}
        return camp, msgs

    def test_d8_kampanya_kalanlari_gonderir_gecersizi_gerekceli_hata(self):
        camp, msgs = self._sending_campaign(self.ago(days=3))
        self.run_queue()
        self.assertEqual(self.net.sent_numbers, ['5320800000'])
        self.refresh(camp, *msgs.values())
        self.assertEqual(msgs['bad'].state, 'error')
        self.assertIn('İYS', msgs['bad'].error)
        self.assertEqual(camp.state, 'done', 'kampanya geçersiz tek numara yüzünden beklememeli')

    def test_d8_yalniz_gecersiz_numara_bayatsa_da_kampanya_ilerler(self):
        camp, msgs = self._sending_campaign(self.ago(days=3))
        msgs['good'].contact_id.iys_checked_at = self.ago(hours=1)   # taze: sorgulanmaz
        self.run_queue()
        self.assertEqual(self.net.queried, [self.BAD])
        self.assertEqual(self.net.sent_numbers, ['5320800000'])
        self.refresh(camp, *msgs.values())
        self.assertEqual(msgs['bad'].state, 'error')
        self.assertEqual(camp.state, 'done')

    def test_d8_planli_kampanya_taslaga_donmez(self):
        lst = self.make_list()
        self.make_contact('5320800000', lst, iys_status='approved', iys_checked_at=self.ago(days=3))
        self.make_contact(self.BAD, lst, iys_status='approved', iys_checked_at=self.ago(days=3))
        camp = self.make_campaign(lst, 'commercial', state='scheduled', scheduled_at=self.ago(minutes=1))
        self.run_queue()
        self.refresh(camp)
        self.assertNotEqual(camp.state, 'draft')
        self.assertEqual(self.net.sent_numbers, ['5320800000'])

    def test_d8_hesap_hatasi_hala_bekletir(self):
        camp, msgs = self._sending_campaign(self.ago(days=3))
        self.net.smart_session = smart_error(-1, -1)
        self.run_queue()
        self.assertEqual(self.net.turatel_calls, [])
        self.refresh(*msgs.values())
        self.assertEqual({m.state for m in msgs.values()}, {'queued'})

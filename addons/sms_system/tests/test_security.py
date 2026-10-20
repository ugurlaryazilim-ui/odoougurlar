"""KK-A6 (RPC ile gönderim kapalı), KK-A7 (ACL), KK-A8 (regresyon: yetkisiz kullanıcının normal akışları)."""
from odoo.exceptions import AccessError, UserError
from odoo.service.model import get_public_method
from odoo.tests.common import tagged

from .common import SmsHttpCase, SmsTestCase

PRIVATE_METHODS = (
    ('sms.system.message', 'send_sms'),
    ('sms.system.message', 'check_credit'),
    ('sms.system.iys', 'sync_report'),
    ('sms.system.iys', 'test_connection'),
    ('sms.system.iys', 'refresh_contacts'),
    ('sms.system.contact', 'upsert_numbers'),
)


@tagged('post_install', '-at_install')
class TestSecurity(SmsTestCase):

    # ── KK-A6 ──
    def test_kk_a6_ozel_metotlar_call_kw_yolunda_reddedilir(self):
        for model, method in PRIVATE_METHODS:
            with self.subTest(model=model, method=method):
                with self.assertRaises(AccessError):
                    get_public_method(self.env(user=self.plain_user)[model], method)

    def test_kk_a6_python_cagrisi_calisir_durur(self):
        """@api.private yalnız RPC'yi kapatır; terzi/vendor/sihirbazın Python çağrısı sürer."""
        self.set_param('test_mode', 'True')
        msg = self.Message.with_user(self.plain_user).send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'test')

    # ── KK-A7 ──
    def test_kk_a7_normal_kullanici_mesaj_kaydi_olusturamaz(self):
        before = self.Message.search_count([])
        for state in ('queued', 'sent', 'test', 'error'):
            with self.subTest(state=state):
                with self.assertRaises(AccessError):
                    self.Message.with_user(self.plain_user).create(
                        {'number': '5321234567', 'body': 'x', 'state': state})
        self.assertEqual(self.Message.search_count([]), before)

    def test_kk_a7_normal_kullanici_degistiremez_silemez(self):
        msg = self.make_message(state='error')
        with self.assertRaises(AccessError):
            msg.with_user(self.plain_user).write({'state': 'queued'})
        with self.assertRaises(AccessError):
            msg.with_user(self.plain_user).unlink()

    def test_kk_a7_normal_kullanici_yalniz_kendi_kaydini_okur(self):
        self.set_param('test_mode', 'True')
        mine = self.Message.with_user(self.plain_user).send_sms('05321234567', 'Benim')
        other = self.make_message(state='error', user_id=self.admin_user.id)
        visible = self.Message.with_user(self.plain_user).search([])
        self.assertIn(mine.id, visible.ids)
        self.assertNotIn(other.id, visible.ids)

    # ── KK-A8 (regresyon): "Yeni SMS" sihirbazı ──
    def _wizard_send(self, user, number='05321234567', body='Merhaba'):
        wiz = self.env['sms.system.send.wizard'].with_user(user).create({'number': number, 'body': body})
        return wiz.action_send()

    def test_kk_a8_yeni_sms_numara_basina_1_kayit_ve_user_id(self):
        self.set_param('test_mode', 'True')
        self._wizard_send(self.plain_user)
        records = self.Message.search([('number', '=', '5321234567')])
        self.assertEqual(len(records), 1)
        self.assertEqual(records.user_id, self.plain_user)
        self.assertTrue(records.manual)
        self.assertEqual(records.state, 'test')

    def test_kk_a8_yeni_sms_gunluk_siniri_sayar(self):
        self.set_param('test_mode', 'True')
        self.set_param('user_daily_limit', '1')
        self._wizard_send(self.plain_user, '05321234567')
        with self.assertRaises(UserError):
            self._wizard_send(self.plain_user, '05329999999')
        self.assertEqual(self.Message.search_count([('user_id', '=', self.plain_user.id), ('manual', '=', True)]), 1)
        # başka kullanıcının sayacı ayrı
        self._wizard_send(self.sms_manager, '05328888888')

    def test_kk_a8_canli_modda_yeni_sms_tek_saglayici_cagrisi(self):
        self._wizard_send(self.plain_user)
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(self.net.smartadm_calls, [])
        msg = self.Message.search([('number', '=', '5321234567')])
        self.assertEqual((msg.state, msg.user_id), ('sent', self.plain_user))


@tagged('post_install', '-at_install')
class TestSecurityRpc(SmsHttpCase):

    def _login(self):
        self.authenticate(self.plain_user.login, self.PW)

    # ── KK-A6 (uçtan uca RPC) ──
    def test_kk_a6_rpc_send_sms_hata_kayit_ve_saglayici_cagrisi_yok(self):
        before = self.Message.search_count([])
        self._login()
        body = self.call_kw('sms.system.message', 'send_sms', [['05321234567'], 'Merhaba'])
        self.assertIn('error', body, 'RPC ile send_sms reddedilmedi')
        self.assertNotIn('result', body)
        self.assertIn('AccessError', str(body['error']))
        self.env.invalidate_all()
        self.assertEqual(self.Message.search_count([]), before)
        self.assertEqual(self.net.calls, [], 'Sağlayıcı çağrısı yapıldı')

    def test_kk_a6_rpc_diger_ozel_metotlar_kapali(self):
        self._login()
        for model, method, args in (
                ('sms.system.message', 'check_credit', [[]]),
                ('sms.system.iys', 'sync_report', [[]]),
                ('sms.system.iys', 'test_connection', [[]]),
                ('sms.system.iys', 'refresh_contacts', [[], []]),
                ('sms.system.contact', 'upsert_numbers', [[], [{'mobile': '5321234567'}], 'rpc'])):
            with self.subTest(model=model, method=method):
                body = self.call_kw(model, method, args)
                self.assertIn('error', body, '%s.%s RPC ile reddedilmedi' % (model, method))
                self.assertNotIn('result', body)
                self.assertIn('AccessError', str(body['error']), 'özel metot erişim hatasıyla reddedilmeli')
        self.assertEqual(self.net.calls, [], 'RPC denemesi sağlayıcıya gitti')

    # ── KK-A7 (RPC) ──
    def test_kk_a7_rpc_create_access_error_ve_kayit_yok(self):
        self._login()
        for state in ('queued', 'sent'):
            with self.subTest(state=state):
                body = self.call_kw('sms.system.message', 'create',
                                    [[{'number': '5321234567', 'body': 'RPC', 'state': state}]])
                self.assertIn('error', body, 'RPC create reddedilmedi')
                self.assertIn('AccessError', str(body['error']))
        self.env.invalidate_all()
        self.assertFalse(self.Message.search([('body', '=', 'RPC')]))
        self.assertEqual(self.net.calls, [])

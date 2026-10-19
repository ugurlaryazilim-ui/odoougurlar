"""KK-A1..A5: test modu (K2) ve elle SMS sınırı ayarları."""
import importlib
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .common import SmsHttpCase, SmsTestCase


class SettingsMixin:

    @property
    def Settings(self):
        return self.env['res.config.settings']

    def save_screen(self, **vals):
        """Ayar ekranından kaydet (create + execute: gerçek ekran yolu)."""
        self.Settings.create(vals).execute()

    def screen_value(self, fname):
        return self.Settings.default_get([fname])[fname]

    def param(self, key):
        return self.icp.get_param('sms_system.' + key)

    def send_manual(self, user, number):
        return self.Message.with_user(user).with_context(sms_manual=True).send_sms(number, 'Merhaba')


@tagged('post_install', '-at_install')
class TestTestMode(SettingsMixin, SmsTestCase):

    # ── KK-A1 ──
    def test_kk_a1_kutu_bosaltilinca_parametre_false_metni_olur(self):
        for start in (None, 'True'):
            with self.subTest(baslangic=start):
                self.set_param('test_mode', start)
                self.save_screen(sms_test_mode=False)
                self.assertEqual(self.param('test_mode'), 'False')
                self.assertIs(self.Message._settings()['test_mode'], False)
                self.assertIs(self.screen_value('sms_test_mode'), False,
                              'Ekran yeniden açılınca kutu boş görünmeli')

    # ── KK-A2 ──
    def test_kk_a2_kutu_isaretlenince_true_ve_saglayici_cagrisi_yok(self):
        self.set_param('test_mode', 'False')
        self.save_screen(sms_test_mode=True)
        self.assertEqual(self.param('test_mode'), 'True')
        self.assertIs(self.screen_value('sms_test_mode'), True)
        msg = self.Message.send_sms('05321234567', 'Merhaba')
        self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    # ── KK-A3 (K2) ──
    def test_kk_a3_test_mode_enabled_yalniz_tam_false_kapatir(self):
        module = importlib.import_module('odoo.addons.sms_system.models.sms_message')
        fn = getattr(module, 'test_mode_enabled', None)
        if fn is None:
            self.fail('ARAYÜZ YOK: sms_message.test_mode_enabled(value)')
        for value in (None, False, '', 'True', 'true', '0', '1', 'false', 'FALSE', ' False', 'no', 'off'):
            self.assertTrue(fn(value), 'test_mode_enabled(%r) açık (True) olmalı' % (value,))
        self.assertFalse(fn('False'))

    def test_kk_a3_settings_parametre_degerleri(self):
        """Parametrenin yokluğu, boş değer ya da başka her değer test modu AÇIK; yalnız 'False' kapatır."""
        for value in (None, '', 'True', '0', 'false', 'FALSE', 'no'):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                self.assertIs(self.Message._settings()['test_mode'], True)
        self.set_param('test_mode', 'False')
        self.assertIs(self.Message._settings()['test_mode'], False)

    def test_kk_a3_gecersiz_degerlerde_send_sms_saglayiciya_gitmez(self):
        for value in ('0', 'false', ''):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                msg = self.Message.send_sms('05321234567', 'Merhaba')
                self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    def test_kk_a3_ayar_degismeden_kaydedilince_test_modu_acik_kalir(self):
        for start in (None, 'True'):
            with self.subTest(baslangic=start):
                self.set_param('test_mode', start)
                self.save_screen()
                self.assertIs(self.Message._settings()['test_mode'], True)
                self.assertNotEqual(self.param('test_mode'), 'False')

    def test_kk_a3_ekran_bozuk_degeri_acik_gosterir_ve_kaydetmek_kapatmaz(self):
        self.set_param('test_mode', '0')
        self.assertIs(self.screen_value('sms_test_mode'), True)
        self.save_screen()
        self.assertIs(self.Message._settings()['test_mode'], True)

    def test_kk_a3_migration_test_mode_a_dokunmaz(self):
        root = Path(__file__).resolve().parents[1] / 'migrations'
        if not root.exists():
            return
        for path in root.rglob('*.py'):
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('test_mode', source, '%s sms_system.test_mode parametresine dokunuyor' % path)

    # ── KK-A4 ──
    def test_kk_a4_yetkisiz_set_values_parametre_yazmaz(self):
        ICP = self.icp
        before = {r.key: r.value for r in ICP.search([('key', '=like', 'sms_system.%')])}
        writes = []
        real = type(ICP).set_param

        def spy(this, key, value):
            writes.append(key)
            return real(this, key, value)

        with patch.object(type(ICP), 'set_param', spy):
            with self.assertRaises(AccessError):
                self.Settings.with_user(self.plain_user).set_values()
            self.assertEqual(writes, [], 'yetkisiz set_values parametre yazdı')
        after = {r.key: r.value for r in ICP.search([('key', '=like', 'sms_system.%')])}
        self.assertEqual(after, before)

    def test_kk_a4_sms_yoneticisi_de_set_values_cagiramaz(self):
        with self.assertRaises(AccessError):
            self.Settings.with_user(self.sms_manager).set_values()

    def test_kk_a4_erp_yoneticisi_sistem_yoneticisi_degilse_set_values_cagiramaz(self):
        from odoo.tests.common import new_test_user
        erp = new_test_user(self.env, login='sms_t_erp', groups='base.group_user,base.group_erp_manager')
        before = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        with self.assertRaises(AccessError):
            self.Settings.with_user(erp).create({'sms_test_mode': False}).set_values()
        after = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        self.assertEqual(after, before)

    def test_kk_a4_sistem_yoneticisi_set_values_cagirabilir(self):
        self.set_param('test_mode', 'True')
        settings = self.Settings.with_user(self.admin_user).create({'sms_test_mode': False})
        settings.set_values()
        self.assertEqual(self.param('test_mode'), 'False')

    # ── KK-A5 ──
    def test_kk_a5_limit_sifir_ekrandan_kaydedilince_parametre_0_olur(self):
        self.save_screen(sms_user_daily_limit=0)
        self.assertEqual(self.param('user_daily_limit'), '0')
        self.assertEqual(self.screen_value('sms_user_daily_limit'), 0)

    def test_kk_a5_limit_sifir_60_elle_sms(self):
        self.set_param('test_mode', 'True')
        self.save_screen(sms_user_daily_limit=0)
        for i in range(60):
            self.send_manual(self.plain_user, '53200000%02d' % i)
        count = self.Message.search_count([('user_id', '=', self.plain_user.id), ('manual', '=', True)])
        self.assertEqual(count, 60)

    def test_kk_a5_limit_25_yirmialti_ncida_user_error(self):
        self.set_param('test_mode', 'True')
        self.save_screen(sms_user_daily_limit=25)
        self.assertEqual(self.param('user_daily_limit'), '25')
        for i in range(25):
            self.send_manual(self.plain_user, '53200000%02d' % i)
        with self.assertRaises(UserError):
            self.send_manual(self.plain_user, '5329999999')
        domain = [('user_id', '=', self.plain_user.id), ('manual', '=', True)]
        self.assertEqual(self.Message.search_count(domain), 25)
        self.assertFalse(self.Message.search([('number', '=', '5329999999')]))

    def test_kk_a5_parametre_yokken_varsayilan_50(self):
        self.set_param('test_mode', 'True')
        self.set_param('user_daily_limit', None)
        for i in range(50):
            self.send_manual(self.plain_user, '53200000%02d' % i)
        with self.assertRaises(UserError):
            self.send_manual(self.plain_user, '5329999999')

    def test_kk_a5_ekran_degeri_varsayilan_50(self):
        self.set_param('user_daily_limit', None)
        self.assertEqual(self.screen_value('sms_user_daily_limit'), 50)

    def test_kk_a5_sms_yoneticisi_sinirdan_muaf(self):
        self.set_param('test_mode', 'True')
        self.set_param('user_daily_limit', '2')
        for i in range(4):
            self.send_manual(self.sms_manager, '53200000%02d' % i)


@tagged('post_install', '-at_install')
class TestSettingsRpc(SettingsMixin, SmsHttpCase):

    # ── KK-A4 (RPC) ──
    def test_kk_a4_rpc_ile_set_values_reddedilir_ve_ayar_degismez(self):
        keys = ('test_mode', 'user_daily_limit', 'turatel_originator', 'turatel_password')
        before = {k: self.param(k) for k in keys}
        self.authenticate(self.plain_user.login, self.PW)
        for method in ('set_values', 'execute'):
            with self.subTest(method=method):
                body = self.call_kw('res.config.settings', method, [[]])
                self.assertIn('error', body, '%s RPC ile reddedilmedi' % method)
                self.assertNotIn('result', body)
                self.env.invalidate_all()
                self.assertEqual({k: self.param(k) for k in keys}, before)
        self.assertIsNotNone(self.param('turatel_password'), 'RPC sms_system parametrelerini sildi')

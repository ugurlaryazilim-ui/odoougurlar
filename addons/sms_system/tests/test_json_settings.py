"""KK-C1, C2 (+ekleri), C3 (düğmeler), C9 (JSON şifreleri), C29 (reklam seti doğrulaması), C27 (ayar alanı)."""
import re

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import SmsHttpCase, SmsTestCase, json_err

INFO_FIELDS = ('sms_json_info_user_id', 'sms_json_info_username', 'sms_json_info_password', 'sms_account_info')
COM_FIELDS = ('sms_json_com_user_id', 'sms_json_com_username', 'sms_json_com_password', 'sms_account_commercial')
SECRET_FIELDS = INFO_FIELDS[:3] + COM_FIELDS[:3]
FULL = {
    'sms_api_mode': 'json',
    'sms_json_info_user_id': '20219', 'sms_json_info_username': 'info_user', 'sms_json_info_password': 'info_pw',
    'sms_account_info': '9254',
    'sms_json_com_user_id': '20219', 'sms_json_com_username': 'com_user', 'sms_json_com_password': 'com_pw',
    'sms_account_commercial': '65672',
    'sms_single_url': 'https://platform.turatel.com/singlesms',
    'sms_bulk_url': 'https://platform.turatel.com/bulksms',
    'sms_validity_minutes': 1260,
}
ICP = {   # ekran alanı -> ICP anahtarı (tasarım §5.1)
    'sms_api_mode': 'api_mode', 'sms_json_info_user_id': 'turatel_json_info_user_id',
    'sms_json_info_username': 'turatel_json_info_username', 'sms_json_info_password': 'turatel_json_info_password',
    'sms_account_info': 'turatel_account_info', 'sms_json_com_user_id': 'turatel_json_com_user_id',
    'sms_json_com_username': 'turatel_json_com_username', 'sms_json_com_password': 'turatel_json_com_password',
    'sms_account_commercial': 'turatel_account_commercial', 'sms_single_url': 'turatel_single_url',
    'sms_bulk_url': 'turatel_bulk_url', 'sms_validity_minutes': 'turatel_validity_minutes',
    'sms_test_numbers': 'test_numbers',
}


class JsonSettingsMixin:

    @property
    def Settings(self):
        return self.env['res.config.settings']

    def require_fields(self, names):
        missing = [n for n in names if n not in self.Settings._fields]
        if missing:
            self.fail('ARAYÜZ YOK: res.config.settings alanları yok: %s' % ', '.join(sorted(missing)))

    def save_screen(self, **vals):
        self.require_fields(vals)
        self.Settings.create(vals).execute()

    def param(self, key):
        return self.icp.get_param('sms_system.' + key)

    def creds(self, which):
        value = self.Message._settings().get('json_creds', {}).get(which)
        return tuple(str(x) for x in value) if value else None

    def run_button(self, name, **create_vals):
        """Düğmeyi çalıştır; bildirim metni ve türü. Hata UserError ile gelirse onun metni döner."""
        if not hasattr(type(self.Settings), name):
            self.fail('ARAYÜZ YOK: res.config.settings.%s' % name)
        wizard = self.Settings.create(create_vals)
        try:
            action = getattr(wizard, name)()
        except UserError as e:
            return str(e), 'danger'
        params = (action or {}).get('params') or {}
        return str(params.get('message') or ''), params.get('type')


@tagged('post_install', '-at_install')
class TestJsonSettings(JsonSettingsMixin, SmsTestCase):

    # ── KK-C1 ──
    def test_kk_c1_alanlar_ve_gruplar(self):
        self.require_fields(list(FULL) + ['sms_test_numbers'])
        for name in SECRET_FIELDS:
            self.assertEqual(self.Settings._fields[name].groups, 'base.group_system', name)
        mode = self.Settings._fields['sms_api_mode']
        self.assertEqual({key for key, _label in mode.selection}, {'legacy_xml', 'json'})

    def test_kk_c1_api_modu_cozumlemesi_yok_bos_bilinmeyen_legacy(self):
        self.json_api()
        for value in (None, '', 'xml', 'JSON ', 'bilinmeyen'):
            with self.subTest(deger=value):
                self.set_param('api_mode', value)
                self.assertEqual(self.Message._settings().get('api_mode'), 'legacy_xml')
        self.set_param('api_mode', 'json')
        self.assertEqual(self.Message._settings().get('api_mode'), 'json')
        self.set_param('api_mode', 'legacy_xml')
        self.assertEqual(self.Message._settings().get('api_mode'), 'legacy_xml')

    def test_kk_c1_varsayilanlar_ayarlar_sozlugunde(self):
        """Yalnız kullanıcı adı/şifre girilmiş: userId 20219, hesaplar 9254/65672, URL'ler ve 1260 dk varsayılan."""
        self.json_api()
        for who, user_key in (('info', 'info_user'), ('com', 'com_user')):
            self.set_param('turatel_json_%s_username' % who, user_key)
            self.set_param('turatel_json_%s_password' % who, 'pw-' + who)
            self.set_param('turatel_json_%s_user_id' % who, None)
        self.set_param('turatel_account_info', None)
        self.set_param('turatel_account_commercial', None)
        for key in ('turatel_single_url', 'turatel_bulk_url', 'turatel_validity_minutes'):
            self.set_param(key, None)
        cfg = self.Message._settings()
        self.assertEqual(self.creds('info'), ('20219', 'info_user', 'pw-info', '9254'))
        self.assertEqual(self.creds('com'), ('20219', 'com_user', 'pw-com', '65672'))
        self.assertEqual(cfg['single_url'], 'https://platform.turatel.com/singlesms')
        self.assertEqual(cfg['bulk_url'], 'https://platform.turatel.com/bulksms')
        self.assertEqual(int(cfg['validity_minutes']), 1260)

    def test_kk_c1_varsayilanlar_ekranda(self):
        self.require_fields(FULL)
        for key in ICP.values():
            self.set_param(key, None)
        res = self.Settings.with_user(self.admin_user).default_get(list(FULL))
        self.assertEqual(res.get('sms_api_mode'), 'legacy_xml')
        self.assertEqual(str(res.get('sms_json_info_user_id')), '20219')
        self.assertEqual(str(res.get('sms_json_com_user_id')), '20219')
        self.assertEqual(str(res.get('sms_account_info')), '9254')
        self.assertEqual(str(res.get('sms_account_commercial')), '65672')
        self.assertEqual(int(res.get('sms_validity_minutes')), 1260)

    def test_kk_c1_ekrandan_kaydet_parametreleri_yazar_ve_eskilere_dokunmaz(self):
        old = {k: self.param(k) for k in ('turatel_channel_code', 'turatel_username', 'turatel_password',
                                          'turatel_originator', 'test_mode')}
        self.save_screen(**FULL)
        for field, key in ICP.items():
            if field in FULL:
                self.assertEqual(str(self.param(key)), str(FULL[field]), field)
        self.assertEqual({k: self.param(k) for k in old}, old, 'Eski kimlik parametreleri ve test modu değişmemeli')
        self.assertEqual(self.creds('info'), ('20219', 'info_user', 'info_pw', '9254'))
        self.assertEqual(self.creds('com'), ('20219', 'com_user', 'com_pw', '65672'))
        self.assertEqual(self.Message._settings()['api_mode'], 'json')

    def test_kk_c1_json_kimlikleri_eski_kimliklerden_ayri(self):
        self.save_screen(**FULL)
        self.assertEqual(self.param('turatel_username'), 'user1')
        self.assertEqual(self.param('turatel_password'), 'pass1')
        self.assertNotEqual(self.param('turatel_json_info_username'), self.param('turatel_username'))

    def test_kk_c1_gecerlilik_dakikasi_bos_ya_da_sifir_1260_olur(self):
        for value in (0, False):
            with self.subTest(deger=value):
                self.save_screen(**dict(FULL, sms_validity_minutes=value))
                self.assertEqual(int(self.param('turatel_validity_minutes')), 1260)
                self.assertEqual(int(self.Message._settings()['validity_minutes']), 1260)
        self.save_screen(**dict(FULL, sms_validity_minutes=300))
        self.assertEqual(int(self.Message._settings()['validity_minutes']), 300)

    def test_kk_c1_json_dan_legacy_e_donus_json_alanlarini_istemez(self):
        self.save_screen(**FULL)
        self.save_screen(sms_api_mode='legacy_xml')
        self.assertEqual(self.Message._settings()['api_mode'], 'legacy_xml')
        self.assertEqual(self.creds('info'), ('20219', 'info_user', 'info_pw', '9254'), 'Kimlikler korunur')

    # ── KK-C2 ──
    def test_kk_c2_bilgi_seti_eksikse_json_modu_kaydedilmez(self):
        self.require_fields(FULL)
        self.set_param('api_mode', 'legacy_xml')
        self.set_param('turatel_validity_minutes', '1260')
        for field in INFO_FIELDS:
            with self.subTest(eksik=field):
                with self.assertRaises(UserError):
                    self.save_screen(**dict(FULL, **{field: '', 'sms_validity_minutes': 333}))
                self.assertEqual(self.param('api_mode'), 'legacy_xml', 'Mod kaydedilmemeli')
                self.assertEqual(self.param('turatel_validity_minutes'), '1260', 'Hiçbir parametre yazılmamalı')

    def test_kk_c2_bosluk_dolu_alan_eksik_sayilir(self):
        self.set_param('api_mode', 'legacy_xml')
        with self.assertRaises(UserError):
            self.save_screen(**dict(FULL, sms_json_info_username='   '))
        self.assertEqual(self.param('api_mode'), 'legacy_xml')

    def test_kk_c2_legacy_modda_json_alanlari_bos_olabilir(self):
        self.save_screen(sms_api_mode='legacy_xml', sms_json_info_username='', sms_json_info_password='')
        self.assertEqual(self.Message._settings()['api_mode'], 'legacy_xml')

    # ── KK-C2 eki / KK-C29 (set doğrulaması) ──
    def test_kk_c29_yarim_reklam_seti_reddedilir_hicbir_sey_yazilmaz(self):
        self.require_fields(FULL)
        self.set_param('api_mode', 'legacy_xml')
        for key in ICP.values():
            if key != 'api_mode':
                self.set_param(key, None)
        base = dict(FULL, sms_json_com_user_id='20219', sms_account_commercial='65672')
        cases = {
            'yalniz-kullanici-adi': dict(base, sms_json_com_username='com_user', sms_json_com_password=''),
            'yalniz-sifre': dict(base, sms_json_com_username='', sms_json_com_password='com_pw'),
            'kullanici-adi-var-userid-yok': dict(base, sms_json_com_username='com_user',
                                                 sms_json_com_password='com_pw', sms_json_com_user_id=''),
            'kullanici-adi-var-hesap-yok': dict(base, sms_json_com_username='com_user',
                                                sms_json_com_password='com_pw', sms_account_commercial=''),
        }
        for label, vals in cases.items():
            with self.subTest(durum=label):
                with self.assertRaises(UserError):
                    self.save_screen(**dict(vals, sms_validity_minutes=444))
                self.assertEqual(self.param('api_mode'), 'legacy_xml')
                self.assertFalse(self.param('turatel_json_info_username'), 'Bilgi seti de yazılmamalı')
                self.assertFalse(self.param('turatel_validity_minutes'))

    def test_kk_c29_tamamen_bos_reklam_seti_kaydedilir(self):
        for extra in ({}, {'sms_json_com_user_id': '', 'sms_account_commercial': ''}):
            with self.subTest(ek=extra):
                self.save_screen(**dict(FULL, sms_json_com_username='', sms_json_com_password='', **extra))
                self.assertEqual(self.Message._settings()['api_mode'], 'json')
                self.assertIsNotNone(self.creds('info'))
                self.assertIsNone(self.creds('com'), 'Boş reklam seti = tanımsız (bilgi setine düşmez)')

    def test_kk_c29_ayarlar_sozlugunde_eksik_set_none(self):
        self.configure_json(commercial=False)
        cfg = self.Message._settings()
        self.assertIsNotNone(self.creds('info'))
        self.assertIsNone(cfg['json_creds']['commercial'])
        self.configure_json(commercial=True)
        self.assertIsNotNone(self.creds('com'))

    # ── KK-C3 düğmeler ──
    def test_kk_c3_dugmeler_test_modunda_da_calisir_iki_set_ayri_satir(self):
        self.configure_json(test_mode='True')
        text, _kind = self.run_button('action_turatel_accounts')
        self.assertIn('9254', text)
        self.assertIn('65672', text)
        self.assertEqual(len(self.net.tj.calls_to('Sms/GetUserAccounts')), 2, 'Her set için ayrı sorgu')
        self.assertEqual({c['user'] for c in self.net.tj.calls_to('Sms/GetUserAccounts')}, {'info_user', 'com_user'})
        self.assertTrue(self.net.tj.calls_to('Auth/GetToken', 'singlesms'),
                        'Bilgi seti için singlesms GetToken da denenir (tekli yol)')
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c3_kredi_dugmesi_iki_hesap_icin_adet_gosterir(self):
        self.configure_json(test_mode='True')
        text, _kind = self.run_button('action_turatel_credit')
        credits = self.net.tj.calls_to('Sms/GetCredit')
        self.assertEqual(sorted((c['user'], c['payload']['accountId']) for c in credits),
                         [('com_user', 65672), ('info_user', 9254)])
        digits = re.sub(r'\D', '', text)
        self.assertIn('90680', digits)
        self.assertIn('5000', digits)
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c3_baslik_listede_yoksa_uyari(self):
        self.configure_json(test_mode='True', originator='YOKBASLIK')
        text, kind = self.run_button('action_turatel_originators')
        self.assertIn('UGURLARGRUP', text)
        self.assertIn('YOKBASLIK', text)
        self.assertIn(kind, ('warning', 'danger'))

    def test_kk_c3_baslik_listede_ise_uyari_yok(self):
        self.configure_json(test_mode='True', originator='TESTBASLIK')
        text, kind = self.run_button('action_turatel_originators')
        self.assertEqual(kind, 'success', text)

    def test_kk_c3_hata_kodu_ve_mesaji_gorunur(self):
        self.configure_json(test_mode='True')
        self.net.tj.add_script('Sms/GetCredit', json_err(-5, 'Boom'))
        text, _kind = self.run_button('action_turatel_credit')
        self.assertIn('Turatel hatası -5: Boom', text)

    def test_kk_c3_ip_hatasi_acik_metin(self):
        self.configure_json(test_mode='True')
        self.net.tj.add_script('Sms/GetUserAccounts', json_err(-22, 'Unauthorized IP Address'),
                               json_err(-22, 'Unauthorized IP Address'))
        text, _kind = self.run_button('action_turatel_accounts')
        self.assertIn("Sunucu IP'si Turatel'de yetkili değil", text)

    def test_kk_c3_hesap_listede_yoksa_uyari_ve_1000_metni(self):
        """Reklam seti yanlış hesaba ayarlı (9254): hesabı görmüyor uyarısı; GetCredit -1000 açık metin."""
        self.configure_json(test_mode='True')
        self.set_param('turatel_account_commercial', '9254')
        text, kind = self.run_button('action_turatel_accounts')
        self.assertIn('görmüyor', text)
        self.assertIn(kind, ('warning', 'danger'))
        text, _kind = self.run_button('action_turatel_credit')
        self.assertIn('Hesap bu Turatel kullanıcısında tanımlı değil', text)

    def test_kk_c3_reklam_seti_bossa_ayri_satir_ve_istek_yok(self):
        self.configure_json(commercial=False, test_mode='True')
        for name in ('action_turatel_accounts', 'action_turatel_originators', 'action_turatel_credit'):
            with self.subTest(dugme=name):
                text, _kind = self.run_button(name)
                self.assertIn('Reklam kimliği tanımlı değil', text)
        self.assertNotIn('com_user', {c['user'] for c in self.net.json_calls})
        self.assertNotIn(65672, [c['payload'].get('accountId') for c in self.net.json_calls])


@tagged('post_install', '-at_install')
class TestJsonSettingsSecrets(JsonSettingsMixin, SmsTestCase):

    def seed(self):
        self.configure_json()
        self.icp.set_param('sms_system.iys_password', 'SMARTADM-SIR-2')

    # ── KK-C9 (JSON şifreleri) ──
    def test_kk_c9_default_get_yonetici_olmayana_json_sirlarini_vermez(self):
        self.seed()
        self.require_fields(SECRET_FIELDS)
        for user in (self.plain_user, self.sms_manager):
            res = self.Settings.with_user(user).default_get(list(SECRET_FIELDS) + ['sms_api_mode', 'sms_test_mode'])
            for name in SECRET_FIELDS:
                self.assertNotIn(name, res, '%s yönetici olmayana döndü' % name)
            for secret in ('info_pw', 'com_pw', 'SMARTADM-SIR-2'):
                self.assertNotIn(secret, repr(res))

    def test_kk_c9_get_values_yonetici_olmayana_json_sirlarini_vermez(self):
        self.seed()
        res = self.Settings.with_user(self.plain_user).get_values()
        for secret in ('info_pw', 'com_pw', 'info_user', 'com_user'):
            self.assertNotIn(secret, repr(res))

    def test_kk_c9_sistem_yoneticisi_iki_json_sifresini_gorur(self):
        self.seed()
        res = self.Settings.with_user(self.admin_user).default_get(list(SECRET_FIELDS))
        self.assertEqual(res.get('sms_json_info_password'), 'info_pw')
        self.assertEqual(res.get('sms_json_com_password'), 'com_pw')

    def test_kk_c9_json_ayarlari_yonetici_olmayan_tarafindan_yazilamaz(self):
        self.seed()
        self.require_fields(FULL)
        wizard = self.Settings.create(dict(FULL, sms_json_info_password='SALDIRGAN'))
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            wizard.with_user(self.plain_user).set_values()
        self.assertEqual(self.param('turatel_json_info_password'), 'info_pw')


@tagged('post_install', '-at_install')
class TestJsonSettingsRpc(JsonSettingsMixin, SmsHttpCase):

    def test_kk_c9_rpc_default_get_ve_web_read_json_sirlarini_dondurmez(self):
        self.configure_json()
        self.require_fields(SECRET_FIELDS)
        wizard = self.Settings.with_user(self.sms_manager).create({})
        self.authenticate(self.plain_user.login, self.PW)
        body = self.call_kw('res.config.settings', 'default_get', [list(SECRET_FIELDS) + ['sms_api_mode']])
        for secret in ('info_pw', 'com_pw'):
            self.assertNotIn(secret, repr(body))
        for name in SECRET_FIELDS:
            self.assertNotIn(name, body.get('result') or {})
        body = self.call_kw('res.config.settings', 'web_read', [[wizard.id]],
                            {'specification': {name: {} for name in SECRET_FIELDS}})
        for secret in ('info_pw', 'com_pw'):
            self.assertNotIn(secret, repr(body))

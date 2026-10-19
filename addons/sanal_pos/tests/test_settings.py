# -*- coding: utf-8 -*-
"""G1 / ayarlar, gruplar ve sır alanları. KK-36, KK-37 (sır alanı kısıtı), U-1, U-3, U-4.

Ayar alanı adları tasarımda sabit değil: ``config_parameter`` değerinden
bulunur (``common.field_for_param``).
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .common import SanalPosCase, field_for_param

SECRET_PARAMS = ('paratika_merchant_password', 'paratika_secret_key', 'mssql_user', 'mssql_password')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSettingsDefaults(TransactionCase):
    """Kurulum sonrası ham varsayılanlar (testin kendi ayarı yok)."""

    def _default(self, param):
        Settings = self.env['res.config.settings']
        fname = field_for_param(Settings, 'sanal_pos.%s' % param)
        self.assertTrue(fname, 'Ayar alanı yok: sanal_pos.%s' % param)
        return Settings.default_get([fname])[fname]

    def test_g1_varsayilanlar(self):
        """G1/U-4: ortam=test, süre=168, require_contact açık, ASCII kapalı, biçim '10', görünüm adı."""
        self.assertEqual(self._default('environment'), 'test')
        self.assertEqual(int(self._default('default_expiry_hours')), 168)
        self.assertTrue(self._default('require_contact'), 'U-4: e-posta ve telefon zorunlu ayarı varsayılan AÇIK olmalı')
        self.assertFalse(self._default('ascii_mode'))
        self.assertEqual(self._default('paratika_phone_format'), '10')
        self.assertEqual(self._default('mssql_view_name'), 'dbo.vw_TerziFaturalar')

    def test_kk17_link_url_gosterimi_varsayilan_kapali(self):
        """KK-17: P-2 teyidine kadar link adresi gizli (ayar varsayılan kapalı)."""
        self.assertFalse(self._default('paratika_show_link_url'))

    def test_g1_paratika_url_varsayilanlari(self):
        self.assertEqual(self._default('paratika_test_url'),
                         'https://test.paratika.com.tr/paratika/api/v2')
        self.assertTrue(str(self._default('paratika_live_url')).startswith('https://'))

    def test_g1_mssql_port_varsayilan(self):
        self.assertEqual(str(self._default('mssql_port')), '1433')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestGroups(SanalPosCase):

    def test_g1_gruplar_ve_ima(self):
        """G1: yönetici grubu kullanıcı grubunu kapsar; kullanıcı yönetici değildir."""
        self.assertTrue(self.user_sp.has_group('sanal_pos.group_sanal_pos_user'))
        self.assertFalse(self.user_sp.has_group('sanal_pos.group_sanal_pos_manager'))
        self.assertTrue(self.user_mgr.has_group('sanal_pos.group_sanal_pos_manager'))
        self.assertTrue(self.user_mgr.has_group('sanal_pos.group_sanal_pos_user'),
                        'Yönetici grubu Kullanıcı grubunu kapsamalı')
        self.assertFalse(self.user_plain.has_group('sanal_pos.group_sanal_pos_user'))

    def test_u3_sistem_yoneticisi_otomatik_sanal_pos_yoneticisi_degil(self):
        """U-3: base.group_system üyesi iade yetkisini otomatik almaz."""
        self.assertTrue(self.user_sys.has_group('base.group_system'))
        self.assertFalse(self.user_sys.has_group('sanal_pos.group_sanal_pos_manager'))
        self.assertFalse(self.user_sys.has_group('sanal_pos.group_sanal_pos_user'))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSettingsSecurity(SanalPosCase):

    def test_kk36_sir_alanlari_yalniz_base_group_system(self):
        """KK-36: API şifresi, secretKey, MSSQL kullanıcı/şifre alanları groups='base.group_system'."""
        Settings = self.env['res.config.settings']
        for param in SECRET_PARAMS:
            with self.subTest(param=param):
                fname = field_for_param(Settings, 'sanal_pos.%s' % param)
                self.assertTrue(fname, 'Ayar alanı yok: %s' % param)
                self.assertIn('base.group_system', str(Settings._fields[fname].groups))

    def test_kk36_sir_alanlari_yoneticiye_gorunmez(self):
        """KK-36: Sanal POS yöneticisinin fields_get'inde sır alanları yok (erişim hatası da güvenlidir)."""
        Settings = self.env['res.config.settings']
        names = {p: field_for_param(Settings, 'sanal_pos.%s' % p) for p in SECRET_PARAMS}
        try:
            visible = Settings.with_user(self.user_mgr).fields_get()
        except AccessError:
            visible = {}
        for param, fname in names.items():
            with self.subTest(param=param):
                self.assertNotIn(fname, visible)

    def test_kk36_sir_alanlari_sistem_yoneticisine_gorunur(self):
        Settings = self.env['res.config.settings']
        visible = Settings.with_user(self.user_sys).fields_get()
        for param in SECRET_PARAMS:
            with self.subTest(param=param):
                self.assertIn(field_for_param(Settings, 'sanal_pos.%s' % param), visible)

    def test_kk36_sirlar_config_parameter_uzerinden_yoneticiye_okunmaz(self):
        """KK-36: yönetici ir.config_parameter'dan şifre satırını okuyamaz."""
        ICP = self.env['ir.config_parameter'].with_user(self.user_mgr)
        with self.assertRaises(AccessError):
            ICP.search([('key', '=', 'sanal_pos.paratika_merchant_password')]).mapped('value')

    def test_u1_ayarlari_sanal_pos_yoneticisi_degistiremez(self):
        """U-1: ayarları yalnız base.group_system (Odoo yönetici) değiştirir."""
        Settings = self.env['res.config.settings']
        fname = field_for_param(Settings, 'sanal_pos.environment')
        with self.assertRaises(AccessError):
            Settings.with_user(self.user_mgr).create({fname: 'live'}).execute()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.environment'), 'test')

    def test_u1_ayarlari_sistem_yoneticisi_degistirebilir(self):
        Settings = self.env['res.config.settings']
        fname = field_for_param(Settings, 'sanal_pos.environment')
        Settings.with_user(self.user_sys).create({fname: 'live'}).execute()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.environment'), 'live')

    def test_g1_bildirim_ve_donus_adresi_bilgisi(self):
        """G1: ayar ekranı bildirim adresini (web.base.url + /sanal_pos/paratika/notify) gösterir."""
        Settings = self.env['res.config.settings']
        rcs = Settings.with_user(self.user_sys).create({})
        values = []
        for name, field in rcs._fields.items():
            if field.type in ('char', 'text', 'html'):
                try:
                    values.append(str(rcs[name] or ''))
                except Exception:  # alan okunamıyorsa atla
                    continue
        joined = '\n'.join(values)
        self.assertIn('https://odoo.example.com/sanal_pos/paratika/notify', joined)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSettingsRoundTrip(SanalPosCase):

    def test_u4_require_contact_ekrandan_kapatilabilir(self):
        """U-4/P-4: Odoo boolean ayarı kapatınca config_parameter satırını siler;
        varsayılan True olan ayar bu yüzden kapatılamaz hale gelmemeli."""
        self.assertTrue(self.get_setting_value('require_contact'))
        self.set_setting('require_contact', False)
        self.assertFalse(self.get_setting_value('require_contact'),
                         'Ayar kapatıldı ama yeniden okununca hâlâ açık (varsayılan True tuzağı)')
        self.set_setting('require_contact', True)
        self.assertTrue(self.get_setting_value('require_contact'))

    def test_kk15_ascii_modu_ekrandan_acilip_kapanir(self):
        self.assertFalse(self.get_setting_value('ascii_mode'))
        self.set_setting('ascii_mode', True)
        self.assertTrue(self.get_setting_value('ascii_mode'))
        self.set_setting('ascii_mode', False)
        self.assertFalse(self.get_setting_value('ascii_mode'))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCopyTailorSettings(SanalPosCase):

    def _set_tailor(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ugurlar_tailor.mssql_server', 'tailor-mssql.invalid')
        ICP.set_param('ugurlar_tailor.mssql_port', '14330')
        ICP.set_param('ugurlar_tailor.mssql_database', 'TailorDB')
        ICP.set_param('ugurlar_tailor.mssql_user', 'tailor_user')
        ICP.set_param('ugurlar_tailor.mssql_password', 'TailorPw-42')

    def test_g3_terzi_ayarlarindan_kopyala(self):
        """G3: ugurlar_tailor.mssql_* ayarları sanal_pos.mssql_* alanlarına kopyalanır."""
        self._set_tailor()
        Settings = self.env['res.config.settings']
        rcs = Settings.with_user(self.user_sys).create({})
        rcs.action_copy_tailor_mssql()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('sanal_pos.mssql_server') != 'tailor-mssql.invalid':
            rcs.execute()  # kopya sihirbaz alanlarına yazılıyorsa kaydet
        self.assertEqual(ICP.get_param('sanal_pos.mssql_server'), 'tailor-mssql.invalid')
        self.assertEqual(ICP.get_param('sanal_pos.mssql_database'), 'TailorDB')
        self.assertEqual(ICP.get_param('sanal_pos.mssql_user'), 'tailor_user')
        self.assertEqual(ICP.get_param('sanal_pos.mssql_password'), 'TailorPw-42')

    def test_g3_kopyala_yalniz_sistem_yoneticisi(self):
        self._set_tailor()
        Settings = self.env['res.config.settings']
        with self.assertRaises((AccessError, UserError)):
            rcs = Settings.with_user(self.user_mgr).create({})
            rcs.action_copy_tailor_mssql()
            rcs.execute()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.mssql_server'),
                         'mssql.invalid')

    def test_g3_terzi_ayari_yoksa_mevcut_degerler_bozulmaz(self):
        """G3: terzi parametreleri yoksa kopyalama mevcut sanal_pos ayarını boşaltmaz."""
        self.env['ir.config_parameter'].sudo().search(
            [('key', '=like', 'ugurlar_tailor.mssql_%')]).unlink()
        Settings = self.env['res.config.settings']
        rcs = Settings.with_user(self.user_sys).create({})
        try:
            rcs.action_copy_tailor_mssql()
        except UserError:
            pass  # kullanıcıya "terzi ayarı yok" demek de kabul
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.mssql_server'),
                         'mssql.invalid')
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sanal_pos.mssql_password'),
                         'MssqlPw-123!zz')

# -*- coding: utf-8 -*-
"""A5 K1/N1: res.config.settings config_parameter değerleri sistem yöneticisi olmayana default_get/get_values ile dönmez."""
from odoo.service.model import call_kw
from odoo.tests import TransactionCase, new_test_user, tagged

# QA K-1 (04-test-raporu-A5 H1) ve güvenlik K1/N1'de sızdığı görülen alanlar (kuruluysa)
_REPORTED = (
    'nebim_password', 'nebim_url', 'tailor_mssql_password', 'sync_agent_api_key', 'powerbi_api_key',
    'social_meta_app_secret', 'social_youtube_client_secret', 'social_tiktok_client_secret',
    'social_tiktok_client_key', 'social_openai_api_key', 'social_gemini_api_key',
    'ai_td_gemini_api_key', 'ai_td_openai_api_key', 'ai_studio_fal_api_key', 'ai_studio_fashn_api_key',
    'ai_studio_gemini_api_key', 'ads_gemini_api_key', 'ads_openai_api_key', 'ads_claude_api_key',
    'google_gmail_client_secret', 'microsoft_outlook_client_secret', 'twilio_account_token',
    'twilio_account_sid', 'recaptcha_private_key', 'sfu_server_key', 'tenor_api_key',
    'google_translate_api_key', 'unsplash_access_key',
)


@tagged('post_install', '-at_install', 'odoougurlar')
class TestSettingsSecretGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        RS = cls.env['res.config.settings']
        # NEDEN: ad kalıbı yok - N1 sözleşmesi "TÜM config_parameter alanları" (char/text/bool/int fark etmez)
        cls.icp_fields = {n: f for n, f in RS._fields.items() if getattr(f, 'config_parameter', None)}
        cls.char_fields = {n: f for n, f in cls.icp_fields.items() if f.type in ('char', 'text')}
        ICP = cls.env['ir.config_parameter'].sudo()
        for name, field in cls.char_fields.items():
            ICP.set_param(field.config_parameter, 'MARK_' + name)
        cls.user = new_test_user(cls.env, login='a5_plain', groups='base.group_user')
        cls.admin = new_test_user(cls.env, login='a5_admin', groups='base.group_user,base.group_system')

    def _leaks(self, values):
        return sorted(n for n in self.char_fields if values.get(n) == 'MARK_' + n)

    def test_reported_fields_are_covered(self):
        installed = [n for n in _REPORTED if n in self.env['res.config.settings']._fields]
        self.assertIn('nebim_password', installed)
        self.assertFalse(set(installed) - set(self.icp_fields), 'rapordaki alan config_parameter değil')

    def test_plain_user_gets_no_config_parameter_value(self):
        RS = self.env['res.config.settings'].with_user(self.user)
        out = call_kw(RS, 'default_get', [list(RS._fields)], {})
        self.assertEqual(self._leaks(out), [])
        # kalıba uymayan hassas değerler dahil (N1): Nebim/MSSQL sunucu, twilio sid
        self.assertFalse(set(out) & set(self.icp_fields), 'config_parameter alanı yönetici olmayana döndü')
        for name in ('nebim_url', 'twilio_account_sid', 'tailor_mssql_server'):
            self.assertNotIn(name, out)
        # yalnız istenen alanlar listesiyle de aynı
        out_few = call_kw(RS, 'default_get', [list(self.char_fields)], {})
        self.assertFalse(set(out_few) & set(self.icp_fields))

    def test_plain_user_get_values_returns_no_config_parameter_value(self):
        out = call_kw(self.env['res.config.settings'].with_user(self.user), 'get_values', [], {})
        self.assertFalse(set(out) & set(self.icp_fields))

    def test_admin_and_superuser_still_see_values(self):
        out = self.env['res.config.settings'].with_user(self.admin).default_get(list(self.char_fields))
        self.assertEqual(self._leaks(out), sorted(self.char_fields))
        out_su = self.env['res.config.settings'].sudo().default_get(['nebim_password'])
        self.assertEqual(out_su['nebim_password'], 'MARK_nebim_password')

    def test_admin_save_keeps_values(self):
        # NEDEN: sistem yöneticisi kaydı default_get'ten gelen değerlerle yazar; filtre ona uygulanmazsa
        # değerler silinmez (eksik alan çekirdekte parametreyi boşaltırdı)
        ICP = self.env['ir.config_parameter'].sudo()
        RS = self.env['res.config.settings'].with_user(self.admin)
        RS.create({}).set_values()
        for name, field in self.char_fields.items():
            if field.groups and field.groups != 'base.group_system':
                continue
            self.assertEqual(ICP.get_param(field.config_parameter), 'MARK_' + name, name)

    def test_groups_restricted_non_config_field_dropped(self):
        RS = self.env['res.config.settings']
        restricted = [n for n, f in RS._fields.items() if f.groups == 'base.group_system']
        self.assertIn('nebim_password', restricted)
        dropped = RS.with_user(self.user)._ugurlar_secret_fields()
        self.assertFalse(set(restricted) - dropped)
        self.assertFalse(set(self.icp_fields) - dropped)
        self.assertEqual(RS.with_user(self.admin)._ugurlar_drop_secrets({'nebim_password': 'x'}), {'nebim_password': 'x'})

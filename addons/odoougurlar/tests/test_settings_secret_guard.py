# -*- coding: utf-8 -*-
"""A5 K1: res.config.settings sırları sistem yöneticisi olmayana default_get/get_values ile dönmez."""
import re

from odoo.service.model import call_kw
from odoo.tests import TransactionCase, new_test_user, tagged

# NEDEN: güvenlik PoC'siyle (poc_a5_settings_sec2.py) aynı kalıp; filtre kalıbından bağımsız tutulur
_POC_RE = re.compile(r'key|secret|password|token|pass|sifre', re.I)
# QA K-1 (04-test-raporu-A5 H1) ve güvenlik K1'de sızdığı görülen alanlar (kuruluysa)
_REPORTED = (
    'nebim_password', 'tailor_mssql_password', 'sync_agent_api_key', 'powerbi_api_key',
    'social_meta_app_secret', 'social_youtube_client_secret', 'social_tiktok_client_secret',
    'social_tiktok_client_key', 'social_openai_api_key', 'social_gemini_api_key',
    'ai_td_gemini_api_key', 'ai_td_openai_api_key', 'ai_studio_fal_api_key', 'ai_studio_fashn_api_key',
    'ai_studio_gemini_api_key', 'ads_gemini_api_key', 'ads_openai_api_key', 'ads_claude_api_key',
    'google_gmail_client_secret', 'microsoft_outlook_client_secret', 'twilio_account_token',
    'recaptcha_private_key', 'sfu_server_key', 'tenor_api_key', 'google_translate_api_key',
    'unsplash_access_key',
)


@tagged('post_install', '-at_install', 'odoougurlar')
class TestSettingsSecretGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        RS = cls.env['res.config.settings']
        cls.secret_fields = {
            n: f for n, f in RS._fields.items()
            if getattr(f, 'config_parameter', None) and f.type in ('char', 'text')
            and _POC_RE.search(n + f.config_parameter)}
        ICP = cls.env['ir.config_parameter'].sudo()
        for name, field in cls.secret_fields.items():
            ICP.set_param(field.config_parameter, 'MARK_' + name)
        cls.user = new_test_user(cls.env, login='a5_plain', groups='base.group_user')
        cls.admin = new_test_user(cls.env, login='a5_admin', groups='base.group_user,base.group_system')

    def _leaks(self, values):
        return sorted(n for n in self.secret_fields if values.get(n) == 'MARK_' + n)

    def test_reported_fields_are_covered(self):
        installed = [n for n in _REPORTED if n in self.env['res.config.settings']._fields]
        self.assertIn('nebim_password', installed)
        self.assertFalse(set(installed) - set(self.secret_fields), 'rapordaki alan kalıp dışında kaldı')

    def test_plain_user_rpc_default_get_returns_no_secret(self):
        RS = self.env['res.config.settings'].with_user(self.user)
        out = call_kw(RS, 'default_get', [list(self.secret_fields)], {})
        self.assertEqual(self._leaks(out), [])
        # tüm alanlarla (ekranın istediği gibi) de sızmaz
        out_all = call_kw(RS, 'default_get', [list(RS._fields)], {})
        self.assertEqual(self._leaks(out_all), [])

    def test_plain_user_get_values_returns_no_secret(self):
        out = call_kw(self.env['res.config.settings'].with_user(self.user), 'get_values', [], {})
        self.assertEqual(self._leaks(out), [])

    def test_admin_and_superuser_still_see_values(self):
        out = self.env['res.config.settings'].with_user(self.admin).default_get(list(self.secret_fields))
        self.assertEqual(self._leaks(out), sorted(self.secret_fields))
        out_su = self.env['res.config.settings'].sudo().default_get(['nebim_password'])
        self.assertEqual(out_su['nebim_password'], 'MARK_nebim_password')

    def test_non_secret_values_still_returned(self):
        self.env['ir.config_parameter'].sudo().set_param('odoougurlar.nebim_url', 'http://nebim.example')
        out = self.env['res.config.settings'].with_user(self.user).default_get(['nebim_url'])
        self.assertEqual(out.get('nebim_url'), 'http://nebim.example')

    def test_groups_restricted_non_config_field_dropped(self):
        RS = self.env['res.config.settings']
        restricted = [n for n, f in RS._fields.items() if f.groups == 'base.group_system']
        self.assertIn('nebim_password', restricted)
        dropped = RS.with_user(self.user)._ugurlar_secret_fields()
        self.assertFalse(set(restricted) - dropped)
        self.assertEqual(RS.with_user(self.admin)._ugurlar_drop_secrets({'nebim_password': 'x'}), {'nebim_password': 'x'})

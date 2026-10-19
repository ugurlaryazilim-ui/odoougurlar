"""C6 ek testleri: düğme yetkisi/maskeleme, ticari kampanyada reklam kredisi, boş reklam setinde bilgi kampanyası."""
import re

from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .common import SmsTestCase
from .test_json_routing import RET_TEXT
from .test_json_settings import JsonSettingsMixin
from .test_json_text import TextMixin


@tagged('post_install', '-at_install')
class TestJsonButtonsExtra(JsonSettingsMixin, TextMixin, SmsTestCase):

    def test_c6_dugmeler_yalniz_sistem_yoneticisi(self):
        self.configure_json(test_mode='True')
        for name in ('action_turatel_accounts', 'action_turatel_originators', 'action_turatel_credit'):
            with self.subTest(dugme=name):
                wizard = self.Settings.create({})
                for user in (self.plain_user, self.sms_manager):
                    with self.assertRaises(AccessError):
                        getattr(wizard.with_user(user), name)()
        self.assertEqual(self.net.json_calls, [], 'Yetkisiz çağrıda Turatel isteği yapılmamalı')

    def test_c6_kimlik_hatasinda_sifre_ve_jeton_bildirimde_yok(self):
        self.configure_json(test_mode='True')
        self.set_param('turatel_json_info_password', 'YANLIS-SIFRE-123')
        self.set_param('turatel_json_com_password', 'YANLIS-SIFRE-456')
        for name in ('action_turatel_accounts', 'action_turatel_originators', 'action_turatel_credit'):
            with self.subTest(dugme=name):
                text, kind = self.run_button(name)
                self.assertEqual(kind, 'danger')
                self.assertIn('kimlik hatası', text)
                for secret in ('YANLIS-SIFRE', 'Bearer', 'info_user', 'com_user'):
                    self.assertNotIn(secret, text)

    def test_c6_ticari_kampanya_yetersiz_reklam_kredisi_uyarisi(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        self.net.tj.credits[65672] = 1     # bilgi hesabı bol (90680), reklam hesabı yetersiz
        camp = self.make_json_campaign(names=('A', 'B', 'C'), message_type='commercial', body='Indirim')
        camp.invalidate_recordset()
        _wiz, text = self.wizard_text(camp)
        self.assertIn('Kredi yetersiz: gerekli %d, kalan 1' % camp.preview_credit, text)
        self.assertEqual({(c['user'], c['payload']['accountId']) for c in self.net.tj.calls_to('Sms/GetCredit')},
                         {('com_user', 65672)}, 'Bilgi hesabının kredisi okunmamalı')

    def test_c6_reklam_seti_bosken_bilgi_kampanyasi_onaylanir_kredi_bilgi_setinden(self):
        self.configure_json(commercial=False)
        camp = self.make_json_campaign()
        wiz, text = self.wizard_text(camp)
        self.assertIn('90680', re.sub(r'\D', '', text))
        wiz.action_confirm()
        self.assertEqual(camp.state, 'sending')

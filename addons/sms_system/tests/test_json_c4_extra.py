"""C4 ek testleri: sihirbaz sayacı (KK-C24/C23), gönderim sırasında ret metni silinirse bekleme (KK-C26)."""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import SmsTestCase
from .test_json_routing import JsonModelMixin, RET_TEXT


@tagged('post_install', '-at_install')
class TestJsonC4Extra(JsonModelMixin, SmsTestCase):

    def wizard(self, body):
        return self.env['sms.system.send.wizard'].new({'number': '05321234567', 'body': body})

    def test_sihirbaz_json_modunda_402_siniri_ve_json_parcalari(self):
        self.configure_json()
        wiz = self.wizard('a' * 402)
        self.assertEqual((wiz.char_count, wiz.segments, wiz.too_long), (402, 3, False))
        wiz = self.wizard('a' * 403)
        self.assertTrue(wiz.too_long)
        wiz = self.wizard('Şöyle ğüzel')   # GSM-7 dışı harf (ğ) → UCS-2: 70 karakter tek parça
        self.assertEqual(wiz.segments, 1)

    def test_sihirbaz_eski_modda_7_parca_siniri_degismez(self):
        self.configure_json()
        self.set_param('api_mode', 'legacy_xml')
        wiz = self.wizard('a' * 403)
        self.assertFalse(wiz.too_long)   # 403 karakter = 3 parça (eski hesap)
        self.assertTrue(self.wizard('a' * 1200).too_long)

    def test_gonderim_sirasinda_ret_metni_silinirse_ticari_kuyruk_bekler(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', '')
        camp = self.make_json_campaign(message_type='commercial', body='Büyük indirim', state='sending')
        contact = self.env['sms.system.contact'].search([('list_ids', 'in', camp.list_ids.ids)], limit=1)
        msg = self.campaign_message(camp, contact, state='queued', body='Büyük indirim')
        self.run_queue()
        self.refresh_all(camp, msg)
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(camp.state, 'sending')
        self.assertEqual(self.net.json_sends, [])
        self.set_param('optout_text', RET_TEXT)   # ayar girilince sürer
        self.run_queue()
        self.refresh_all(camp, msg)
        self.assertNotEqual(msg.state, 'queued')

    def test_hatalari_yeniden_dene_ticari_ret_metni_ister(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', '')
        camp = self.make_json_campaign(message_type='commercial', state='done')
        with self.assertRaises(UserError):
            camp.action_retry_errors()

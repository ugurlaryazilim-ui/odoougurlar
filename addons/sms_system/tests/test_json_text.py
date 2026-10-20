"""KK-C20 (kredi), C21 (kişiselleştirme), C22 ({sayı}), C23 (402), C24 (parça), C25 (geçerlilik), C26 (ret metni)."""
import re

from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.tools import html2plaintext

from .common import json_err, tail10, SmsTestCase
from .test_json_routing import JsonModelMixin, NUMBER, RET_TEXT

NO_RET = 'Ticari SMS için ret metni (çıkış talimatı ve Mersis no) zorunludur'


class TextMixin(JsonModelMixin):

    def wizard_text(self, camp):
        action = camp.action_confirm_send()
        wiz = self.env['sms.system.campaign.confirm'].browse(action['res_id'])
        return wiz, html2plaintext(wiz.summary or '')

    def segments_of(self, body, names=('Ayşe',), message_type='info'):
        camp = self.make_json_campaign(names=names, body=body, message_type=message_type)
        camp.invalidate_recordset()
        return camp.preview_segments, camp.preview_credit


@tagged('post_install', '-at_install')
class TestJsonCredit(TextMixin, SmsTestCase):

    # ── KK-C20 ──
    def test_kk_c20_onay_penceresi_kalan_ve_tahmini_krediyi_gosterir(self):
        camp = self.make_json_campaign()
        _wiz, text = self.wizard_text(camp)
        self.assertIn('Kalan kredi', text)
        digits = re.sub(r'\D', '', text)
        self.assertIn('90680', digits)
        credit_calls = self.net.tj.calls_to('Sms/GetCredit')
        self.assertEqual({(c['user'], c['payload']['accountId']) for c in credit_calls}, {('info_user', 9254)},
                         'Kampanyanın hesabı için o hesabın kimlik setiyle sorgulanır')
        self.assertNotIn('Kredi yetersiz', text)
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c20_ticari_kampanya_reklam_hesabi_kredisi(self):
        self.configure_json(iys=True)
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial')
        _wiz, text = self.wizard_text(camp)
        self.assertIn('5000', re.sub(r'\D', '', text))
        credit_calls = self.net.tj.calls_to('Sms/GetCredit')
        self.assertEqual({(c['user'], c['payload']['accountId']) for c in credit_calls}, {('com_user', 65672)})

    def test_kk_c20_yetersiz_kredi_uyarisi_engellemez(self):
        self.net.tj.credits[9254] = 2
        camp = self.make_json_campaign(names=('A', 'B', 'C'), body='Duyuru')
        camp.invalidate_recordset()
        need = camp.preview_credit
        self.assertEqual(need, 3)
        wiz, text = self.wizard_text(camp)
        self.assertIn('Kredi yetersiz: gerekli %d, kalan 2' % need, text)
        wiz.action_confirm()   # engellenmez
        self.assertEqual(camp.state, 'sending')

    def test_kk_c20_yeterli_kredide_uyari_yok(self):
        camp = self.make_json_campaign(names=('A', 'B'), body='Duyuru')
        self.net.tj.credits[9254] = 2   # tam yeter: tahmini <= kalan
        _wiz, text = self.wizard_text(camp)
        self.assertNotIn('Kredi yetersiz', text)

    def test_kk_c20_kredi_alinamazsa_yazi_ve_onay_engellenmez(self):
        self.net.tj.add_script('Sms/GetCredit', json_err(-5, 'Boom'))
        camp = self.make_json_campaign()
        wiz, text = self.wizard_text(camp)
        self.assertIn('Kalan kredi alınamadı', text)
        wiz.action_confirm()
        self.assertEqual(camp.state, 'sending')

    def test_kk_c20_test_modunda_da_kredi_okunur_gonderim_yok(self):
        self.configure_json(test_mode='True')
        camp = self.make_json_campaign()
        _wiz, text = self.wizard_text(camp)
        self.assertIn('90680', re.sub(r'\D', '', text))
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c20_legacy_modda_kredi_sorgusu_yok(self):
        self.set_param('api_mode', 'legacy_xml')
        camp = self.make_json_campaign()
        _wiz, text = self.wizard_text(camp)
        self.assertIn('Tahmini kredi', text)
        self.assertEqual(self.net.json_calls, [])
        self.assertNotIn('Kalan kredi', text)


@tagged('post_install', '-at_install')
class TestJsonPersonalization(TextMixin, SmsTestCase):

    # ── KK-C21 ──
    def test_kk_c21_1200_alici_uc_istek_parametreler_sirali(self):
        lst = self.make_list('Büyük')
        names = {}
        vals = []
        for i in range(1200):
            mobile = self.new_mobile()
            names[mobile] = 'Kişi%d' % i
            vals.append({'name': names[mobile], 'mobile': mobile, 'iys_status': 'unknown',
                         'list_ids': [(6, 0, lst.ids)]})
        self.Contact.create(vals)
        camp = self.make_campaign(lst, 'info', state='draft', body='Merhaba {ad}, hoş geldiniz')
        msgs = self.launch(camp)
        self.assertEqual(len(msgs), 1200)
        self.assertEqual(set(msgs.mapped('state')), {'sent'})
        sends = self.net.json_sends
        self.assertEqual(len(sends), 3, 'ceil(1200 / 500) = 3 SendSms')
        self.assertEqual(sorted(len(c['payload']['receiverList']) for c in sends), [200, 500, 500])
        seen = 0
        for call in sends:
            payload = call['payload']
            self.assertEqual(payload['messageText'], 'Merhaba {1}, hoş geldiniz')
            self.assertNotIn('{ad}', payload['messageText'])
            receivers, personal = payload['receiverList'], payload['personalMessages']
            self.assertEqual(len(personal), len(receivers))
            for number, item in zip(receivers, personal):
                mobile = tail10(number)
                self.assertEqual(item['parameter'], [names[mobile]], 'parameter sırası receiverList ile aynı olmalı')
                seen += 1
        self.assertEqual(seen, 1200)
        for msg in msgs[:50]:
            self.assertEqual(msg.body, 'Merhaba %s, hoş geldiniz' % names[msg.number[-10:]],
                             'body kişiye özel son metni göstermeli')

    def test_kk_c21_kisisel_olmayan_kampanya_parametresiz(self):
        msgs = self.launch(self.make_json_campaign(body='Genel duyuru'))
        call = self.net.json_sends[0]
        self.assertEqual(call['payload']['messageText'], 'Genel duyuru')
        for item in call['payload']['personalMessages']:
            self.assertFalse(item.get('parameter'))
        self.assertEqual(set(msgs.mapped('body')), {'Genel duyuru'})

    def test_kk_c21_ad_birden_fazla_yerde_her_biri_1_olur(self):
        """{ad} yinelenirse her biri {1}; parametre listesi alıcı başına tek ad."""
        self.launch(self.make_json_campaign(names=('Ayşe',), body='{ad}, merhaba {ad}'))
        payload = self.net.json_sends[0]['payload']
        self.assertEqual(payload['messageText'], '{1}, merhaba {1}')
        self.assertEqual(payload['personalMessages'][0]['parameter'], ['Ayşe'])

    def test_kk_c21_guncel_ad_gonderimde_kullanilir(self):
        camp = self.make_json_campaign(names=('Eski Ad',), body='Selam {ad}')
        camp.action_send()
        self.Contact.search([('list_ids', 'in', camp.list_ids.ids)]).write({'name': 'Yeni Ad'})
        self.run_queue()
        msg = self.campaign_msgs(camp)
        self.assertEqual(self.net.json_sends[0]['payload']['personalMessages'][0]['parameter'], ['Yeni Ad'])
        self.assertEqual(msg.body, 'Selam Yeni Ad', 'Gönderilen = görünen')

    def test_kk_c21_legacy_modda_kisisellestirme_eski_gibi(self):
        self.set_param('api_mode', 'legacy_xml')
        msgs = self.launch(self.make_json_campaign(names=('Ayşe', 'Can'), body='Merhaba {ad}'))
        self.assertEqual(self.net.json_calls, [])
        self.assertEqual(sorted(msgs.mapped('body')), ['Merhaba Ayşe', 'Merhaba Can'])
        self.assertEqual(len(self.net.turatel_calls), 2, 'Eski mod: kişiye özel metin numara başı ayrı istek')

    # ── KK-C22 ──
    def test_kk_c22_kullanici_yazdigi_sayi_yer_tutucusu_onayda_user_error(self):
        for body in ('Merhaba {1}', 'Merhaba {ad} {2}', 'Kod {10} geçerli'):
            with self.subTest(govde=body):
                camp = self.make_json_campaign(body=body)
                with self.assertRaises(UserError):
                    camp.action_confirm_send()
                with self.assertRaises(UserError):
                    camp.action_send()
                self.assertEqual(camp.state, 'draft')
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c22_ad_yer_tutucusu_ve_sayisiz_metin_gecer(self):
        camp = self.make_json_campaign(body='Merhaba {ad}, 1 numaralı kampanya')
        act = camp.action_confirm_send()
        self.assertEqual(act['res_model'], 'sms.system.campaign.confirm')

    def test_kk_c22_legacy_modda_engel_yok(self):
        self.set_param('api_mode', 'legacy_xml')
        camp = self.make_json_campaign(body='Merhaba {1}')
        act = camp.action_confirm_send()
        self.assertEqual(act['res_model'], 'sms.system.campaign.confirm')


@tagged('post_install', '-at_install')
class TestJson402(TextMixin, SmsTestCase):

    # ── KK-C23 ──
    def test_kk_c23_tekli_402_asarsa_user_error_kayit_yok(self):
        before = self.Message.sudo().search_count([])
        for body in ('a' * 403, 'ş' * 500):
            with self.subTest(uzunluk=len(body)):
                with self.assertRaises(UserError):
                    self.Message.send_sms(NUMBER, body)
        self.assertEqual(self.Message.sudo().search_count([]), before, 'Kayıt oluşmamalı')
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c23_tam_402_karakter_gonderilir(self):
        msg = self.Message.send_sms(NUMBER, 'a' * 402)
        self.assertEqual(msg.state, 'sent', msg.error)
        self.assertEqual(len(self.net.json_sends[0]['payload']['messageText']), 402)

    def test_kk_c23_kuyruk_yolu_da_ayni_siniri_uygular(self):
        with self.assertRaises(UserError):
            self.Message.send_sms(NUMBER, 'a' * 403, queue=True)

    def test_kk_c23_kampanya_ornek_ad_402_asarsa_onay_engellenir(self):
        camp = self.make_json_campaign(names=('Ali',), body='a' * 395 + '{ad}')
        with self.assertRaises(UserError):
            camp.action_confirm_send()
        with self.assertRaises(UserError):
            camp.action_send()
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c23_kampanya_402_altinda_onaylanir(self):
        camp = self.make_json_campaign(names=('Ali',), body='a' * 380 + '{ad}')
        act = camp.action_confirm_send()
        self.assertEqual(act['res_model'], 'sms.system.campaign.confirm')

    def test_kk_c23_adi_uzun_alici_hata_diger_alicilar_gider(self):
        long_name = 'U' * 40
        camp = self.make_json_campaign(names=('Ali', long_name, 'Veli'), body='b' * 385 + ' {ad}')
        msgs = self.launch(camp)
        by_name = {m.contact_id.name: m for m in msgs}
        self.assertEqual(by_name['Ali'].state, 'sent', by_name['Ali'].error)
        self.assertEqual(by_name['Veli'].state, 'sent', by_name['Veli'].error)
        long_msg = by_name[long_name]
        self.assertEqual(long_msg.state, 'error')
        self.assertIn('metin 402 karakteri aşıyor', long_msg.error)
        self.assertEqual(len(self.net.json_sends), 1)
        sent = [tail10(n) for n in self.net.json_sent_receivers]
        self.assertEqual(sorted(sent), sorted([by_name['Ali'].number[-10:], by_name['Veli'].number[-10:]]))
        self.assertNotIn(long_msg.number[-10:], sent)

    def test_kk_c23_legacy_modda_402_siniri_yok(self):
        self.set_param('api_mode', 'legacy_xml')
        msg = self.Message.send_sms(NUMBER, 'a' * 403)
        self.assertEqual(msg.state, 'sent', msg.error)


@tagged('post_install', '-at_install')
class TestJsonSegments(TextMixin, SmsTestCase):

    # ── KK-C24 ──
    def test_kk_c24_gsm7_turkce_harfler_dahil_160_153(self):
        cases = ((1, 'a' * 160), (2, 'a' * 161), (2, 'ş' * 160 + 'ğ' * 146), (3, 'ş' * 307),
                 (1, 'şğıİçöü' * 22), (2, 'ğ' * 161))
        for expected, body in cases:
            with self.subTest(uzunluk=len(body), beklenen=expected):
                segments, credit = self.segments_of(body, names=('Ali',))
                self.assertEqual(segments, expected)
                self.assertEqual(credit, expected, 'preview_credit = alıcı x parça')

    def test_kk_c24_gsm7_disi_karakter_70_67(self):
        for expected, body in ((1, '中' * 70), (2, '中' * 71), (2, '中' * 134), (3, '中' * 135)):
            with self.subTest(uzunluk=len(body)):
                segments, _credit = self.segments_of(body, names=('Ali',))
                self.assertEqual(segments, expected)

    def test_kk_c24_ahmetin_160_karakterlik_turkce_metni_tek_parca(self):
        """Eski mod 155'te 2 parça sayardı; json modunda 1 parça."""
        segments, credit = self.segments_of('ş' * 160, names=('A', 'B', 'C'))
        self.assertEqual((segments, credit), (1, 3))

    def test_kk_c24_ascii_modu_calismaya_devam_eder(self):
        self.set_param('ascii_mode', 'True')
        segments, _credit = self.segments_of('ş' * 161, names=('Ali',))
        self.assertEqual(segments, 2, 'ASCII modunda ş -> s (GSM-7), 161 karakter = 2 parça')
        msg = self.Message.send_sms(NUMBER, 'ğış' * 20)
        self.assertEqual(self.net.json_sends[0]['payload']['messageText'], 'gis' * 20)
        self.assertEqual(msg.segments, 1)

    def test_kk_c24_mesaj_kaydi_parca_sayisi_json_hesabiyla(self):
        msg = self.Message.send_sms(NUMBER, 'ş' * 160)
        self.assertEqual(msg.segments, 1)
        msg = self.Message.send_sms('05321234568', '中' * 71)
        self.assertEqual(msg.segments, 2)

    def test_kk_c24_eski_modda_hesap_degismez(self):
        self.set_param('api_mode', 'legacy_xml')
        segments, credit = self.segments_of('ş' * 160, names=('Ali',))
        self.assertEqual((segments, credit), (2, 2), 'Eski mod: Türkçe harfli metin 155/149')
        msg = self.Message.send_sms(NUMBER, 'ş' * 160)
        self.assertEqual(msg.segments, 2)

    # ── KK-C25 (model düzeyi) ──
    def test_kk_c25_gecerlilik_dakikasi_ayardan_send_date_bos(self):
        self.set_param('turatel_validity_minutes', '300')
        self.Message.send_sms(NUMBER, 'Geçerlilik')
        self.launch(self.make_json_campaign())
        self.set_param('turatel_validity_minutes', None)
        self.Message.send_sms('05321234568', 'Varsayılan')
        calls = self.net.json_sends
        self.assertEqual([c['payload']['validityPeriod'] for c in calls], [300, 300, 1260])
        for call in calls:
            self.assertIsNone(call['payload'].get('sendDate'))
        # Kullanıcı kararı (20.10): gönderim sonrası paket başına tek ConfirmSms (varsayılan açık); AbortSms yok.
        # Senkron gönderim istekte onaylanmaz (iletim cron'u onaylar); kampanya paketi cron içinde onaylanır
        self.assertEqual(len(self.net.tj.calls_to('Sms/ConfirmSms')), 1)
        self.assertEqual(self.net.tj.calls_to('Sms/AbortSms'), [])


@tagged('post_install', '-at_install')
class TestJsonOptout(TextMixin, SmsTestCase):

    # ── KK-C26 ──
    def setUp(self):
        super().setUp()
        self.configure_json(iys=True)

    def assert_blocked(self, camp):
        with self.assertRaises(UserError) as ctx:
            camp.action_confirm_send()
        self.assertIn(NO_RET, str(ctx.exception))
        with self.assertRaises(UserError) as ctx:
            camp.action_send()
        self.assertIn(NO_RET, str(ctx.exception))
        self.assertEqual(camp.state, 'draft')

    def test_kk_c26_ret_metni_bos_ticari_kampanya_engellenir_iki_modda(self):
        for mode in ('json', 'legacy_xml'):
            for blank in (None, '', '   '):
                with self.subTest(mod=mode, ret=blank):
                    self.set_param('api_mode', mode)
                    self.set_param('optout_text', blank)
                    self.assert_blocked(self.make_json_campaign(message_type='commercial'))
        self.assertEqual(self.net.json_sends, [])
        self.assertEqual(self.net.turatel_calls, [])

    def test_kk_c26_planli_ticari_kampanya_ret_metni_bosken_gonderilmez(self):
        self.set_param('optout_text', RET_TEXT)
        camp = self.make_json_campaign(message_type='commercial')
        camp.action_send()
        self.assertEqual(camp.state, 'scheduled')
        self.set_param('optout_text', '')   # planlandıktan sonra ayar silindi
        self.run_queue()
        self.refresh_all(camp)
        self.assertNotEqual(camp.state, 'sending')
        self.assertEqual(self.campaign_msgs(camp).filtered(lambda m: m.state in ('sent', 'sending')).ids, [])
        self.assertEqual(self.net.json_sends, [])

    def test_kk_c26_ret_metni_varsa_gecer_ve_metne_eklenir(self):
        for mode in ('json', 'legacy_xml'):
            with self.subTest(mod=mode):
                self.set_param('api_mode', mode)
                self.set_param('optout_text', RET_TEXT)
                camp = self.make_json_campaign(message_type='commercial', body='Büyük indirim')
                act = camp.action_confirm_send()
                self.assertEqual(act['res_model'], 'sms.system.campaign.confirm')

    def test_kk_c26_bilgilendirme_ve_personel_ret_metni_istemez(self):
        self.set_param('optout_text', '')
        for message_type in ('info', 'staff'):
            camp = self.make_json_campaign(message_type=message_type)
            act = camp.action_confirm_send()
            self.assertEqual(act['res_model'], 'sms.system.campaign.confirm')

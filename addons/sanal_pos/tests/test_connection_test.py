# -*- coding: utf-8 -*-
"""Ayar ekranı "Bağlantıyı test et" düğmesi ve kimlik bilgisi boşluk temizliği."""
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import html2plaintext

from .common import (
    LIVE_URL_PREFIX, PASSWORD, TEST_URL_PREFIX, SanalPosCase, err_body, timeout_exc,
)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestConnectionTest(SanalPosCase):

    def run_test(self, user=None, **vals):
        """Ayar ekranını (kaydetmeden) açıp düğmeye basar; sonuç penceresini döndürür."""
        env = self.env(user=user or self.user_sys)
        settings = env['res.config.settings'].create(vals)
        action = settings.action_sanal_pos_test_connection()
        self.assertEqual(action['res_model'], 'sanal.pos.connection.test.wizard')
        self.assertEqual(action['target'], 'new')
        return env['sanal.pos.connection.test.wizard'].browse(action['res_id'])

    def text(self, wizard):
        return '%s\n%s' % (wizard.summary, html2plaintext(wizard.details or ''))

    # ------------------------------------------------------------ sonuçlar
    def test_basarili(self):
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'success', self.text(wiz))
        self.assertIn('Bağlantı başarılı', wiz.summary)
        self.assertEqual(self.mock.actions, ['QUERYTRANSACTION'])
        call = self.mock.last('QUERYTRANSACTION')
        self.assertTrue(call.url.startswith(TEST_URL_PREFIX))
        self.assertEqual(call.params['MERCHANT'], 'TESTMERCHANT')
        self.assertEqual(call.params['MERCHANTUSER'], 'api.user@ugurlar.test')
        self.assertEqual(call.params['MERCHANTPASSWORD'], PASSWORD)
        self.assertTrue(call.params['MERCHANTPAYMENTID'].startswith('BAGLANTI-TESTI-'))
        # Link oluşmaz
        self.assertFalse(self.env['sanal.pos.payment'].sudo().search_count([]))

    def test_kayit_bulunamadi_yaniti_da_basarili(self):
        """ERR10030 gibi bir yanıt kimliğin doğrulandığını gösterir."""
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10030', 'Transaction not found'))
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'success', self.text(wiz))
        self.assertIn('ERR10030', self.text(wiz))

    def test_err10020_kimlik_reddi(self):
        self.mock.queue('QUERYTRANSACTION', err_body(
            'ERR10020', 'Geçersiz kullanıcı bilgileri', violatorParam='MERCHANTUSER'))
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'danger')
        text = self.text(wiz)
        self.assertIn('Kimlik doğrulanamadı', text)
        self.assertIn('ERR10020', text)
        # Test ortamındayken canlı ortamı denemesi önerilir
        self.assertIn('Canlı', text)

    def test_yetki_eksik(self):
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10053', 'No API permission'))
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'danger')
        self.assertIn('API yetkisi eksik', self.text(wiz))

    def test_zaman_asimi(self):
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'danger')
        self.assertIn('ulaşılamadı', self.text(wiz))

    # ------------------------------------------------------------ yerel kontroller
    def test_eksik_alan_istek_gonderilmez(self):
        wiz = self.run_test(sanal_pos_paratika_merchant_password='  ')
        self.assertEqual(wiz.level, 'danger')
        self.assertIn('API şifresi', self.text(wiz))
        self.assertNoParatikaCalls()

    def test_bosluk_temizlenir_ve_uyarilir(self):
        wiz = self.run_test(sanal_pos_paratika_merchant_password=' %s \n' % PASSWORD,
                            sanal_pos_paratika_merchant_user='api.user@ugurlar.test ')
        self.assertEqual(wiz.level, 'warning', self.text(wiz))
        self.assertIn('boşluk', self.text(wiz))
        call = self.mock.last('QUERYTRANSACTION')
        self.assertEqual(call.params['MERCHANTPASSWORD'], PASSWORD)
        self.assertEqual(call.params['MERCHANTUSER'], 'api.user@ugurlar.test')

    def test_kaydedilmemis_canli_bilgilerle_denenir(self):
        ICP = self.env['ir.config_parameter'].sudo()
        wiz = self.run_test(sanal_pos_environment='live',
                            sanal_pos_paratika_merchant_user='live.user@ugurlar.test')
        self.assertEqual(wiz.level, 'success', self.text(wiz))
        call = self.mock.last('QUERYTRANSACTION')
        self.assertTrue(call.url.startswith(LIVE_URL_PREFIX))
        self.assertEqual(call.params['MERCHANTUSER'], 'live.user@ugurlar.test')
        # Test ayarları değiştirmez
        self.assertEqual(ICP.get_param('sanal_pos.environment'), 'test')
        self.assertEqual(ICP.get_param('sanal_pos.paratika_merchant_user'), 'api.user@ugurlar.test')

    def test_ortam_adres_uyumsuzlugu_uyarilir(self):
        wiz = self.run_test(sanal_pos_environment='live',
                            sanal_pos_paratika_live_url=TEST_URL_PREFIX)
        self.assertEqual(wiz.level, 'warning', self.text(wiz))
        self.assertIn('test sunucusunu', self.text(wiz))

    def test_gecersiz_api_adresi(self):
        wiz = self.run_test(sanal_pos_paratika_test_url='test.paratika.com.tr/api')
        self.assertEqual(wiz.level, 'danger')
        self.assertIn('API adresi geçersiz', self.text(wiz))
        self.assertNoParatikaCalls()

    def test_http_sistem_adresi_uyarilir(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'http://odoo.example.com')
        wiz = self.run_test()
        self.assertEqual(wiz.level, 'warning', self.text(wiz))
        self.assertIn('web.base.url', self.text(wiz))

    # ------------------------------------------------------------ güvenlik / log
    def test_yalniz_sistem_yoneticisi(self):
        # Yönetici ayar kaydı açamaz (çekirdek ACL); RPC ile var olan kayıtta düğme de kapalı
        settings = self.env['res.config.settings'].create({})
        with self.assertRaises(AccessError):
            settings.with_user(self.user_mgr).action_sanal_pos_test_connection()
        self.assertNoParatikaCalls()

    def test_log_yazilir_sifre_maskeli(self):
        other_password = 'EkrandakiYeniSifre-42'
        self.run_test(sanal_pos_paratika_merchant_password=other_password)
        log = self.env['sanal.pos.log'].sudo().search([], limit=1)
        self.assertEqual(log.action, 'QUERYTRANSACTION')
        self.assertFalse(log.payment_id)
        self.assertEqual(log.environment, 'test')
        self.assertNotIn(other_password, self.all_log_text())
        self.assertNotIn(PASSWORD, self.all_log_text())


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCredentialWhitespace(SanalPosCase):

    def test_kaydederken_bosluk_temizlenir(self):
        self.set_setting('paratika_merchant_password', ' %s ' % PASSWORD)
        self.set_setting('paratika_merchant_user', ' api.user@ugurlar.test\t')
        ICP = self.env['ir.config_parameter'].sudo()
        self.assertEqual(ICP.get_param('sanal_pos.paratika_merchant_password'), PASSWORD)
        self.assertEqual(ICP.get_param('sanal_pos.paratika_merchant_user'), 'api.user@ugurlar.test')

    def test_bosluklu_kayitli_sifre_yanitta_gecse_de_maskelenir(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'sanal_pos.paratika_merchant_password', ' %s ' % PASSWORD)
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10030', 'echo %s' % PASSWORD))
        payment = self.make_payment()
        self.env['sanal.pos.provider.paratika'].query_status(payment)
        self.assertNotIn(PASSWORD, self.all_log_text())

    def test_kayitli_bosluklu_deger_istekte_temizlenir(self):
        """Eski sürümde boşlukla kaydedilmiş değerler de temiz gönderilir."""
        self.env['ir.config_parameter'].sudo().set_param(
            'sanal_pos.paratika_merchant_password', '%s ' % PASSWORD)
        payment = self.make_payment(state='sending', provider_token=False)
        self.env['sanal.pos.provider.paratika'].create_link(payment)
        call = self.mock.last('PAYBYLINKPAYMENT')
        self.assertEqual(call.params['MERCHANTPASSWORD'], PASSWORD)

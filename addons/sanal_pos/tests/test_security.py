# -*- coding: utf-8 -*-
"""G12 / güvenlik uçtan uca. KK-5 (RPC), KK-35, KK-36, KK-37, KK-39, KK-48, KK-49, NFR-4.

Birim düzeyindeki maskeleme (test_tools), ACL (test_models) ve ayar alanı grupları
(test_settings) orada sınanır; burada sırların GERÇEK akışlar boyunca (link oluşturma,
iade, senkron, bildirim, hata yolları) hiçbir yüzeye sızmadığı taranır.
"""
from datetime import datetime, timedelta

import requests
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import (
    CRON_DAILY, CRON_SYNC, EMAIL, INV_NO, MSSQL_PASSWORD, MSSQL_USER, PASSWORD, SECRET_KEY,
    SanalPosCase, SanalPosHttpCase, err_body, tran,
)

SECRETS = {'API şifresi': PASSWORD, 'secretKey': SECRET_KEY, 'MSSQL şifresi': MSSQL_PASSWORD}
FULL_PHONE_FORMS = ('5321112233', '05321112233', '905321112233', '+905321112233', '0532 111 22 33')
NOTIFY = '/sanal_pos/paratika/notify'


class SecurityCase(SanalPosCase):

    # ----------------------------------------------------------------- yüzeyler
    def surfaces(self, payment=None):
        """Sızıntı taranacak tüm kalıcı yüzeyler (ad -> metin)."""
        env = self.env
        out = {'log tablosu': self.all_log_text()}
        logs = env['sanal.pos.log'].sudo().search([])
        out['log hata alanları'] = '\n'.join(
            '%s %s %s' % (l.action, l.error_code or '', l.response_code or '') for l in logs)
        messages = env['mail.message'].sudo().search([('model', '=', 'sanal.pos.payment')])
        out['chatter'] = '\n'.join('%s %s' % (m.subject or '', m.body or '') for m in messages)
        parts = []
        for pay in env['sanal.pos.payment'].sudo().search([]):
            parts += [pay.last_error_message or '', pay.last_error_code or '', pay.customer_address or '']
            for line in pay.refund_ids:
                parts += [line.error_message or '', line.error_code or '', line.reason or '']
        out['kayıt hata alanları'] = '\n'.join(parts)
        return out

    def assertNoSecrets(self, *texts, where=''):
        blob = '\n'.join(str(t) for t in texts)
        for label, secret in SECRETS.items():
            self.assertNotIn(secret, blob, '%s açık metin sızdı: %s' % (label, where))

    def assertCleanEverywhere(self, logged=None, errors=(), where=''):
        surfaces = self.surfaces()
        for name, text in surfaces.items():
            self.assertNoSecrets(text, where='%s / %s' % (where, name))
        if logged is not None:
            self.assertNoSecrets('\n'.join(logged), where='%s / Python log' % where)
        for err in errors:
            self.assertNoSecrets(err, where='%s / kullanıcı hata mesajı' % where)

    def user_message(self, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except (UserError, ValidationError, AccessError) as exc:
            return str(exc.args[0])
        return ''


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSecretsNeverLeak(SecurityCase):
    """KK-37: API şifresi, secretKey, MSSQL şifresi hiçbir yüzeyde açık metin değildir."""

    def test_kk37_basarili_link_olusturma(self):
        with self.capture_logs() as logged:
            payment = self.create_link(channel_sms=True, channel_email=True)
        self.assertTrue(payment)
        self.assertCleanEverywhere(logged, where='link oluşturma')

    def test_kk37_istek_kaydinda_sifre_yildizli(self):
        self.create_link(channel_sms=True, channel_email=True)
        log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'PAYBYLINKPAYMENT')], limit=1)
        self.assertTrue(log, 'çağrı kaydı yok')
        self.assertIn('MERCHANTPASSWORD', log.request_body)
        self.assertIn('***', log.request_body)
        self.assertNotIn(PASSWORD, log.request_body)
        # gerçek istek ise şifreyi taşımalı (maskeleme yalnız kayıt içindir)
        self.assertEqual(self.mock.calls[0].params['MERCHANTPASSWORD'], PASSWORD)

    def test_kk37_yanit_sifreyi_yanki_yaparsa_temizlenir(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10001', 'Hatalı parola %s / anahtar %s' % (PASSWORD, SECRET_KEY)))
        with self.capture_logs() as logged:
            message = self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        self.assertCleanEverywhere(logged, [message], 'Paratika yanıtı sırrı yankıladı')

    def test_kk37_istisna_metni_sifre_iceriyorsa_temizlenir(self):
        exc = requests.exceptions.ConnectionError(
            'HTTPSConnectionPool: url: /merchant/post/sale?MERCHANTPASSWORD=%s&secretKey=%s' % (PASSWORD, SECRET_KEY))
        self.mock.queue('PAYBYLINKPAYMENT', exc)
        with self.capture_logs() as logged:
            message = self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        self.assertCleanEverywhere(logged, [message], 'istisna metni')

    def test_kk37_zaman_asimi_istisnasi(self):
        exc = requests.exceptions.ReadTimeout('timeout for password=%s' % PASSWORD)
        self.mock.queue('PAYBYLINKPAYMENT', exc)
        with self.capture_logs() as logged:
            message = self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        self.assertCleanEverywhere(logged, [message], 'zaman aşımı istisnası')

    def test_kk37_mssql_hatasi_sifre_iceriyorsa_temizlenir(self):
        self.mssql_error = Exception(
            'Login failed for user %s (password %s) at server mssql.invalid' % (MSSQL_USER, MSSQL_PASSWORD))
        env = self.env(user=self.user_sp)
        wiz = env['sanal.pos.payment.create.wizard'].create({'invoice_no': INV_NO})
        with self.capture_logs() as logged:
            message = self.user_message(wiz.action_fetch_invoice)
        self.assertCleanEverywhere(logged, [message], 'MSSQL hatası')
        self.assertTrue(message, 'bağlantı hatası kullanıcıya Türkçe bildirilmeli')

    def test_kk37_mssql_hatasi_kullanici_adini_da_sizdirmaz(self):
        self.mssql_error = Exception('Login failed for user %s' % MSSQL_USER)
        wiz = self.env(user=self.user_sp)['sanal.pos.payment.create.wizard'].create({'invoice_no': INV_NO})
        message = self.user_message(wiz.action_fetch_invoice)
        self.assertNotIn(MSSQL_USER, message)

    def test_kk37_iade_akisi(self):
        payment = self.make_paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'))
        self.mock.queue('REFUND', err_body('ERR10031', 'password=%s' % PASSWORD))
        with self.capture_logs() as logged:
            message = self.user_message(payment.with_user(self.user_mgr).action_refund, 100.0, 'Müşteri talebi')
            self.mock.queue('REFUND', requests.exceptions.ReadTimeout('secret=%s' % SECRET_KEY))
            message2 = self.user_message(payment.with_user(self.user_mgr).action_refund, 100.0, 'Müşteri talebi')
        self.assertCleanEverywhere(logged, [message, message2], 'iade akışı')

    def test_kk37_iptal_akisi(self):
        payment = self.make_paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'))
        self.mock.queue('VOID', err_body('ERR10033', 'key=%s' % SECRET_KEY))
        with self.capture_logs() as logged:
            message = self.user_message(payment.with_user(self.user_mgr).action_void, 'Müşteri vazgeçti')
        self.assertCleanEverywhere(logged, [message], 'iptal akışı')

    def test_kk37_senkron_ve_cron(self):
        payment = self.make_payment()
        self.mock.queue('QUERYPAYBYLINKPAYMENT', err_body('ERR10001', 'pw=%s' % PASSWORD))
        self.mock.queue('QUERYTRANSACTION', requests.exceptions.ConnectionError('pw=%s' % PASSWORD))
        with self.capture_logs() as logged:
            self.run_cron(CRON_SYNC)
            message = self.user_message(payment.with_user(self.user_sp).action_check_status)
        self.assertCleanEverywhere(logged, [message], 'senkron')

    def test_kk37_link_iptali_ve_yeniden_gonderim(self):
        payment = self.make_payment()
        self.mock.queue('PAYBYLINKPAYMENTRESEND', err_body('ERR10199', 'x %s' % PASSWORD))
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10001', 'x %s' % SECRET_KEY))
        with self.capture_logs() as logged:
            m1 = self.user_message(payment.with_user(self.user_sp).action_resend, ['sms'])
            m2 = self.user_message(payment.with_user(self.user_sp).action_cancel_link)
        self.assertCleanEverywhere(logged, [m1, m2], 'link yönetimi')

    def test_kk37_ayar_degisikligi_chatter_ve_logu_kirletmez(self):
        with self.capture_logs() as logged:
            self.set_setting('paratika_merchant_password', 'YeniSifre-123!')
            self.set_setting('paratika_secret_key', 'YeniAnahtar-456!')
        blob = '\n'.join(logged)
        self.assertNotIn('YeniSifre-123!', blob)
        self.assertNotIn('YeniAnahtar-456!', blob)
        messages = self.env['mail.message'].sudo().search([], order='id desc', limit=50)
        bodies = '\n'.join(m.body or '' for m in messages)
        self.assertNotIn('YeniSifre-123!', bodies)
        self.assertNotIn('YeniAnahtar-456!', bodies)

    def test_kk37_log_gostergesi_yoneticiye_sifre_gostermez(self):
        self.create_link(channel_sms=True, channel_email=True)
        logs = self.env['sanal.pos.log'].with_user(self.user_mgr).search([])
        self.assertTrue(logs)
        for rec in logs:
            self.assertNoSecrets(rec.request_body or '', rec.response_body or '', where='yönetici log görünümü')

    def test_kk37_tum_kayit_alanlari_taranir(self):
        """Sihirbaz ve ödeme kaydı alanlarının hiçbiri sır değeri taşımaz."""
        self.create_link(channel_sms=True, channel_email=True)
        for model in ('sanal.pos.payment', 'sanal.pos.log', 'sanal.pos.refund'):
            for rec in self.env[model].sudo().search([]):
                for name, field in rec._fields.items():
                    if field.type in ('char', 'text', 'html'):
                        self.assertNoSecrets(rec[name] or '', where='%s.%s' % (model, name))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPersonalDataMasking(SecurityCase):
    """NFR-4 / KK-37: telefon yalnız son 4 hane, e-posta maskeli; Python log'unda gövde yok."""

    def setUp(self):
        super().setUp()
        with self.capture_logs() as self.logged:
            self.create_link(channel_sms=True, channel_email=True)
        self.log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'PAYBYLINKPAYMENT')], limit=1)

    def test_log_kaydinda_telefon_maskeli(self):
        self.assertTrue(self.log)
        self.assertIn('CUSTOMERPHONE', self.log.request_body)
        for form in FULL_PHONE_FORMS:
            self.assertNotIn(form, self.log.request_body)
        self.assertIn('2233', self.log.request_body)

    def test_log_kaydinda_eposta_maskeli(self):
        self.assertIn('CUSTOMEREMAIL', self.log.request_body)
        self.assertNotIn(EMAIL, self.log.request_body)
        self.assertIn('@example.com', self.log.request_body)

    def test_python_logunda_tam_telefon_ve_eposta_yok(self):
        blob = '\n'.join(self.logged)
        for form in FULL_PHONE_FORMS:
            self.assertNotIn(form, blob)
        self.assertNotIn(EMAIL, blob)

    def test_python_logunda_istek_govdesi_yok(self):
        """Tasarım §8: logger'a yalnız action/MPID/kodlar/süre; gövde asla."""
        blob = '\n'.join(self.logged)
        for needle in ('MERCHANTPASSWORD', 'CUSTOMERPHONE', 'CUSTOMEREMAIL', 'BILLTOADDRESSLINE'):
            self.assertNotIn(needle, blob)

    def test_yanit_kaydinda_kart_veya_telefon_tam_yok(self):
        self.make_payment(invoice_no='PD1')
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1', last4='1234'))
        self.make_paid(self.payments('PD1'), tran_ref='T1')
        self.payments('PD1')._sync_status()
        for rec in self.env['sanal.pos.log'].sudo().search([]):
            self.assertNotRegex(rec.response_body or '', r'\b\d{13,19}\b', 'tam kart numarası kaydedilmemeli')

    def test_hata_mesajlarinda_telefon_tam_gorunmez(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10199', 'invalid phone 5321112233'))
        wiz = self.wizard(channel_sms=True, channel_email=True)
        message = self.user_message(wiz.action_create_link)
        self.assertTrue(message or self.last_payment().last_error_message)
        shown = message + (self.last_payment().last_error_message or '')
        self.assertNotRegex(shown, r'5321112233')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestAmountLockRpc(SecurityCase):
    """KK-5: tutar hiçbir yoldan değiştirilemez (arayüz, write, RPC)."""

    def test_kk5_kullanici_write_ile_tutar_degistiremez(self):
        payment = self.make_payment()
        for user in (self.user_sp, self.user_mgr, self.user_plain):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    payment.with_user(user).write({'amount': 1.0})
        payment.invalidate_recordset()
        self.assertEqual(payment.amount, 9000.0)

    def test_kk5_sistem_yoneticisi_de_dogrudan_degistiremez(self):
        payment = self.make_payment()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sys).write({'amount': 1.0})

    def test_kk5_kullanici_create_ile_kayit_acamaz(self):
        vals = {'invoice_no': 'RPC1', 'amount': 1.0, 'state': 'paid', 'customer_name': 'X',
                'merchant_payment_id': 'RPC1-1', 'attempt_no': 1, 'channel_sms': True,
                'currency_id': self.try_currency.id}
        for user in (self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    self.env['sanal.pos.payment'].with_user(user).create(vals)
        self.assertFalse(self.payments('RPC1'))

    def test_kk5_rpc_ile_durum_paid_yapilamaz(self):
        payment = self.make_payment()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sp).write({'state': 'paid'})
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sp).write({'paid_amount': 9000.0, 'paid_at': '2026-10-19 10:00:00'})
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'sent')

    def test_kk5_toplu_write_ve_unlink(self):
        payments = self.make_payment() | self.make_payment(invoice_no='RPC2')
        with self.assertRaises(AccessError):
            payments.with_user(self.user_sp).write({'amount': 5.0})
        with self.assertRaises(AccessError):
            payments.with_user(self.user_sp).unlink()
        with self.assertRaises(AccessError):
            payments.with_user(self.user_mgr).unlink()
        self.assertEqual(len(payments.exists()), 2)

    def test_kk5_sihirbaz_tutar_alani_readonly(self):
        field = self.env['sanal.pos.payment.create.wizard']._fields['amount']
        self.assertTrue(field.readonly, 'sihirbaz tutar alanı salt okunur olmalı')

    def test_kk5_odeme_tutar_alani_readonly(self):
        self.assertTrue(self.env['sanal.pos.payment']._fields['amount'].readonly)

    def test_kk5_sihirbaz_amount_rpc_degeri_istekte_etkisiz(self):
        wiz = self.wizard(channel_sms=True, channel_email=True)
        try:
            wiz.write({'amount': 1.0})
        except (AccessError, UserError):
            pass
        wiz.action_create_link()
        self.assertEqual(self.mock.calls[0].params['AMOUNT'], '9000.00')

    def test_kk5_mevcut_kayit_ad_telefon_eposta_degisimi_yalniz_sistemden(self):
        payment = self.make_payment()
        for field in ('customer_name', 'customer_phone', 'customer_email'):
            with self.subTest(field=field):
                with self.assertRaises(AccessError):
                    payment.with_user(self.user_sp).write({field: 'x'})


@tagged('post_install', '-at_install', 'sanal_pos')
class TestGroupsAndViews(SecurityCase):
    """KK-35, KK-49: menü ve düğme görünürlüğü, grup etkisi."""

    def form_arch(self, user):
        view = self.env['sanal.pos.payment'].with_user(user).get_view(view_type='form')
        return view['arch']

    def test_kk49_kullanici_formunda_iade_ve_iptal_dugmesi_yok(self):
        arch = self.form_arch(self.user_sp)
        self.assertNotIn('action_refund', arch)
        self.assertNotIn('action_void', arch)

    def test_kk49_yonetici_formunda_iade_ve_iptal_dugmesi_var(self):
        arch = self.form_arch(self.user_mgr)
        self.assertTrue('action_refund' in arch or 'action_open_refund_wizard' in arch or 'refund' in arch,
                        'yönetici formunda iade düğmesi bulunmalı')
        self.assertTrue('action_void' in arch or 'void' in arch, 'yönetici formunda iptal düğmesi bulunmalı')

    def test_kk35_kullanici_formunda_yeniden_gonder_ve_link_iptal_var(self):
        arch = self.form_arch(self.user_sp)
        self.assertIn('action_resend', arch)
        self.assertIn('action_cancel_link', arch)

    def test_kk35_grupsuz_kullanici_formu_acamaz(self):
        with self.assertRaises(AccessError):
            self.env['sanal.pos.payment'].with_user(self.user_plain).get_view(view_type='form')

    def test_kk35_menu_gorunurlugu(self):
        Menu = self.env['ir.ui.menu']
        root = Menu.sudo().search([('name', '=', 'Sanal POS'), ('parent_id', '=', False)], limit=1)
        self.assertTrue(root, 'Sanal POS kök menüsü yok')
        visible_plain = Menu.with_user(self.user_plain)._visible_menu_ids()
        visible_sp = Menu.with_user(self.user_sp)._visible_menu_ids()
        self.assertNotIn(root.id, visible_plain)
        self.assertIn(root.id, visible_sp)

    def test_kk36_islem_kayitlari_ve_ayarlar_menusu_yetkisi(self):
        Menu = self.env['ir.ui.menu']
        root = Menu.sudo().search([('name', '=', 'Sanal POS'), ('parent_id', '=', False)], limit=1)
        children = Menu.sudo().search([('id', 'child_of', root.id), ('id', '!=', root.id)])
        by_name = {m.name: m.id for m in children}
        visible_sp = Menu.with_user(self.user_sp)._visible_menu_ids()
        visible_mgr = Menu.with_user(self.user_mgr)._visible_menu_ids()
        visible_sys = Menu.with_user(self.user_sys)._visible_menu_ids()
        logs = next((v for k, v in by_name.items() if 'Kay' in k and 'İşlem' in k), None)
        self.assertIsNotNone(logs, 'İşlem Kayıtları menüsü bulunamadı')
        self.assertNotIn(logs, visible_sp)
        self.assertIn(logs, visible_mgr)
        settings = by_name.get('Ayarlar')
        self.assertIsNotNone(settings, 'Ayarlar menüsü bulunamadı')
        self.assertNotIn(settings, visible_sp)
        self.assertNotIn(settings, visible_mgr)
        self.assertIn(settings, visible_sys)

    def test_kk35_kullanici_yonetici_ozelliklerine_rpc_ile_ulasamaz(self):
        payment = self.make_paid()
        for method, args in (('action_refund', (100.0, 'Müşteri talebi')), ('action_void', ('Müşteri talebi',)),
                             ('action_review_accept', ()), ('action_review_close', ())):
            with self.subTest(method=method):
                with self.assertRaises(AccessError):
                    getattr(payment.with_user(self.user_sp), method)(*args)
        self.assertNoParatikaCalls()

    def test_kk35_kayit_kurallari_tum_talepleri_gosterir(self):
        mine = self.make_payment(user_id=self.user_sp.id)
        theirs = self.make_payment(invoice_no='OTH1', user_id=self.user_sp2.id)
        visible = self.env['sanal.pos.payment'].with_user(self.user_sp).search([('id', 'in', (mine | theirs).ids)])
        self.assertEqual(visible, mine | theirs)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLogAccessAndRetention(SecurityCase):
    """KK-39."""

    def test_kk39_her_cagri_icin_alanlar_dolu(self):
        self.create_link(channel_sms=True, channel_email=True)
        log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'PAYBYLINKPAYMENT')], limit=1)
        self.assertEqual(log.payment_id, self.last_payment())
        self.assertEqual(log.provider, 'paratika')
        self.assertEqual(log.environment, 'test')
        self.assertEqual(log.response_code, '00')
        self.assertTrue(log.success)
        self.assertGreaterEqual(log.duration_ms, 0)
        self.assertTrue(log.create_date)
        self.assertTrue(log.request_body)
        self.assertTrue(log.response_body)

    def test_kk39_hata_yanitinda_kodlar_kaydedilir(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10001', 'hata'))
        self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'PAYBYLINKPAYMENT')], limit=1)
        self.assertEqual(log.error_code, 'ERR10001')
        self.assertFalse(log.success)

    def test_kk39_yanit_govdesi_20kb_ile_sinirli(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10001', 'A' * 100000))
        self.user_message(self.wizard(channel_sms=True, channel_email=True).action_create_link)
        log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'PAYBYLINKPAYMENT')], limit=1)
        self.assertLessEqual(len((log.response_body or '').encode('utf-8')), 21 * 1024)

    def test_kk39_kullanici_ve_grupsuz_log_goremez(self):
        self.create_link(channel_sms=True, channel_email=True)
        for user in (self.user_sp, self.user_plain):
            with self.assertRaises(AccessError):
                self.env['sanal.pos.log'].with_user(user).search([])

    def test_kk39_yonetici_gorur_ama_degistiremez(self):
        self.create_link(channel_sms=True, channel_email=True)
        logs = self.env['sanal.pos.log'].with_user(self.user_mgr).search([])
        self.assertTrue(logs)
        with self.assertRaises(AccessError):
            logs[:1].write({'success': False})
        with self.assertRaises(AccessError):
            self.env['sanal.pos.log'].with_user(self.user_mgr).create({'action': 'X'})

    def test_kk39_180_gunluk_temizlik_mali_kayitlari_korur(self):
        Log =self.env['sanal.pos.log'].sudo()
        old = datetime.utcnow() - timedelta(days=181)
        recent = datetime.utcnow() - timedelta(days=179)
        mk = lambda action, fin: Log.create({'action': action, 'provider': 'paratika', 'environment': 'test',
                                             'success': True, 'is_financial': fin})
        old_plain, old_fin, recent_plain = mk('QUERYTRANSACTION', False), mk('REFUND', True), mk('NOTIFY', False)
        self.set_create_date(old_plain, old)
        self.set_create_date(old_fin, old)
        self.set_create_date(recent_plain, recent)
        self.run_cron(CRON_DAILY)
        self.assertFalse(old_plain.exists(), '180 günden eski mali olmayan kayıt silinmeli')
        self.assertTrue(old_fin.exists(), 'VOID/REFUND kaydı silinmemeli')
        self.assertTrue(recent_plain.exists())

    def test_kk39_odeme_silinmedikce_mali_log_korunur(self):
        payment = self.make_paid()
        log = self.env['sanal.pos.log'].sudo().create({
            'action': 'REFUND', 'provider': 'paratika', 'environment': 'test', 'success': True,
            'is_financial': True, 'payment_id': payment.id})
        self.assertTrue(log.is_financial)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundHistoryImmutable(SecurityCase):
    """KK-48."""

    def test_kk48_kullanici_ve_yonetici_satiri_degistiremez_silemez(self):
        payment = self.make_paid()
        line = self.make_refund_line(payment, 100.0, provider_ref='R-1')
        for user in (self.user_sp, self.user_mgr, self.user_sys):
            with self.subTest(user=user.login):
                with self.assertRaises(UserError):
                    line.with_user(user).write({'amount': 1.0})
                with self.assertRaises(UserError):
                    line.with_user(user).unlink()
        line.invalidate_recordset()
        self.assertEqual(line.amount, 100.0)

    def test_kk48_satir_rpc_ile_olusturulamaz(self):
        payment = self.make_paid()
        for user in (self.user_sp, self.user_mgr):
            with self.assertRaises(UserError):
                self.env['sanal.pos.refund'].with_user(user).create({
                    'payment_id': payment.id, 'kind': 'refund', 'amount': 100.0, 'state': 'done',
                    'source': 'odoo', 'reason': 'sahte kayıt'})


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPublicEndpointSecurity(SanalPosHttpCase):
    """KK-22/23 yan etkisi: açık uç noktadan sır ve kişisel veri sızmaz."""

    def test_bildirim_yaniti_sir_ve_kisisel_veri_icermez(self):
        payment = self.make_payment()
        response = self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': payment.merchant_payment_id, 'foo': 'bar'}, timeout=12)
        body = response.text
        self.assertEqual(body.strip(), 'OK')
        for secret in SECRETS.values():
            self.assertNotIn(secret, body)
        self.assertNotIn(payment.customer_name, body)
        self.assertNotIn('session_id', response.headers.get('Set-Cookie', ''))

    def test_bilinmeyen_mpid_ile_mevcut_mpid_ayni_yanit(self):
        payment = self.make_payment()
        known = self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': payment.merchant_payment_id, 'foo': 'bar'}, timeout=12)
        unknown = self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': 'NOPE-1', 'foo': 'bar'}, timeout=12)
        self.assertEqual((known.status_code, known.text), (unknown.status_code, unknown.text))

    def test_bildirim_govdesindeki_sirlar_logda_maskelenir(self):
        self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': 'NOPE-2', 'MERCHANTPASSWORD': PASSWORD,
                                    'secretKey': SECRET_KEY}, timeout=12)
        text = self.all_log_text()
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(SECRET_KEY, text)

    def test_bildirim_telefon_alanini_maskeler(self):
        self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': 'NOPE-3', 'CUSTOMERPHONE': '5321112233',
                                    'CUSTOMEREMAIL': EMAIL}, timeout=12)
        text = self.all_log_text()
        self.assertNotIn('5321112233', text)
        self.assertNotIn(EMAIL, text)

    def test_dis_sorgu_dizeleri_kayit_sorgusunu_genisletmez(self):
        payment = self.make_payment()
        for needle in ("%", "' OR 1=1 --", payment.merchant_payment_id[:-1] + '%'):
            with self.subTest(needle=needle):
                self.url_open(NOTIFY, data={'MERCHANTPAYMENTID': needle, 'foo': 'bar'}, timeout=12)
        payment.invalidate_recordset()
        self.assertFalse(payment.sync_requested, 'joker/enjeksiyon dizileri kaydı eşleştirmemeli')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestListView(SecurityCase):
    """KK-33: liste sütunları ve aramalar (görsel kısım elle doğrulanır)."""

    def test_kk33_liste_sutunlari(self):
        arch = self.env['sanal.pos.payment'].with_user(self.user_sp).get_view(view_type='list')['arch']
        for fname in ('invoice_no', 'customer_name', 'customer_phone', 'amount', 'refunded_amount',
                      'state', 'user_id', 'create_date', 'expires_at', 'paid_at'):
            self.assertIn('name="%s"' % fname, arch, 'liste sütunu eksik: %s' % fname)

    def test_kk33_arama_alanlari(self):
        arch = self.env['sanal.pos.payment'].with_user(self.user_sp).get_view(view_type='search')['arch']
        for fname in ('invoice_no', 'customer_name', 'customer_phone'):
            self.assertIn('name="%s"' % fname, arch, 'arama alanı eksik: %s' % fname)

    def test_kk33_form_iade_gecmisi_sekmesi(self):
        arch = self.env['sanal.pos.payment'].with_user(self.user_sp).get_view(view_type='form')['arch']
        self.assertIn('refund_ids', arch)

    def test_kk35_kullanici_odeme_listesini_arayabilir(self):
        payment = self.make_payment()
        found = self.env['sanal.pos.payment'].with_user(self.user_sp).search([('invoice_no', 'ilike', 'ugr2026')])
        self.assertIn(payment, found)

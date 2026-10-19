# -*- coding: utf-8 -*-
"""G7 / yeni link sihirbazı ve oluşturma akışı.

KK-1, KK-1b (sihirbaz), KK-2, KK-3, KK-4, KK-5, KK-6..KK-11, KK-12, KK-13, KK-14,
KK-15 (bayt düzeyi), KK-16 (belirsiz), KK-17, U-4 ``require_contact`` açık/kapalı,
ve tasarım §6.1 "dış çağrıdan önce commit".

Varsayım (04-kabul-testleri.md): sihirbaz alan adları ödeme modeliyle aynıdır
(customer_name/phone/email/address/city/zip, channel_sms/email, expiry_hours, amount).
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import (
    CUSTOMER_NAME, EMAIL, INV_NO, PASSWORD, SanalPosCase, err_body, invoice_rows, ok_body,
    timeout_exc,
)

BOTH = {'channel_sms': True, 'channel_email': True}
WIZARD = 'sanal.pos.payment.create.wizard'


class LinkCase(SanalPosCase):

    def reject(self, text, **kw):
        """Sihirbazı kur + Link Oluştur; UserError beklenir, istek ve kayıt oluşmaz."""
        with self.assertRaises(UserError) as ctx:
            wiz = self.wizard(**kw)
            wiz.action_create_link()
        message = str(ctx.exception.args[0])
        if text:
            self.assertIn(text, message)
        self.assertNoParatikaCalls()
        self.assertFalse(self.payments(), 'hatalı girişte kayıt oluşmamalı')
        return message

    def link_for(self, invoice_no, **kw):
        """Başka fatura numarasıyla (aynı örnek veriyle) link oluşturur."""
        self.set_invoice(invoice_rows(invoice_no=invoice_no), invoice_no=invoice_no)
        self.wizard(invoice_no=invoice_no, **kw).action_create_link()
        return self.last_payment(invoice_no)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestWizardFetch(LinkCase):

    def test_kk1_faturayi_getir_alanlari_doldurur(self):
        wiz = self.wizard(email=None, **BOTH)
        self.assertTrue(wiz.fetched)
        self.assertEqual(wiz.amount, 9000.0)
        self.assertEqual(wiz.customer_name, CUSTOMER_NAME)
        self.assertEqual(wiz.customer_phone, '5321112233')
        self.assertFalse(wiz.customer_email)
        self.assertFalse(wiz.customer_address)
        self.assertEqual(wiz.currency_id.name, 'TRY')

    def test_kk1_tutar_alani_salt_okunur(self):
        """KK-1: tutar arayüzde düzenlenemez (readonly)."""
        self.assertTrue(self.env[WIZARD]._fields['amount'].readonly)

    def test_kk1_fetch_ayni_sihirbazi_yeniden_acar(self):
        wiz = self.env[WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO})
        action = wiz.action_fetch_invoice()
        self.assertEqual(action.get('res_model'), WIZARD)
        self.assertEqual(action.get('res_id'), wiz.id)
        self.assertEqual(action.get('target'), 'new')

    def test_kk1_fetch_kayit_olusturmaz(self):
        self.wizard(**BOTH)
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()

    def test_kk1_tutar_satir_toplami_degil(self):
        self.assertEqual(self.wizard().amount, 9000.0)

    def test_v3_varsayilan_kanal_sms(self):
        wiz = self.env[WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO})
        self.assertTrue(wiz.channel_sms)

    def test_v2_varsayilan_sure_ayardan(self):
        self.assertEqual(self.env[WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO}).expiry_hours, 168)
        self.set_setting('default_expiry_hours', 24)
        self.assertEqual(self.env[WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO}).expiry_hours, 24)

    def test_kk1b_tutarsiz_fatura_getirilemez(self):
        rows = invoice_rows()
        rows[1]['FaturaToplam'] = rows[1]['FaturaToplam'] + 1
        self.set_invoice(rows)
        with self.assertRaises(UserError) as ctx:
            self.wizard()
        self.assertIn('Fatura tutarı tutarsız; link oluşturulamaz.', str(ctx.exception.args[0]))
        self.assertFalse(self.payments())

    def test_kk2_kisa_numara(self):
        with self.assertRaises(UserError) as ctx:
            self.wizard(invoice_no='AB')
        self.assertIn('En az 3 karakter giriniz.', str(ctx.exception.args[0]))
        self.assertEqual(self.mssql_calls, [])
        self.assertFalse(self.payments('AB'))

    def test_kk2_fatura_bulunamadi(self):
        with self.assertRaises(UserError) as ctx:
            self.wizard(invoice_no='NOPE123')
        self.assertIn('Fatura bulunamadı: NOPE123', str(ctx.exception.args[0]))
        self.assertFalse(self.payments('NOPE123'))

    def test_kk3_baglanti_hatasi(self):
        self.mssql_error = Exception('login failed password=x')
        with self.assertRaises(UserError) as ctx:
            self.wizard()
        self.assertIn('Fatura sistemine ulaşılamadı, daha sonra tekrar deneyin.', str(ctx.exception.args[0]))
        self.assertFalse(self.payments())

    def test_kk4_gecersiz_tutarda_link_olusturulamaz(self):
        """KK-4: tutar geçersizse sihirbaz getirmez/oluşturma reddedilir; Paratika'ya istek yok."""
        self.set_invoice(invoice_rows(total='0'))
        with self.assertRaises(UserError):
            self.wizard().action_create_link()
        self.assertNoParatikaCalls()
        self.set_invoice(invoice_rows(currency='USD'))
        with self.assertRaises(UserError):
            self.wizard().action_create_link()
        self.assertNoParatikaCalls()
        self.assertFalse(self.payments())

    def test_kk4_getirilmemis_sihirbazda_link_olusturulamaz(self):
        """KK-4 'düğme pasif': getirme yapılmamış sihirbaz ödeme isteği başlatamaz."""
        wiz = self.wizard(fetch=False, customer_name=CUSTOMER_NAME, customer_phone='5321112233',
                          customer_email=EMAIL, **BOTH)
        self.assertFalse(wiz.fetched)
        with self.assertRaises(UserError):
            wiz.action_create_link()
        self.assertNoParatikaCalls()
        self.assertFalse(self.payments())

    def test_kk34_sihirbazda_test_uyarisi_bayragi(self):
        self.assertTrue(self.wizard().is_test)
        self.set_setting('environment', 'live')
        self.assertFalse(self.wizard().is_test)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCreateSuccess(LinkCase):

    def test_kk12_kk13_basarili_olusturma(self):
        wiz = self.wizard(**BOTH)
        action = wiz.action_create_link()
        # istek
        self.assertEqual(self.mock.actions, ['PAYBYLINKPAYMENT'])
        # kayıt
        payment = self.last_payment()
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.provider_token, 'TOK-001')
        self.assertEqual(payment.merchant_payment_id, '%s-1' % INV_NO)
        self.assertEqual(payment.attempt_no, 1)
        self.assertEqual(payment.amount, 9000.0)
        self.assertEqual(payment.currency_id.name, 'TRY')
        self.assertEqual(payment.invoice_no, INV_NO)
        self.assertEqual(payment.customer_code, 'M-555')
        self.assertEqual(payment.customer_name, CUSTOMER_NAME)
        self.assertEqual(payment.customer_phone, '5321112233')
        self.assertEqual(payment.customer_email, EMAIL)
        self.assertTrue(payment.channel_sms and payment.channel_email)
        self.assertEqual(payment.expiry_hours, 168)
        self.assertEqual(payment.environment, 'test')
        self.assertEqual(payment.user_id, self.user_sp)
        self.assertEqual(payment.create_uid, self.user_sp)
        self.assertEqual(payment.provider, 'paratika')
        self.assertEqual(payment.invoice_source, 'nebim')
        # zamanlar (KK-13)
        self.assertTrue(payment.sent_at)
        self.assertLess(abs(fields.Datetime.now() - payment.sent_at), timedelta(minutes=2))
        self.assertEqual(payment.expires_at - payment.sent_at, timedelta(hours=168))
        # chatter (KK-13)
        self.assertIn('Link oluşturuldu, SMS+E-posta ile gönderildi', self.chatter(payment))
        # sihirbaz ödeme formunu açar
        self.assertEqual(action.get('res_model'), 'sanal.pos.payment')
        self.assertEqual(action.get('res_id'), payment.id)

    def test_kk12_gonderilen_istek_alanlari(self):
        self.wizard(**BOTH).action_create_link()
        p = self.mock.calls[0].params
        self.assertEqual(p['AMOUNT'], '9000.00')
        self.assertEqual(p['MERCHANTPAYMENTID'], '%s-1' % INV_NO)
        self.assertEqual(p['NOTIFICATIONCHANNELS'], 'EMAIL,SMS')
        self.assertEqual(p['SESSIONEXPIRY'], '168h')
        self.assertEqual(p['CUSTOMERNAME'], CUSTOMER_NAME)
        self.assertEqual(p['CUSTOMERPHONE'], '5321112233')
        self.assertEqual(p['CUSTOMEREMAIL'], EMAIL)

    def test_kk13_kanal_notlari(self):
        sms = self.link_for('CHN1', channel_sms=True, channel_email=False)
        mail = self.link_for('CHN2', channel_sms=False, channel_email=True)
        self.assertIn('Link oluşturuldu, SMS ile gönderildi', self.chatter(sms))
        self.assertIn('Link oluşturuldu, E-posta ile gönderildi', self.chatter(mail))
        self.assertEqual(self.mock.calls[0].params['NOTIFICATIONCHANNELS'], 'SMS')
        self.assertEqual(self.mock.calls[1].params['NOTIFICATIONCHANNELS'], 'EMAIL')

    def test_kk13_sure_secimi(self):
        payment = self.link_for('EXP1', expiry_hours=24, **BOTH)
        self.assertEqual(payment.expiry_hours, 24)
        self.assertEqual(payment.expires_at - payment.sent_at, timedelta(hours=24))
        self.assertEqual(self.mock.calls[0].params['SESSIONEXPIRY'], '24h')

    def test_kk15_turkce_ad_istek_baytlarinda(self):
        name = 'Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'
        self.wizard(customer_name=name, **BOTH).action_create_link()
        call = self.mock.calls[0]
        self.assertEqual(call.params['CUSTOMERNAME'], name)
        self.assertIn('charset=utf-8', call.content_type.lower())
        self.assertEqual(self.last_payment().customer_name, name)

    def test_kk15_ascii_modu(self):
        self.set_setting('ascii_mode', True)
        name = 'Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'
        self.wizard(customer_name=name, **BOTH).action_create_link()
        self.assertEqual(self.mock.calls[0].params['CUSTOMERNAME'], 'Cagri Sukru Ogut IGUSOC igusoc')

    def test_kk11_bosluk_temizligi(self):
        self.wizard(customer_name='  ÇAĞRI   ŞAHİN ', customer_address='  Atatürk   Cad.  No:5 ', **BOTH
                    ).action_create_link()
        payment = self.last_payment()
        self.assertEqual(payment.customer_name, 'ÇAĞRI ŞAHİN')
        self.assertEqual(payment.customer_address, 'Atatürk Cad. No:5')
        self.assertEqual(self.mock.calls[0].params['CUSTOMERNAME'], 'ÇAĞRI ŞAHİN')
        self.assertEqual(self.mock.calls[0].params['BILLTOADDRESSLINE'], 'Atatürk Cad. No:5')

    def test_kk17_link_adresi_gizli(self):
        self.wizard(**BOTH).action_create_link()
        self.assertFalse(self.last_payment().link_url)

    def test_tutar_sihirbazdan_degistirilse_de_kaynak_tutari_gider(self):
        """KK-5: sihirbaz kaydı RPC ile bozulsa da istek ve kayıt faturadaki tutarı kullanır."""
        wiz = self.wizard(**BOTH)
        wiz.sudo().write({'amount': 1.0})
        wiz.action_create_link()
        self.assertEqual(self.mock.calls[0].params['AMOUNT'], '9000.00')
        self.assertEqual(self.last_payment().amount, 9000.0)

    def test_tutar_sihirbaza_yazilamasa_bile_degisirse_hata(self):
        """§6.1: link oluştururken fatura yeniden okunur; tutar değiştiyse istek gitmez."""
        wiz = self.wizard(**BOTH)
        self.set_invoice(invoice_rows(total='7000.00'))
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_link()
        self.assertIn('Fatura tutarı değişti', str(ctx.exception.args[0]))
        self.assertNoParatikaCalls()
        self.assertFalse(self.payments())

    def test_olusturmada_fatura_yeniden_okunur(self):
        wiz = self.wizard(**BOTH)
        before = len(self.mssql_calls)
        wiz.action_create_link()
        self.assertGreater(len(self.mssql_calls), before, 'oluşturma sırasında fatura yeniden okunmalı')

    def test_olusturmada_fatura_tutarsizlasirsa_hata(self):
        wiz = self.wizard(**BOTH)
        rows = invoice_rows()
        rows[0]['FaturaToplam'] = rows[0]['FaturaToplam'] + 5
        self.set_invoice(rows)
        with self.assertRaises(UserError):
            wiz.action_create_link()
        self.assertNoParatikaCalls()

    def test_tr_disi_para_birimine_donerse_hata(self):
        wiz = self.wizard(**BOTH)
        self.set_invoice(invoice_rows(currency='EUR'))
        with self.assertRaises(UserError):
            wiz.action_create_link()
        self.assertNoParatikaCalls()


@tagged('post_install', '-at_install', 'sanal_pos')
class TestChangeNotes(LinkCase):

    def lines(self, payment):
        return [l for l in self.chatter(payment).splitlines() if 'faturadan gelen değer' in l]

    def test_kk5_ad_degisikligi_notu(self):
        payment = self.create_link(customer_name='MEHMET YILMAZ', **BOTH)
        match = [l for l in self.lines(payment) if 'ÇAĞRI ŞAHİN' in l and 'MEHMET YILMAZ' in l]
        self.assertTrue(match, self.chatter(payment))
        self.assertIn('girilen', match[0])
        self.assertEqual(payment.customer_name, 'MEHMET YILMAZ')
        self.assertEqual(payment.source_name, CUSTOMER_NAME)

    def test_kk5_telefon_degisikligi_notu(self):
        payment = self.create_link(customer_phone='0555 444 33 22', **BOTH)
        self.assertTrue([l for l in self.lines(payment) if '5554443322' in l], self.chatter(payment))
        self.assertEqual(payment.customer_phone, '5554443322')
        self.assertIn(payment.source_phone, ('5321112233', '0532 111 22 33'))

    def test_kk5_eposta_degisikligi_notu(self):
        self.set_invoice(invoice_rows(MusteriEposta='eski@example.com'))
        payment = self.create_link(email='yeni@example.com', **BOTH)
        match = [l for l in self.lines(payment) if 'eski@example.com' in l and 'yeni@example.com' in l]
        self.assertTrue(match, self.chatter(payment))
        self.assertEqual(payment.source_email, 'eski@example.com')

    def test_kk5_degismeyen_alan_icin_not_yok(self):
        payment = self.create_link(**BOTH)
        self.assertFalse([l for l in self.lines(payment) if 'ÇAĞRI' in l or '5321112233' in l],
                         self.chatter(payment))

    def test_kk5_ham_kaynak_degerleri_saklanir(self):
        payment = self.create_link(customer_name='BAŞKA AD', **BOTH)
        self.assertEqual(payment.source_name, CUSTOMER_NAME)
        self.assertEqual(payment.customer_name, 'BAŞKA AD')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPhoneAndChannels(LinkCase):

    def test_kk6_bes_yazim_biciminin_hepsi_normalize(self):
        forms = ('0532 111 22 33', '+90 532 111 22 33', '905321112233', '(532) 111-22-33', '5321112233')
        for i, raw in enumerate(forms):
            with self.subTest(raw=raw):
                inv = 'PHN%d' % i
                payment = self.link_for(inv, customer_phone=raw, **BOTH)
                self.assertEqual(payment.customer_phone, '5321112233')
                self.assertEqual(self.mock.calls[-1].params['CUSTOMERPHONE'], '5321112233')

    def test_kk6_gecersiz_numaralar_reddedilir(self):
        for raw in ('0212 111 22 33', '532111223', '53211122334'):
            with self.subTest(raw=raw):
                self.mock.calls.clear()
                with self.assertRaises(UserError):
                    self.wizard(customer_phone=raw, **BOTH).action_create_link()
                self.assertNoParatikaCalls()
        self.assertFalse(self.payments())

    def test_kk7_sms_icin_bos_telefon(self):
        msg = self.reject('SMS için geçerli bir cep telefonu girin (5XX XXX XX XX).',
                          customer_phone='', channel_sms=True, channel_email=False)
        self.assertIn('5XX XXX XX XX', msg)

    def test_kk7_sms_icin_gecersiz_telefon(self):
        self.reject('SMS için geçerli bir cep telefonu girin (5XX XXX XX XX).',
                    customer_phone='0212 111 22 33', channel_sms=True, channel_email=False)

    def test_kk8_eposta_kanali_icin_bos_eposta(self):
        msg = self.reject('', customer_email='', email='', channel_sms=False, channel_email=True)
        self.assertIn('e-posta', msg.lower())

    def test_kk8_gecersiz_eposta_sms_kanalinda_da_reddedilir(self):
        """KK-8: kanal ne olursa olsun girilen e-posta geçersizse reddedilir."""
        self.set_setting('require_contact', False)
        for bad in ('abc', 'abc@', '@example.com', 'a b@example.com'):
            with self.subTest(bad=bad):
                msg = self.reject('', customer_email=bad, channel_sms=True, channel_email=False)
                self.assertIn('e-posta', msg.lower())

    def test_kk8_eposta_64_karakter_siniri(self):
        ok64 = 'a' * 59 + '@b.co'
        self.reject('64', customer_email='a' * 60 + '@b.co', **BOTH)
        payment = self.link_for('MAIL64', customer_email=ok64, **BOTH)
        self.assertEqual(payment.customer_email, ok64)

    def test_kk9_kanal_secilmemis(self):
        self.reject('En az bir gönderim kanalı seçin.', channel_sms=False, channel_email=False)

    def test_kk9_kanal_hatasi_istek_gitmez(self):
        with self.assertRaises(UserError):
            self.wizard(channel_sms=False, channel_email=False).action_create_link()
        self.assertEqual(self.mock.count(), 0)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRequireContact(LinkCase):
    """U-4 / P-4: e-posta ve telefon zorunluluğu ayarı (varsayılan açık)."""

    def test_acikken_sms_icin_eposta_da_zorunlu(self):
        msg = self.reject('', customer_email='', email='', channel_sms=True, channel_email=False)
        self.assertIn('e-posta', msg.lower())

    def test_acikken_eposta_kanali_icin_telefon_da_zorunlu(self):
        msg = self.reject('', customer_phone='', channel_sms=False, channel_email=True)
        self.assertIn('telefon', msg.lower())

    def test_kapaliyken_sms_icin_eposta_gerekmez(self):
        self.set_setting('require_contact', False)
        payment = self.link_for('RC1', customer_email='', email='', channel_sms=True, channel_email=False)
        self.assertEqual(payment.state, 'sent')
        self.assertNotIn('CUSTOMEREMAIL', self.mock.calls[-1].params)

    def test_kapaliyken_eposta_kanali_icin_telefon_gerekmez(self):
        self.set_setting('require_contact', False)
        payment = self.link_for('RC2', customer_phone='', channel_sms=False, channel_email=True)
        self.assertEqual(payment.state, 'sent')
        self.assertNotIn('CUSTOMERPHONE', self.mock.calls[-1].params)

    def test_kapaliyken_kanalin_kendi_alani_yine_zorunlu(self):
        self.set_setting('require_contact', False)
        self.reject('SMS için geçerli bir cep telefonu girin', customer_phone='',
                    channel_sms=True, channel_email=False)

    def test_acikken_ikisi_de_dolu_olunca_gecer(self):
        payment = self.create_link(channel_sms=True, channel_email=False)
        self.assertEqual(payment.state, 'sent')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLengthLimits(LinkCase):

    def test_kk10_asan_alan_reddedilir_sinir_belirtilir(self):
        cases = {
            'customer_name': ('128', 129),
            'customer_address': ('255', 256),
            'customer_city': ('32', 33),
            'customer_zip': ('16', 17),
        }
        for field, (limit, size) in cases.items():
            with self.subTest(field=field):
                self.mock.calls.clear()
                with self.assertRaises(UserError) as ctx:
                    self.wizard(**{field: 'a' * size}, **BOTH).action_create_link()
                self.assertIn(limit, str(ctx.exception.args[0]))
                self.assertNoParatikaCalls()
        self.assertFalse(self.payments())

    def test_kk10_sinirdaki_degerler_kabul_edilir(self):
        payment = self.create_link(
            customer_name='a' * 128, customer_address='b' * 255, customer_city='c' * 32,
            customer_zip='d' * 16, **BOTH)
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(len(payment.customer_name), 128)
        self.assertEqual(len(payment.customer_address), 255)

    def test_kk10_sessiz_kirpma_yok(self):
        with self.assertRaises(UserError):
            self.wizard(customer_name='x' * 200, **BOTH).action_create_link()
        self.assertFalse(self.payments())

    def test_sure_araligi(self):
        for hours in (0, -3, 169):
            with self.subTest(hours=hours):
                with self.assertRaises(UserError):
                    self.wizard(expiry_hours=hours, **BOTH).action_create_link()
                self.assertNoParatikaCalls()
        for hours in (1, 168):
            self.link_for('HRS%d' % hours, expiry_hours=hours, **BOTH)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestProviderOutcomes(LinkCase):

    def test_kk14_hata_durumu_ve_mesaj(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10199', 'invalid phone'))
        wiz = self.wizard(**BOTH)
        wiz.action_create_link()          # raise yok: sonuç kayda yazılır
        payment = self.last_payment()
        self.assertEqual(payment.state, 'error')
        self.assertEqual(payment.last_error_code, 'ERR10199')
        self.assertIn('telefon', payment.last_error_message.lower())
        self.assertFalse(payment.provider_token)

    def test_kk14_hata_kullaniciya_gosterilir(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10233', 'invalid mail'))
        result = self.wizard(**BOTH).action_create_link()
        shown = str(result) + (self.last_payment().last_error_message or '')
        self.assertIn('e-posta', shown.lower())

    def test_kk14_yeniden_deneme_yeni_sonek(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10233', 'invalid mail'))
        self.wizard(**BOTH).action_create_link()
        self.wizard(**BOTH).action_create_link()
        first, second = self.payments()
        self.assertEqual((first.state, second.state), ('error', 'sent'))
        self.assertEqual(second.attempt_no, 2)
        self.assertEqual(second.merchant_payment_id, '%s-2' % INV_NO)
        self.assertEqual(self.mock.calls[1].params['MERCHANTPAYMENTID'], '%s-2' % INV_NO)
        # üçüncü: ikincisi açık olduğu için engellenir; kapatınca -3
        second.sudo().write({'state': 'link_cancelled'})
        self.wizard(**BOTH).action_create_link()
        self.assertEqual(self.last_payment().merchant_payment_id, '%s-3' % INV_NO)

    def test_kk14_bilinen_hata_kodlari_kullaniciya_turkce(self):
        for code in ('ERR10199', 'ERR10233', 'ERR10244', 'ERR10012', 'ERR10020', 'ERR10048'):
            with self.subTest(code=code):
                inv = 'ERC%s' % code[-3:]
                self.mock.queue('PAYBYLINKPAYMENT', err_body(code, 'English only message'))
                payment = self.link_for(inv, **BOTH)
                self.assertEqual(payment.state, 'error')
                self.assertEqual(payment.last_error_code, code)
                self.assertNotIn('English only message', payment.last_error_message)

    def test_kk16_zaman_asimi_belirsiz(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        result = self.wizard(**BOTH).action_create_link()
        payment = self.last_payment()
        self.assertEqual(payment.state, 'unknown')
        shown = str(result) + (payment.last_error_message or '') + self.chatter(payment)
        self.assertIn('Paratika yanıt vermedi; link oluşmuş olabilir. Durum otomatik kontrol edilecek.', shown)

    def test_kk16_belirsizde_uzlastirma_tetiklenir(self):
        before = self.cron_trigger_count()
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        self.wizard(**BOTH).action_create_link()
        self.assertGreater(self.cron_trigger_count(), before, 'cron tetiği (en geç 10 dk) kurulmalı')

    def test_kk16_belirsizde_yeni_link_olusamaz(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        self.wizard(**BOTH).action_create_link()
        self.mock.calls.clear()
        with self.assertRaises(UserError) as ctx:
            self.wizard(**BOTH).action_create_link()
        self.assertIn('açık bir link var', str(ctx.exception.args[0]))
        self.assertNoParatikaCalls()
        self.assertEqual(len(self.payments()), 1)

    def test_basarili_yanit_tokensiz_gonderildi_olmaz(self):
        self.mock.queue('PAYBYLINKPAYMENT', ok_body())
        self.wizard(**BOTH).action_create_link()
        payment = self.last_payment()
        self.assertNotEqual(payment.state, 'sent', 'tokensız yanıt Gönderildi sayılmamalı')

    def test_sistem_hatasi_http_500_belirsiz(self):
        from .common import RawResponse
        self.mock.queue('PAYBYLINKPAYMENT', RawResponse(500, 'oops'))
        self.wizard(**BOTH).action_create_link()
        self.assertEqual(self.last_payment().state, 'unknown')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCommitDiscipline(LinkCase):
    """Tasarım §2/§6.1: dış çağrıdan ÖNCE 'Gönderiliyor' yazılır ve commit edilir."""

    def test_sending_kaydi_dis_cagridan_once_commit_edilir(self):
        self.wizard(**BOTH).action_create_link()
        call = self.mock.calls[0]
        self.assertGreaterEqual(call.probe['commits'], 1, 'Paratika çağrısından önce commit yapılmadı')
        self.assertEqual(call.probe['rows'].get('%s-1' % INV_NO), 'sending',
                         'çağrı anında kayıt Gönderiliyor olarak DB’de olmalı')

    def test_sonuc_dis_cagridan_sonra_commit_edilir(self):
        self.wizard(**BOTH).action_create_link()
        self.assertGreaterEqual(self.commit_count, 2)

    def test_hata_sonucu_da_commit_edilir(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10199', 'x'))
        self.wizard(**BOTH).action_create_link()
        self.assertGreaterEqual(self.commit_count, 2)

    def test_dogrulama_hatasinda_commit_ve_kayit_yok(self):
        with self.assertRaises(UserError):
            self.wizard(channel_sms=False, channel_email=False).action_create_link()
        self.assertEqual(self.commit_count, 0)
        self.assertFalse(self.payments())

    def test_dis_cagri_sirasinda_istisna_kaydi_kaybetmez(self):
        """Beklenmeyen istisna (ör. bellek hatası) olsa bile 'Gönderiliyor' kaydı commit edilmiş kalır."""
        self.mock.queue('PAYBYLINKPAYMENT', RuntimeError('beklenmeyen: %s' % PASSWORD))
        try:
            self.wizard(**BOTH).action_create_link()
        except Exception as exc:  # noqa: BLE001 - mesajda sır olmamalı
            self.assertNotIn(PASSWORD, str(exc))
        self.assertTrue(self.payments(), 'dış çağrı öncesi yazılan kayıt kaybolmamalı')
        self.assertGreaterEqual(self.commit_count, 1)

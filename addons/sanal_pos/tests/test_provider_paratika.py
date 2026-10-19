# -*- coding: utf-8 -*-
"""G6 / Paratika sağlayıcı katmanı. KK-12, KK-14, KK-15, KK-16, KK-37, KK-39, KK-52 (sağlayıcı düzeyi).

Doğrudan ``sanal.pos.provider.paratika`` arayüzü (02-tasarim §5) çağrılır;
HTTP ``requests.Session.send`` seviyesinde taklit edilir (mocks.py), böylece
gönderilen bayt, başlık, URL ve zaman aşımı gözlenir.
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import (
    CUSTOMER_NAME, EMAIL, INV_NO, LIVE_URL_PREFIX, PASSWORD, SECRET_KEY, TEST_URL_PREFIX,
    RawResponse, SanalPosCase, connection_exc, err_body, ok_body, timeout_exc, tran,
)

PROVIDER = 'sanal.pos.provider.paratika'
TURKISH_NAME = 'Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'


class ProviderCase(SanalPosCase):

    @property
    def provider(self):
        return self.env[PROVIDER]

    def pay(self, **vals):
        """Sağlayıcıya verilecek 'Gönderiliyor' ödeme kaydı (henüz token yok)."""
        vals.setdefault('state', 'sending')
        vals.setdefault('provider_token', False)
        vals.setdefault('sent_at', False)
        vals.setdefault('expires_at', False)
        return self._payment(**vals)

    def sent(self, **vals):
        return self._payment(**vals)

    def _payment(self, **vals):
        """Aynı testte tekrar çağrılabilir: ilk kayıt varsayılan fatura no/MPID'i kullanır,
        sonrakiler benzersiz fatura no alır (MPID ve 'tek açık link' kısıtları çakışmasın)."""
        if 'invoice_no' not in vals and 'merchant_payment_id' not in vals:
            self._fixture_count = getattr(self, '_fixture_count', 0) + 1
            if self._fixture_count > 1:
                vals['invoice_no'] = '%s-F%d' % (INV_NO, self._fixture_count)
        return self.make_payment(**vals)

    def call(self, action=None):
        calls = self.mock.calls_for(action) if action else self.mock.calls
        self.assertTrue(calls, 'Paratika çağrısı yapılmadı (%s)' % self.mock.actions)
        return calls[-1]


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCreateLinkRequest(ProviderCase):

    def test_kk12_alan_listesi(self):
        """KK-12: PAYBYLINKPAYMENT alanları, tek istek, SESSIONTYPE/ORDERITEMS yok."""
        payment = self.pay()
        res = self.provider.create_link(payment)
        self.assertEqual(self.mock.actions, ['PAYBYLINKPAYMENT'])
        p = self.call().params
        self.assertEqual(p['ACTION'], 'PAYBYLINKPAYMENT')
        self.assertEqual(p['MERCHANT'], 'TESTMERCHANT')
        self.assertEqual(p['MERCHANTUSER'], 'api.user@ugurlar.test')
        self.assertEqual(p['MERCHANTPASSWORD'], PASSWORD)
        self.assertEqual(p['AMOUNT'], '9000.00')
        self.assertEqual(p['CURRENCY'], 'TRY')
        self.assertEqual(p['MERCHANTPAYMENTID'], '%s-1' % INV_NO)
        self.assertEqual(p['CUSTOMER'], 'M-555')
        self.assertEqual(p['CUSTOMERNAME'], CUSTOMER_NAME)
        self.assertEqual(p['CUSTOMERPHONE'], '5321112233')
        self.assertEqual(p['CUSTOMEREMAIL'], EMAIL)
        self.assertEqual(p['NOTIFICATIONCHANNELS'], 'EMAIL,SMS')
        self.assertEqual(p['SESSIONEXPIRY'], '168h')
        self.assertTrue(p['RETURNURL'].isascii())
        self.assertEqual(p['RETURNURL'], 'https://odoo.example.com/sanal_pos/paratika/return')
        # U-2: MERCHANTNOTE = MERCHANTPAYMENTID (deneme sırası dahil)
        self.assertEqual(p['MERCHANTNOTE'], '%s-1' % INV_NO)
        for absent in ('SESSIONTYPE', 'ORDERITEMS', 'REFLECTCOMMISSION'):
            self.assertNotIn(absent, p)
        self.assertTrue(res['ok'])
        self.assertEqual(res['token'], 'TOK-001')

    def test_kk12_bos_opsiyonel_alanlar_gonderilmez(self):
        payment = self.pay(customer_address=False, customer_city=False, customer_zip=False)
        self.provider.create_link(payment)
        p = self.call().params
        for key in ('BILLTOADDRESSLINE', 'BILLTOCITY', 'BILLTOPOSTALCODE', 'BILLTOCOUNTRY'):
            self.assertNotIn(key, p)
        for key, value in p.items():
            self.assertNotEqual(value, '', 'boş alan gönderilmiş: %s' % key)

    def test_kk12_dolu_adres_alanlari_gider(self):
        payment = self.pay(customer_address='Atatürk Cad. No:5', customer_city='İstanbul',
                           customer_zip='34710')
        self.provider.create_link(payment)
        p = self.call().params
        self.assertEqual(p['BILLTOADDRESSLINE'], 'Atatürk Cad. No:5')
        self.assertEqual(p['BILLTOCITY'], 'İstanbul')
        self.assertEqual(p['BILLTOPOSTALCODE'], '34710')
        self.assertEqual(p['BILLTOCOUNTRY'], 'TUR')

    def test_kk12_tutar_bicimi_noktali_iki_hane_binliksiz(self):
        for amount, text in ((1234.5, '1234.50'), (12345678.9, '12345678.90'),
                             (0.5, '0.50'), (6500.01, '6500.01'), (9000, '9000.00')):
            with self.subTest(amount=amount):
                self.mock.calls.clear()
                self.provider.create_link(self.pay(
                    amount=amount, invoice_no='AMT%s' % str(amount).replace('.', ''),
                    merchant_payment_id='AMT%s-1' % str(amount).replace('.', '')))
                self.assertEqual(self.call().params['AMOUNT'], text)

    def test_kk12_kanal_degerleri(self):
        cases = (({'channel_sms': True, 'channel_email': True}, {'EMAIL', 'SMS'}),
                 ({'channel_sms': True, 'channel_email': False}, {'SMS'}),
                 ({'channel_sms': False, 'channel_email': True}, {'EMAIL'}))
        for i, (vals, expected) in enumerate(cases):
            with self.subTest(vals=vals):
                self.mock.calls.clear()
                self.provider.create_link(self.pay(
                    invoice_no='CH%d' % i, merchant_payment_id='CH%d-1' % i, **vals))
                got = set(self.call().params['NOTIFICATIONCHANNELS'].split(','))
                self.assertEqual(got, expected)

    def test_kk12_sure_saat_olarak(self):
        for hours in (1, 24, 168):
            with self.subTest(hours=hours):
                self.mock.calls.clear()
                self.provider.create_link(self.pay(
                    expiry_hours=hours, invoice_no='EX%d' % hours,
                    merchant_payment_id='EX%d-1' % hours))
                self.assertEqual(self.call().params['SESSIONEXPIRY'], '%dh' % hours)

    def test_kk12_musteri_kodu_bossa_fatura_bazli(self):
        """§7.2: CUSTOMER boşsa INV-<fatura no>."""
        self.provider.create_link(self.pay(customer_code=False))
        self.assertEqual(self.call().params['CUSTOMER'], 'INV-%s' % INV_NO)

    def test_kk12_deneme_sirasi_mpid_ve_note(self):
        self.provider.create_link(self.pay(attempt_no=3, merchant_payment_id='%s-3' % INV_NO))
        p = self.call().params
        self.assertEqual(p['MERCHANTPAYMENTID'], '%s-3' % INV_NO)
        self.assertEqual(p['MERCHANTNOTE'], '%s-3' % INV_NO)

    def test_p3_telefon_bicimi_ayari(self):
        for fmt, expected in (('10', '5321112233'), ('0', '05321112233'),
                              ('90', '905321112233'), ('+90', '+905321112233')):
            with self.subTest(fmt=fmt):
                self.set_setting('paratika_phone_format', fmt)
                self.mock.calls.clear()
                tag = fmt.replace('+', 'p')   # '90' ile '+90' aynı MPID'i üretmesin
                self.provider.create_link(self.pay(
                    invoice_no='PH%s' % tag, merchant_payment_id='PH%s-1' % tag))
                self.assertEqual(self.call().params['CUSTOMERPHONE'], expected)

    def test_returnurl_ascii_degilse_hata(self):
        """§7: web.base.url ASCII değilse link oluşturma hata verir; istek gitmez."""
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://ödeme.example.com')
        try:
            res = self.provider.create_link(self.pay())
            self.assertFalse(res['ok'])
            self.assertIn('ASCII', res['error_message'])
        except UserError as exc:
            self.assertIn('ASCII', str(exc.args[0]))
        self.assertNoParatikaCalls()


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRequestEncoding(ProviderCase):

    def test_kk15_utf8_baytlari_ve_baslik(self):
        """KK-15: gövde UTF-8 percent-encoded bayt, başlıkta charset=UTF-8."""
        self.provider.create_link(self.pay(customer_name=TURKISH_NAME))
        call = self.call()
        self.assertIsInstance(call.raw_body, bytes)
        self.assertIn('application/x-www-form-urlencoded', call.content_type.lower())
        self.assertIn('charset=utf-8', call.content_type.lower())
        call.raw_body.decode('ascii')  # percent-encoded: ham bayt ASCII olmalı
        self.assertEqual(call.params['CUSTOMERNAME'], TURKISH_NAME)
        self.assertIn(b'%C3%87', call.raw_body)   # Ç = C3 87
        self.assertIn(b'%C4%B0', call.raw_body)   # İ = C4 B0
        self.assertNotIn(b'%C7', call.raw_body.replace(b'%C3%87', b''), 'Latin-1/cp1254 kodlama sızmış')

    def test_kk15_adres_ve_il_utf8(self):
        self.provider.create_link(self.pay(
            customer_address='Şişli Mah. Çağlayan Sk. İş Hanı', customer_city='İzmir'))
        p = self.call().params
        self.assertEqual(p['BILLTOADDRESSLINE'], 'Şişli Mah. Çağlayan Sk. İş Hanı')
        self.assertEqual(p['BILLTOCITY'], 'İzmir')

    def test_kk15_ascii_modu_kapaliyken_varsayilan(self):
        self.assertFalse(self.get_setting_value('ascii_mode'))
        self.provider.create_link(self.pay(customer_name=TURKISH_NAME))
        self.assertEqual(self.call().params['CUSTOMERNAME'], TURKISH_NAME)

    def test_kk15_ascii_modu_acikken_donusur(self):
        """KK-15: ASCII modunda ad, adres ve il ASCII'ye çevrilir; kayıttaki değer değişmez."""
        self.set_setting('ascii_mode', True)
        payment = self.pay(customer_name=TURKISH_NAME, customer_address='Şişli Çağlayan',
                           customer_city='İzmir')
        self.provider.create_link(payment)
        p = self.call().params
        self.assertEqual(p['CUSTOMERNAME'], 'Cagri Sukru Ogut IGUSOC igusoc')
        self.assertEqual(p['BILLTOADDRESSLINE'], 'Sisli Caglayan')
        self.assertEqual(p['BILLTOCITY'], 'Izmir')
        self.assertEqual(payment.customer_name, TURKISH_NAME)

    def test_kk16_zaman_asimi_degerleri(self):
        """NFR-2/KK-16: bağlanma 10 sn, okuma 30 sn."""
        self.provider.create_link(self.pay())
        self.assertEqual(tuple(self.call().timeout), (10, 30))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestEnvironmentUrl(ProviderCase):

    def test_test_ortami_test_adresine_gider(self):
        self.provider.create_link(self.pay(environment='test'))
        self.assertTrue(self.call().url.startswith(TEST_URL_PREFIX), self.call().url)

    def test_kk52_kayit_ortami_ayardan_baskindir(self):
        """KK-52: kayıt 'test' ise ayar canlıya alınsa bile sonraki çağrılar test API'sine gider."""
        self.set_setting('environment', 'live')
        payment = self.sent(environment='test')
        self.provider.query_status(payment)
        self.assertTrue(self.call().url.startswith(TEST_URL_PREFIX), self.call().url)

    def test_kk52_canli_kayit_canli_adrese_gider(self):
        self.env['ir.config_parameter'].sudo().set_param('sanal_pos.paratika_live_url', LIVE_URL_PREFIX)
        payment = self.sent(environment='live')
        self.provider.query_status(payment)
        self.assertTrue(self.call().url.startswith(LIVE_URL_PREFIX), self.call().url)

    def test_kk52_test_ayari_canli_kayit_icin_degismez(self):
        self.env['ir.config_parameter'].sudo().set_param('sanal_pos.paratika_live_url', LIVE_URL_PREFIX)
        self.assertEqual(self.get_setting_value('environment'), 'test')
        self.provider.cancel_link(self.sent(environment='live'))
        self.assertTrue(self.call().url.startswith(LIVE_URL_PREFIX))

    def test_kk52_void_ve_refund_kayit_ortamina_gider(self):
        payment = self.make_paid(self.sent(environment='test'))
        line = self.make_refund_line(payment, 9000.0, kind='void', state='processing')
        self.set_setting('environment', 'live')
        self.provider.void(payment, line)
        self.assertTrue(self.call('VOID').url.startswith(TEST_URL_PREFIX))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestResultMapping(ProviderCase):

    def test_basari_sonucu(self):
        res = self.provider.create_link(self.pay())
        self.assertTrue(res['ok'])
        self.assertFalse(res['timeout'])
        self.assertFalse(res.get('error_code'))

    def test_kk14_bilinen_hata_kodlari_turkce(self):
        """KK-14: bilinen kodlar Türkçe açıklamayla döner, kod saklanır."""
        expectations = {
            'ERR10199': 'telefon',
            'ERR10233': 'e-posta',
            'ERR10244': 'telefon ve e-posta',
            'ERR10012': 'uzunluk',
            'ERR10020': 'yöneticinize başvurun',
            'ERR10047': 'yöneticinize başvurun',
            'ERR10053': 'yöneticinize başvurun',
            'ERR10266': 'yöneticinize başvurun',
            'ERR10048': 'sipariş',
            'ERR10107': 'sipariş',
            'ERR10117': 'sipariş',
            'ERR10118': 'sipariş',
        }
        for code, keyword in expectations.items():
            with self.subTest(code=code):
                self.mock.queue('PAYBYLINKPAYMENT', err_body(code, 'English provider message'))
                res = self.provider.create_link(self.pay(
                    invoice_no='E%s' % code[-5:], merchant_payment_id='E%s-1' % code[-5:]))
                self.assertFalse(res['ok'])
                self.assertFalse(res['timeout'])
                self.assertEqual(res['error_code'], code)
                self.assertIn(keyword, res['error_message'].lower())
                self.assertNotIn('English provider message', res['error_message'],
                                 'bilinen kod için Türkçe açıklama kullanılmalı')

    def test_kk14_bilinmeyen_kod_provider_mesaji_ve_kod(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR55555', 'Something odd happened'))
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])
        self.assertEqual(res['error_code'], 'ERR55555')
        self.assertIn('Something odd happened', res['error_message'])
        self.assertIn('ERR55555', res['error_message'])

    def test_kk46_iade_hata_kodlari_turkce(self):
        payment = self.make_paid(self.sent())
        expectations = {
            'ERR20040': 'Gün sonu geçmeden iade yapılamaz',
            'ERR10033': 'Gün sonu geçtiği için iptal edilemedi; iade (REFUND) yapın.',
            'ERR10262': 'kısmi iade yapılamıyor',
            'ERR10031': 'iade edilemez',
            'ERR10030': 'bulunamadı',
        }
        for code, text in expectations.items():
            with self.subTest(code=code):
                self.mock.queue('REFUND', err_body(code, 'English'))
                line = self.make_refund_line(payment, 100.0, state='failed', provider_ref='X%s' % code)
                res = self.provider.refund(payment, line)
                self.assertFalse(res['ok'])
                self.assertEqual(res['error_code'], code)
                self.assertIn(text.lower(), res['error_message'].lower())

    def test_kk46_err10032_kodu_doner(self):
        payment = self.make_paid(self.sent())
        self.mock.queue('REFUND', err_body('ERR10032', 'English'))
        line = self.make_refund_line(payment, 100.0, state='processing')
        res = self.provider.refund(payment, line)
        self.assertFalse(res['ok'])
        self.assertEqual(res['error_code'], 'ERR10032')

    def test_kk16_okuma_zaman_asimi(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_kk16_ag_hatasi_belirsiz_sayilir(self):
        self.mock.queue('PAYBYLINKPAYMENT', connection_exc())
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_kk16_http_5xx_belirsiz_sayilir(self):
        """Tasarım §5.1: 5xx'te işlem gerçekleşmiş olabilir -> timeout=True."""
        self.mock.queue('PAYBYLINKPAYMENT', RawResponse(500, '<html>Internal Server Error</html>'))
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_http_4xx_hata_kodu(self):
        self.mock.queue('PAYBYLINKPAYMENT', RawResponse(403, 'Forbidden'))
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])
        self.assertFalse(res['timeout'])
        self.assertEqual(res['error_code'], 'HTTP403')

    def test_json_olmayan_200_yaniti_hata(self):
        self.mock.queue('PAYBYLINKPAYMENT', RawResponse(200, 'not json at all', 'text/plain'))
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])

    def test_bos_yanit_govdesi_hata(self):
        self.mock.queue('PAYBYLINKPAYMENT', RawResponse(200, '', 'application/json'))
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'])

    def test_basarili_yanitta_token_yoksa_hata_sayilir(self):
        """00 dönüp sessionToken gelmezse 'başarılı' sayılıp token'sız 'Gönderildi' olmamalı."""
        self.mock.queue('PAYBYLINKPAYMENT', ok_body())
        res = self.provider.create_link(self.pay())
        self.assertFalse(res['ok'] and res.get('token'), 'tokensız başarı kabul edilmemeli')
        self.assertFalse(res.get('token'))

    def test_istisna_mesajinda_sifre_sizmaz(self):
        """KK-37: istisna metni (str(e)) sır içerse bile sonuçta/kayıtta açık metin yok."""
        leak = requests.exceptions.RequestException(
            'connection failed password=%s secret=%s' % (PASSWORD, SECRET_KEY))
        self.mock.queue('PAYBYLINKPAYMENT', leak)
        res = self.provider.create_link(self.pay())
        blob = '%s %s' % (res.get('error_message'), res.get('error_code'))
        self.assertNotIn(PASSWORD, blob)
        self.assertNotIn(SECRET_KEY, blob)
        self.assertNotIn(PASSWORD, self.all_log_text())
        self.assertNotIn(SECRET_KEY, self.all_log_text())


@tagged('post_install', '-at_install', 'sanal_pos')
class TestOtherActions(ProviderCase):

    def test_resend_istegi(self):
        payment = self.sent(provider_token='TOK-XYZ')
        res = self.provider.resend(payment, ['sms'])
        p = self.call('PAYBYLINKPAYMENTRESEND').params
        self.assertEqual(p['PAYBYLINKTOKEN'], 'TOK-XYZ')
        self.assertEqual(p['NOTIFICATIONCHANNELS'], 'SMS')
        self.assertTrue(res['ok'])

    def test_resend_iki_kanal(self):
        self.provider.resend(self.sent(), ['sms', 'email'])
        got = set(self.call('PAYBYLINKPAYMENTRESEND').params['NOTIFICATIONCHANNELS'].split(','))
        self.assertEqual(got, {'SMS', 'EMAIL'})

    def test_resend_hata(self):
        self.mock.queue('PAYBYLINKPAYMENTRESEND', err_body('ERR10143', 'closed'))
        res = self.provider.resend(self.sent(), ['email'])
        self.assertFalse(res['ok'])
        self.assertEqual(res['error_code'], 'ERR10143')

    def test_cancel_link_istegi(self):
        res = self.provider.cancel_link(self.sent(provider_token='TOK-C1'))
        self.assertEqual(self.call('PAYBYLINKPAYMENTCANCEL').params['PAYBYLINKTOKEN'], 'TOK-C1')
        self.assertTrue(res['ok'])

    def test_kk32_cancel_err10143_already_closed(self):
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10143', 'already closed'))
        res = self.provider.cancel_link(self.sent())
        self.assertTrue(res.get('already_closed'))

    def test_cancel_diger_hata_already_closed_degil(self):
        self.mock.queue('PAYBYLINKPAYMENTCANCEL', err_body('ERR10020', 'auth'))
        res = self.provider.cancel_link(self.sent())
        self.assertFalse(res['ok'])
        self.assertFalse(res.get('already_closed'))

    def test_kk16_find_link_istegi_ve_bos_sonuc(self):
        sent_at = datetime.utcnow().replace(microsecond=0)
        payment = self.make_payment(state='unknown', sent_at=sent_at, provider_token=False)
        res = self.provider.find_link(payment)
        p = self.call('QUERYPAYBYLINKPAYMENT').params
        self.assertEqual(p['MERCHANTNOTE'], payment.merchant_payment_id)
        fmt = re.compile(r'^\d{2}-\d{2}-\d{4} \d{2}:\d{2}$')
        self.assertRegex(p['STARTDATE'], fmt)
        self.assertRegex(p['ENDDATE'], fmt)
        start = datetime.strptime(p['STARTDATE'], '%d-%m-%Y %H:%M')
        end = datetime.strptime(p['ENDDATE'], '%d-%m-%Y %H:%M')
        self.assertLess(start, end)
        self.assertLessEqual(end - start, timedelta(days=30))
        self.assertTrue(res['ok'])
        self.assertFalse(res['found'])

    def test_kk16_find_link_zaman_asimi(self):
        self.mock.queue('QUERYPAYBYLINKPAYMENT', timeout_exc())
        res = self.provider.find_link(self.make_payment(state='unknown'))
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def _find_with(self, *items, invoice_no=INV_NO):
        payment = self.make_payment(state='unknown', provider_token=False, invoice_no=invoice_no,
                                    sent_at=datetime.utcnow().replace(microsecond=0))
        self.mock.queue('QUERYPAYBYLINKPAYMENT', ok_body(payByLinkPaymentList=list(items)))
        return payment, self.provider.find_link(payment)

    def link_item(self, token, amount='9000.00', **kw):
        epoch_ms = int(datetime.utcnow().timestamp() * 1000)
        return dict({'token': token, 'amount': amount, 'createdTs': epoch_ms, 'status': 'ACTIVE'}, **kw)

    def test_kk16_find_link_tek_aday_bulunur(self):
        _payment, res = self._find_with(self.link_item('TOK-FL1'))
        self.assertTrue(res['ok'])
        self.assertTrue(res['found'])
        self.assertEqual(res['token'], 'TOK-FL1')

    def test_kk16_find_link_iki_aday_ambiguous(self):
        _payment, res = self._find_with(self.link_item('TOK-FL1'), self.link_item('TOK-FL2'))
        self.assertTrue(res['ambiguous'])
        self.assertFalse(res['ok'])
        self.assertFalse(res['found'])

    def test_ob_liste_dolu_ama_aday_yoksa_ambiguous_bulunamadi_degil(self):
        """Ö-B: MERCHANTNOTE (MPID) ile gelen kalemler eşleşmiyorsa 'bulunamadı' sayılmaz."""
        other = self.make_payment(invoice_no='UGRFL-OTHER', provider_token='TOK-USED')
        cases = (
            ('tutar farklı', self.link_item('TOK-FL3', amount='8999.99')),
            ('token başka kayıtta', self.link_item(other.provider_token)),
            ('token yok', self.link_item(False)),
        )
        for i, (label, item) in enumerate(cases):
            with self.subTest(label):
                payment, res = self._find_with(item, invoice_no='UGRFL-%d' % i)
                self.assertTrue(res['ambiguous'], label)
                self.assertFalse(res['ok'])
                self.assertFalse(res['found'])
                self.assertEqual(res['error_code'], 'AMBIGUOUS')
                # kayıt unknown kalır, LINK_NOT_FOUND sayacı artmaz
                self.mock.queue('QUERYPAYBYLINKPAYMENT', ok_body(payByLinkPaymentList=[item]))
                payment.sudo()._reconcile_unknown_link()
                payment.invalidate_recordset()
                self.assertEqual(payment.state, 'unknown')
                self.assertEqual(payment.link_not_found_count, 0)

    def test_void_istegi(self):
        payment = self.make_paid(self.sent(), tran_ref='T1')
        line = self.make_refund_line(payment, 9000.0, kind='void', state='processing')
        res = self.provider.void(payment, line)
        p = self.call('VOID').params
        self.assertEqual(p['PGTRANID'], 'T1')
        self.assertEqual(p['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertTrue(res['ok'])
        self.assertTrue(res['ref'])

    def test_kk42_refund_istegi(self):
        payment = self.make_paid(self.sent(), tran_ref='T1')
        line = self.make_refund_line(payment, 2500.0, state='processing')
        res = self.provider.refund(payment, line)
        p = self.call('REFUND').params
        self.assertEqual(p['PGTRANID'], 'T1')
        self.assertEqual(p['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertEqual(p['AMOUNT'], '2500.00')
        self.assertEqual(p['CURRENCY'], 'TRY')
        self.assertNotIn('REFLECTCOMMISSION', p)
        self.assertTrue(res['ok'])
        self.assertTrue(res['ref'])

    def test_refund_zaman_asimi_belirsiz(self):
        payment = self.make_paid(self.sent())
        self.mock.queue('REFUND', timeout_exc())
        line = self.make_refund_line(payment, 100.0, state='processing')
        res = self.provider.refund(payment, line)
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_void_http_5xx_belirsiz(self):
        payment = self.make_paid(self.sent())
        self.mock.queue('VOID', RawResponse(502, 'Bad Gateway'))
        line = self.make_refund_line(payment, 9000.0, kind='void', state='processing')
        res = self.provider.void(payment, line)
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_parse_notification(self):
        p = self.provider
        self.assertEqual(p.parse_notification({'MERCHANTPAYMENTID': '%s-1' % INV_NO}), '%s-1' % INV_NO)
        self.assertEqual(p.parse_notification({'merchantPaymentId': 'ABC-2'}), 'ABC-2')
        self.assertFalse(p.parse_notification({}))
        self.assertFalse(p.parse_notification({'AMOUNT': '9000.00', 'STATUS': 'AP'}))
        self.assertFalse(p.parse_notification({'MERCHANTPAYMENTID': ''}))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestQueryStatusNormalization(ProviderCase):

    def query(self, *transactions):
        self.set_query_transactions(*transactions)
        return self.provider.query_status(self.sent())

    def test_sorgu_istegi_mpid(self):
        payment = self.sent()
        self.provider.query_status(payment)
        self.assertEqual(self.call('QUERYTRANSACTION').params['MERCHANTPAYMENTID'],
                         payment.merchant_payment_id)

    def test_kk22_onayli_satis_normalize(self):
        res = self.query(tran('AP', 'SALE', '9000.00', 'T1', 'TRY', 3, '4242'))
        self.assertTrue(res['ok'])
        self.assertEqual(len(res['transactions']), 1)
        t = res['transactions'][0]
        self.assertEqual(t['ref'], 'T1')
        self.assertEqual(t['kind'], 'sale')
        self.assertEqual(t['status'], 'approved')
        self.assertEqual(t['amount'], Decimal('9000.00'))
        self.assertIsInstance(t['amount'], Decimal)
        self.assertEqual(t['currency'], 'TRY')
        self.assertEqual(int(t['installment_count']), 3)
        self.assertEqual(t['card_last4'], '4242')

    def test_durum_esleme_tablosu(self):
        table = [
            (('AP', 'SALE'), [('sale', 'approved')]),
            (('FA', 'SALE'), [('sale', 'failed')]),
            (('CA', 'SALE'), [('sale', 'cancelled')]),
            (('IP', 'SALE'), [('sale', 'pending')]),
            (('MR', 'SALE'), [('sale', 'review')]),
            (('AP', 'VOID'), [('void', 'approved')]),
            (('AP', 'REFUND'), [('refund', 'approved')]),
            (('AP', 'PTREFUND'), [('refund', 'approved')]),
            # satışın iptali: iki biçim de kabul (P-10)
            (('VD', 'SALE'), [('void', 'approved'), ('sale', 'voided')]),
        ]
        for (status, ttype), accepted in table:
            with self.subTest(status=status, ttype=ttype):
                res = self.query(tran(status, ttype, '100.00', 'R1'))
                t = res['transactions'][0]
                self.assertIn((t['kind'], t['status']), accepted)

    def test_zaman_alani_olmadan_patlamaz(self):
        """Paratika zaman biçimi belgesiz: alan yoksa da normalize edilebilmeli."""
        res = self.query(tran('AP', 'SALE'))
        self.assertTrue(res['ok'])
        self.assertEqual(len(res['transactions']), 1)

    def test_bos_liste(self):
        res = self.query()
        self.assertTrue(res['ok'])
        self.assertEqual(res['transactions'], [])

    def test_birden_cok_islem(self):
        res = self.query(tran('AP', 'SALE', ref='T1'), tran('AP', 'REFUND', '2500.00', 'R1'),
                         tran('FA', 'SALE', ref='T0'))
        self.assertEqual({t['ref'] for t in res['transactions']}, {'T1', 'R1', 'T0'})

    def test_hata_ve_zaman_asimi(self):
        self.mock.queue('QUERYTRANSACTION', err_body('ERR10030', 'not found'))
        res = self.provider.query_status(self.sent())
        self.assertFalse(res['ok'])
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        res = self.provider.query_status(self.sent())
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

@tagged('post_install', '-at_install', 'sanal_pos')
class TestProviderLogging(ProviderCase):

    def logs(self, action=None):
        domain = [('action', '=', action)] if action else []
        return self.env['sanal.pos.log'].sudo().search(domain, order='id')

    def test_kk39_basarili_cagri_kaydi(self):
        payment = self.pay()
        self.provider.create_link(payment)
        log = self.logs('PAYBYLINKPAYMENT')
        self.assertEqual(len(log), 1)
        self.assertEqual(log.payment_id, payment)
        self.assertEqual(log.provider, 'paratika')
        self.assertEqual(log.environment, 'test')
        self.assertTrue(log.success)
        self.assertEqual(log.http_status, 200)
        self.assertEqual(log.response_code, '00')
        self.assertFalse(log.error_code)
        self.assertGreaterEqual(log.duration_ms, 0)
        self.assertFalse(log.is_financial)

    def test_kk39_hata_kaydi(self):
        self.mock.queue('PAYBYLINKPAYMENT', err_body('ERR10199', 'phone'))
        self.provider.create_link(self.pay())
        log = self.logs('PAYBYLINKPAYMENT')
        self.assertFalse(log.success)
        self.assertEqual(log.error_code, 'ERR10199')
        self.assertEqual(log.response_code, '99')

    def test_kk39_zaman_asimi_da_kaydedilir(self):
        self.mock.queue('PAYBYLINKPAYMENT', timeout_exc())
        self.provider.create_link(self.pay())
        log = self.logs('PAYBYLINKPAYMENT')
        self.assertEqual(len(log), 1)
        self.assertFalse(log.success)

    def test_kk39_finansal_cagrilar_isaretlenir(self):
        payment = self.make_paid(self.sent())
        line = self.make_refund_line(payment, 100.0, state='processing')
        self.provider.refund(payment, line)
        line2 = self.make_refund_line(payment, 9000.0, kind='void', state='failed', provider_ref='V9')
        self.provider.void(payment, line2)
        self.provider.query_status(payment)
        self.assertTrue(self.logs('REFUND').is_financial)
        self.assertTrue(self.logs('VOID').is_financial)
        self.assertFalse(self.logs('QUERYTRANSACTION').is_financial)

    def test_kk37_istek_kaydi_maskeli(self):
        """KK-37/NFR-4: şifre '***', telefon son 4 hane, e-posta maskeli."""
        self.provider.create_link(self.pay())
        body = self.logs('PAYBYLINKPAYMENT').request_body
        self.assertNotIn(PASSWORD, body)
        self.assertIn('***', body)
        self.assertNotIn('5321112233', body)
        self.assertIn('2233', body)
        self.assertNotIn(EMAIL, body)
        self.assertNotIn('cagri.sahin', body)
        self.assertIn('example.com', body)
        self.assertIn('9000.00', body, 'maskeleme finansal alanları bozmamalı')

    def test_kk37_yanit_kaydinda_sirlar_silinir(self):
        """KK-37 (savunma): yanıtta sır geçerse '***'."""
        self.mock.queue('PAYBYLINKPAYMENT', ok_body(
            sessionToken='TOK-A', debug='pw=%s key=%s' % (PASSWORD, SECRET_KEY)))
        self.provider.create_link(self.pay())
        body = self.logs('PAYBYLINKPAYMENT').response_body
        self.assertNotIn(PASSWORD, body)
        self.assertNotIn(SECRET_KEY, body)

    def test_kk37_python_loglarinda_govde_ve_sir_yok(self):
        """Tasarım §5.1: logger'a gövde yazılmaz; telefon yalnız son 4 hane."""
        # Fixture'lar yakalamanın DIŞINDA kurulur: yalnız sağlayıcı çağrıları izlenir.
        pay = self.pay()
        sent = self.sent()
        with self.capture_logs() as records:
            self.provider.create_link(pay)
            self.provider.query_status(sent)
        text = '\n'.join(records)
        for secret in (PASSWORD, SECRET_KEY, '5321112233', EMAIL, 'MERCHANTPASSWORD=%s' % PASSWORD):
            self.assertNotIn(secret, text)

    def test_kk39_yanit_govdesi_kirpilir(self):
        big = 'x' * 40000
        self.mock.queue('PAYBYLINKPAYMENT', ok_body(sessionToken='TOK-BIG', note=big))
        self.provider.create_link(self.pay())
        self.assertLessEqual(len(self.logs('PAYBYLINKPAYMENT').response_body), 21 * 1024)

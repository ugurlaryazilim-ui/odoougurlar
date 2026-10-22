# -*- coding: utf-8 -*-
"""Mail Order (kart bilgisi Odoo sayfasında, Paratika Direct POST 3D) kabul testleri.

KK-1..KK-21 (02-tasarim §2 uyarlanmış metin). Özellik yazılmadan önce yazıldı: tasarımdaki
arayüz adları kullanılır (``payment_method``, ``sanal.pos.mail.order.wizard``,
``action_create_mail_order``, ``create_session`` ...). HTTP/PCI testleri ayrı dosyalarda.

Kural: her olumsuz teste olumlu çapa vardır (aynı kurulum başarılı olabilir); yetkisiz
kullanıcı testlerinde ACL AccessError'u ``_check_sanal_pos_user`` korumasını maskelemesin diye
geçici ACL verilir (``grant_plain``).
"""
import json
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.service.model import get_public_method
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import (
    CRON_SYNC, CUSTOMER_NAME, EMAIL, INV_NO, LEAK_CVV, LEAK_OWNER, LEAK_PAN, MAIL_ORDER_PAY_PATH,
    PASSWORD, TEST_URL_PREFIX, LIVE_URL_PREFIX, RawResponse, SanalPosCase, connection_exc, err_body,
    installment_body, invoice_rows, ok_body, timeout_exc, tran,
)
from ..models.sanal_pos_payment import BUSY_MSG

PROVIDER = 'sanal.pos.provider.paratika'
MO_WIZARD = 'sanal.pos.mail.order.wizard'
LINK_WIZARD = 'sanal.pos.payment.create.wizard'
BOTH = {'channel_sms': True, 'channel_email': True}
OPEN_LINK = 'açık bir link'
OPEN_MO = 'açık bir mail order'
PAID_PART = 'ödeme alınmış/incelemede'
SESSION_FAIL_MSG = 'Paratika yanıt vermedi; kart sayfası açılamadı. Tekrar deneyebilirsiniz.'
WARNING_TEXT = ('Kart bilgisini yalnız bu ekrandan açılan kart sayfasına girin; not almayın, '
                'e-posta/mesajla almayın, tarayıcıya kaydettirmeyin. Banka doğrulama (SMS) kodunu '
                'müşteriden alıp yalnız banka sayfasına girin.')
LINK_ACTIONS = ('PAYBYLINKPAYMENT', 'PAYBYLINKPAYMENTRESEND', 'PAYBYLINKPAYMENTCANCEL',
                'QUERYPAYBYLINKPAYMENT')


def luhn_complete(prefix):
    """``prefix`` rakamlarına Luhn sağlama hanesi ekler (testte geçerli PAN üretmek için)."""
    digits = [int(c) for c in prefix]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return prefix + str((10 - total % 10) % 10)


def plain_text(arch):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', arch)).strip()


class MailOrderCase(SanalPosCase):

    # ------------------------------------------------------------------ yardımcılar
    def mo_attempt(self, **kw):
        """Mail order sihirbazını çalıştırır; UserError/AccessError metni (başarıda None)."""
        try:
            self.mail_order_wizard(**kw).action_create_mail_order()
        except UserError as exc:
            return str(exc.args[0])
        return None

    def link_attempt(self, **kw):
        try:
            self.wizard(**dict(BOTH, **kw)).action_create_link()
        except UserError as exc:
            return str(exc.args[0])
        return None

    def reload(self, record):
        record.invalidate_recordset()
        return record

    def link_calls(self):
        return self.mock.count(*LINK_ACTIONS)

    def new_invoice(self, invoice_no, **kw):
        self.set_invoice(invoice_rows(invoice_no, **kw), invoice_no)
        return invoice_no

    def past(self, **delta):
        return datetime.utcnow().replace(microsecond=0) - timedelta(**(delta or {'minutes': 5}))

    def sync(self, payment):
        payment.sudo()._sync_status()
        return self.reload(payment)

    def grant_plain(self, *model_names):
        """Grupsuz iç kullanıcıya GEÇİCİ ACL: AccessError'un ``_check_sanal_pos_user``
        korumasını maskelemesini önler (DERSLER)."""
        group = self.env.ref('base.group_user')
        for name in model_names:
            self.env['ir.model.access'].sudo().create({
                'name': 'tmp plain %s' % name,
                'model_id': self.env['ir.model']._get(name).id,
                'group_id': group.id,
                'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': False,
            })

    def blob(self, payment):
        return '\n'.join([payment.last_error_message or '', payment.last_error_code or '',
                          self.chatter(payment)])


# ======================================================================================
# KK-20 / alan koruması
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestPaymentMethodField(MailOrderCase):

    def test_kk20_alan_ozellikleri(self):
        field = self.env['sanal.pos.payment']._fields['payment_method']
        self.assertEqual(field.selection, [('link', 'Link'), ('mail_order', 'Mail Order')])
        self.assertEqual(field.string, 'Yöntem')
        self.assertTrue(field.required)
        self.assertTrue(field.readonly)
        self.assertTrue(field.index)
        self.assertFalse(field.copy)

    def test_kk20_varsayilan_link_ve_eski_kayitlar_link(self):
        self.assertEqual(self.make_payment().payment_method, 'link')
        self.assertEqual(self.env['sanal.pos.payment'].default_get(['payment_method'])
                         .get('payment_method'), 'link')
        self.env.cr.execute("""
            SELECT is_nullable FROM information_schema.columns
             WHERE table_name = 'sanal_pos_payment' AND column_name = 'payment_method'""")
        self.assertEqual(self.env.cr.fetchone(), ('NO',))
        self.env.cr.execute("SELECT count(*) FROM sanal_pos_payment "
                            "WHERE payment_method IS NULL OR payment_method NOT IN ('link','mail_order')")
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_link_sihirbazi_kaydi_link_olur(self):
        payment = self.create_link(**BOTH)
        self.assertEqual(payment.payment_method, 'link')

    def test_default_baglami_yontemi_degistiremez_link_sihirbazi(self):
        """default_payment_method bağlamı vals'ta olmayan alana uygulanır (DERSLER 3. tekrar)."""
        env = self.env(user=self.user_sp, context=dict(self.env.context, default_payment_method='mail_order'))
        wiz = env[LINK_WIZARD].create({'invoice_no': INV_NO})
        wiz.action_fetch_invoice()
        wiz.write(dict(BOTH, customer_email=EMAIL))
        wiz.action_create_link()
        payment = self.last_payment()
        self.assertEqual(payment.payment_method, 'link')
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 1)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)

    def test_default_baglami_yontemi_degistiremez_mail_order_sihirbazi(self):
        env = self.env(user=self.user_sp, context=dict(self.env.context, default_payment_method='link'))
        wiz = env[MO_WIZARD].create({'invoice_no': INV_NO})
        wiz.action_fetch_invoice()
        wiz.action_create_mail_order()
        self.assertEqual(self.last_payment().payment_method, 'mail_order')
        self.assertEqual(self.link_calls(), 0)

    def test_insert_sending_yontem_anahtarsiz_vals_reddedilir(self):
        Payment = self.env['sanal.pos.payment']
        vals = {
            'provider': 'paratika', 'environment': 'test', 'invoice_source': 'nebim',
            'invoice_no': INV_NO, 'customer_name': CUSTOMER_NAME, 'amount': 9000.0,
            'currency_id': self.try_currency.id, 'state': 'sending', 'attempt_no': 1,
            'merchant_payment_id': '%s-1' % INV_NO, 'expiry_hours': 1, 'user_id': self.user_sp.id,
            'payment_method': 'mail_order',
        }
        created = Payment._insert_sending(dict(vals))          # olumlu çapa
        self.assertEqual(created.payment_method, 'mail_order')
        created.sudo().write({'state': 'expired'})
        created.flush_recordset()
        bare = dict(vals, attempt_no=2, merchant_payment_id='%s-2' % INV_NO)
        del bare['payment_method']
        with self.assertRaises(Exception), self.env.cr.savepoint():
            Payment._insert_sending(bare)
        self.assertEqual(len(self.payments()), 1)

    def test_kullanici_yontem_alanini_yazamaz_olusturamaz(self):
        payment = self.make_mail_order()
        for user in (self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    payment.with_user(user).write({'payment_method': 'link'})
                with self.assertRaises(AccessError):
                    self.env['sanal.pos.payment'].with_user(user).create(
                        {'invoice_no': 'RPCMO', 'payment_method': 'mail_order', 'amount': 1.0,
                         'customer_name': 'X', 'merchant_payment_id': 'RPCMO-1', 'attempt_no': 1,
                         'currency_id': self.try_currency.id})
        self.assertEqual(self.reload(payment).payment_method, 'mail_order')
        self.assertFalse(self.payments('RPCMO'))


# ======================================================================================
# Sağlayıcı katmanı
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestProviderSession(MailOrderCase):

    def sending_mo(self, **vals):
        return self.make_mail_order(state='sending', provider_token=False, sent_at=False,
                                    expires_at=False, **vals)

    def test_create_session_parametreleri(self):
        payment = self.sending_mo()
        res = self.env[PROVIDER].create_session(payment)
        self.assertTrue(res['ok'])
        self.assertEqual(res['token'], 'MOT-001')
        for key in ('ok', 'timeout', 'error_code', 'error_message', 'raw_code'):
            self.assertIn(key, res)
        call = self.mock.last('SESSIONTOKEN')
        self.assertEqual(self.mock.actions, ['SESSIONTOKEN'])
        p = call.params
        self.assertEqual(p['SESSIONTYPE'], 'PAYMENTSESSION')
        self.assertEqual(p['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertEqual(p['AMOUNT'], '9000.00')
        self.assertEqual(p['CURRENCY'], 'TRY')
        self.assertEqual(p['CUSTOMERNAME'], CUSTOMER_NAME)
        self.assertEqual(p['CUSTOMEREMAIL'], EMAIL)
        self.assertEqual(p['CUSTOMER'], 'M-555')
        self.assertEqual(p['CUSTOMERPHONE'], '5321112233')
        self.assertEqual(p['SESSIONEXPIRY'], '1h')
        self.assertEqual(p['RETURNURL'], 'https://odoo.example.com/sanal_pos/paratika/mo_return')
        self.assertTrue(p.get('MERCHANTNOTE'))
        for forbidden in ('NAMEONCARD', 'NOTIFICATIONCHANNELS', 'EXTRA'):
            self.assertNotIn(forbidden, p)
        self.assertEqual([k for k in p if k.startswith('CARD')], [])
        self.assertTrue(call.url.startswith(TEST_URL_PREFIX))

    def test_create_session_islem_kaydi_yazar(self):
        payment = self.sending_mo()
        self.env[PROVIDER].create_session(payment)
        log = self.env['sanal.pos.log'].sudo().search(
            [('payment_id', '=', payment.id), ('action', '=', 'SESSIONTOKEN')])
        self.assertEqual(len(log), 1)
        self.assertTrue(log.success)
        self.assertNotIn(PASSWORD, (log.request_body or '') + (log.response_body or ''))

    def test_create_session_returnurl_ascii_degilse_reddeder(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://odoo.örnek.test')
        res = self.env[PROVIDER].create_session(self.sending_mo())
        self.assertFalse(res['ok'])
        self.assertEqual(res['error_code'], 'RETURNURL')
        self.assertIn('ASCII', res['error_message'])
        self.assertNoParatikaCalls()

    def test_create_session_hata_varyantlari_ok_false_istisna_yok(self):
        variants = {
            'timeout': timeout_exc(),
            'baglanti': connection_exc(),
            'http500': RawResponse(500, 'Internal Server Error'),
            'html200': RawResponse(200, '<html>bakim</html>'),
            'token_yok': ok_body(),
            'red': err_body('ERR10136', 'x'),
        }
        for name, response in variants.items():
            with self.subTest(variant=name):
                self.mock.queue('SESSIONTOKEN', response)
                payment = self.sending_mo(invoice_no='PV-%s' % name, merchant_payment_id='PV-%s-1' % name)
                res = self.env[PROVIDER].create_session(payment)
                self.assertFalse(res['ok'])
                self.assertFalse(res.get('token'))

    def test_hata_kodlari_turkce(self):
        from odoo.addons.sanal_pos.models.provider_paratika import ERROR_MESSAGES
        for code in ('ERR10136', 'ERR10154'):
            with self.subTest(code=code):
                self.assertIn(code, ERROR_MESSAGES)
                self.assertTrue(ERROR_MESSAGES[code])
                self.mock.queue('SESSIONTOKEN', err_body(code, 'English text'))
                res = self.env[PROVIDER].create_session(self.sending_mo(
                    invoice_no='EC-%s' % code, merchant_payment_id='EC-%s-1' % code))
                self.assertEqual(res['error_code'], code)
                self.assertEqual(res['error_message'], ERROR_MESSAGES[code])
                self.assertNotIn('(%s)' % code, res['error_message'])

    def test_bilinmeyen_kod_mesaj_ve_kod(self):
        self.mock.queue('SESSIONTOKEN', err_body('ERR77777', 'Beklenmeyen sorun'))
        res = self.env[PROVIDER].create_session(self.sending_mo())
        self.assertEqual(res['error_code'], 'ERR77777')
        self.assertIn('Beklenmeyen sorun', res['error_message'])
        self.assertIn('ERR77777', res['error_message'])

    # -- direct_post_url
    def test_direct_post_url_ortama_gore(self):
        provider = self.env[PROVIDER]
        test = self.make_mail_order(provider_token='TOK-A')
        live = self.make_mail_order(provider_token='TOK-B', environment='live', invoice_no='LIVE1')
        self.assertEqual(provider.direct_post_url(test), TEST_URL_PREFIX + '/post/sale3d/TOK-A')
        self.assertEqual(provider.direct_post_url(live), LIVE_URL_PREFIX + '/post/sale3d/TOK-B')
        self.assertNoParatikaCalls()

    def test_direct_post_url_ozel_adres_ve_token_yok(self):
        # G-1: ayardaki adres kartın gideceği yerdir; izin listesi (DIRECT_POST_HOSTS) dışı -> None
        params = self.env['ir.config_parameter'].sudo()
        payment = self.make_mail_order(provider_token='TOK-C')
        for url in ('https://sandbox.example.test/api/v2/', 'http://test.paratika.com.tr/paratika/api/v2',
                    'https://test.paratika.com.tr:8443/paratika/api/v2',
                    'https://x@test.paratika.com.tr/paratika/api/v2',
                    'https://test.paratika.com.tr.evil.example/api/v2'):
            with self.subTest(url=url):
                params.set_param('sanal_pos.paratika_test_url', url)
                self.assertIsNone(self.env[PROVIDER].direct_post_url(payment))
        # olumlu çapa: izinli host, özel yol, sondaki '/' kırpılır
        params.set_param('sanal_pos.paratika_test_url', 'https://test.paratika.com.tr/ozel/api/v2/')
        self.assertEqual(self.env[PROVIDER].direct_post_url(payment),
                         'https://test.paratika.com.tr/ozel/api/v2/post/sale3d/TOK-C')
        self.assertIsNone(self.env[PROVIDER].direct_post_url(
            self.make_mail_order(provider_token=False, invoice_no='NOTOK')))

    # -- query_installments
    def test_query_installments_normalizasyon(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(
            ('AXESS', 'AXESS', [(1, 0), (2, 0), (3, 1.5), (6, 3.0)]),
            ('BONUS', 'BONUS', [(3, 1.5), ('NOT_ON_US', 0), (9, 4.5)])))
        payment = self.make_mail_order()
        res = self.env[PROVIDER].query_installments(payment)
        self.assertTrue(res['ok'])
        by_count = {o['count']: o for o in res['options']}
        self.assertEqual(sorted(by_count), [2, 3, 6, 9])
        self.assertTrue(all(isinstance(o['count'], int) for o in res['options']))
        self.assertEqual(sorted(by_count[3]['networks']), ['AXESS', 'BONUS'])
        self.assertEqual(by_count[2]['networks'], ['AXESS'])
        self.assertEqual(by_count[3]['rate'], 1.5)
        self.assertEqual(by_count[6]['rate'], 3.0)
        self.assertEqual(self.mock.actions, ['QUERYINSTALLMENT'])
        params = self.mock.last('QUERYINSTALLMENT').params
        self.assertNotIn('BIN', params)

    def test_query_installments_hata_bos_liste(self):
        for i, response in enumerate((timeout_exc(), RawResponse(500, 'x'), err_body('ERR1', 'x'))):
            with self.subTest(response=type(response).__name__):
                self.mock.queue('QUERYINSTALLMENT', response)
                payment = self.make_mail_order(invoice_no='QI-%d' % i, merchant_payment_id='QI-%d-1' % i)
                res = self.env[PROVIDER].query_installments(payment)
                self.assertEqual(res['options'], [])
                self.assertFalse(res['ok'])


@tagged('post_install', '-at_install', 'sanal_pos')
class TestCardMasking(MailOrderCase):
    """KK-17(e): kart anahtarları ve Luhn-geçerli PAN günlükte görünmez."""

    CARD_KEYS = ('CARDPAN', 'PAN', 'CVV', 'CARDCVV', 'CARDEXPIRY', 'EXPIRYMONTH', 'EXPIRYYEAR',
                 'NAMEONCARD', 'CARDOWNER', 'CARDTOKEN', 'cardOwner', 'pan', 'expiryMonth',
                 'expiryYear', 'cvv', 'NameOnCard')

    def test_mask_request_kart_anahtarlari(self):
        params = {key: 'DEGER-%d' % i for i, key in enumerate(self.CARD_KEYS)}
        params.update({'MERCHANTPAYMENTID': 'UGR1-1', 'MERCHANTPASSWORD': PASSWORD, 'AMOUNT': '9000.00'})
        text = self.env[PROVIDER]._mask_request(params)
        data = json.loads(text)
        for key in self.CARD_KEYS:
            self.assertEqual(data[key], '***', key)
        self.assertEqual(data['MERCHANTPAYMENTID'], 'UGR1-1')
        self.assertEqual(data['AMOUNT'], '9000.00')
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn('DEGER-', text)

    def test_log_call_govdeleri_merkezi_maskelenir(self):
        payment = self.make_mail_order()
        provider = self.env[PROVIDER]
        provider._log_call(payment, 'TESTMASK', 'paratika', 'test',
                           request_body='pan=%s&x=1' % LEAK_PAN,
                           response_body=json.dumps({'kart': LEAK_PAN, 'tamam': '9000.00'}))
        log = self.env['sanal.pos.log'].sudo().search([('action', '=', 'TESTMASK')])
        self.assertEqual(len(log), 1)
        self.assertNotIn(LEAK_PAN, log.request_body + log.response_body)
        self.assertIn('****4358', log.request_body)
        self.assertIn('****4358', log.response_body)
        self.assertIn('9000.00', log.response_body)

    def test_call_yolunda_yanit_ve_istisna_metnindeki_pan_loga_girmez(self):
        payment = self.make_mail_order()
        provider = self.env[PROVIDER]
        self.mock.queue('QUERYINSTALLMENT', err_body('ERR1', 'kart %s hatali' % LEAK_PAN))
        provider._call(payment, 'QUERYINSTALLMENT', {'MERCHANTPAYMENTID': payment.merchant_payment_id})
        self.mock.queue('QUERYINSTALLMENT', type(timeout_exc())('read timed out kart %s' % LEAK_PAN))
        provider._call(payment, 'QUERYINSTALLMENT', {'MERCHANTPAYMENTID': payment.merchant_payment_id})
        self.assertGreaterEqual(len(self.env['sanal.pos.log'].sudo().search([('payment_id', '=', payment.id)])), 2)
        self.assertNotIn(LEAK_PAN, self.all_log_text())

    # -- tools.mask_card_data birimleri
    def mask(self, text):
        from odoo.addons.sanal_pos import tools
        return tools.mask_card_data(text)

    def test_mask_luhn_gecerli_uzunluklar(self):
        for prefix_len, prefix in ((12, '422222222222'), (14, '37828224631000'), (15, '411111111111111'),
                                   (18, '630400000000000000')):
            pan = luhn_complete(prefix[:prefix_len])
            with self.subTest(length=len(pan)):
                self.assertGreaterEqual(len(pan), 13)
                self.assertLessEqual(len(pan), 19)
                masked = self.mask('kart: %s tamam' % pan)
                self.assertNotIn(pan, masked)
                self.assertIn('****%s' % pan[-4:], masked)
                self.assertTrue(masked.startswith('kart: '))
                self.assertTrue(masked.endswith(' tamam'))

    def test_mask_ayracli_pan(self):
        for text in ('4355 0843 5508 4358', '4355-0843-5508-4358', '4355084355084358'):
            with self.subTest(text=text):
                masked = self.mask('x %s y' % text)
                self.assertIn('****4358', masked)
                self.assertNotIn('4355', masked)
                self.assertNotIn('5508', masked)

    def test_mask_g5_kacan_bicimler(self):
        # G-5 (güvenlik PoC'leri): harfe/alt çizgiye bitişik, nokta/artı/NBSP/çift boşluk ayraçlı
        # ve URL kodlu PAN da maskelenir
        cases = ('x4355084355084358', 'card_4355084355084358', '4355084355084358TL',
                 '4355.0843.5508.4358', '4355  0843  5508  4358', '4355 0843 5508 4358',
                 '4355+0843+5508+4358', 'pan%3D4355084355084358', 'pan=4355%200843%205508%204358',
                 '4355%2D0843%2D5508%2D4358', 'a 9000.00 4355 0843 5508 4358 b')
        for text in cases:
            with self.subTest(text=text):
                masked = self.mask(text)
                self.assertIn('****4358', masked)
                for part in ('4355', '0843', '5508'):
                    self.assertNotIn(part, masked)
                self.assertEqual(self.mask(masked), masked)       # idempotent

    def test_mask_harfe_bitisik_mpid_anahtarliysa_korunur(self):
        # NEDEN (G-5 sonrası güncelleme): harfe bitişik PAN artık maskelendiği için serbest metindeki
        # 'UGR<13 hane Luhn>-1' de maskelenir; günlükte anahtarlı MPID (JSON/form) korunur.
        valid13 = luhn_complete('422222222222')
        mpid = 'UGR%s-1' % valid13
        for text in (json.dumps({'merchantPaymentId': mpid}), 'MERCHANTPAYMENTID=%s&x=1' % mpid):
            with self.subTest(text=text):
                self.assertEqual(self.mask(text), text)
        self.assertNotIn(valid13, self.mask('serbest %s' % mpid))          # olumlu çapa

    def test_mask_response_kart_sahibi_bin_son4_anahtarlari(self):
        # G-4: Paratika yanıtındaki kart sahibi adı / BIN / pan benzeri alanlar günlükte '***'
        data = {'transactionList': [{
            'cardHolderName': 'AHMET YILMAZ', 'nameOnCard': 'AHMET', 'cardOwner': 'AHMET',
            'panFirst6': '435508', 'panLast4': '4358', 'maskedPan': '435508******4358',
            'cardBin': 435508, 'bin': '435508', 'company': 'UGURLAR', 'amount': '9000.00',
            'pgTranId': 'PG-1', 'merchantPaymentId': 'UGR1-1'}]}
        text = self.env[PROVIDER]._mask_response(data)
        row = json.loads(text)['transactionList'][0]
        for key in ('cardHolderName', 'nameOnCard', 'cardOwner', 'panFirst6', 'panLast4',
                    'maskedPan', 'cardBin', 'bin'):
            self.assertEqual(row[key], '***', key)
        for key in ('company', 'amount', 'pgTranId', 'merchantPaymentId'):          # olumlu çapa
            self.assertEqual(row[key], data['transactionList'][0][key], key)
        for needle in ('AHMET', '435508'):
            self.assertNotIn(needle, text)

    def test_mask_bozulmayanlar(self):
        valid12 = luhn_complete('43550843550')
        self.assertEqual(len(valid12), 12)
        cases = {
            'luhn_gecersiz_uzun': 'ref 4355084355084359 bitti',
            'on_iki_hane': 'no %s bitti' % valid12,
            'pgTranRefId_json': json.dumps({'pgTranRefId': LEAK_PAN, 'a': 1}),
            'pgTranRefId_urlencoded': 'pgTranRefId=%s&x=1' % LEAK_PAN,
            'tarih_zaman': 'created 2026-10-22 13:45:10',
            'tutar_ve_tarih': 'amount=9000.00&date=22.10.2026',
            'yuzde_kodlu_kisa': 'a%20b%2012345',
            'bos': '',
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.mask(text), text)

    def test_mask_idempotent_ve_cok_pan(self):
        text = 'a %s b %s c' % (LEAK_PAN, luhn_complete('411111111111111'))
        once = self.mask(text)
        self.assertEqual(self.mask(once), once)
        self.assertEqual(once.count('****'), 2)

    def test_luhn_yardimcisi_dogru(self):
        self.assertEqual(luhn_complete(LEAK_PAN[:-1]), LEAK_PAN)


# ======================================================================================
# Menü, yetki, sihirbaz (KK-1, KK-2, KK-3)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMenuAndAccess(MailOrderCase):

    def test_kk1_menu_new_linkin_hemen_sagi(self):
        menu = self.env.ref('sanal_pos.menu_sanal_pos_mail_order')
        new_link = self.env.ref('sanal_pos.menu_sanal_pos_new_link')
        root = self.env.ref('sanal_pos.menu_sanal_pos_root')
        self.assertEqual(menu.name, 'Mail Order')
        self.assertEqual(menu.parent_id, root)
        siblings = self.env['ir.ui.menu'].sudo().search(
            [('parent_id', '=', root.id), ('id', 'not in', (menu.id, new_link.id))])
        later = [m.sequence for m in siblings if m.sequence >= new_link.sequence]
        self.assertGreater(menu.sequence, new_link.sequence)
        self.assertTrue(all(menu.sequence < seq for seq in later), 'menü new_link ile sonraki kardeş arasında değil')
        action = self.env.ref('sanal_pos.action_sanal_pos_mail_order_wizard')
        self.assertEqual(action.res_model, MO_WIZARD)
        self.assertEqual(action.target, 'new')
        self.assertEqual(menu.action.id, action.id)

    def test_kk1_kk2_menu_gorunurlugu(self):
        Menu = self.env['ir.ui.menu']
        menu = self.env.ref('sanal_pos.menu_sanal_pos_mail_order')
        for user in (self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                self.assertIn(menu.id, Menu.with_user(user)._visible_menu_ids())
        self.assertNotIn(menu.id, Menu.with_user(self.user_plain)._visible_menu_ids())

    def test_acl_ve_kayit_kurali(self):
        Access = self.env['ir.model.access'].sudo()
        rows = Access.search([('model_id.model', '=', MO_WIZARD)])
        self.assertTrue(rows, 'sihirbaz için ACL satırı yok')
        for row in rows:
            self.assertTrue(row.group_id, 'grupsuz (herkese açık) ACL satırı: %s' % row.name)
            self.assertFalse(row.perm_unlink)
        groups = {row.group_id.id: row for row in rows}
        for xmlid in ('sanal_pos.group_sanal_pos_user', 'sanal_pos.group_sanal_pos_manager'):
            row = groups.get(self.env.ref(xmlid).id)
            self.assertTrue(row, xmlid)
            self.assertEqual((row.perm_read, row.perm_write, row.perm_create), (True, True, True))
        rules = self.env['ir.rule'].sudo().search([('model_id.model', '=', MO_WIZARD)])
        self.assertTrue(rules)
        for rule in rules:
            self.assertEqual(rule.domain_force.replace(' ', ''), "[('create_uid','=',user.id)]")

    def test_g8_provider_token_yalniz_yonetici_okur_link_adresi_calisir(self):
        payment = self.make_mail_order()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sp).read(['provider_token'])
        self.assertEqual(payment.with_user(self.user_mgr).read(['provider_token'])[0]['provider_token'],
                         payment.provider_token)                           # olumlu çapa
        # kardeş yol: link adresi (KK-17 ayarı açıkken) Sanal POS kullanıcısına hâlâ hesaplanır
        self.set_setting('paratika_show_link_url', True)
        link = self.make_payment(invoice_no='G8-LINK')
        self.assertIn(link.provider_token, link.with_user(self.user_sp).link_url or '')

    def test_baska_kullanici_sihirbazi_okuyamaz(self):
        wiz = self.mail_order_wizard(user=self.user_sp)
        self.assertEqual(wiz.with_user(self.user_sp).read(['invoice_no'])[0]['invoice_no'], INV_NO)
        with self.assertRaises(AccessError):
            wiz.with_user(self.user_sp2).read(['invoice_no'])

    def test_kk2_grupsuz_kullanici_olusturamaz_paratika_yok(self):
        """ACL açıkken bile (maskeleme yok) model koruması AccessError verir."""
        self.grant_plain(MO_WIZARD, 'sanal.pos.payment')
        wiz = self.env[MO_WIZARD].with_user(self.user_plain).create({'invoice_no': INV_NO})
        wiz.sudo()._write_fetched({
            'fetched': True, 'fetched_invoice_no': INV_NO, 'fetched_amount': 9000.0, 'amount': 9000.0,
            'customer_name': CUSTOMER_NAME})
        with self.assertRaises(AccessError) as ctx:
            wiz.action_create_mail_order()
        self.assertIn('Sanal POS kullanıcı yetkisi', str(ctx.exception))
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()
        # olumlu çapa: yetkili kullanıcı aynı kurulumla başarır
        self.assertIsNone(self.mo_attempt())
        self.assertEqual(len(self.payments()), 1)

    def test_kk2_grupsuz_kart_sayfasi_kapatma_kart_degerleri_yetkisiz(self):
        self.grant_plain('sanal.pos.payment')
        payment = self.make_mail_order()
        calls = (('action_open_card_page', ()), ('action_mail_order_close', ()),
                 ('_mail_order_card_values', ()))
        for method, args in calls:
            with self.subTest(method=method):
                with self.assertRaises(AccessError) as ctx:
                    getattr(payment.with_user(self.user_plain), method)(*args)
                self.assertIn('Sanal POS kullanıcı yetkisi', str(ctx.exception))
        self.assertNoParatikaCalls()
        self.assertEqual(self.reload(payment).state, 'sent')
        # olumlu çapa
        action = payment.with_user(self.user_sp).action_open_card_page()
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_rpc_yuzeyi(self):
        user_payment = self.env(user=self.user_sp)['sanal.pos.payment']
        for name in ('action_open_card_page', 'action_mail_order_close'):
            get_public_method(user_payment, name)              # çağrılabilir (olumlu)
        for name in ('_run_create_session', '_apply_session_result', '_mail_order_card_values',
                     '_mail_order_after_return'):
            with self.subTest(method=name):
                with self.assertRaises(AccessError):
                    get_public_method(user_payment, name)
        get_public_method(self.env(user=self.user_sp)[MO_WIZARD], 'action_create_mail_order')
        provider = self.env(user=self.user_mgr)[PROVIDER]
        for name in ('create_session', 'direct_post_url', 'query_installments'):
            with self.subTest(provider=name):
                with self.assertRaises(AccessError):
                    get_public_method(provider, name)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestWizardForm(MailOrderCase):

    def arch(self):
        return self.env[MO_WIZARD].with_user(self.user_sp).get_view(view_type='form')['arch']

    def test_kk3_gorunumde_kanal_ve_gecerlilik_alani_yok_uyari_var(self):
        arch = self.arch()
        for name in ('channel_sms', 'channel_email', 'expiry_hours'):
            self.assertNotIn('name="%s"' % name, arch)
        self.assertIn('name="invoice_no"', arch)               # olumlu çapa
        self.assertIn(WARNING_TEXT, plain_text(arch))

    def test_kk3_tutar_salt_okunur_ve_fatura_alanlari_dolar(self):
        self.assertTrue(self.env[MO_WIZARD]._fields['amount'].readonly)
        wiz = self.mail_order_wizard()
        self.assertEqual((wiz.amount, wiz.customer_name), (9000.0, CUSTOMER_NAME))
        self.assertTrue(wiz.fetched)
        self.assertIn('5321112233', wiz.customer_phone or '')

    def test_kk3_link_sihirbazi_formu_degismedi(self):
        arch = self.env[LINK_WIZARD].with_user(self.user_sp).get_view(view_type='form')['arch']
        for name in ('channel_sms', 'channel_email', 'expiry_hours'):
            self.assertIn('name="%s"' % name, arch)
        self.assertNotIn(WARNING_TEXT, plain_text(arch))

    def test_link_eylemi_mail_order_sihirbazinda_calismaz(self):
        wiz = self.mail_order_wizard(**BOTH)
        with self.assertRaises(UserError):
            wiz.action_create_link()
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()


# ======================================================================================
# KK-4, KK-5, KK-6, doğrulamalar
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestCreateMailOrder(MailOrderCase):

    def test_kk4_kayit_ve_tek_sessiontoken(self):
        mails_before = self.env['mail.mail'].sudo().search_count([])
        wiz = self.mail_order_wizard()
        result = wiz.action_create_mail_order()
        payments = self.payments()
        self.assertEqual(len(payments), 1)
        payment = payments
        self.assertEqual(payment.payment_method, 'mail_order')
        self.assertEqual(payment.state, 'sent')
        self.assertEqual((payment.invoice_no, payment.amount), (INV_NO, 9000.0))
        self.assertEqual((payment.attempt_no, payment.merchant_payment_id), (1, '%s-1' % INV_NO))
        self.assertEqual(payment.user_id, self.user_sp)
        self.assertEqual(payment.create_uid, self.user_sp)
        self.assertEqual(payment.provider_token, 'MOT-001')
        self.assertFalse(payment.channel_sms)
        self.assertFalse(payment.channel_email)
        self.assertEqual(payment.expiry_hours, 1)
        self.assertTrue(payment.sent_at)
        target = datetime.utcnow() + timedelta(minutes=60)
        self.assertLess(abs((payment.expires_at - target).total_seconds()), 120)
        # Paratika
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)
        self.assertEqual(self.link_calls(), 0)
        call = self.mock.last('SESSIONTOKEN')
        self.assertEqual(call.params['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertEqual(call.params['SESSIONTYPE'], 'PAYMENTSESSION')
        self.assertNotIn('NOTIFICATIONCHANNELS', call.params)
        self.assertEqual(call.probe['rows'].get(payment.merchant_payment_id), 'sending')
        self.assertGreaterEqual(call.probe['commits'], 1, 'dış çağrıdan önce kayıt commit edilmeli')
        # yönlendirme: aynı sekmede kart sayfası
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertEqual(result['url'], MAIL_ORDER_PAY_PATH % payment.id)
        self.assertEqual(result['target'], 'self')
        # müşteriye mesaj yok, denetim izi var
        self.assertEqual(self.env['mail.mail'].sudo().search_count([]), mails_before)
        self.assertIn('Mail order oturumu açıldı', self.chatter(payment))
        self.assertIn(self.user_sp.name, self.chatter(payment))

    def test_kk4_ikinci_deneme_numarasi(self):
        first = self.create_mail_order()
        # NEDEN: Paratika oturumu (sent_at + 1 saat) bitmiş olmalı; canlıysa aynı MPID yeniden
        # kullanılır (K-15, TestMpidReuse)
        first.sudo().write({'state': 'expired', 'sent_at': self.past(hours=2)})
        first.flush_recordset()
        second = self.create_mail_order()
        self.assertNotEqual(second, first)
        self.assertEqual((second.attempt_no, second.merchant_payment_id), (2, '%s-2' % INV_NO))
        self.assertEqual(self.mock.calls_for('SESSIONTOKEN')[-1].params['MERCHANTPAYMENTID'], '%s-2' % INV_NO)

    def test_kk5_tutar_degisti_kayit_ve_cagri_yok(self):
        wiz = self.mail_order_wizard()
        self.set_invoice(invoice_rows(total='9500.00'))
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_mail_order()
        self.assertIn('Fatura tutarı değişti', str(ctx.exception))
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()
        # olumlu çapa: faturayı yeniden getirince çalışır
        wiz.action_fetch_invoice()
        wiz.action_create_mail_order()
        self.assertEqual(self.last_payment().amount, 9500.0)

    def test_kk5_getirilmeden_olusturulamaz(self):
        wiz = self.mail_order_wizard(fetch=False)
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_mail_order()
        self.assertIn('Faturayı Getir', str(ctx.exception))
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()

    def test_kk5_istemci_tutar_ve_korumali_alan_yazamaz(self):
        wiz = self.mail_order_wizard()
        for vals in ({'fetched_amount': 1.0}, {'fetched_invoice_no': 'X'}, {'fetched': False}):
            with self.subTest(vals=vals):
                with self.assertRaises(UserError) as ctx:
                    wiz.write(vals)
                self.assertIn('Faturayı Getir', str(ctx.exception))
        try:
            wiz.write({'amount': 1.0})
        except (AccessError, UserError):
            pass
        wiz.action_create_mail_order()
        self.assertEqual(self.mock.last('SESSIONTOKEN').params['AMOUNT'], '9000.00')
        self.assertEqual(self.last_payment().amount, 9000.0)

    def test_kk6_cift_basma_tek_kayit_tek_cagri(self):
        wiz = self.mail_order_wizard()
        wiz.action_create_mail_order()
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_mail_order()
        self.assertIn(OPEN_MO, str(ctx.exception))
        self.assertEqual(len(self.payments()), 1)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)

    def test_kk6_iki_kullanici_ikisi_de_acik_sihirbazda(self):
        wiz1 = self.mail_order_wizard(user=self.user_sp)
        wiz2 = self.mail_order_wizard(user=self.user_sp2)
        wiz1.action_create_mail_order()
        with self.assertRaises(UserError) as ctx:
            wiz2.action_create_mail_order()
        message = str(ctx.exception.args[0])
        self.assertIn(OPEN_MO, message)
        self.assertIn(self.user_sp.name, message)
        self.assertEqual(len(self.payments()), 1)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)

    def test_kanal_ve_gecerlilik_istemciden_yok_sayilir(self):
        self.assertIsNone(self.mo_attempt(channel_sms=True, channel_email=True, expiry_hours=100))
        payment = self.last_payment()
        self.assertFalse(payment.channel_sms or payment.channel_email)
        self.assertEqual(payment.expiry_hours, 1)
        self.assertEqual(self.mock.last('SESSIONTOKEN').params['SESSIONEXPIRY'], '1h')

    def test_gecersiz_gecerlilik_degeri_engel_olmaz(self):
        for hours in (0, 500):
            with self.subTest(hours=hours):
                inv = self.new_invoice('EXP-%d' % hours)
                self.assertIsNone(self.mo_attempt(invoice_no=inv, expiry_hours=hours))
                self.assertEqual(self.last_payment(inv).expiry_hours, 1)

    def test_dogrulamalar(self):
        self.assertIn('Müşteri adı zorunludur.', self.mo_attempt(customer_name='') or '')
        self.assertIn('Geçerli bir e-posta adresi girin.', self.mo_attempt(customer_email='abc') or '')
        self.assertIsNotNone(self.mo_attempt(customer_phone='123'))
        self.assertFalse(self.payments())
        self.assertNoParatikaCalls()
        # olumlu çapa
        self.assertIsNone(self.mo_attempt())

    def test_telefon_ve_eposta_zorunlu_degil(self):
        self.assertIsNone(self.mo_attempt(email=None, customer_phone='', customer_email=''))
        params = self.mock.last('SESSIONTOKEN').params
        self.assertNotIn('CUSTOMEREMAIL', params)
        self.assertNotIn('CUSTOMERPHONE', params)
        payment = self.last_payment()
        self.assertFalse(payment.customer_email)
        self.assertFalse(payment.customer_phone)


# ======================================================================================
# KK-7: çift tahsilat engeli iki yönlü
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestDuplicateBlocks(MailOrderCase):

    def free(self, payment):
        # NEDEN: Paratika oturumu da bitmiş sayılır (sent_at pencere dışı); canlı oturumlu kapalı
        # mail order link'i engeller (K-15, TestMpidReuse.test_canli_mo_link_engeller)
        payment.sudo().write({'state': 'expired', 'sent_at': self.past(hours=2)})
        payment.flush_recordset()

    def test_a_acik_link_mail_orderi_engeller(self):
        for i, state in enumerate(('sending', 'sent', 'unknown'), start=1):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, attempt_no=i)
                self.mock.calls.clear()
                message = self.mo_attempt()
                self.assertIsNotNone(message, 'engellenmeliydi')
                self.assertIn(OPEN_LINK, message)
                self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
                self.assertEqual(len(self.payments()), i)
                self.free(payment)
        self.assertIsNone(self.mo_attempt())                       # olumlu çapa

    def test_b_acik_mail_order_linki_engeller(self):
        for i, state in enumerate(('sending', 'sent'), start=1):
            with self.subTest(state=state):
                extra = {'provider_token': False} if state == 'sending' else {}
                payment = self.make_mail_order(state=state, attempt_no=i, **extra)
                self.mock.calls.clear()
                message = self.link_attempt()
                self.assertIsNotNone(message, 'engellenmeliydi')
                self.assertIn(OPEN_MO, message)
                self.assertNotIn(OPEN_LINK, message)
                self.assertEqual(self.link_calls(), 0)
                self.assertEqual(len(self.payments()), i)
                self.free(payment)
        self.assertIsNone(self.link_attempt())                     # olumlu çapa

    def test_b_sihirbaz_on_bilgisi_yontemi_soyler(self):
        self.make_mail_order()
        wiz = self.env[LINK_WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO})
        wiz.action_fetch_invoice()
        self.assertIn(OPEN_MO, wiz.blocking_message or '')
        mo_wiz = self.mail_order_wizard()
        self.assertIn(OPEN_MO, mo_wiz.blocking_message or '')

    def test_c_odenmis_incelemede_iade_bekleyen(self):
        for i, state in enumerate(('paid', 'partial_refund', 'review', 'refund_pending'), start=1):
            for maker in (self.make_payment, self.make_mail_order):
                with self.subTest(state=state, maker=maker.__name__):
                    payment = maker(state=state, attempt_no=i * 2 + (maker == self.make_mail_order))
                    self.mock.calls.clear()
                    message = self.mo_attempt()
                    self.assertIn(PAID_PART, message or '')
                    self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
                    self.assertIn(PAID_PART, self.link_attempt() or '')
                    self.free(payment)

    def test_d_onceki_iade_onay_ister(self):
        for n, state in enumerate(('voided', 'refunded'), start=1):
            with self.subTest(state=state):
                # attempt_no=n*10: onayla açılan yeni deneme MAX+1 alır (1. turda 2); n ile 2. turdaki
                # sabit 2 çakışıp unique ihlali verirdi (test kurulum hatası, G3'te düzeltildi)
                payment = self.make_mail_order(state=state, attempt_no=n * 10, provider_tran_ref='T-OLD%d' % n)
                self.mock.calls.clear()    # 1. turdaki onaylı deneme 2. turun sayacını kirletmesin
                message = self.mo_attempt()
                self.assertIn('iade', message or '')
                self.assertNotIn(OPEN_MO, message)
                self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
                self.assertIsNone(self.mo_attempt(confirm_prior_refund=True))
                self.free(self.last_payment())
                self.free(payment)

    def test_db_indeksi_iki_yonde(self):
        self.make_mail_order(state='sent')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.make_payment(state='sent', attempt_no=2)
        self.assertEqual(len(self.payments()), 1)
        other = 'IDX-2'
        self.make_payment(state='sent', invoice_no=other)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.make_mail_order(invoice_no=other, attempt_no=2)

    def test_on_kontrol_atlatilsa_da_veritabani_engeller(self):
        Model = type(self.env['sanal.pos.payment'])
        self.make_payment(state='sent')
        with patch.object(Model, '_new_link_blocker', return_value=''):
            with self.assertRaises(UserError) as ctx:
                self.mail_order_wizard().action_create_mail_order()
        self.assertIn(OPEN_LINK, str(ctx.exception))
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(len(self.payments()), 1)

    def test_on_kontrol_atlatilsa_da_veritabani_engeller_ters_yon(self):
        Model = type(self.env['sanal.pos.payment'])
        self.make_mail_order(state='sent')
        with patch.object(Model, '_new_link_blocker', return_value=''):
            with self.assertRaises(UserError) as ctx:
                self.wizard(**BOTH).action_create_link()
        self.assertIn(OPEN_MO, str(ctx.exception))
        self.assertEqual(self.link_calls(), 0)
        self.assertEqual(len(self.payments()), 1)


# ======================================================================================
# K-15 (Ö-3/G-2): "Kapat" Paratika oturumunu bitiremez -> yeni deneme aynı MPID ile
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMpidReuse(MailOrderCase):

    def closed(self):
        """Kart sayfası açılmış (token verilmiş) ve personelce kapatılmış deneme."""
        payment = self.create_mail_order()
        payment.with_user(self.user_sp).action_mail_order_close()
        self.assertEqual(self.reload(payment).state, 'expired')
        self.old_token = payment.sudo().provider_token
        self.mock.calls.clear()
        return payment

    def assertUnchanged(self, payment, state='expired'):
        self.reload(payment)
        self.assertEqual(len(self.payments()), 1)
        self.assertEqual(payment.state, state)
        self.assertEqual(payment.sudo().provider_token, self.old_token)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)

    def test_kapat_sonra_ayni_mpid(self):
        payment = self.closed()
        self.assertIsNone(self.mo_attempt())
        self.assertEqual(self.payments(), payment)                       # yeni kayıt yok
        self.reload(payment)
        self.assertEqual((payment.state, payment.attempt_no, payment.merchant_payment_id),
                         ('sent', 1, '%s-1' % INV_NO))
        self.assertNotEqual(payment.sudo().provider_token, self.old_token)
        # önce eski MPID sorgulanır, sonra aynı MPID ile tek SESSIONTOKEN
        self.assertEqual(self.mock.actions, ['QUERYTRANSACTION', 'SESSIONTOKEN'])
        call = self.mock.last('SESSIONTOKEN')
        self.assertEqual(call.params['MERCHANTPAYMENTID'], '%s-1' % INV_NO)
        self.assertEqual(call.params['AMOUNT'], '9000.00')
        self.assertEqual(call.probe['rows'].get('%s-1' % INV_NO), 'sending')
        self.assertGreaterEqual(call.probe['commits'], 1, 'dış çağrıdan önce kayıt commit edilmeli')
        self.assertIn('Aynı ödeme numarasıyla', self.chatter(payment))
        # aynı kullanıcı, aynı müşteri bilgisi: önceki sahip / yok sayılan alan notu yok
        self.assertNotIn('Önceki deneme', self.chatter(payment))
        self.assertNotIn('kullanılmadı', self.chatter(payment))

    def test_eski_mpidde_onay_token_yok_odendi(self):
        payment = self.closed()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-OLD'))
        result = self.mail_order_wizard().action_create_mail_order()
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(self.payments(), payment)
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('Ödendi', result['params']['message'])
        # kardeş: tutar farklı onay -> inceleme, yine token yok
        other = self.new_invoice('REUSE-RV')
        self.set_query_transactions()
        self.create_mail_order(invoice_no=other)
        rv = self.last_payment(other)
        rv.with_user(self.user_sp).action_mail_order_close()
        self.set_query_transactions(tran('AP', 'SALE', '8000.00', 'PG-RV'))
        self.assertIsNone(self.mo_attempt(invoice_no=other))
        self.assertEqual(self.reload(rv).state, 'review')
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)              # yalnız rv'nin ilk oturumu

    def test_bekleyen_islem_engeller(self):
        payment = self.closed()
        self.set_query_transactions(tran('IP', 'SALE', '9000.00', 'PG-IP'))
        self.assertIn('devam eden bir işlem', self.mo_attempt() or '')
        self.assertUnchanged(payment)
        self.assertTrue(payment.sync_requested)               # sonuç cron'la toplanır (commit'li)

    def test_sorgu_yanitsiz_kaydi_degistirmez(self):
        payment = self.closed()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.assertIn('sorgulanamadı', self.mo_attempt() or '')
        self.assertUnchanged(payment)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_tutar_farkli_engel(self):
        payment = self.closed()
        self.set_invoice(invoice_rows(total='9500.00'))
        message = self.mo_attempt() or ''
        self.assertIn('tutarı/müşteri kodu değişmiş', message)
        self.assertIn(payment._live_session_end_local(), message)
        self.assertUnchanged(payment)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_pencere_bitince_yeni_mpid(self):
        payment = self.closed()
        payment.sudo().write({'sent_at': self.past(minutes=61)})
        payment.flush_recordset()
        self.assertIsNone(self.mo_attempt())
        new = self.last_payment()
        self.assertNotEqual(new, payment)
        self.assertEqual((new.attempt_no, new.merchant_payment_id), (2, '%s-2' % INV_NO))
        self.assertEqual(self.mock.last('SESSIONTOKEN').params['MERCHANTPAYMENTID'], '%s-2' % INV_NO)
        self.assertEqual(self.reload(payment).state, 'expired')

    def test_oturum_hatasi_sonrasi_ayni_mpid(self):
        payment = self.closed()
        sent_at = payment.sent_at
        self.mock.queue('SESSIONTOKEN', err_body('ERR77777', 'Beklenmeyen sorun'))
        self.assertIsNone(self.mo_attempt())
        self.reload(payment)
        self.assertEqual(self.payments(), payment)
        self.assertEqual(payment.state, 'error')
        self.assertEqual(payment.sent_at, sent_at)        # son verilen token'ın zamanı korunur
        # sonraki deneme yine aynı kayıt / aynı MPID
        self.assertIsNone(self.mo_attempt())
        self.assertEqual((self.reload(payment).state, len(self.payments())), ('sent', 1))
        mpids = [c.params['MERCHANTPAYMENTID'] for c in self.mock.calls_for('SESSIONTOKEN')]
        self.assertEqual(mpids, ['%s-1' % INV_NO] * 2)

    def test_canli_mo_link_engeller(self):
        payment = self.closed()
        message = self.link_attempt() or ''
        self.assertIn('saatine kadar geçerli', message)
        self.assertIn(payment._live_session_end_local(), message)
        self.assertEqual(self.link_calls(), 0)
        wiz = self.env[LINK_WIZARD].with_user(self.user_sp).create({'invoice_no': INV_NO})
        wiz.action_fetch_invoice()
        self.assertIn('saatine kadar geçerli', wiz.blocking_message or '')
        # mail order sihirbazı engellenmez (aynı MPID ile yeniden açar)
        self.assertFalse(self.mail_order_wizard().blocking_message)
        # olumlu çapa: oturum bitince link açılır
        payment.sudo().write({'sent_at': self.past(hours=2)})
        payment.flush_recordset()
        self.assertIsNone(self.link_attempt())

    def test_kilit_mesgul_busy(self):
        payment = self.closed()
        Model = type(self.env['sanal.pos.payment'])
        with patch.object(Model, '_lock_for_provider_call', return_value=False):
            message = self.mo_attempt() or ''
        self.assertEqual(message, BUSY_MSG)
        self.assertUnchanged(payment)
        self.assertEqual(self.mock.calls, [])

    def test_yeniden_acilan_kayit_bayat_sayilmaz(self):
        # B: commit ile kilit arasında yeniden açılmış kayıt; create_date eski denemenin zamanı
        payment = self.closed()
        reopened = self.mail_order_wizard()._create_sending_payment('mail_order')
        self.assertEqual((reopened, reopened.state), (payment, 'sending'))
        self.env.cr.execute('UPDATE sanal_pos_payment SET create_date = %s WHERE id = %s',
                            [self.past(hours=2), payment.id])
        payment.invalidate_recordset()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'sending')
        with self.assertRaises(UserError) as ctx:
            payment.with_user(self.user_sp).action_check_status()
        self.assertEqual(str(ctx.exception.args[0]), BUSY_MSG)
        # olumlu çapa: yeniden açılma da 5 dk'dan eskiyse yarıda kalmış sayılır
        self.set_create_date(payment, self.past(minutes=10))
        self.run_cron(CRON_SYNC)
        self.assertEqual((self.reload(payment).state, payment.last_error_code), ('error', 'STALE_SENDING'))

    def age(self, payment, minutes):
        """Zaman geçer: kayıt yazımı ve son sorgu ``minutes`` dakika önce."""
        when = self.past(minutes=minutes)
        self.set_create_date(payment, when)
        self.env.cr.execute('UPDATE sanal_pos_payment SET last_checked_at = %s WHERE id = %s',
                            [when, payment.id])
        payment.invalidate_recordset()
        return when

    def test_bildirim_bayragi_bayatlamayi_engellemez(self):
        # Y-1: yarıda kalmış yeniden açma; Paratika dönüş bildirimleri bayrak yazar
        payment = self.closed()
        self.mail_order_wizard()._create_sending_payment('mail_order')
        self.assertEqual(self.reload(payment).state, 'sending')
        mpid = payment.merchant_payment_id
        Payment = self.env['sanal.pos.payment']
        self.age(payment, 10)
        Payment._mark_sync_requested(mpid)                     # ilk bildirim: bayrak yazımı
        self.assertTrue(self.reload(payment).sync_requested)
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'sending')  # yazım yaşı yeniledi (DIKKAT)
        when = self.age(payment, 10)
        Payment._mark_sync_requested(mpid)                     # tekrarlanan bildirim yazmaz
        self.assertEqual(self.reload(payment).write_date, when)
        self.run_cron(CRON_SYNC)
        self.assertEqual((self.reload(payment).state, payment.last_error_code),
                         ('error', 'STALE_SENDING'))

    def test_baska_kullanicinin_denemesi_hesap_verebilir(self):
        # güvenlik önerisi: sudo ile başkasının denemesi açılır; önceki sahip yazılır ve bildirilir
        payment = self.closed()
        self.assertEqual(payment.user_id, self.user_sp)
        self.assertIsNone(self.mo_attempt(user=self.user_sp2))
        self.reload(payment)
        self.assertEqual((payment.state, payment.user_id), ('sent', self.user_sp2))
        note = 'Önceki deneme %s tarafından başlatılmıştı' % self.user_sp.name
        self.assertIn(note, self.chatter(payment))
        self.assertIn(note, self.notification_texts(payment, self.user_sp.partner_id))
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))
        # kardeş: aynı kullanıcı yeniden açınca önceki sahip notu/bildirimi yok
        payment.with_user(self.user_sp2).action_mail_order_close()
        self.assertIsNone(self.mo_attempt(user=self.user_sp2))
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertEqual(self.chatter(payment).count('Önceki deneme'), 1)
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))

    def test_yeniden_acmada_musteri_bilgisi_sessiz_degil(self):
        # Y-5: sihirbaz önceden uyarır; farklı girilen alanlar notta listelenir
        fresh = self.mail_order_wizard(invoice_no=self.new_invoice('REUSE-Y5'))
        self.assertFalse(fresh.reuse_notice)                   # önceki deneme yok -> uyarı yok
        payment = self.closed()
        old_name = payment.customer_name
        wiz = self.mail_order_wizard(customer_name='Başka Müşteri')
        self.assertIn(payment.name, wiz.reuse_notice)
        self.assertIn('burada yaptığınız değişiklikler kullanılmaz', wiz.reuse_notice)
        wiz.action_create_mail_order()
        self.reload(payment)
        self.assertEqual((payment.state, payment.customer_name), ('sent', old_name))
        self.assertIn('Sihirbazda girilen farklı bilgiler kullanılmadı: Müşteri Adı.',
                      self.chatter(payment))


# ======================================================================================
# KK-8 kart sayfasını yeniden açma, kart değerleri
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestOpenCardPage(MailOrderCase):

    def test_kk8_ayni_token_yeni_sessiontoken_yok(self):
        payment = self.create_mail_order()
        self.mock.calls.clear()
        action = payment.with_user(self.user_sp2).action_open_card_page()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['url'], MAIL_ORDER_PAY_PATH % payment.id)
        self.assertEqual(action['target'], 'self')
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertNoParatikaCalls()
        self.assertEqual(self.reload(payment).provider_token, 'MOT-001')

    def test_kk8_uygunsuz_durumlar_reddedilir(self):
        self.make_mail_order(invoice_no='OK-1')                    # olumlu çapa kaydı
        cases = {
            'suresi_dolmus': dict(expires_at=self.past(minutes=5)),
            'odendi': dict(state='paid'),
            'hata': dict(state='error'),
            'expired': dict(state='expired'),
            'gonderiliyor': dict(state='sending'),
        }
        for name, vals in cases.items():
            with self.subTest(case=name):
                payment = self.make_mail_order(invoice_no='C-%s' % name, **vals)
                with self.assertRaises(UserError):
                    payment.with_user(self.user_sp).action_open_card_page()
        link = self.make_payment(invoice_no='C-link')
        with self.assertRaises(UserError):
            link.with_user(self.user_sp).action_open_card_page()
        self.assertNoParatikaCalls()

    def test_kart_degerleri_form_action_ve_kartsiz_taksit_sorgusu(self):
        self.mock.queue('QUERYINSTALLMENT', installment_body(('AXESS', 'AXESS', [(1, 0), (3, 1.5)])))
        payment = self.make_mail_order(provider_token='TOK-CARD')
        values = payment.with_user(self.user_sp)._mail_order_card_values()
        self.assertEqual(values['form_action'], TEST_URL_PREFIX + '/post/sale3d/TOK-CARD')
        self.assertEqual(self.mock.actions, ['QUERYINSTALLMENT'])
        self.assertEqual([k for k in self.mock.last('QUERYINSTALLMENT').params if k.upper().startswith('CARD')], [])
        paid = self.make_mail_order(state='paid', invoice_no='PD-1')
        with self.assertRaises(UserError):
            paid.with_user(self.user_sp)._mail_order_card_values()


# ======================================================================================
# KK-9, KK-10, KK-12, KK-13, KK-14 senkron ve hata durumları
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestSyncAndErrors(MailOrderCase):

    def test_kk9_odendi_notu_ve_alanlar(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-MO1', installments=3, last4='4242'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual((payment.provider_tran_ref, payment.paid_amount, payment.installment_count,
                          payment.card_last4), ('PG-MO1', 9000.0, 3, '4242'))
        self.assertTrue(payment.paid_at)
        note = self.chatter(payment)
        self.assertIn('Mail order ödemesi alındı', note)
        self.assertIn('9.000,00', note)
        self.assertIn('4242', note)
        self.assertIn(self.user_sp.name, note)
        self.assertEqual(self.link_calls(), 0)
        self.assertIn(self.user_sp.partner_id, self.notified_partners(payment))

    def test_kk9_link_odeme_notu_degismedi(self):
        payment = self.make_payment()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LNK', installments=1, last4='4242'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertNotIn('Mail order ödemesi alındı', self.chatter(payment))

    def test_kk9_dongu_cron_ile_de_odenir(self):
        payment = self.make_mail_order(sync_requested=True)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-MO2'))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(self.link_calls(), 0)

    def test_kk9_tutar_farkli_inceleme(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '8500.00', 'PG-MO3'))
        self.assertEqual(self.sync(payment).state, 'review')

    def test_kk10_reddedilen_kart_acik_kalir_ve_hata_kaydi(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-F1', errorCode='ERR20051',
                                         errorMsg='Yetersiz limit'))
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.failed_attempt_count, 1)
        self.assertEqual(payment.last_error_code, 'ERR20051')
        self.assertTrue(payment.last_error_message)
        self.assertNotIn('Kart denemesi başarısız', payment.last_error_message)
        self.assertNotEqual(payment.state, 'paid')
        # aynı işlem tekrar sorgulanınca sayaç şişmez
        self.sync(payment)
        self.assertEqual(payment.failed_attempt_count, 1)

    def test_kk10_son_hata_islem_zamanina_gore_secilir(self):
        # Ö-4: Paratika listeyi yeniden eskiye verse de "son hata" en yeni işlemin nedenidir
        payment = self.make_mail_order()
        self.set_query_transactions(
            tran('FA', 'SALE', '9000.00', 'PG-N', errorCode='ERR20051', errorMsg='Yetersiz limit',
                 timeCreated='2026-10-22 10:05:00'),
            tran('FA', 'SALE', '9000.00', 'PG-O', errorCode='ERR20054', errorMsg='Hatali CVV',
                 timeCreated='2026-10-22 10:00:00'))
        self.sync(payment)
        self.assertEqual(payment.failed_attempt_count, 2)
        # mesaj biçimi KK-10 normalizasyonu ('<mesaj> (<kod>)'); kod ve metin en yeni işleminki
        self.assertEqual((payment.last_error_code, payment.last_error_message),
                         ('ERR20051', 'Yetersiz limit (ERR20051)'))

    def test_kk10_link_davranisi_degismedi(self):
        payment = self.make_payment()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-F2', errorCode='ERR20051',
                                         errorMsg='Yetersiz limit'))
        self.sync(payment)
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(payment.failed_attempt_count, 1)
        self.assertEqual(payment.last_error_code, 'CARD_FAILED')

    def test_kk12_oturum_hatalari_error_unknown_degil(self):
        variants = {
            'timeout': timeout_exc(), 'baglanti': connection_exc(),
            'http500': RawResponse(500, 'hata'), 'html200': RawResponse(200, '<html>x</html>'),
            'token_yok': ok_body(),
        }
        for name, response in variants.items():
            with self.subTest(variant=name):
                inv = self.new_invoice('K12-%s' % name)
                self.mock.calls.clear()
                self.mock.queue('SESSIONTOKEN', response)
                wiz = self.mail_order_wizard(invoice_no=inv)
                result = wiz.action_create_mail_order()
                payment = self.last_payment(inv)
                self.assertEqual(payment.state, 'error')
                self.assertNotEqual(payment.state, 'unknown')
                self.assertIn(SESSION_FAIL_MSG, self.blob(payment) + str(result))
                if isinstance(result, dict):
                    self.assertNotEqual(result.get('type'), 'ir.actions.act_url')
                self.assertEqual(self.link_calls(), 0)
                # hemen yeni deneme açılabilir
                self.assertIsNone(self.mo_attempt(invoice_no=inv))
                again = self.last_payment(inv)
                self.assertEqual((again.attempt_no, again.state), (2, 'sent'))

    def test_kk12_oturum_hatasi_sonrasi_cron_unknown_yapmaz(self):
        self.mock.queue('SESSIONTOKEN', timeout_exc())
        self.mail_order_wizard().action_create_mail_order()
        payment = self.last_payment()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'error')
        self.assertEqual(self.link_calls(), 0)

    def test_kk13_yapilandirma_hatalari_turkce(self):
        from odoo.addons.sanal_pos.models.provider_paratika import ERROR_MESSAGES
        for code in ('ERR10136', 'ERR10266', 'ERR10047', 'ERR10053', 'ERR10154'):
            with self.subTest(code=code):
                inv = self.new_invoice('K13-%s' % code)
                self.mock.queue('SESSIONTOKEN', err_body(code, 'English text'))
                self.mail_order_wizard(invoice_no=inv).action_create_mail_order()
                payment = self.last_payment(inv)
                self.assertEqual(payment.state, 'error')
                self.assertEqual(payment.last_error_code, code)
                self.assertTrue(ERROR_MESSAGES.get(code), 'ERROR_MESSAGES[%s] eksik' % code)
                self.assertIn(ERROR_MESSAGES[code], self.blob(payment))
                self.assertNotIn('English text', payment.last_error_message or '')

    def test_kk13_bilinmeyen_kod_mesaj_ve_kod(self):
        self.mock.queue('SESSIONTOKEN', err_body('ERR77777', 'Beklenmeyen sorun'))
        self.mail_order_wizard().action_create_mail_order()
        payment = self.last_payment()
        self.assertEqual(payment.state, 'error')
        self.assertIn('Beklenmeyen sorun', payment.last_error_message)
        self.assertIn('ERR77777', payment.last_error_message)

    def test_kk14_suresi_dolunca_expired_ve_yeni_deneme(self):
        # NEDEN: gerçekçi fikstür: süresi 30 dk önce dolan 1 saatlik oturum 90 dk önce açılmıştır
        # (sent_at canlı pencere dışında -> yeni MPID; canlıysa K-15 aynı MPID'yi kullanır)
        payment = self.make_mail_order(expires_at=self.past(minutes=30), sent_at=self.past(minutes=90))
        self.assertEqual(self.sync(payment).state, 'expired')
        self.assertIsNone(self.mo_attempt())
        self.assertEqual(self.last_payment().attempt_no, 2)
        self.assertNotEqual(self.last_payment(), payment)

    def test_kk14_suresi_gecmemis_sent_kalir(self):
        payment = self.make_mail_order()
        self.assertEqual(self.sync(payment).state, 'sent')

    def test_kk14_cron_ile_expired(self):
        payment = self.make_mail_order(expires_at=self.past(minutes=30))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'expired')
        self.assertEqual(self.link_calls(), 0)

    def test_kk14_bekleyen_islem_varsa_sent_kalir(self):
        payment = self.make_mail_order(expires_at=self.past(minutes=30))
        self.set_query_transactions(tran('IP', 'SALE', '9000.00', 'PG-IP'))
        self.assertEqual(self.sync(payment).state, 'sent')

    def test_kk14_gec_odeme_inceleme(self):
        payment = self.make_mail_order(state='expired', expires_at=self.past(minutes=30))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LATE'))
        self.sync(payment)
        self.assertEqual(payment.state, 'review')
        self.assertEqual(payment.last_error_code, 'REVIEW_LATE')

    def test_apply_session_result_birim(self):
        payment = self.make_mail_order(state='sending', provider_token=False, sent_at=False, expires_at=False)
        provider = self.env[PROVIDER]
        payment.sudo()._apply_session_result(provider._result(ok=True, token='TOK-UNIT'))
        self.assertEqual((payment.state, payment.provider_token), ('sent', 'TOK-UNIT'))
        self.assertTrue(payment.sent_at)
        self.assertLess(abs((payment.expires_at - (datetime.utcnow() + timedelta(hours=1))).total_seconds()), 120)
        for i, result in enumerate((provider._result(ok=False, timeout=True, error_code='TIMEOUT'),
                                    provider._result(ok=True),                       # token yok
                                    provider._result(ok=False, error_code='ERR10136', error_message='x'))):
            with self.subTest(result=i):
                p = self.make_mail_order(state='sending', provider_token=False, sent_at=False,
                                         expires_at=False, invoice_no='AU-%d' % i)
                p.sudo()._apply_session_result(result)
                self.assertEqual(p.state, 'error')

    def test_run_create_session_beklenmeyen_istisna_error_ve_pan_loglanmaz(self):
        payment = self.make_mail_order(state='sending', provider_token=False, sent_at=False, expires_at=False)
        Provider = type(self.env[PROVIDER])
        boom = RuntimeError('kart %s patladi' % LEAK_PAN)
        with self.capture_logs() as records:
            with patch.object(Provider, 'create_session', side_effect=boom):
                payment.sudo()._run_create_session()
        self.assertEqual(self.reload(payment).state, 'error')
        self.assertNotIn(LEAK_PAN, '\n'.join(records))
        self.assertNotIn(LEAK_PAN, self.chatter(payment))


# ======================================================================================
# Bayat sending, unknown, KK-15, KK-16, KK-21
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestLifecycleBranches(MailOrderCase):

    def stale(self, maker, **vals):
        payment = maker(state='sending', provider_token=False, sent_at=False, expires_at=False, **vals)
        self.set_create_date(payment, datetime.utcnow() - timedelta(minutes=10))
        return payment

    def test_bayat_sending_mail_order_error(self):
        payment = self.stale(self.make_mail_order, invoice_no='ST-MO')
        fresh = self.make_mail_order(state='sending', provider_token=False, sent_at=False,
                                     expires_at=False, invoice_no='ST-FRESH')
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.reload(payment).state, 'error')
        self.assertIn('Mail order oturumu açılamadı (istek yarıda kaldı)', self.chatter(payment))
        self.assertEqual(self.reload(fresh).state, 'sending')
        self.assertEqual(self.link_calls(), 0)

    def test_bayat_sending_dugme_ile_error(self):
        payment = self.stale(self.make_mail_order, invoice_no='ST-BTN')
        payment.with_user(self.user_sp).action_check_status()
        self.assertEqual(self.reload(payment).state, 'error')
        self.assertEqual(self.link_calls(), 0)
        self.assertIsNone(self.mo_attempt(invoice_no=self.new_invoice('ST-BTN')))

    def test_bayat_sending_link_unknown_yolu_korunur(self):
        payment = self.stale(self.make_payment, invoice_no='ST-LNK')
        self.run_cron(CRON_SYNC)
        self.assertIn(self.reload(payment).state, ('unknown', 'sent', 'error'))
        self.assertNotEqual(payment.state, 'sending')
        self.assertNotIn('Mail order oturumu açılamadı', self.chatter(payment))

    def test_unknown_mail_order_find_link_cagrilmaz(self):
        payment = self.make_mail_order(state='unknown', provider_token=False, sent_at=False, expires_at=False,
                                       unknown_since=datetime.utcnow() - timedelta(minutes=20))
        self.run_cron(CRON_SYNC)
        payment.with_user(self.user_sp).action_check_status()
        self.assertEqual(self.link_calls(), 0)

    # -- KK-15
    def test_kk15_link_eylemleri_mail_orderda_reddedilir(self):
        payment = self.make_mail_order()
        for method, args in (('action_resend', (['sms'],)), ('action_cancel_link', ()), ('action_new_link', ())):
            with self.subTest(method=method):
                with self.assertRaises(UserError):
                    getattr(payment.with_user(self.user_sp), method)(*args)
        self.assertEqual(self.link_calls(), 0)
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertFalse(payment.can_resend)

    def test_kk15_link_url_bos_ayar_acikken_bile(self):
        self.set_setting('paratika_show_link_url', True)
        mo = self.make_mail_order()
        link = self.make_payment(invoice_no='LNK-URL')
        self.assertTrue(self.reload(link).link_url)                # olumlu çapa
        self.assertFalse(self.reload(mo).link_url)

    def test_kk15_link_olmayan_yol_link_kaydinda_calisir(self):
        link = self.make_payment()
        link.with_user(self.user_sp).action_resend(['sms'])
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENTRESEND'), 1)
        self.assertTrue(link.can_resend)

    def test_kk15_tum_akis_boyunca_link_cagrisi_yok(self):
        payment = self.create_mail_order()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-X', errorCode='ERR20051'))
        self.sync(payment)
        payment.with_user(self.user_sp).action_check_status()
        self.run_cron(CRON_SYNC)
        payment.with_user(self.user_sp).action_mail_order_close()
        self.assertEqual(self.link_calls(), 0)

    # -- KK-16
    def test_kk16_iptal_ve_iade_link_ile_ayni(self):
        void = self.make_paid(self.make_mail_order(invoice_no='V-1'))
        void.with_user(self.user_mgr).action_void('Müşteri vazgeçti')
        call = self.mock.last('VOID')
        self.assertEqual(call.params['PGTRANID'], 'T1')
        self.assertEqual(self.reload(void).state, 'voided')
        refund = self.make_paid(self.make_mail_order(invoice_no='R-1'))
        refund.with_user(self.user_mgr).action_refund(100.0, 'Müşteri talebi')
        rcall = self.mock.last('REFUND')
        self.assertEqual(rcall.params['PGTRANID'], 'T1')
        self.assertEqual(self.reload(refund).state, 'refund_pending')
        line = refund.refund_ids
        self.assertEqual((len(line), line.state), (1, 'pending_approval'))

    def test_kk16_kullanici_grubu_iade_yapamaz(self):
        payment = self.make_paid(self.make_mail_order())
        for method, args in (('action_void', ('x' * 10,)), ('action_refund', (100.0, 'Müşteri talebi'))):
            with self.subTest(method=method):
                with self.assertRaises(AccessError):
                    getattr(payment.with_user(self.user_sp), method)(*args)
        self.assertEqual(self.mock.count('VOID', 'REFUND'), 0)

    # -- KK-21
    def close(self, payment, user=None):
        return payment.with_user(user or self.user_sp).action_mail_order_close()

    def test_kk21_satis_yok_expired_ve_yeni_deneme(self):
        payment = self.create_mail_order()
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'expired')
        self.assertLessEqual(payment.expires_at, datetime.utcnow() + timedelta(seconds=5))
        self.assertIsNone(self.mo_attempt())
        # K-15: "Kapat" Paratika oturumunu bitiremez; yeni deneme aynı kayıt ve aynı MPID ile
        self.assertEqual(self.last_payment(), payment)
        self.assertEqual(len(self.payments()), 1)
        self.assertEqual((self.reload(payment).state, payment.attempt_no, payment.merchant_payment_id),
                         ('sent', 1, '%s-1' % INV_NO))
        mpids = [c.params['MERCHANTPAYMENTID'] for c in self.mock.calls_for('SESSIONTOKEN')]
        self.assertEqual(mpids, ['%s-1' % INV_NO] * 2)
        self.assertEqual(self.link_calls(), 0)

    def test_kk21_reddedilmis_deneme_expired(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('FA', 'SALE', '9000.00', 'PG-F'))
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'expired')

    def test_kk21_onayli_satis_varsa_paid(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-AP'))
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'paid')

    def test_kk21_tutar_farkli_inceleme(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '8000.00', 'PG-AP2'))
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'review')

    def test_kk21_bekleyen_islem_varsa_kapanmaz(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('IP', 'SALE', '9000.00', 'PG-IP'))
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'sent')
        message = self.mo_attempt()
        self.assertIn(OPEN_MO, message or '')

    def test_kk21_sorgu_yanitsizsa_durum_degismez(self):
        payment = self.make_mail_order()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.close(payment)
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertIn(OPEN_MO, self.mo_attempt() or '')

    def test_kk21_uygunsuz_kayitlar_reddedilir(self):
        cases = (self.make_payment(invoice_no='CL-LINK'),
                 self.make_mail_order(state='error', invoice_no='CL-ERR'),
                 self.make_mail_order(state='expired', invoice_no='CL-EXP'),
                 self.make_paid(self.make_mail_order(invoice_no='CL-PAID')))
        for payment in cases:
            with self.subTest(invoice=payment.invoice_no):
                with self.assertRaises(UserError):
                    self.close(payment)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)


# ======================================================================================
# KK-19: liste / arama / form
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestViews(MailOrderCase):

    def view(self, view_type):
        return self.env['sanal.pos.payment'].with_user(self.user_sp).get_view(view_type=view_type)['arch']

    def test_kk19_liste_ve_arama(self):
        self.assertIn('name="payment_method"', self.view('list'))
        search = self.view('search')
        self.assertRegex(search, r"payment_method[^\"]{0,12}mail_order")
        self.assertRegex(search, r"payment_method[^\"]{0,12}'link'")
        # Yöntem etiketi
        label = dict(self.env['sanal.pos.payment']._fields['payment_method'].selection)
        self.assertEqual(label['mail_order'], 'Mail Order')

    def test_kk19_form_dugmeleri_ve_gizleme(self):
        arch = self.view('form')
        self.assertIn('name="payment_method"', arch)
        for name in ('action_open_card_page', 'action_mail_order_close'):
            self.assertRegex(arch, r'<button[^>]*name="%s"' % name)
        for name in ('action_resend', 'action_cancel_link', 'action_new_link'):
            tags = re.findall(r'<button[^>]*name="%s"[^>]*>' % name, arch)
            self.assertTrue(tags, name)
            for tag in tags:
                self.assertIn('payment_method', tag, '%s mail order kaydında gizlenmiyor' % name)
        self.assertRegex(arch, r'invisible="[^"]*payment_method')

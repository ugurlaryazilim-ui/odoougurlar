# -*- coding: utf-8 -*-
"""Mail Order Aşama 3 kabul testleri: sonuç sayfası, red nedenleri, deneme geçmişi, art arda başarısız
deneme sınırı, Tekrar dene / Bunun yerine link gönder (KK-3.1 ... KK-3.9, K-15, K-17).

Kaynak: .ekip/20261023-mo-kart-pro/01-gereksinimler.md (Aşama 3), 02-tasarim.md §5. Testler koddan ÖNCE
yazıldı: tasarımdaki adlar kullanılır (``sanal.pos.payment.attempt``, ``_mail_order_attempt_block``,
``action_mail_order_retry``, ``action_mail_order_to_link``, ``POST /sanal_pos/mail_order/retry|link/<id>``).

* Model henüz yoksa sınıf düzeyinde hiçbir şey patlamaz: ilgili test ``assertIn(model, registry)`` ile düşer.
* Paratika taklit edilir (ağ yok). Sonuç sayfası durumu, kayıt ``sent`` iken ve en yeni deneme ``failed``
  ise "reddedildi" olur; sorgu atlansın diye ``last_checked_at`` gelecekte tutulur (NFR-3.1 10 sn kuralı).
* Tarayıcı davranışı (görünüm, tıklama, geri düğmesi) burada SINANAMAZ: 04-kabul-testleri.md
  "Aşama 3 - elle doğrulanacak".
"""
import json
import re
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import patch

from lxml import html as lxml_html

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import (
    CUSTOMER_NAME, EMAIL, INV_NO, LEAK_PAN, MAIL_ORDER_BIN_PATH, MAIL_ORDER_PAY_PATH,
    MAIL_ORDER_RESULT_PATH, SanalPosCase, querybin_body, timeout_exc, tran,
)
from .test_mail_order_http import CSS_HREF_RE, LINK_ACTIONS, PAYMENT_LIST, MoHttpCase

ATTEMPT = 'sanal.pos.payment.attempt'
RETRY_PATH = '/sanal_pos/mail_order/retry/%d'
LINK_PATH = '/sanal_pos/mail_order/link/%d'
PAYMENT = 'sanal.pos.payment'
LIMIT_MSG = ('Bu fatura için 3 başarısız kart denemesi yapıldı; güvenlik nedeniyle mail order 24 saat '
             'kapalı. Müşteriye ödeme linki gönderin.')
REASON_51 = 'Yetersiz bakiye/limit'
ADVICE_51 = 'Başka kart ya da daha az taksit'
CARD_INPUTS = {'pan', 'cvv', 'cardOwner', 'expiryMonth', 'expiryYear', 'installmentCount'}

# 01-gereksinimler §KK-3.3 asgari eşleme tablosu: kod -> (Türkçe neden, öneri)
DECLINE_TABLE = {
    'ERR20005': ('Banka işlemi onaylamadı', 'Müşteri bankasını arasın ya da başka kart'),
    'ERR20012': ('Geçersiz işlem', 'Başka kart deneyin'),
    'ERR20051': (REASON_51, ADVICE_51),
    'ERR20054': ('Kartın süresi dolmuş', 'SKT\'yi kontrol edin'),
    'ERR20057': ('Kart bu işleme kapalı', 'Müşteri bankasından açtırsın'),
    'ERR20082': ('Güvenlik kodu (CVV) hatalı', 'CVV\'yi yeniden alın'),
    'ERR20084': ('Güvenlik kodu (CVV) hatalı', 'CVV\'yi yeniden alın'),
    'ERR20093': ('Kart internet işlemine kapalı', 'Müşteri bankasından açtırsın'),
    'ERR20099': ('Banka geçici hata', 'Birkaç dakika sonra tekrar deneyin'),
    'ERR200YK': ('Kart bankaca engelli', 'Başka kart'),
    'ERR200GK': ('Yabancı kartlar kapalı', 'Yurt içi kart'),
    'ERR30002': ('3D doğrulama tamamlanmadı', 'SMS kodunu yeniden girin'),
    'ERR30004': ('Dolandırıcılık kuralı reddi', 'Link gönderin'),
    'ERR30005': ('Bankadan 3D yanıtı gelmedi', 'Tekrar deneyin'),
    'CA': ('Banka doğrulaması iptal edildi', 'Tekrar deneyin'),
}
ALL_ADVICE = sorted({advice for _reason, advice in DECLINE_TABLE.values()}, key=len, reverse=True)


def norm(text):
    return ' '.join((text or '').split())


def iso_ago(minutes):
    """Paratika ``timeCreated`` (saat dilimli ISO; _parse_time naive UTC'ye çevirir)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def fail_tran(ref, code='ERR20051', status='FA', minutes_ago=None, **extra):
    if code:
        extra.setdefault('errorCode', code)
        extra.setdefault('errorMsg', 'banka mesaji')
    if minutes_ago is not None:
        extra['timeCreated'] = iso_ago(minutes_ago)
    return tran(status, 'SALE', '9000.00', ref, **extra)


def utc_ago(**delta):
    return datetime.utcnow().replace(microsecond=0) - timedelta(**delta)


def utc_ahead(**delta):
    return datetime.utcnow().replace(microsecond=0) + timedelta(**delta)


# ======================================================================================
# Ortak yardımcılar
# ======================================================================================
class ResultMixin:
    """Deneme satırı üretimi, sonuç sayfası/POST yardımcıları. Yeni yardımcı değil: common/MoHttpCase üstüne."""

    _attempt_seq = count(1)

    # -- model ----------------------------------------------------------------------
    def reload(self, record):
        record.invalidate_recordset()
        return record

    def link_calls(self):
        return self.mock.count(*LINK_ACTIONS)

    def attempt_model(self):
        self.assertIn(ATTEMPT, self.env.registry, 'Aşama 3: %s modeli yok (K-17)' % ATTEMPT)
        return self.env[ATTEMPT].sudo()

    def add_attempt(self, payment, status='failed', ago=None, ref=None, code='ERR20051', reason=REASON_51,
                    last4='1234', installments=1, user=None):
        """Doğrudan deneme satırı (``_record_attempts`` yolunun çıktısı); ``ago``: timedelta ya da dakika."""
        model = self.attempt_model()
        if ago is None:
            ago = timedelta(minutes=5)
        elif not isinstance(ago, timedelta):
            ago = timedelta(minutes=ago)
        values = {
            'payment_id': payment.id,
            'tran_ref': ref or 'AT-%d' % next(self._attempt_seq),
            'tran_time': datetime.utcnow().replace(microsecond=0) - ago,
            'status': status,
            'error_code': code if status in ('failed', 'cancelled') else False,
            'reason': reason if status in ('failed', 'cancelled') else False,
            'installment_count': installments,
            'card_last4': last4,
            'user_id': (user or self.user_sp).id,
        }
        return model.create(values)

    def attempts_of(self, payment):
        return self.attempt_model().search([('payment_id', '=', payment.id)])

    def fresh(self, payment):
        """Sonuç sayfası QUERYTRANSACTION atlasın (son sorgu 10 sn içinde sayılır)."""
        payment.sudo().write({'last_checked_at': utc_ahead(seconds=60)})
        return payment

    def sync(self, payment, *transactions):
        self.set_query_transactions(*transactions)
        payment.sudo()._sync_status()
        payment.invalidate_recordset()
        return payment

    def count_messages(self, payment, needle):
        messages = self.env['mail.message'].sudo().search([('model', '=', PAYMENT), ('res_id', '=', payment.id)])
        from odoo.tools import html2plaintext
        return len([m for m in messages if needle in html2plaintext(m.body or '')])

    def message_count(self, payment):
        return self.env['mail.message'].sudo().search_count([('model', '=', PAYMENT), ('res_id', '=', payment.id)])

    def k15_text(self, payment):
        return "Link en erken %s'de gönderilebilir" % payment._format_local(
            payment.sent_at + timedelta(hours=1))[-5:]

    # -- HTTP -------------------------------------------------------------------------
    def result(self, payment=None, mpid=None, n=None, user=None):
        if user is not False:
            self.login_as(user or self.user_sp)
        mpid = mpid if mpid is not None else payment.merchant_payment_id
        path = '%s?mpid=%s' % (MAIL_ORDER_RESULT_PATH, mpid)
        if n is not None:
            path += '&n=%s' % n
        return self.url_open(path, allow_redirects=False)

    def doc(self, response):
        return lxml_html.fromstring(response.text)

    def text(self, response):
        return norm(self.doc(response).text_content())

    def forms(self, response, kind):
        return self.doc(response).xpath('//form[contains(@action,"/mail_order/%s/")]' % kind)

    def refresh_meta(self, response):
        found = self.doc(response).xpath('//meta[translate(@http-equiv,"REFSH","refsh")="refresh"]/@content')
        return found[0] if found else None

    def post_action(self, path, payment_id, user=None, csrf=True, extra=None):
        self.login_as(user or self.user_sp)
        data = dict(extra or {})
        if csrf:
            data['csrf_token'] = http.Request.csrf_token(self)
        return self.url_open(path % payment_id, data=data, method='POST', allow_redirects=False)

    def pay_get(self, payment, user=None):
        self.login_as(user or self.user_sp)
        return self.url_open(MAIL_ORDER_PAY_PATH % payment.id, allow_redirects=False)

    def assertNotCardPageRedirect(self, response):
        location = response.headers.get('Location', '')
        self.assertNotIn('/sanal_pos/mail_order/pay/', location, 'kart sayfasına yönlendirmemeliydi')

    def declined(self, ref='PG-F1', code='ERR20051', **kw):
        """Kayıt `sent`; QUERYTRANSACTION FA döndürür; sonuç sayfası canlı sorguyla 'reddedildi' olur."""
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran(ref, code, **kw))
        return payment


class ResultCase(ResultMixin, MoHttpCase):
    pass


# ======================================================================================
# KK-3.1 ... KK-3.4, KK-3.9: sonuç sayfası
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestResultPage(ResultCase):

    def test_kk_3_1_standalone_sayfa_303_degil_basliklar_scriptsiz_form_action_self(self):
        payment = self.declined()
        response = self.result(payment)
        self.assertEqual(response.status_code, 200, 'backend forma 303 değil, standalone sayfa')
        self.assertIn('text/html', response.headers['Content-Type'])
        self.assertTrue(response.text.startswith('<!DOCTYPE html>'), response.text[:40])
        policy = self.csp(response)
        self.assertEqual(policy.get('default-src'), ["'none'"])
        self.assertEqual(policy.get('style-src'), ["'self'"])
        self.assertEqual(policy.get('img-src'), ["'self'"])
        self.assertEqual(policy.get('form-action'), ["'self'"], "yalnız bu sayfada, Tekrar dene/Link POST'ları için")
        self.assertEqual(policy.get('frame-ancestors'), ["'none'"])
        self.assertEqual(policy.get('base-uri'), ["'none'"])
        self.assertNotIn('script-src', policy, 'sonuç sayfasında script yok')
        self.assertNotIn('connect-src', policy)
        self.assertNotIn('<script', response.text.lower())
        self.assertNotRegex(response.text.lower(), r'\son[a-z]+\s*=')
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(response.headers.get('Referrer-Policy'), 'no-referrer')
        self.assertEqual(response.headers.get('Cross-Origin-Opener-Policy'), 'same-origin')

    def test_kk_3_1_ayni_gorunum_ailesi_adim_seridi_3_etkin_kayda_git(self):
        payment = self.declined()
        response = self.result(payment)
        doc = self.doc(response)
        hrefs = doc.xpath('//link[@rel="stylesheet"]/@href')
        self.assertEqual(len(hrefs), 1, hrefs)
        self.assertRegex(hrefs[0], CSS_HREF_RE, 'kart sayfasıyla aynı sürümlü stil dosyası')
        steps = doc.xpath('//ol[contains(@class,"mo-steps")]/li')
        self.assertEqual(len(steps), 3)
        self.assertEqual([s.get('aria-current') for s in steps], [None, None, 'step'], '3. adım etkin')
        links = doc.xpath('//a[contains(normalize-space(.),"Kayda git")]/@href')
        self.assertTrue(links, '"Kayda git" bağlantısı')
        self.assertTrue(links[0].endswith('/odoo/action-sanal_pos.action_sanal_pos_payment/%d' % payment.id),
                        links[0])

    def test_kk_3_2_odendi_gorunumu(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-AP1', installments=2, last4='4358'))
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        text = self.text(response)
        self.assertIn('Ödeme alındı', text)
        self.assertIn('9.000,00', text)
        self.assertRegex(text, r'(?i)(2\s*taksit|taksit[^0-9]{0,15}\b2\b)')
        self.assertIn('**** **** **** 4358', text)
        self.assertIn('PG-AP1', text)
        self.assertNotIn('43550843', response.text)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'),
                         'ödenmiş kayıtta Tekrar dene/Link yok')
        self.assertIsNone(self.refresh_meta(response))

    def test_kk_3_2_inceleme_gorunumu_dugme_yok(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '1.00', 'PG-RV1', last4='4358'))   # tutar farkı -> review
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reload(payment).state, 'review')
        self.assertRegex(self.text(response).lower(), r'nceleme|ncelen')
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'))
        self.assertIsNone(self.refresh_meta(response))

    def test_kk_3_3_reddedildi_turkce_neden_oneri_ve_kod(self):
        payment = self.declined('PG-F51', 'ERR20051')
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        text = self.text(response)
        self.assertIn('Ödeme reddedildi', text)
        self.assertIn(REASON_51, text)
        self.assertIn(ADVICE_51, text)
        self.assertIn('(ERR20051)', text, 'kod parantez içinde')
        self.assertEqual(self.reload(payment).state, 'sent', 'reddedilen deneme kaydı kapatmaz')
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk_3_3_iki_haneli_iso_kodu_err200_onekiyle_eslenir(self):
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran('PG-ISO', code=None, pgTranReturnCode='51'))
        text = self.text(self.result(payment))
        self.assertIn(REASON_51, text)
        self.assertIn('ERR20051', text)

    def test_kk_3_3_bilinmeyen_kod_paratika_mesaji_maskeli_oneri_yok(self):
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran('PG-UNK', 'ERR99999',
                                              errorMsg='Bilinmeyen banka hatasi XQ kart %s' % LEAK_PAN))
        response = self.result(payment)
        text = self.text(response)
        self.assertIn('Bilinmeyen banka hatasi XQ', text)
        self.assertIn('ERR99999', text)
        self.assertNotIn(LEAK_PAN, response.text, 'PAN maskelenir')
        for advice in ALL_ADVICE:
            self.assertNotIn(advice, text, 'bilinmeyen kodda öneri gösterilmez')
        for row in self.attempts_of(payment):
            self.assertNotIn(LEAK_PAN, row.reason or '')
        self.assertNotIn(LEAK_PAN, self.chatter(payment))

    def test_kk_3_3_ca_durumu_banka_dogrulamasi_iptal(self):
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran('PG-CA', code=None, status='CA'))
        text = self.text(self.result(payment))
        self.assertIn('Banka doğrulaması iptal edildi', text)
        self.assertIn('Tekrar deneyin', text)
        rows = self.attempts_of(payment)
        self.assertEqual(rows.mapped('status'), ['cancelled'])

    def test_kk_3_4_beklemede_meta_refresh_5sn_dugmeler_gorunmez(self):
        payment = self.make_mail_order()                    # sorgu boş döner: bekleniyor
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        text = self.text(response)
        self.assertIn('Banka sonucu bekleniyor', text)
        content = self.refresh_meta(response)
        self.assertIsNotNone(content, '<meta http-equiv="refresh">')
        self.assertRegex(content, r'^5;\s*url=')
        self.assertIn('mpid=%s' % payment.merchant_payment_id, content)
        self.assertRegex(content, r'[?&]n=1\b')
        self.assertNotIn('<script', response.text.lower())
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'),
                         'bekleme süresince Tekrar dene/Link görünmez (çift tahsilat)')
        self.assertEqual(self.reload(payment).state, 'sent')

    def test_kk_3_4_yenileme_sayaci_ve_2_dakikada_durur(self):
        payment = self.fresh(self.make_mail_order())
        meta = self.refresh_meta(self.result(payment, n=23))
        self.assertIsNotNone(meta)
        self.assertRegex(meta, r'[?&]n=24\b')
        response = self.result(payment, n=24)
        self.assertIsNone(self.refresh_meta(response), 'n >= 24 (~2 dk): yenileme durur')
        text = self.text(response)
        self.assertIn('Sonuç henüz gelmedi', text)
        self.assertIn('10 dk', text)
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'),
                         'durduktan sonra da düğme yok')

    def test_kk_3_4_gecersiz_n_guvenli_yenileme_sonsuz_artmaz(self):
        payment = self.fresh(self.make_mail_order())
        for n in ('abc', '-5', '999999', '', '1;2', '24.5'):
            with self.subTest(n=n):
                response = self.result(payment, n=n)
                self.assertEqual(response.status_code, 200)
                meta = self.refresh_meta(response)
                if meta:
                    nxt = re.search(r'[?&]n=(\d+)', meta)
                    self.assertTrue(nxt and 1 <= int(nxt.group(1)) <= 24, meta)
                self.assertNotIn('<script', response.text.lower())

    def test_kk_3_4_kilitli_sorgu_ve_en_yeni_deneme_bekliyor_ise_bekleniyor(self):
        payment = self.make_mail_order()
        with patch.object(type(self.env[PAYMENT]), '_try_lock_nowait', return_value=False):
            response = self.result(payment)
        self.assertIn('Banka sonucu bekleniyor', self.text(response))
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)
        other = self.fresh(self.make_mail_order(invoice_no='PEND-ATT'))
        self.add_attempt(other, status='failed', ago=30)
        self.add_attempt(other, status='pending', ago=1, code=False, reason=False)
        response = self.result(other)
        self.assertIn('Banka sonucu bekleniyor', self.text(response))
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'))

    def test_kk_3_5_kapali_kayit_yeni_deneme_ac_ve_link(self):
        for state in ('expired', 'error'):
            with self.subTest(state=state):
                payment = self.make_mail_order(invoice_no='CLOSED-%s' % state, state=state,
                                               sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
                response = self.result(payment)
                self.assertEqual(response.status_code, 200)
                text = self.text(response)
                retry, link = self.forms(response, 'retry'), self.forms(response, 'link')
                self.assertEqual(len(retry), 1)
                self.assertIn('Yeni deneme aç', norm(retry[0].text_content()))
                self.assertNotIn('Tekrar dene', text)
                self.assertEqual(len(link), 1, 'K-15 penceresi bitti: link düğmesi var')
                self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0, 'sent olmayan kayıtta sorgu yok')

    def test_kk_3_5_declined_tekrar_dene_formu_ve_k15_penceresinde_link_metni(self):
        payment = self.declined()
        response = self.result(payment)
        retry = self.forms(response, 'retry')
        self.assertEqual(len(retry), 1)
        self.assertIn('Tekrar dene', norm(retry[0].text_content()))
        self.assertTrue(retry[0].get('action').endswith(RETRY_PATH % payment.id))
        # KK-3.8(b) / S3.2: oturum açık (sent_at = şimdi) -> düğme yerine bekleme metni
        self.assertEqual(self.forms(response, 'link'), [], 'K-15 penceresinde Link formu yok')
        self.assertIn(self.k15_text(self.reload(payment)), self.text(response))
        self.assertIn('açık banka oturumu', self.text(response))

    def test_kk_3_9_formlar_csrf_post_kart_alani_yok(self):
        payment = self.declined()
        # pencere dışı kapalı kayıt: iki form da görünsün
        closed = self.make_mail_order(invoice_no='CSRF-2', state='expired',
                                      sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        for record in (payment, closed):
            response = self.result(record)
            doc = self.doc(response)
            forms = doc.xpath('//form')
            self.assertTrue(forms)
            for form in forms:
                self.assertEqual((form.get('method') or '').lower(), 'post')
                self.assertRegex(form.get('action'), r'^/sanal_pos/mail_order/(retry|link)/%d$' % record.id)
                self.assertTrue(form.xpath('.//input[@name="csrf_token"]/@value'), 'CSRF jetonu')
            names = set(doc.xpath('//input/@name') + doc.xpath('//select/@name') + doc.xpath('//textarea/@name'))
            self.assertFalse(names & CARD_INPUTS, 'sonuç sayfasında kart alanı yok')
            self.assertNotIn(LEAK_PAN, response.text)

    def test_kk_3_9_yetki_oturumsuz_ve_grupsuz(self):
        payment = self.declined()
        anon = self.result(payment, user=False)
        self.assertIn(anon.status_code, (301, 302, 303, 307))
        self.assertIn('/web/login', anon.headers.get('Location', ''))
        plain = self.result(payment, user=self.user_plain)
        self.assertEqual(plain.status_code, 403)
        for needle in (REASON_51, 'Tekrar dene', INV_NO, 'csrf_token'):
            self.assertNotIn(needle, plain.text)
        self.assertNoParatikaCalls()
        self.assertEqual(self.result(payment, user=self.user_sp).status_code, 200)    # olumlu çapa

    def test_kk_3_9_link_kaydi_ve_bilinmeyen_mpid_listeye(self):
        link = self.make_payment(invoice_no='RES-LINK')
        for name, mpid in (('link', link.merchant_payment_id), ('bilinmeyen', 'YOK-9-9'), ('bozuk', 'a b;c')):
            with self.subTest(case=name):
                response = self.result(mpid=mpid)
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response.headers['Location'].endswith(PAYMENT_LIST))
        self.assertNoParatikaCalls()

    def test_nfr_3_1_sayfa_acilisi_en_cok_1_querytransaction_baska_cagri_yok(self):
        payment = self.declined()
        self.assertEqual(self.result(payment).status_code, 200)
        self.assertLessEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.assertEqual(self.mock.count(), self.mock.count('QUERYTRANSACTION'), self.mock.actions)
        self.assertEqual(self.link_calls(), 0)
        # 10 sn kuralı korunur: hemen yenilenince sorgu tekrarlanmaz
        self.assertEqual(self.result(payment).status_code, 200)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk_3_7_kalan_deneme_ikinci_basarisizliktan_sonra_1(self):
        one = self.make_mail_order(invoice_no='REM-1')
        self.set_query_transactions(fail_tran('R1', minutes_ago=10))
        self.assertIn('Kalan deneme: 2', self.text(self.result(one)))
        two = self.make_mail_order(invoice_no='REM-2')
        self.set_query_transactions(fail_tran('R1', minutes_ago=10), fail_tran('R2', 'ERR20005', minutes_ago=5))
        response = self.result(two)
        self.assertIn('Kalan deneme: 1', self.text(response))
        self.assertEqual(len(self.forms(response, 'retry')), 1)


# ======================================================================================
# KK-3.6: deneme geçmişi + chatter
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestAttemptHistory(ResultCase):

    def history_order(self, text, last4s):
        positions = [text.find(x) for x in last4s]
        self.assertNotIn(-1, positions, 'beklenen satır(lar) geçmişte yok: %s' % dict(zip(last4s, positions)))
        return positions

    def test_kk_3_6_en_cok_10_satir_yeniden_eskiye(self):
        payment = self.fresh(self.make_mail_order())
        for i in range(12):                                   # 1001 en eski ... 1012 en yeni
            self.add_attempt(payment, ago=timedelta(minutes=120 - i * 5), last4='%04d' % (1001 + i),
                             ref='H-%02d' % i)
        text = self.text(self.result(payment))
        shown = ['%04d' % x for x in range(1012, 1002, -1)]    # en yeni 10
        positions = self.history_order(text, shown)
        self.assertEqual(positions, sorted(positions), 'yeniden eskiye')
        for old in ('1001', '1002'):
            self.assertNotIn(old, text, 'en çok 10 satır: en eski 2 gösterilmez')

    def test_kk_3_6_diger_kayitlar_yalniz_ayni_fatura_ve_son_24_saat(self):
        main = self.fresh(self.make_mail_order(invoice_no=INV_NO, attempt_no=2))
        self.add_attempt(main, last4='1111', ago=10)
        near = self.make_mail_order(invoice_no=INV_NO, attempt_no=1, state='expired',
                                    sent_at=utc_ago(hours=3), expires_at=utc_ago(hours=2))
        self.add_attempt(near, last4='2222', ago=timedelta(hours=3))
        old = self.make_mail_order(invoice_no=INV_NO, attempt_no=3, state='expired',
                                   sent_at=utc_ago(hours=40), expires_at=utc_ago(hours=39))
        self.add_attempt(old, last4='3333', ago=timedelta(hours=30))
        other_invoice = self.make_mail_order(invoice_no='BASKA-FATURA', state='expired',
                                             sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        self.add_attempt(other_invoice, last4='4444', ago=20)
        text = self.text(self.result(main))
        self.assertIn('1111', text)
        self.assertIn('2222', text, 'aynı faturanın son 24 saatteki diğer mail order denemesi')
        self.assertNotIn('3333', text, '24 saatten eski diğer kayıt gösterilmez')
        self.assertNotIn('4444', text, 'başka faturanın denemesi gösterilmez')
        positions = self.history_order(text, ['1111', '2222'])
        self.assertEqual(positions, sorted(positions))

    def test_kk_3_6_bu_kaydin_tum_denemeleri_24_saatten_eski_olsa_da_gosterilir(self):
        payment = self.fresh(self.make_mail_order())
        self.add_attempt(payment, last4='5555', ago=timedelta(hours=30), ref='OLD-OWN')
        self.add_attempt(payment, last4='6666', ago=5, ref='NEW-OWN')
        text = self.text(self.result(payment))
        self.assertIn('5555', text)
        self.assertIn('6666', text)

    def test_kk_3_6_satir_ayrintilari_sonuc_adlari_neden_kod_taksit_son4_baslatan(self):
        payment = self.fresh(self.make_mail_order())
        self.add_attempt(payment, status='pending', ago=50, last4='8001', ref='S-P', code=False, reason=False)
        self.add_attempt(payment, status='approved', ago=40, last4='8002', ref='S-A', code=False, reason=False)
        self.add_attempt(payment, status='cancelled', ago=30, last4='8003', ref='S-C', code='CA',
                         reason='Banka doğrulaması iptal edildi')
        self.add_attempt(payment, status='failed', ago=10, last4='8004', ref='S-F', code='ERR20054',
                         reason='Kartın süresi dolmuş', installments=3, user=self.user_sp2)
        text = self.text(self.result(payment))
        for label in ('Onaylandı', 'Reddedildi', 'İptal', 'Bekliyor'):
            self.assertIn(label, text)
        self.assertIn('Kartın süresi dolmuş', text)
        self.assertIn('ERR20054', text)
        self.assertRegex(text, r'(?i)3\s*taksit|taksit[^0-9]{0,15}\b3\b|\b3\s*x\b')
        self.assertIn('8004', text)
        self.assertIn(self.user_sp2.name, text, 'başlatan kullanıcı')

    def test_kk_3_6_ayni_pgtranid_tek_satir_tek_chatter_notu(self):
        payment = self.make_mail_order()
        self.sync(payment, fail_tran('PG-ONE', 'ERR20051', minutes_ago=5))
        self.assertEqual(len(self.attempts_of(payment)), 1)
        self.assertEqual(self.count_messages(payment, REASON_51), 1, 'yeni başarısız işlem: bir not')
        before = self.message_count(payment)
        self.sync(payment, fail_tran('PG-ONE', 'ERR20051', minutes_ago=5))
        self.sync(payment, fail_tran('PG-ONE', 'ERR20051', minutes_ago=5))
        self.assertEqual(len(self.attempts_of(payment)), 1, 'aynı pgTranId tek satır')
        self.assertEqual(self.count_messages(payment, REASON_51), 1, 'aynı pgTranId için tekrar not yok')
        self.assertEqual(self.message_count(payment), before)
        # yeni pgTranId: yeni satır + yeni not
        self.sync(payment, fail_tran('PG-ONE', minutes_ago=5), fail_tran('PG-TWO', 'ERR20005', minutes_ago=2))
        self.assertEqual(len(self.attempts_of(payment)), 2)
        self.assertEqual(self.count_messages(payment, 'Banka işlemi onaylamadı'), 1)
        self.assertEqual(self.count_messages(payment, REASON_51), 1)

    def test_kk_3_6_bekleyen_islem_sonradan_reddedilirse_ayni_satir_guncellenir(self):
        payment = self.make_mail_order()
        self.sync(payment, tran('IP', 'SALE', '9000.00', 'PG-IPFA'))
        rows = self.attempts_of(payment)
        self.assertEqual((rows.tran_ref, rows.status), ('PG-IPFA', 'pending'))
        self.assertEqual(self.count_messages(payment, REASON_51), 0, 'bekleyen işlem için red notu yok')
        self.sync(payment, fail_tran('PG-IPFA', 'ERR20051'))
        rows = self.attempts_of(payment)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows.status, rows.error_code), ('failed', 'ERR20051'))
        self.assertIn(REASON_51, rows.reason)
        self.assertEqual(self.count_messages(payment, REASON_51), 1)

    def test_kk_3_6_yalniz_mail_order_ve_yalniz_satis_islemleri_yazilir(self):
        link = self.make_payment(invoice_no='LINK-ATT')
        self.sync(link, fail_tran('PG-LINK', 'ERR20051'))
        self.assertEqual(len(self.attempts_of(link)), 0, 'link kaydı için deneme satırı yok')
        payment = self.make_mail_order(invoice_no='SALE-ONLY')
        self.sync(payment, tran('FA', 'REFUND', '10.00', 'PG-RFD', errorCode='ERR10153'),
                  fail_tran('PG-SALE', 'ERR20051'))
        self.assertEqual(self.attempts_of(payment).mapped('tran_ref'), ['PG-SALE'])

    def test_kk_3_6_attempt_ids_formda_salt_okunur_acl(self):
        payment = self.make_mail_order()
        self.add_attempt(payment, ref='ACL-1')
        self.assertTrue(payment.attempt_ids, 'sanal.pos.payment.attempt_ids (o2m)')
        view = self.env[PAYMENT].get_view(view_type='form')
        arch = lxml_html.fromstring('<root>%s</root>' % view['arch'])
        self.assertTrue(arch.xpath('//field[@name="attempt_ids"]'), 'kayıt formunda deneme listesi')
        field = arch.xpath('//field[@name="attempt_ids"]')[0]
        self.assertTrue(field.get('readonly') in ('1', 'True', 'true') or payment._fields['attempt_ids'].readonly,
                        'salt okunur')
        Model = self.env[ATTEMPT]
        row = self.attempts_of(payment)[:1]
        self.assertTrue(row.with_user(self.user_sp).read(['status']), 'kullanıcı okur')
        self.assertTrue(row.with_user(self.user_mgr).read(['status']), 'yönetici okur')
        with self.assertRaises(AccessError):
            row.with_user(self.user_plain).read(['status'])
        for user in (self.user_sp, self.user_mgr):
            with self.assertRaises(AccessError):
                Model.with_user(user).create({'payment_id': payment.id, 'tran_ref': 'X-%d' % user.id,
                                              'tran_time': fields.Datetime.now(), 'status': 'failed'})
            with self.assertRaises(AccessError):
                row.with_user(user).write({'status': 'approved'})
            with self.assertRaises(AccessError):
                row.with_user(user).unlink()

    def test_kk_3_6_tekil_kisit_payment_id_tran_ref(self):
        payment = self.make_mail_order()
        self.add_attempt(payment, ref='DUP-1')
        with self.assertRaises(Exception), self.cr.savepoint():
            self.add_attempt(payment, ref='DUP-1')

    def test_kk_3_6_attempt_modelinde_kart_alani_yok_ve_alan_adlari(self):
        model = self.attempt_model()
        for name in ('payment_id', 'tran_ref', 'tran_time', 'status', 'error_code', 'reason',
                     'installment_count', 'card_last4', 'approval_code', 'user_id'):
            self.assertIn(name, model._fields, name)
        self.assertEqual(set(dict(model._fields['status'].selection)),
                         {'approved', 'failed', 'cancelled', 'pending', 'review'})
        self.assertEqual(model._fields['payment_id'].ondelete, 'cascade')


# ======================================================================================
# KK-3.3 birim: neden/öneri sözlükleri, ISO eşlemesi, approval_code
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestDeclineTable(SanalPosCase):

    def provider(self):
        return self.env['sanal.pos.provider.paratika']

    def tables(self):
        from odoo.addons.sanal_pos.models import provider_paratika as module
        self.assertTrue(hasattr(module, 'DECLINE_ADVICE'), 'DECLINE_ADVICE sözlüğü yok (tasarım §5.2)')
        return module.ERROR_MESSAGES, module.DECLINE_ADVICE

    def test_kk_3_3_neden_ve_oneri_tablosu_14_satir_ca_dahil(self):
        messages, advice = self.tables()
        for code, (reason, tip) in DECLINE_TABLE.items():
            with self.subTest(code=code):
                self.assertIn(code, messages)
                self.assertIn(reason, messages[code])
                self.assertIn(code, advice)
                self.assertIn(tip, advice[code])
        self.assertNotIn('ERR20051', ' '.join(advice.values()), 'öneri sözlüğünde neden yinelenmez')

    def test_kk_3_3_error_message_tek_kaynak_neden_metni(self):
        self.tables()
        provider = self.provider()
        self.assertIn(REASON_51, provider._error_message('ERR20051', 'banka'))
        self.assertIn('Bankadan 3D yanıtı gelmedi', provider._error_message('ERR30005', None))
        unknown = provider._error_message('ERR99999', 'Garip hata')
        self.assertIn('Garip hata', unknown)
        self.assertIn('ERR99999', unknown)

    def test_kk_3_3_iso_eslemesi_normalize_transaction(self):
        self.tables()
        provider = self.provider()
        cases = (
            ({'pgTranReturnCode': '51'}, 'ERR20051'),
            ({'pgTranReturnCode': '05'}, 'ERR20005'),
            ({'pgTranReturnCode': 'YK'}, 'ERR200YK'),
            ({'pgTranReturnCode': '00'}, None),
            ({'pgTranReturnCode': '123'}, None),
            ({'pgTranReturnCode': ''}, None),
            ({'pgTranReturnCode': '51', 'errorCode': 'ERR30002'}, 'ERR30002'),
            ({'pgTranReturnCode': '51', 'pgTranErrorCode': 'ERR20012'}, 'ERR20012'),
        )
        for extra, expected in cases:
            with self.subTest(extra=extra):
                item = tran('FA', 'SALE', '9000.00', 'PG-X', **extra)
                self.assertEqual(provider._normalize_transaction(item).get('error_code'), expected)

    def test_kk_3_6_approval_code_normalize_ve_bin_okunmaz(self):
        self.tables()
        item = tran('AP', 'SALE', '9000.00', 'PG-AC', pgTranApprCode='A12345', bin='43550843')
        normalized = self.provider()._normalize_transaction(item)
        self.assertEqual(normalized.get('approval_code'), 'A12345')
        self.assertNotIn('43550843', repr(normalized), 'bin alanı okunmaz')

    def test_nfr_3_2_manifest_surumu_en_az_1_4_0(self):
        import ast
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '__manifest__.py')
        with open(path, encoding='utf-8') as handle:
            manifest = ast.literal_eval(handle.read())
        version = tuple(int(x) for x in manifest['version'].split('.'))
        self.assertGreaterEqual(version, (19, 0, 1, 4, 0), 'yeni tablo: manifest sürümü yükseltilir (NFR-3.2)')


# ======================================================================================
# KK-3.7: art arda başarısız deneme sınırı
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestAttemptLimit(ResultCase):

    def fail_n(self, payment, n, **kw):
        for i in range(n):
            self.add_attempt(payment, ago=timedelta(minutes=60 - i * 10), ref='L-%d-%d' % (payment.id, i), **kw)
        return payment

    def block(self, invoice_no=INV_NO):
        self.attempt_model()
        return self.env[PAYMENT]._mail_order_attempt_block(invoice_no)

    def test_kk_3_7_blok_fonksiyonu_esik_pencere_onay_fatura(self):
        payment = self.make_mail_order()
        self.assertFalse(self.block())
        self.fail_n(payment, 2)
        self.assertFalse(self.block(), '2 başarısız: açık')
        self.add_attempt(payment, status='cancelled', ago=1, ref='L-CA', code='CA', reason='Banka doğrulaması iptal edildi')
        self.assertEqual(self.block(), LIMIT_MSG, '2 FA + 1 CA = 3 başarısız')
        self.assertFalse(self.block('BASKA-FATURA'), 'başka fatura etkilenmez')
        self.add_attempt(payment, status='approved', ago=0, ref='L-AP', code=False, reason=False)
        self.assertFalse(self.block(), 'araya onay girince sayaç sıfırlanır')

    def test_kk_3_7_24_saat_disindaki_basarisizlar_sayilmaz(self):
        payment = self.make_mail_order()
        self.add_attempt(payment, ago=timedelta(hours=25), ref='W-1')
        self.add_attempt(payment, ago=timedelta(hours=30), ref='W-2')
        self.add_attempt(payment, ago=timedelta(minutes=10), ref='W-3')
        self.assertFalse(self.block(), '3 işlemden yalnız 1\'i son 24 saatte')
        self.add_attempt(payment, ago=timedelta(hours=23), ref='W-4')
        self.add_attempt(payment, ago=timedelta(hours=22), ref='W-5')
        self.assertEqual(self.block(), LIMIT_MSG)

    def test_kk_3_7_onaydan_once_basarisizlar_sayilmaz_sonrakiler_sayilir(self):
        payment = self.make_mail_order()
        for i in range(3):
            self.add_attempt(payment, ago=timedelta(hours=5 - i), ref='B-%d' % i)
        self.add_attempt(payment, status='approved', ago=timedelta(hours=1), ref='B-AP', code=False, reason=False)
        self.assertFalse(self.block())
        self.add_attempt(payment, ago=timedelta(minutes=50), ref='B-N1')
        self.add_attempt(payment, ago=timedelta(minutes=40), ref='B-N2')
        self.assertFalse(self.block())
        self.add_attempt(payment, ago=timedelta(minutes=30), ref='B-N3')
        self.assertEqual(self.block(), LIMIT_MSG)

    def test_kk_3_7_a_kart_sayfasi_get_engellenir_metin_ve_form_yok(self):
        payment = self.make_mail_order()
        self.fail_n(payment, 2)
        self.assertEqual(self.pay_get(payment).status_code, 200, 'olumlu çapa: 2 başarısız açık')
        self.add_attempt(payment, ago=1, ref='G-3')
        response = self.pay_get(payment)
        self.assertEqual(response.status_code, 409)
        self.assertIn(LIMIT_MSG, self.text(response))
        self.assertNotIn('name="pan"', response.text)
        self.assertEqual(self.reload(payment).state, 'sent', 'kayıt değişmez')
        # geri düğmesi: sayfa no-store olduğundan her GET denetlenir
        self.assertEqual(self.pay_get(payment).status_code, 409)

    def test_kk_3_7_a_24_saat_disi_ve_onay_sonrasi_kart_sayfasi_acik(self):
        old = self.make_mail_order()
        for i in range(3):
            self.add_attempt(old, ago=timedelta(hours=26 + i), ref='O-%d' % i)
        self.assertEqual(self.pay_get(old).status_code, 200)
        approved = self.make_mail_order(invoice_no='AP-AFTER')
        for i in range(3):
            self.add_attempt(approved, ago=timedelta(hours=4 - i), ref='P-%d' % i)
        self.add_attempt(approved, status='approved', ago=1, ref='P-AP', code=False, reason=False)
        self.assertEqual(self.pay_get(approved).status_code, 200)

    def test_kk_3_7_a_rpc_kart_bilgisi_gir_reddedilir(self):
        payment = self.make_mail_order()
        self.fail_n(payment, 3)
        with self.assertRaises(UserError) as cm:
            payment.with_user(self.user_sp).action_open_card_page()
        self.assertUserErrorContains(cm.exception, LIMIT_MSG)
        with self.assertRaises(UserError) as cm:
            payment.with_user(self.user_sp)._mail_order_card_values()
        self.assertUserErrorContains(cm.exception, LIMIT_MSG)
        self.assertNoParatikaCalls('limit dolunca QUERYINSTALLMENT dahil hiçbir çağrı yok')

    def test_kk_3_7_a_bin_ucu_409(self):
        self.mock.default('QUERYBIN', lambda p: querybin_body('DEBIT'))
        payment = self.make_mail_order()
        self.fail_n(payment, 3)
        self.login_as(self.user_sp)
        response = self.url_open(MAIL_ORDER_BIN_PATH, data=json.dumps({'payment_id': payment.id, 'bin': '43550843'}),
                                 headers={'Content-Type': 'application/json'}, method='POST',
                                 allow_redirects=False)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'ok': False, 'error': 'closed'})
        self.assertEqual(self.mock.count('QUERYBIN'), 0)

    def test_kk_3_7_b_sonuc_sayfasinda_tekrar_dene_gorunmez_link_yolu_acik(self):
        payment = self.fresh(self.make_mail_order(sent_at=utc_ago(hours=2), expires_at=utc_ahead(minutes=20)))
        self.fail_n(payment, 3)
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.forms(response, 'retry'), [], 'Tekrar dene görünmez')
        self.assertNotIn('Tekrar dene', self.text(response))
        self.assertEqual(len(self.forms(response, 'link')), 1, 'link yolu açık kalır')

    def test_kk_3_7_c_sihirbaz_yeni_deneme_reddedilir_oturum_ve_k15_yeniden_acma_oncesi(self):
        for name, sent_at in (('pencere_disi', utc_ago(hours=2)), ('k15_pencere_icinde', utc_ago(minutes=10))):
            with self.subTest(case=name):
                inv = 'LIM-%s' % name
                self.invoices[inv] = self.invoices[INV_NO]
                prior = self.make_mail_order(invoice_no=inv, state='expired', sent_at=sent_at,
                                             expires_at=utc_ago(minutes=1))
                self.fail_n(prior, 3)
                before = self.env[PAYMENT].sudo().search_count([('invoice_no', '=', inv)])
                with self.assertRaises(UserError) as cm:
                    self.create_mail_order(invoice_no=inv)
                self.assertUserErrorContains(cm.exception, LIMIT_MSG)
                self.assertNoParatikaCalls('ne SESSIONTOKEN ne K-15 QUERYTRANSACTION')
                self.assertEqual(self.env[PAYMENT].sudo().search_count([('invoice_no', '=', inv)]), before)

    def test_kk_3_7_c_olumlu_capa_2_basarisizlikta_sihirbaz_acar(self):
        prior = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(minutes=1))
        self.fail_n(prior, 2)
        payment = self.create_mail_order()
        self.assertEqual(payment.state, 'sent')
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)

    def test_kk_3_7_link_yolu_acik_kalir(self):
        prior = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        self.fail_n(prior, 3)
        link = self.create_link()
        self.assertEqual(link.payment_method, 'link')
        self.assertEqual(link.state, 'sent')
        self.assertEqual(self.link_calls(), 1)

    def test_kk_3_7_d_esik_gecisinde_deneme_siniri_doldu_notu_bir_kez_ve_bildirim(self):
        payment = self.make_mail_order()
        f1 = fail_tran('E-1', minutes_ago=30)
        f2 = fail_tran('E-2', 'ERR20005', minutes_ago=20)
        f3 = fail_tran('E-3', 'ERR20012', minutes_ago=10)
        f4 = fail_tran('E-4', 'ERR20099', minutes_ago=5)
        self.sync(payment, f1, f2)
        self.assertEqual(self.count_messages(payment, 'Deneme sınırı doldu'), 0)
        self.sync(payment, f1, f2, f3)
        self.assertEqual(self.count_messages(payment, 'Deneme sınırı doldu'), 1)
        self.assertIn('Deneme sınırı doldu', self.notification_texts(payment, self.user_sp.partner_id),
                      'oluşturana bildirim gider')
        self.sync(payment, f1, f2, f3)                           # aynı sorgu tekrar: yeni not yok
        self.sync(payment, f1, f2, f3, f4)                       # 4. başarısızlık: eşik geçişi değil
        self.assertEqual(self.count_messages(payment, 'Deneme sınırı doldu'), 1, 'bir kez')
        self.assertEqual(len(self.attempts_of(payment)), 4)

    def test_kk_3_7_onay_sonrasi_sayac_sifirlanir_fa_sonra_ap(self):
        payment = self.make_mail_order()
        f = [fail_tran('Z-%d' % i, minutes_ago=30 - i * 5) for i in range(3)]
        self.sync(payment, *f)
        self.assertEqual(self.block(), LIMIT_MSG)
        self.sync(payment, *f, tran('AP', 'SALE', '9000.00', 'Z-AP', last4='4358', timeCreated=iso_ago(1)))
        self.assertEqual(payment.state, 'paid')
        self.assertFalse(self.block(), 'FA -> AP sonrası sınır kalkar')


# ======================================================================================
# KK-3.5, KK-3.8, KK-3.9: Tekrar dene / Link gönder POST rotaları
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestRetryLinkRoutes(ResultCase):

    def snapshot(self, payment):
        self.reload(payment)
        return (payment.state, payment.expires_at, payment.provider_token, payment.sent_at,
                self.env[PAYMENT].sudo().search_count([]))

    def test_kk_3_9_csrfsiz_post_reddedilir_kayit_ve_paratika_degismez(self):
        payment = self.make_mail_order()
        for path in (RETRY_PATH, LINK_PATH):
            with self.subTest(path=path):
                before = self.snapshot(payment)
                response = self.post_action(path, payment.id, csrf=False)
                self.assertIn(response.status_code, (400, 403), response.status_code)
                self.assertNotCardPageRedirect(response)
                self.assertEqual(self.snapshot(payment), before)
        self.assertNoParatikaCalls()

    def test_kk_3_9_get_ile_tetiklenmez(self):
        payment = self.make_mail_order()
        self.login_as(self.user_sp)
        for path in (RETRY_PATH, LINK_PATH):
            with self.subTest(path=path):
                response = self.url_open(path % payment.id, allow_redirects=False)
                self.assertIn(response.status_code, (404, 405))
        self.assertNoParatikaCalls()

    def test_kk_3_9_grupsuz_kullanici_post_yapamaz(self):
        payment = self.declined()
        for path in (RETRY_PATH, LINK_PATH):
            with self.subTest(path=path):
                before = self.snapshot(payment)
                response = self.post_action(path, payment.id, user=self.user_plain)
                self.assertIn(response.status_code, (302, 303, 403))
                self.assertNotCardPageRedirect(response)
                self.assertEqual(self.snapshot(payment), before)
        self.assertNoParatikaCalls()

    def test_kk_3_9_link_kaydi_ve_olmayan_kayit_uzerinde_post_guvenli(self):
        link = self.make_payment(invoice_no='RT-LINK')
        for path in (RETRY_PATH, LINK_PATH):
            for name, target in (('link', link.id), ('olmayan', 987654321)):
                with self.subTest(path=path, case=name):
                    response = self.post_action(path, target)
                    self.assertNotEqual(response.status_code, 500)
                    self.assertNotCardPageRedirect(response)
        self.assertNoParatikaCalls()
        self.assertEqual(self.reload(link).state, 'sent')

    def test_kk_3_5_tekrar_dene_formdan_tek_tikla_bos_kart_sayfasi_ayni_mpid(self):
        payment = self.declined('PG-RT1')
        mpid = payment.merchant_payment_id
        page = self.result(payment)
        form = self.forms(page, 'retry')[0]
        token = form.xpath('.//input[@name="csrf_token"]/@value')[0]
        response = self.url_open(form.get('action'), data={'csrf_token': token}, method='POST',
                                 allow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text[:300])
        location = response.headers['Location']
        self.assertRegex(location, r'/sanal_pos/mail_order/pay/\d+$')
        target = self.env[PAYMENT].sudo().browse(int(location.rsplit('/', 1)[1]))
        self.assertEqual(target.merchant_payment_id, mpid, 'K-15: aynı MPID')
        self.assertEqual(target.invoice_no, INV_NO)
        self.assertEqual(self.reload(target).state, 'sent')
        self.assertGreater(target.expires_at, fields.Datetime.now())
        self.assertEqual(self.link_calls(), 0)
        card = self.url_open(location, allow_redirects=False)
        self.assertEqual(card.status_code, 200)
        doc = self.doc(card)
        for name in ('pan', 'cvv', 'cardOwner'):
            values = doc.xpath('//input[@name="%s"]/@value' % name)
            self.assertTrue(doc.xpath('//input[@name="%s"]' % name), name)
            self.assertEqual([v for v in values if v], [], 'kart alanları boş gelir: %s' % name)

    def test_kk_3_5_tekrar_dene_odeme_bulunursa_yeni_oturum_yok(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LATE', last4='4358'))
        response = self.post_action(RETRY_PATH, payment.id)
        self.assertNotCardPageRedirect(response)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0, 'çift tahsilat: yeni oturum açılmaz')
        self.assertEqual(self.reload(payment).state, 'paid')

    def test_kk_3_5_tekrar_dene_kapat_yanitsizsa_kayit_degismez_fail_closed(self):
        payment = self.make_mail_order()
        self.mock.default('QUERYTRANSACTION', lambda p: timeout_exc())
        before = self.snapshot(payment)
        response = self.post_action(RETRY_PATH, payment.id)
        self.assertNotCardPageRedirect(response)
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.snapshot(payment), before)

    def test_kk_3_5_tekrar_dene_bekleyen_islem_varsa_yeni_oturum_yok(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('IP', 'SALE', '9000.00', 'PG-IP'))
        response = self.post_action(RETRY_PATH, payment.id)
        self.assertNotCardPageRedirect(response)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.reload(payment).state, 'sent')

    def test_kk_3_5_tekrar_dene_3_basarisizliktan_sonra_reddedilir_paratika_yok(self):
        payment = self.make_mail_order()
        for i in range(3):
            self.add_attempt(payment, ago=timedelta(minutes=30 - i * 5), ref='RJ-%d' % i)
        before = self.snapshot(payment)
        response = self.post_action(RETRY_PATH, payment.id)
        self.assertNotCardPageRedirect(response)
        self.assertIn(LIMIT_MSG, self.text(response))
        self.assertNoParatikaCalls('sınır denetimi Kapat/QUERYTRANSACTION\'dan önce')
        self.assertEqual(self.snapshot(payment), before)

    def test_kk_3_5_suresi_dolmus_kayitta_yeni_deneme_ac(self):
        prior = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        response = self.post_action(RETRY_PATH, prior.id)
        self.assertEqual(response.status_code, 303, response.text[:300])
        self.assertRegex(response.headers['Location'], r'/sanal_pos/mail_order/pay/\d+$')
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 1)
        newest = self.last_payment()
        self.assertEqual(newest.state, 'sent')
        self.assertEqual(newest.payment_method, 'mail_order')
        self.assertTrue(response.headers['Location'].endswith('/pay/%d' % newest.id))

    def test_kk_3_8_k15_penceresinde_link_post_yazim_ve_paratika_yok_bekleme_metni(self):
        for state in ('sent', 'expired'):
            with self.subTest(state=state):
                payment = self.make_mail_order(invoice_no='K15-%s' % state, state=state,
                                               sent_at=utc_ago(minutes=10))
                wizards = self.env['sanal.pos.payment.create.wizard'].sudo().search_count([])
                before = self.snapshot(payment)
                response = self.post_action(LINK_PATH, payment.id)
                self.assertNotEqual(response.status_code, 500)
                self.assertIn(self.k15_text(self.reload(payment)), self.text(response))
                self.assertIn('açık banka oturumu', self.text(response))
                self.assertEqual(self.mock.calls, [], 'hiçbir Paratika çağrısı olmaz')
                self.assertEqual(self.snapshot(payment), before, 'hiçbir kayıt değişmez')
                self.assertEqual(self.env['sanal.pos.payment.create.wizard'].sudo().search_count([]), wizards)

    def test_kk_3_8_pencere_sonrasi_link_post_sihirbaza_yonlenir_on_dolu(self):
        payment = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        response = self.post_action(LINK_PATH, payment.id)
        self.assertEqual(response.status_code, 303, response.text[:300])
        location = response.headers['Location']
        self.assertRegex(location, r'/odoo/action-sanal_pos\.[a-z_]+(/\d+)?$',
                         'sihirbaz (ya da tasarım §5.5 yedeği: kayıt formu) adresi')
        wizard = self.env['sanal.pos.payment.create.wizard'].sudo().search(
            [('create_uid', '=', self.user_sp.id)], order='id desc', limit=1)
        self.assertEqual(wizard.invoice_no, INV_NO)
        self.assertEqual(wizard.customer_name, CUSTOMER_NAME)
        self.assertEqual(self.link_calls(), 0, 'sihirbaz açmak link üretmez')


# ======================================================================================
# KK-3.5/3.8/3.9: model düzeyi eylemler (kayıt formundaki düğmeler)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestRetryLinkActions(ResultMixin, SanalPosCase):

    def as_user(self, payment, user=None):
        return payment.with_user(user or self.user_sp)

    def wizard_count(self):
        return self.env['sanal.pos.payment.create.wizard'].sudo().search_count([])

    def call(self, payment, method='action_mail_order_to_link'):
        """(sonuç, UserError metni): assertRaises savepoint'i geri alır (DERSLER); try/except kullanılır."""
        try:
            return getattr(self.as_user(payment), method)(), None
        except UserError as exc:
            return None, str(exc)

    def test_kk_3_8_k15_penceresinde_hicbir_yazim_ya_paratika_cagrisi_yok(self):
        payment = self.make_mail_order(state='expired', sent_at=utc_ago(minutes=20))
        wizards, payments = self.wizard_count(), self.env[PAYMENT].sudo().search_count([])
        with self.assertRaises(UserError) as cm:
            self.as_user(payment).action_mail_order_to_link()
        self.assertUserErrorContains(cm.exception, self.k15_text(payment))
        self.assertUserErrorContains(cm.exception, '(açık banka oturumu)')
        self.assertEqual(self.mock.calls, [])
        self.assertEqual(self.wizard_count(), wizards)
        self.assertEqual(self.env[PAYMENT].sudo().search_count([]), payments)

    def test_kk_3_8_pencere_sonrasi_sihirbaz_fatura_getirilmis_musteri_on_dolu(self):
        payment = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1),
                                       customer_phone='5321112233')
        action, error = self.call(payment)
        self.assertIsNone(error)
        self.assertEqual(action.get('res_model'), 'sanal.pos.payment.create.wizard')
        wizard = self.env['sanal.pos.payment.create.wizard'].with_user(self.user_sp).browse(action['res_id'])
        self.assertEqual(wizard.invoice_no, INV_NO)
        self.assertEqual(wizard.customer_name, CUSTOMER_NAME)
        self.assertEqual(wizard.customer_phone, '5321112233')
        self.assertEqual(wizard.customer_email, EMAIL)
        self.assertEqual(wizard.amount, 9000.0, 'fatura getirilmiş')
        self.assertEqual(self.link_calls(), 0)

    def test_kk_3_8_a_acik_kayit_once_kapat_sonra_sihirbaz(self):
        payment = self.make_mail_order(sent_at=utc_ago(hours=2), expires_at=utc_ahead(minutes=20))
        action, error = self.call(payment)
        self.assertIsNone(error)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1, 'Mail Order\'ı Kapat (fail-closed sorgu)')
        self.assertEqual(self.reload(payment).state, 'expired')
        self.assertEqual(action.get('res_model'), 'sanal.pos.payment.create.wizard')

    def test_kk_3_8_a_kapat_odeme_bulursa_link_acilmaz_odeme_alinmis(self):
        payment = self.make_mail_order(sent_at=utc_ago(hours=2), expires_at=utc_ahead(minutes=20))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-LATE', last4='4358'))
        wizards = self.wizard_count()
        action, error = self.call(payment)
        text = error if error is not None else json.dumps(action, ensure_ascii=False)
        self.assertIn('Ödeme alınmış', text)
        self.assertEqual(self.reload(payment).state, 'paid')
        self.assertEqual(self.wizard_count(), wizards, 'sihirbaz açılmaz')
        self.assertEqual(self.link_calls(), 0)

    def test_kk_3_8_a_kapat_yanitsizsa_kayit_degismez_sihirbaz_yok(self):
        payment = self.make_mail_order(sent_at=utc_ago(hours=2), expires_at=utc_ahead(minutes=20))
        expires = payment.expires_at
        self.mock.default('QUERYTRANSACTION', lambda p: timeout_exc())
        wizards = self.wizard_count()
        action, error = self.call(payment)
        self.assertEqual(self.reload(payment).state, 'sent')
        self.assertEqual(payment.expires_at, expires)
        self.assertEqual(self.wizard_count(), wizards)
        if action:
            self.assertNotEqual(action.get('res_model'), 'sanal.pos.payment.create.wizard')

    def test_kk_3_9_yetki_ve_yontem_denetimi_paratika_cagrisindan_once(self):
        mo = self.make_mail_order(sent_at=utc_ago(hours=2), expires_at=utc_ahead(minutes=20))
        link = self.make_payment(invoice_no='ACT-LINK')
        for method in ('action_mail_order_retry', 'action_mail_order_to_link'):
            with self.subTest(method=method, case='grupsuz'):
                with self.assertRaises(AccessError):
                    getattr(mo.with_user(self.user_plain), method)()
            with self.subTest(method=method, case='link kaydı'):
                with self.assertRaises(UserError):
                    getattr(link.with_user(self.user_sp), method)()
        self.assertNoParatikaCalls()

    def test_kk_3_5_tekrar_dene_3_basarisizliktan_sonra_userror(self):
        payment = self.make_mail_order()
        for i in range(3):
            self.add_attempt(payment, ago=timedelta(minutes=30 - i * 5), ref='MR-%d' % i)
        with self.assertRaises(UserError) as cm:
            self.as_user(payment).action_mail_order_retry()
        self.assertUserErrorContains(cm.exception, LIMIT_MSG)
        self.assertNoParatikaCalls()

    def test_kk_3_5_tekrar_dene_kart_sayfasi_eylemi_doner(self):
        payment = self.make_mail_order()
        self.add_attempt(payment, ref='MR-OK')
        self.set_query_transactions(fail_tran('MR-OK', 'ERR20051'))
        action, error = self.call(payment, 'action_mail_order_retry')
        self.assertIsNone(error)
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        self.assertRegex(action.get('url', ''), r'^/sanal_pos/mail_order/pay/\d+$')
        self.assertEqual(self.link_calls(), 0)

    def test_kk_3_5_kayit_formunda_iki_dugme(self):
        view = self.env[PAYMENT].get_view(view_type='form')
        arch = lxml_html.fromstring('<root>%s</root>' % view['arch'])
        for name in ('action_mail_order_retry', 'action_mail_order_to_link'):
            self.assertTrue(arch.xpath('//button[@name="%s"]' % name), 'form düğmesi: %s' % name)

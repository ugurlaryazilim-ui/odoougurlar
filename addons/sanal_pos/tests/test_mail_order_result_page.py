# -*- coding: utf-8 -*-
"""A3-G2 geliştirici testleri: sonuç sayfasının kabul testlerinde kapsanmayan yolları.

* ``_mail_order_link_wait``: K-15 bekleme metni tek yerden (sayfa + A3-G3 link eylemi).
* Geçmiş yalnız mail order kayıtlarını sayar (aynı fatura no'lu link kaydı karışmaz).
* Bilinmeyen durumlarda (ör. iade edilmiş) düğme ve yenileme yoktur; sınır dolunca "Kalan deneme" yoktur.
* Yenileme durunca elle "Yeniden denetle" bağlantısı (GET, aynı mpid, n yok) çıkar.
"""
from datetime import timedelta

from odoo.tests import tagged

from .common import INV_NO, timeout_exc, tran
from .test_mail_order_result import LIMIT_MSG, LINK_PATH, RETRY_PATH, ResultCase, utc_ago


@tagged('post_install', '-at_install', 'sanal_pos')
class TestResultPageExtras(ResultCase):

    def test_link_bekleme_metni_pencere_icinde_dolu_disinda_bos(self):
        inside = self.make_mail_order(sent_at=utc_ago(minutes=10))
        self.assertEqual(inside._mail_order_link_wait(), self.k15_text(inside) + ' (açık banka oturumu)')
        outside = self.make_mail_order(invoice_no='W-OUT', sent_at=utc_ago(hours=2))
        self.assertFalse(outside._mail_order_link_wait())
        never = self.make_mail_order(invoice_no='W-NEVER', sent_at=False, state='error')
        self.assertFalse(never._mail_order_link_wait(), 'oturum hiç açılmadıysa bekleme yok')

    def test_gecmis_ayni_fatura_no_li_link_kaydini_saymaz(self):
        payment = self.fresh(self.make_mail_order(invoice_no=INV_NO, attempt_no=2))
        self.add_attempt(payment, last4='1111', ago=10, ref='OWN')
        link = self.make_payment(invoice_no=INV_NO, attempt_no=1, state='expired')
        self.add_attempt(link, last4='7777', ago=20, ref='LINK-ROW')
        text = self.text(self.result(payment))
        self.assertIn('1111', text)
        self.assertNotIn('7777', text)

    def test_iade_edilmis_kayitta_dugme_ve_yenileme_yok(self):
        payment = self.make_mail_order(state='refunded')
        response = self.result(payment)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Kayıt durumu', self.text(response))
        self.assertFalse(self.forms(response, 'retry') or self.forms(response, 'link'))
        self.assertIsNone(self.refresh_meta(response))
        self.assertNoParatikaCalls()

    def test_sinir_dolunca_kalan_deneme_yok_mesaj_var(self):
        payment = self.fresh(self.make_mail_order(sent_at=utc_ago(hours=2)))
        for i in range(3):
            self.add_attempt(payment, ago=timedelta(minutes=30 - i * 5), ref='LM-%d' % i)
        text = self.text(self.result(payment))
        self.assertIn(LIMIT_MSG, text)
        self.assertNotIn('Kalan deneme', text)

    def test_yenileme_durunca_elle_yeniden_denetle_baglantisi(self):
        payment = self.fresh(self.make_mail_order())
        doc = self.doc(self.result(payment, n=24))
        hrefs = doc.xpath('//a[contains(normalize-space(.),"Yeniden denetle")]/@href')
        self.assertEqual(hrefs, ['/sanal_pos/mail_order/result?mpid=%s' % payment.merchant_payment_id])
        running = self.doc(self.result(payment, n=3))
        self.assertFalse(running.xpath('//a[contains(normalize-space(.),"Yeniden denetle")]'))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestResultPageFix1(ResultCase):
    """Düzeltme turu #1 (05-inceleme-A3 Ö-1, Ö-9, Ö-13)."""

    def reopened_with_old_decline(self, invoice_no):
        """K-15 ile yeniden açılmış kayıt: tek deneme satırı ÖNCEKİ oturumun reddi (session_sent_at eski)."""
        payment = self.make_mail_order(invoice_no=invoice_no, sent_at=utc_ago(minutes=1))
        old = self.add_attempt(payment, ago=20, ref='OLD-FA')
        old.write({'session_sent_at': utc_ago(minutes=30)})
        return payment

    def test_o1_yeniden_acilan_kayitta_eski_oturum_reddi_gosterilmez(self):
        cases = (('sorgu_atlandi', lambda: None),
                 ('sorgu_zaman_asimi', lambda: self.mock.default('QUERYTRANSACTION', lambda p: timeout_exc())))
        for name, prepare in cases:
            with self.subTest(name):
                payment = self.reopened_with_old_decline('O1-%s' % name)
                if name == 'sorgu_atlandi':
                    self.fresh(payment)
                prepare()
                response = self.result(payment)
                text = self.text(response)
                self.assertIn('Banka sonucu bekleniyor', text)
                self.assertNotIn('Ödeme reddedildi', text)
                self.assertFalse(self.forms(response, 'retry'), 'eski oturum reddi Tekrar dene açmaz (KK-3.4)')
                self.assertFalse(self.forms(response, 'link'))
                self.assertIn('Reddedildi', text, 'geçmişte eski satır yine görünür')

    def test_o1_ayni_oturumun_reddi_gosterilir(self):
        payment = self.fresh(self.make_mail_order(sent_at=utc_ago(minutes=30)))
        row = self.add_attempt(payment, ago=5, ref='NEW-FA')
        row.write({'session_sent_at': payment.sent_at})
        response = self.result(payment)
        self.assertIn('Ödeme reddedildi', self.text(response))
        self.assertTrue(self.forms(response, 'retry'))

    def test_o9_kapat_odeme_bulursa_bildirim_basari_renginde(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'N9-AP'))
        response = self.post_action(RETRY_PATH, payment.id)
        self.assertEqual(response.status_code, 200)
        classes = self.doc(response).xpath(
            '//div[contains(@class,"mo-alert")][p[contains(normalize-space(.),"Ödeme alınmış")]]/@class')
        self.assertEqual(len(classes), 1)
        self.assertIn('mo-alert-success', classes[0])
        self.assertNotIn('mo-alert-danger', classes[0])

    def test_o13_grupsuz_kullanici_olmayan_kayitta_403(self):
        for path in (RETRY_PATH, LINK_PATH):
            with self.subTest(path=path):
                response = self.post_action(path, 987654321, user=self.user_plain)
                self.assertEqual(response.status_code, 403, 'kayıt varlığı grupsuz kullanıcıya sızmaz')

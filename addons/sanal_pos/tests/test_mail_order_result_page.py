# -*- coding: utf-8 -*-
"""A3-G2 geliştirici testleri: sonuç sayfasının kabul testlerinde kapsanmayan yolları.

* ``_mail_order_link_wait``: K-15 bekleme metni tek yerden (sayfa + A3-G3 link eylemi).
* Geçmiş yalnız mail order kayıtlarını sayar (aynı fatura no'lu link kaydı karışmaz).
* Bilinmeyen durumlarda (ör. iade edilmiş) düğme ve yenileme yoktur; sınır dolunca "Kalan deneme" yoktur.
* Yenileme durunca elle "Yeniden denetle" bağlantısı (GET, aynı mpid, n yok) çıkar.
"""
from datetime import timedelta

from odoo.tests import tagged

from .common import INV_NO
from .test_mail_order_result import LIMIT_MSG, ResultCase, utc_ago


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

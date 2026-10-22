# -*- coding: utf-8 -*-
"""Taksit vade farkı: çekilen tutar beklenen vade farklı toplamla tutuyorsa Ödendi + not.

Kullanıcı kararı (2026-10-22): Paratika taksitte müşteri vade farkını (QUERYINSTALLMENT
``customerCostCommissionRate``) AMOUNT'a ekler. Çekilen tutar, işlemin taksit sayısı için beklenen
toplamla (±taksit sayısı kadar kuruş) tutarsa Ödendi; tutmazsa (fazla, az, oran bilinmiyor,
tek çekim, oran 0) İnceleme (REVIEW_AMOUNT). Oran sync anında sorgulanır (yeni alan yok).
9000 x 1,1357 = 10.221,30 TL; vade farkı 1.221,30 TL.
"""
from odoo.tests import tagged

from .common import err_body, installment_body, timeout_exc, tran
from .test_refund import RefundCase
from .test_sync import SyncCase

NOTE = 'Vade farkı 1.221,30 TL (7 taksit, %13,57)'
AXESS = ('Axess Sanal POS', 'AXESS', [(3, 4.5), (7, 13.57)])
BONUS = ('Bonus Sanal POS', 'BONUS', [(7, 15.0)])


class SurchargeCase(SyncCase, RefundCase):

    def rates(self, *systems):
        body = installment_body(*systems)
        self.mock.default('QUERYINSTALLMENT', lambda p: body)

    def pay(self, amount, installments=7, payment=None, **extra):
        payment = payment or self.sent()
        self.set_query_transactions(tran('AP', 'SALE', amount, 'PG-VF', installments=installments,
                                         **extra))
        self.mock.calls.clear()
        return self.sync(payment)

    def assertReviewAmount(self, payment):
        self.assertEqual(payment.state, 'review')
        self.assertEqual(payment.last_error_code, 'REVIEW_AMOUNT')
        self.assertNotIn('Vade farkı', self.chatter(payment))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSurchargeAccepted(SurchargeCase):

    def test_link_7_taksit_beklenen_toplam_odendi(self):
        self.rates(AXESS)
        payment = self.pay('10221.30')
        self.assertEqual(payment.state, 'paid')
        self.assertFalse(payment.last_error_code)
        self.assertEqual(payment.paid_amount, 10221.30)
        self.assertEqual(payment.installment_count, 7)
        self.assertIn(NOTE, self.chatter(payment))
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 1)
        self.assertIn(self.user_sp.partner_id, self.notified_partners(payment))

    def test_kurus_payi_taksit_sayisi_kadar(self):
        """±7 kuruş (7 taksit) içinde Ödendi; 8 kuruş sapma İnceleme."""
        self.rates(AXESS)
        for i, (amount, state) in enumerate((('10221.37', 'paid'), ('10221.23', 'paid'),
                                              ('10221.38', 'review'), ('10221.22', 'review'))):
            with self.subTest(amount=amount):
                payment = self.make_payment(state='sent', invoice_no='KP-%d' % i)
                self.pay(amount, payment=payment)
                self.assertEqual(payment.state, state)

    def test_mail_order_7_taksit_odendi_not(self):
        self.rates(AXESS)
        payment = self.pay('10221.30', payment=self.make_mail_order())
        self.assertEqual(payment.state, 'paid')
        note = self.chatter(payment)
        self.assertIn('Mail order ödemesi alındı', note)
        self.assertIn(NOTE, note)

    def test_ag_bilinmiyorsa_oranlardan_biri_yeter(self):
        self.rates(BONUS, AXESS)
        payment = self.pay('10221.30')
        self.assertEqual(payment.state, 'paid')
        self.assertIn(NOTE, self.chatter(payment))

    def test_ag_biliniyorsa_yalniz_kendi_orani(self):
        self.rates(AXESS, BONUS)
        for i, (system, state) in enumerate((('AXESS', 'paid'), ('Axess Sanal POS', 'paid'),
                                              ('BONUS', 'review'), ('Bonus Sanal POS', 'review'),
                                              ('TANIMSIZ', 'paid'))):
            with self.subTest(system=system):
                payment = self.make_payment(state='sent', invoice_no='AG-%d' % i)
                self.pay('10221.30', payment=payment, paymentSystem=system)
                self.assertEqual(payment.state, state)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSurchargeRejected(SurchargeCase):

    def test_beklenenden_1_tl_fazla_inceleme(self):
        self.rates(AXESS)
        payment = self.pay('10222.30')
        self.assertReviewAmount(payment)
        self.assertIn('10.222,30', self.chatter(payment))

    def test_fatura_tutarindan_az_inceleme_sorgu_yok(self):
        self.rates(AXESS)
        payment = self.pay('8999.00')
        self.assertReviewAmount(payment)
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 0)

    def test_oran_bilinmiyor_inceleme(self):
        cases = (
            ('sayi_yok', installment_body(('Axess Sanal POS', 'AXESS', [(3, 4.5), (6, 9.0)]))),
            ('bos_liste', installment_body()),
            ('hata', err_body('ERR10001', 'x')),
            ('zaman_asimi', timeout_exc()),
        )
        for i, (label, response) in enumerate(cases):
            with self.subTest(case=label):
                self.mock.default('QUERYINSTALLMENT', lambda p, r=response: r)
                payment = self.make_payment(state='sent', invoice_no='OB-%d' % i)
                self.pay('10221.30', payment=payment)
                self.assertReviewAmount(payment)

    def test_sifir_oranda_kurus_fazla_inceleme(self):
        self.rates(('Axess Sanal POS', 'AXESS', [(7, 0)]))
        payment = self.pay('9000.05')
        self.assertReviewAmount(payment)

    def test_tek_cekim_fazla_tahsilat_inceleme_sorgu_yok(self):
        self.rates(AXESS)
        payment = self.pay('10221.30', installments=1)
        self.assertReviewAmount(payment)
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 0)

    def test_taksit_sayisi_yoksa_inceleme(self):
        self.rates(AXESS)
        payment = self.sent()
        item = tran('AP', 'SALE', '10221.30', 'PG-NOI')
        item.pop('installmentCount')
        self.set_query_transactions(item)
        self.sync(payment)
        self.assertReviewAmount(payment)

    def test_tek_cekim_esit_tutar_aynen_odendi_sorgu_yok(self):
        self.rates(AXESS)
        payment = self.pay('9000.00', installments=1)
        self.assertEqual(payment.state, 'paid')
        self.assertNotIn('Vade farkı', self.chatter(payment))
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 0)

    def test_para_birimi_farkli_vade_farkli_inceleme(self):
        self.rates(AXESS)
        payment = self.pay('10221.30', currency='USD')
        self.assertEqual(payment.state, 'review')
        self.assertNotIn('Vade farkı', self.chatter(payment))

    def test_gec_odeme_vade_farkli_yine_inceleme_sorgu_yok(self):
        self.rates(AXESS)
        payment = self.pay('10221.30', payment=self.make_payment(state='expired'))
        self.assertEqual(payment.state, 'review')
        self.assertEqual(payment.last_error_code, 'REVIEW_LATE')
        self.assertEqual(self.mock.count('QUERYINSTALLMENT'), 0)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestSurchargeRefundLimit(SurchargeCase):
    """Vade farkı dahil çekilen tutar iade edilebilir (Paratika'nın üst sınırı da odur)."""

    def test_iade_ust_siniri_cekilen_tutar(self):
        self.rates(AXESS)
        payment = self.pay('10221.30')
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.refundable_amount, 10221.30)
        self.assertRejected(payment, 'action_refund', 10221.31, 'Müşteri talebi',
                            text='İade tutarı 0,01 ile 10.221,30 TL arasında olmalı.')
        _, message = self.refund(payment, 10221.30)
        self.assertIsNone(message)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '10221.30')
        self.approve_refund(payment)
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 10221.30)

    def test_liste_tahsil_edilen_sutunu(self):
        """İade edilen, Tutar'ı (fatura) aşabilir; listede tahsil edilen tutar da görünür."""
        views = self.env['sanal.pos.payment'].with_user(self.user_sp).get_views([(False, 'list')])
        self.assertIn('name="paid_amount"', views['views']['list']['arch'])

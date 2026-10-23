# -*- coding: utf-8 -*-
"""A3-G1 geliştirici testleri: deneme satırı yazımının kabul testlerinde kapsanmayan yolları.

* K-15 yeniden açma sorgusundaki red/iptaller de satır olur ve sınıra sayılır (sözleşme sapma 4).
* Kodsuz iptal (CA) ve bilinmeyen kodlu red: neden metni maskeli, kart numarası hiçbir yere yazılmaz.
"""
from odoo.tests import tagged

from ..models.sanal_pos_payment import MO_LIMIT_MSG
from .common import INV_NO, LEAK_PAN, tran
from .test_mail_order import MailOrderCase
from .test_mail_order_result import fail_tran

ATTEMPT = 'sanal.pos.payment.attempt'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestAttemptRecording(MailOrderCase):

    def attempts(self, payment):
        return self.env[ATTEMPT].sudo().search([('payment_id', '=', payment.id)], order='id')

    def closed(self):
        """Kart sayfası açılmış ve kapatılmış deneme (boş sorgu: henüz satır yok)."""
        self.set_query_transactions()
        payment = self.create_mail_order()
        payment.with_user(self.user_sp).action_mail_order_close()
        self.assertEqual(self.reload(payment).state, 'expired')
        self.assertFalse(self.attempts(payment))
        self.mock.calls.clear()
        return payment

    def test_k15_yeniden_acma_onceki_basarisizlari_kaydeder(self):
        payment = self.closed()
        self.set_query_transactions(fail_tran('RO-1', 'ERR20051', minutes_ago=3))
        self.assertIsNone(self.mo_attempt(user=self.user_sp2))
        rows = self.attempts(payment)
        self.assertEqual(rows.mapped('tran_ref'), ['RO-1'])
        self.assertEqual(rows.user_id, self.user_sp, 'başlatan önceki oturumun sahibidir')
        self.assertEqual(self.reload(payment).user_id, self.user_sp2)
        self.assertEqual(self.mock.actions, ['QUERYTRANSACTION', 'SESSIONTOKEN'])

    def test_k15_yeniden_acmada_sinir_dolarsa_oturum_acilmaz(self):
        payment = self.closed()
        self.set_query_transactions(fail_tran('RL-1', minutes_ago=30), fail_tran('RL-2', minutes_ago=20))
        payment.sudo()._sync_status()                        # 2 başarısız: sihirbaz açık kalır
        self.assertFalse(self.env['sanal.pos.payment']._mail_order_attempt_block(INV_NO))
        self.mock.calls.clear()
        self.set_query_transactions(fail_tran('RL-1', minutes_ago=30), fail_tran('RL-2', minutes_ago=20),
                                    fail_tran('RL-3', 'ERR20005', minutes_ago=10))
        # DIKKAT: assertRaises değil (DERSLER: savepoint'i geri alır, kalıcılaştırma görünmez)
        self.assertEqual(self.mo_attempt(), MO_LIMIT_MSG)
        self.assertEqual(self.mock.count('SESSIONTOKEN'), 0)
        self.assertEqual(self.mock.actions, ['QUERYTRANSACTION'])
        self.assertEqual(len(self.attempts(payment)), 3)
        self.assertEqual(self.reload(payment).state, 'expired', 'kayıt yeniden açılmaz')
        self.assertEqual(self.env['sanal.pos.payment']._mail_order_attempt_block(INV_NO), MO_LIMIT_MSG)

    def test_ca_kodsuz_iptal_kod_ve_neden(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('CA', 'SALE', '9000.00', 'PG-CA', last4='4321'))
        self.sync(payment)
        row = self.attempts(payment)
        self.assertEqual((row.status, row.error_code, row.card_last4), ('cancelled', 'CA', '4321'))
        self.assertIn('Banka doğrulaması iptal edildi', row.reason)
        self.assertIn('Mail order denemesi iptal edildi', self.chatter(payment))
        # onaylı işlem: onay kodu yazılır, neden/kod boş
        self.set_query_transactions(tran('CA', 'SALE', '9000.00', 'PG-CA', last4='4321'),
                                    tran('AP', 'SALE', '9000.00', 'PG-OK', pgTranApprCode='A77'))
        self.sync(payment)
        ok = self.attempts(payment).filtered(lambda r: r.tran_ref == 'PG-OK')
        self.assertEqual((ok.status, ok.approval_code, ok.error_code, ok.reason),
                         ('approved', 'A77', False, False))

    def test_red_nedeni_ve_notu_pan_maskeli(self):
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran('PG-LK', 'ERR99999', errorMsg='kart %s reddedildi' % LEAK_PAN))
        self.sync(payment)
        row = self.attempts(payment)
        self.assertIn('ERR99999', row.reason, 'bilinmeyen kod nedenle birlikte görünür')
        self.assertNotIn(LEAK_PAN, row.reason)
        self.assertNotIn(LEAK_PAN, self.chatter(payment))
        self.assertIn('Mail order denemesi reddedildi', self.chatter(payment))
        self.assertIn('**** 1234', self.chatter(payment))

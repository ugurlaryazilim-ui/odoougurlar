# -*- coding: utf-8 -*-
"""A3-G1 geliştirici testleri: deneme satırı yazımının kabul testlerinde kapsanmayan yolları.

* K-15 yeniden açma sorgusundaki red/iptaller de satır olur ve sınıra sayılır (sözleşme sapma 4).
* Kodsuz iptal (CA) ve bilinmeyen kodlu red: neden metni maskeli, kart numarası hiçbir yere yazılmaz.
"""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from ..models.sanal_pos_payment import MO_LIMIT_MSG
from .common import INV_NO, LEAK_PAN, tran
from .test_mail_order import MailOrderCase
from .test_mail_order_result import fail_tran, utc_ago

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

    # ------------------------------------------------------------ düzeltme turu #1
    def test_o1_k15_yeniden_acmada_eski_oturum_reddi_sonucta_gosterilmez(self):
        payment = self.closed()
        # NEDEN: yeniden açma aynı saniyede olursa iki oturum damgası eşit olurdu; eski oturum geriye alınır
        old_session = utc_ago(minutes=20)
        payment.sudo().write({'sent_at': old_session})
        self.set_query_transactions(fail_tran('RS-1', 'ERR20051', minutes_ago=15))
        self.assertIsNone(self.mo_attempt())
        self.assertEqual(self.reload(payment).state, 'sent')
        row = self.attempts(payment)
        self.assertEqual(row.session_sent_at, old_session, 'satır eski oturumun damgasını taşır')
        self.assertGreater(payment.sent_at, row.session_sent_at)
        values = payment.with_user(self.user_sp)._mail_order_result_values()
        self.assertEqual(values['view'], 'pending', 'yeni oturumda eski red + Tekrar dene gösterilmez')
        self.assertFalse(values['retry_label'] or values['show_link'])
        self.assertEqual(len(values['history']), 1, 'geçmişte eski satır kalır')

    def test_g3_2_maskeli_pan_son4e_indirgenir(self):
        masked = '454671******1234'
        payment = self.make_mail_order()
        self.set_query_transactions(fail_tran('PG-MS', last4=masked))
        self.sync(payment)
        self.assertEqual(self.attempts(payment).card_last4, '1234')
        self.assertNotIn('454671', self.chatter(payment))
        self.set_query_transactions(fail_tran('PG-MS', last4=masked),
                                    tran('AP', 'SALE', '9000.00', 'PG-MS-OK', last4=masked))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.card_last4, '1234')
        self.env.flush_all()
        self.env.cr.execute("SELECT count(*) FROM sanal_pos_payment_attempt WHERE card_last4 LIKE '%%454671%%'")
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        self.assertNotIn('454671', self.chatter(payment))

    def test_o6_sayi_tipinde_pgtranid_tek_satir(self):
        payment = self.make_mail_order()
        for _i in range(2):
            self.set_query_transactions(fail_tran(987654321))
            self.sync(payment)
        rows = self.attempts(payment)
        self.assertEqual(rows.mapped('tran_ref'), ['987654321'])
        self.assertEqual(self.chatter(payment).count('Mail order denemesi reddedildi'), 1)

    def test_o5_deneme_kaydi_hatasi_durum_kararini_durdurmaz(self):
        payment = self.make_mail_order()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'PG-SP'))
        with patch.object(type(self.env['sanal.pos.payment']), '_record_attempts',
                          side_effect=RuntimeError('boom')), mute_logger('odoo.addons.sanal_pos.models.sanal_pos_payment'):
            self.sync(payment)
        self.assertEqual(payment.state, 'paid', 'yan iş hatası geç onayı kaybettirmez (DERSLER-14)')
        self.assertFalse(self.attempts(payment))

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

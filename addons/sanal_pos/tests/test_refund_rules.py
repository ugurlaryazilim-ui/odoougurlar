# -*- coding: utf-8 -*-
"""G11 kural testleri (11-sozlesme-G11.md; yönetici şartları 1-2).

Kabul testlerine (test_refund.py) ek kanıtlar: belirsiz iade satırı erken 'Başarısız'
olmaz (çift iade = para kaybı), kilit/indeks savunmaları, dış çağrı sonrası raise yok,
R-3 işlem no benimseme ve tek iptal satırı, 2'den fazla ondalık reddi.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CRON_SYNC, ok_body, timeout_exc, tran
from .test_refund import BUSY_MSG, WIZARD, RefundCase

PAYMENT = 'sanal.pos.payment'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestUnknownRefundNotFound(RefundCase):
    """ŞART 1: ≥2 ayrı sorgu + bekleyen (IP) işlem yok + ilk belirsizlikten ≥15 dk."""

    def unknown_refund(self, amount=2500.0):
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, amount)
        line = self.lines(payment)
        self.assertEqual(line.state, 'unknown')
        return payment, line

    def test_tek_sorgu_yetmez_yas_dolmus_olsa_bile(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 20)
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual((line.state, line.not_found_count), ('unknown', 1),
                         'tek sorguda bulunamayan belirsiz iade başarısız sayılmamalı')
        # uzlaştırılmadan yeni iade/iptal yok
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar deniyorum', text=BUSY_MSG)
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual((line.state, line.error_code), ('failed', 'NOT_FOUND'))

    def test_bekleyen_islem_varken_basarisiz_olmaz(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 30)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('IP', 'REFUND', '2500.00', 'R-PEND'))
        for _ in range(3):
            self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual((line.state, line.not_found_count), ('unknown', 0),
                         'bekleyen işlem varken sayaç artmamalı')
        self.assertEqual(len(self.lines(payment)), 1, 'bekleyen işlem panel satırı açmamalı')
        # bekleyen işlem onaylanınca eşleşir
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', 'R-PEND'))
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual((line.state, line.provider_ref), ('done', 'R-PEND'))

    def test_iki_sorgu_ama_15_dk_dolmadan_belirsiz_kalir(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 10)
        for _ in range(3):
            self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual(line.state, 'unknown')
        self.assertGreaterEqual(line.not_found_count, 2)
        self.age_line(line, 16)
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual(line.state, 'failed')

    def test_ikinci_kontrol_tetigi_15_dk_sonrasina_kurulur(self):
        before = self.cron_trigger_count(CRON_SYNC)
        self.unknown_refund()
        self.assertGreaterEqual(self.cron_trigger_count(CRON_SYNC) - before, 2,
                                'hemen + 16 dk sonra iki tetik beklenir')

    def test_cron_adayi_tetiksiz_bulunur(self):
        payment, line = self.unknown_refund()
        self.env['ir.cron.trigger'].sudo().search([]).unlink()
        ids = self.env[PAYMENT].sudo()._sync_candidate_ids(50)
        self.assertIn(payment.id, ids)
        self.mock.calls.clear()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_bayat_isleniyor_once_belirsiz_sonra_basarisiz(self):
        payment = self.paid()
        line = self.make_refund_line(payment, 2500.0, state='processing')
        self.age_line(line, 6)
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual((line.state, line.error_code), ('unknown', 'STALE'))
        self.age_line(line, 30)
        self.run_cron(CRON_SYNC)
        line.invalidate_recordset()
        self.assertEqual(line.state, 'failed')

    def test_genc_isleniyor_dokunulmaz_panel_kopyasi_acilmaz(self):
        payment = self.paid()
        line = self.make_refund_line(payment, 2500.0, state='processing')
        self.age_line(line, 1)   # create_date işlem zamanıdır; açıkça "genç" yapılır
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', 'R-FLY'))
        self.assertNotIn(payment.id, self.env[PAYMENT].sudo()._sync_candidate_ids(50))
        payment.sudo()._sync_status()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'processing')
        self.assertEqual(len(self.lines(payment)), 1, 'uçuştaki istek panel satırı açmamalı')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundFlowGuards(RefundCase):
    """Kilit, indeks ve dış çağrı sonrası savunmalar (sözleşme §4)."""

    def test_birinci_kilit_alinamazsa_mesgul_ve_sorgu_yok(self):
        payment = self.paid()
        with patch.object(type(self.env[PAYMENT]), '_try_lock_nowait', return_value=False):
            self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi', text=BUSY_MSG)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 0)

    def test_ikinci_kilit_alinamazsa_istek_gitmez(self):
        payment = self.paid()
        with patch.object(type(self.env[PAYMENT]), '_try_lock_nowait', side_effect=[True, False]):
            result, message = self.refund(payment, 100.0)
        self.assertIsNone(message, 'commit sonrası raise yok')
        self.assertEqual(self.mock.count('REFUND'), 0)
        line = self.lines(payment)
        self.assertEqual((line.state, line.error_code), ('failed', 'NOT_SENT'))
        self.assertIn(BUSY_MSG, str(result))
        # failed satır yeniden denemeyi engellemez
        _, message = self.refund(payment, 100.0)
        self.assertIsNone(message)
        self.assertEqual(self.mock.count('REFUND'), 1)

    def test_sonuc_yazilamazsa_belirsiz_raise_yok(self):
        payment = self.paid()
        with patch.object(type(self.env[PAYMENT]), '_apply_refund_result',
                          side_effect=RuntimeError('yazılamadı')):
            result, message = self.refund(payment, 100.0)
        self.assertIsNone(message)
        self.assertEqual(self.mock.count('REFUND'), 1)
        line = self.lines(payment)
        self.assertEqual((line.state, line.error_code), ('unknown', 'APPLY_ERROR'))
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar deniyorum', text=BUSY_MSG)

    def test_on_kontrol_korelse_indeks_mesgul_der(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='processing')
        with patch.object(type(self.env[PAYMENT]), '_has_blocking_refund_line', return_value=False):
            self.assertRejected(payment, 'action_refund', 50.0, 'Müşteri talebi', text=BUSY_MSG)

    def test_sihirbaz_ikiden_fazla_ondalik_reddedilir(self):
        payment = self.paid()
        for value in (10.005, 0.001, 2500.999):
            wiz = self.env[WIZARD].with_user(self.user_mgr).create({
                'payment_id': payment.id, 'kind': 'refund', 'amount': value,
                'reason': 'Müşteri talebi'})
            self.mock.calls.clear()
            with self.assertRaises(UserError):
                wiz.action_confirm()
            self.assertEqual(self.mock.count('REFUND'), 0, value)
        self.assertFalse(self.lines(payment))

    def test_iki_ondalik_kurus_tam_gider(self):
        payment = self.paid()
        _, message = self.refund(payment, 0.1 + 0.2)   # 0.30000000000000004 -> reddedilir
        self.assertTrue(message)
        _, message = self.refund(payment, '1234.56')
        self.assertIsNone(message)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '1234.56')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundRefAdoption(RefundCase):
    """R-3: yanıttaki işlem no ile sorgudaki farklıysa aynı iade iki kez sayılmaz."""

    def assertSingleRefund(self, payment, ref, amount=2500.0):
        lines = self.lines(payment)
        payment.invalidate_recordset()
        self.assertEqual(len(lines), 1, 'aynı iade ikinci satır açmamalı')
        self.assertEqual((lines.state, lines.source, lines.provider_ref), ('done', 'odoo', ref))
        self.assertEqual(payment.refunded_amount, amount)

    def test_yanit_ref_satis_ref_ise_saklanmaz_sonra_benimsenir(self):
        payment = self.paid()
        self.mock.queue('REFUND', ok_body(pgTranId='T1', merchantPaymentId=payment.merchant_payment_id))
        self.refund(payment, 2500.0)
        self.assertFalse(self.lines(payment).provider_ref)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', 'R-Q'))
        payment.sudo()._sync_status()
        self.assertSingleRefund(payment, 'R-Q')

    def test_yanit_ref_sorgudakinden_farkliysa_benimsenir(self):
        payment = self.paid()
        self.refund(payment, 2500.0)
        self.assertTrue(self.lines(payment).provider_ref.startswith('R-'))
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', 'R-Q'))
        payment.sudo()._sync_status()
        payment.sudo()._sync_status()
        self.assertSingleRefund(payment, 'R-Q')

    def test_yanit_ref_siz_ise_sonradan_benimsenir(self):
        payment = self.paid()
        self.mock.queue('REFUND', ok_body(merchantPaymentId=payment.merchant_payment_id))
        self.refund(payment, 2500.0)
        self.assertFalse(self.lines(payment).provider_ref)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', 'R-Q'))
        payment.sudo()._sync_status()
        self.assertSingleRefund(payment, 'R-Q')

    def test_iptal_tek_satir_kalir(self):
        payment = self.paid()
        self.void(payment)
        ref = self.lines(payment).provider_ref
        self.set_query_transactions(tran('VD', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'VOID', '9000.00', ref))
        payment.sudo()._sync_status()
        payment.sudo()._sync_status()
        lines = self.lines(payment)
        payment.invalidate_recordset()
        self.assertEqual(len(lines), 1, 'VOID + SALE/VD aynı iptal; tek satır')
        self.assertEqual(payment.state, 'voided')

# -*- coding: utf-8 -*-
"""İade onay geçişi: toleranssız karar kuralı, kilit sırası, hata yalıtımı, süre bütçesi (G5).

Kabul testleri (``test_refund_migration.py``) davranışı sınar; burada gelişmiş kurallar var:
bir "Başarılı" satırı yalnız Paratika'da o satıra ait işlemin onaylı OLMADIĞI kesinse çevrilir.
"""
from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import html2plaintext

from .common import qt_body, tran
from .test_refund import RefundCase
from .test_refund_approval import ms, rt

WIZ = 'sanal.pos.refund.approval.wizard'
PAYMENT = 'sanal.pos.payment'
WIZARD_MODULE = 'odoo.addons.sanal_pos.wizard.refund_approval_wizard'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestMigrationDecisionRules(RefundCase):

    def setUp(self):
        super().setUp()
        self.responses = {}

    def case(self, inv, ref, amount, trans):
        payment = self.paid(invoice_no=inv)
        line = self.make_refund_line(payment, amount, provider_ref=ref)
        payment._recompute_refund_state()
        self.responses[payment.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), *trans)
        # paid() QUERYTRANSACTION varsayılanını ezer: ödeme başına yanıtlayıcıyı yeniden bağla
        self.mock.default('QUERYTRANSACTION', lambda p: self.responses[p.get('MERCHANTPAYMENTID')])
        return payment, line

    def respond(self, payment, *trans):
        self.responses[payment.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), *trans)

    def wizard(self):
        return self.env[WIZ].with_user(self.user_mgr).create({})

    def apply(self):
        wiz = self.wizard()
        wiz.action_compare()
        wiz.action_apply()
        return wiz

    def text(self, wiz):
        wiz.invalidate_recordset()
        return html2plaintext(wiz.report_html or '')

    def when(self, line, minutes):
        return ms(line.create_date + timedelta(minutes=minutes))

    # ------------------------------------------------------------------ toleranssız karar
    def test_refsiz_satir_oncesi_tarihli_islemle_cevrilmez(self):
        payment, line = self.case('RUL-1', False, 2500.0, [])
        self.respond(payment, rt('IP', 2500.0, 'R-OLD', timeCreated=self.when(line, -2)))
        wiz = self.apply()
        self.assertEqual(line.state, 'done', 'önceki denemenin işlemi bu satırın kanıtı değildir')
        self.assertIn('Atlandı', self.text(wiz))
        self.assertEqual(payment.state, 'partial_refund')

    def test_refsiz_satir_zamansiz_islemle_cevrilmez(self):
        payment, line = self.case('RUL-2', False, 2500.0, [rt('IP', 2500.0, 'R-NT')])
        self.apply()
        self.assertEqual(line.state, 'done')
        self.assertFalse(line.provider_ref)

    def test_refsiz_satir_sonrasi_tarihli_islemle_cevrilir_ve_ref_baglanir(self):
        payment, line = self.case('RUL-3', False, 2500.0, [])
        self.respond(payment, rt('IP', 2500.0, 'R-NEW', timeCreated=self.when(line, 1)))
        self.apply()
        self.assertEqual(line.state, 'pending_approval')
        self.assertEqual(line.provider_ref, 'R-NEW')
        self.assertEqual(payment.state, 'refund_pending')

    def test_satirin_kendi_refi_sorguda_yoksa_baska_islem_yerine_gecmez(self):
        payment, line = self.case('RUL-4', 'R-MINE', 2500.0, [])
        self.respond(payment, rt('IP', 2500.0, 'R-OTHER', timeCreated=self.when(line, 1)))
        self.apply()
        self.assertEqual(line.state, 'done')
        self.assertEqual(line.provider_ref, 'R-MINE')

    def test_ref_eslesmesi_zamandan_bagimsiz_karar_verir(self):
        payment, line = self.case('RUL-5', 'R-OWN', 2500.0, [])
        self.respond(payment, rt('FA', 2500.0, 'R-OWN', errorCode='ERR10153',
                                 timeCreated=self.when(line, -30)))
        self.apply()
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(payment.state, 'paid')

    # ------------------------------------------------------------------ kilit sırası, yalıtım, bütçe
    def test_paratika_cagrisi_kilit_altinda_yapilmaz(self):
        self.case('RUL-6', 'R-6', 2500.0, [rt('IP', 2500.0, 'R-6')])
        self.case('RUL-7', 'R-7', 1500.0, [rt('IP', 1500.0, 'R-7')])
        events = []
        model = type(self.env[PAYMENT])
        orig_lock, orig_call, orig_commit = (
            model._try_lock_nowait, model._call_provider_safely, model._sp_commit)

        def lock(this):
            events.append('lock')
            return orig_lock(this)

        def call(this, *args, **kwargs):
            events.append('query')
            return orig_call(this, *args, **kwargs)

        def commit(this):
            events.append('commit')
            return orig_commit(this)

        wiz = self.wizard()
        wiz.action_compare()
        with patch.object(model, '_try_lock_nowait', lock), \
                patch.object(model, '_call_provider_safely', call), \
                patch.object(model, '_sp_commit', commit):
            wiz.action_apply()
        self.assertEqual(events.count('lock'), 2)
        for index, event in enumerate(events):
            if event == 'lock':
                following = events[index + 1:]
                upto = following[:following.index('commit')]
                self.assertNotIn('query', upto, 'kilit tutulurken Paratika sorgusu yapılmamalı')

    def test_bir_odemenin_hatasi_digerlerini_durdurmaz(self):
        p1, l1 = self.case('RUL-8', 'R-8', 2500.0, [rt('IP', 2500.0, 'R-8')])
        p2, l2 = self.case('RUL-9', 'R-9', 1500.0, [rt('IP', 1500.0, 'R-9')])
        model = type(self.env[PAYMENT])
        orig = model._apply_status

        def flaky(this, result):
            if this.id == p1.id:
                raise ValueError('beklenmeyen')
            return orig(this, result)

        wiz = self.wizard()
        wiz.action_compare()
        with patch.object(model, '_apply_status', flaky):
            wiz.action_apply()
        self.assertEqual(l1.state, 'done', 'hatalı ödemenin değişikliği geri alınır')
        self.assertEqual(p1.state, 'partial_refund')
        self.assertEqual(l2.state, 'pending_approval')
        self.assertIn('Atlandı', self.text(wiz))

    def test_sure_butcesi_asilirsa_kalanlar_raporlanir_ve_yeniden_uygulanabilir(self):
        payment, line = self.case('RUL-10', 'R-10', 2500.0, [rt('IP', 2500.0, 'R-10')])
        wiz = self.wizard()
        with patch(WIZARD_MODULE + '.TIME_BUDGET', -1):
            wiz.action_compare()
        self.assertIn('süre sınırı', self.text(wiz))
        wiz.action_compare()
        with patch(WIZARD_MODULE + '.TIME_BUDGET', -1):
            wiz.action_apply()
        self.assertEqual(wiz.state, 'compared', 'işlenmeyen ödeme kaldı: yeniden uygulanabilir')
        self.assertEqual(line.state, 'done')
        wiz.action_apply()
        self.assertEqual(wiz.state, 'applied')
        self.assertEqual(line.state, 'pending_approval')

    def test_onizleme_yapilmadan_uygulama_reddedilir(self):
        payment, line = self.case('RUL-11', 'R-11', 2500.0, [rt('IP', 2500.0, 'R-11')])
        with self.assertRaises(UserError):
            self.wizard().action_apply()
        self.assertEqual(line.state, 'done')

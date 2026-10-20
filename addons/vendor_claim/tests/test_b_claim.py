"""KK-B1, B2 (müşteri telefonu önerisi) ve KK-B3, B4 (yönetici geçiş sıkılığı, mobil denetleyici)."""
from unittest.mock import patch

from odoo.tests.common import tagged

from .common import PW, VcCase, VcHttpCase

CONNECTOR = 'ugurlar.tailor.mssql.connector'


class InvoiceMixin:

    def detail(self, name='Mehmet Kaya', code='C-1', mobile=''):
        return {'invoice_no': 'F-1', 'invoice_date': '2026-10-01', 'customer_code': code, 'customer_name': name,
                'customer_mobile': mobile, 'sales_person': 'S', 'items': []}

    def mobiles_for(self, **kw):
        """Üç yol: _fetch_invoice, denetleyici invoice_detail ve form onchange."""
        connector = type(self.env[CONNECTOR])
        out = {}
        with patch.object(connector, 'get_invoice_detail', return_value=self.detail(**kw)):
            out['fetch'] = self.Claim.with_user(self.user)._fetch_invoice('F-1')['customer_mobile']
            out['mobil'] = self.controller('invoice_detail', invoice_no='F-1').get('customer_mobile')
            rec = self.Claim.with_user(self.user).new({'invoice_no': 'F-1'})
            rec._onchange_invoice_no()
            out['onchange'] = rec.customer_mobile
        return {k: (v or '') for k, v in out.items()}

    def history(self, name='Ali Veli', code='C-1', mobile='05321234567'):
        return self.make_claim(customer_code=code, customer_name=name, customer_mobile=mobile)


@tagged('post_install', '-at_install')
class TestMobileHistory(InvoiceMixin, VcCase):

    # ── KK-B1 ──
    def test_kk_b1_ayni_kod_farkli_ad_telefon_bos_kalir(self):
        self.history(name='Ali Veli')
        got = self.mobiles_for(name='Mehmet Kaya')
        self.assertEqual(got, {'fetch': '', 'mobil': '', 'onchange': ''})

    def test_kk_b1_ad_kismen_benzese_de_ayni_degilse_oneri_yok(self):
        self.history(name='Ali Veli')
        self.assertEqual(self.mobiles_for(name='Ali Veli Yilmaz')['fetch'], '')

    # ── KK-B2 ──
    def test_kk_b2_ayni_kod_ve_ad_buyuk_kucuk_harf_ve_bosluk_duyarsiz_oneri_yapilir(self):
        self.history(name='Ali Veli')
        got = self.mobiles_for(name='  ALI VELI ')
        self.assertEqual(got, {'fetch': '05321234567', 'mobil': '05321234567', 'onchange': '05321234567'})

    def test_kk_b2_ayni_ad_iki_farkli_numara_oneri_yok(self):
        self.history(name='Ali Veli', mobile='05321234567')
        self.history(name='ali veli', mobile='05329876543')
        self.assertEqual(self.mobiles_for(name='Ali Veli')['fetch'], '')

    def test_kk_b2_ad_bos_oneri_yok(self):
        self.history(name='Ali Veli')
        for name in ('', None, '   '):
            with self.subTest(ad=name):
                self.assertEqual(self.mobiles_for(name=name)['fetch'], '')

    def test_kk_b2_faturada_numara_varsa_oldugu_gibi_kalir(self):
        self.history(name='Ali Veli')
        self.assertEqual(self.mobiles_for(name='Mehmet Kaya', mobile='0 (533) 111 22 33')['fetch'], '05331112233')

    def test_kk_b2_farkli_kod_oneri_yok(self):
        self.history(name='Ali Veli', code='C-9')
        self.assertEqual(self.mobiles_for(name='Ali Veli', code='C-1')['fetch'], '')


@tagged('post_install', '-at_install')
class TestStrictController(VcCase):

    def setUp(self):
        super().setUp()
        self.vc_setup(auto_sms=True)   # yanlış geçiş olursa SMS kaydı oluşsun
        self.admin = self.env.ref('base.user_admin')

    def _sms_count(self, claim):
        return len(self.claim_sms(claim))

    # ── KK-B3 ──
    def test_kk_b3_delivered_kayit_bulk_send_reddedilir(self):
        for who in (self.manager, self.admin):
            with self.subTest(kullanici=who.login):
                claim = self.make_claim()
                sent_at = self.ago(days=3)
                self.force_state(claim, 'delivered', sent_at=sent_at)
                before = self._sms_count(claim)
                res = self.controller('bulk', user=who, claim_ids=[claim.id], action='send')
                self.assertFalse(res['results'][0]['ok'], res)
                self.assertTrue(res['results'][0]['error'])
                claim.invalidate_recordset()
                self.assertEqual(claim.state, 'delivered')
                self.assertEqual(claim.sent_at, sent_at)
                self.assertEqual(self._sms_count(claim), before, 'SMS kaydı oluşmamalı')

    def test_kk_b3_action_send_de_reddedilir(self):
        claim = self.make_claim()
        self.force_state(claim, 'delivered', sent_at=self.ago(days=3))
        res = self.controller('action', user=self.manager, claim_id=claim.id, action='send')
        self.assertIn('error', res)
        claim.invalidate_recordset()
        self.assertEqual(claim.state, 'delivered')

    # ── KK-B4 ──
    def test_kk_b4_received_kayit_teslim_reddedilir(self):
        for who in (self.manager, self.admin):
            with self.subTest(kullanici=who.login):
                claim = self.make_claim()
                before = self._sms_count(claim)
                res = self.controller('action', user=who, claim_id=claim.id, action='deliver')
                self.assertIn('error', res)
                bulk = self.controller('bulk', user=who, claim_ids=[claim.id], action='deliver')
                self.assertFalse(bulk['results'][0]['ok'], bulk)
                claim.invalidate_recordset()
                self.assertEqual(claim.state, 'received')
                self.assertEqual(self._sms_count(claim), before)

    def test_kk_b4_sent_den_deliver_de_reddedilir(self):
        claim = self.make_claim()
        self.force_state(claim, 'sent', sent_at=self.ago(days=1))
        res = self.controller('action', user=self.manager, claim_id=claim.id, action='deliver')
        self.assertIn('error', res)
        claim.invalidate_recordset()
        self.assertEqual(claim.state, 'sent')

    def test_kk_b4_normal_akis_calisir(self):
        claim = self.make_claim()
        self.assertNotIn('error', self.controller('action', user=self.manager, claim_id=claim.id, action='send'))
        self.assertEqual(claim.state, 'sent')
        self.assertNotIn('error', self.controller('action', user=self.manager, claim_id=claim.id, action='return',
                                                  vals={'result': 'repaired'}))
        self.assertNotIn('error', self.controller('action', user=self.manager, claim_id=claim.id, action='deliver'))
        self.assertEqual(claim.state, 'delivered')

    def test_kk_b3_denetleyici_baglami_backend_yoneticisini_kisitlamaz(self):
        claim = self.make_claim()
        self.controller('action', user=self.manager, claim_id=claim.id, action='deliver')   # reddedilir
        claim.with_user(self.manager).action_mark_delivered()   # backend: serbest
        self.assertEqual(claim.state, 'delivered')


@tagged('post_install', '-at_install')
class TestStrictHttp(VcHttpCase):

    def test_kk_b3_b4_gercek_oturumla_yonetici_gecis_sikiligi(self):
        self.vc_setup(auto_sms=True)
        claim = self.make_claim()
        delivered = self.make_claim()
        self.force_state(delivered, 'delivered', sent_at=self.ago(days=3))
        self.authenticate(self.manager.login, PW)
        res = self.rpc('/vendor_claim/bulk', claim_ids=[delivered.id], action='send')
        self.assertFalse(res['results'][0]['ok'], res)
        res = self.rpc('/vendor_claim/bulk', claim_ids=[claim.id], action='deliver')
        self.assertFalse(res['results'][0]['ok'], res)
        self.env.invalidate_all()
        self.assertEqual((claim.state, delivered.state), ('received', 'delivered'))

# -*- coding: utf-8 -*-
"""Paratika iade onayı geçiş sihirbazı (KK-15, KK-16, KK-17).

Tasarım §8: mevcut "İade edildi" kayıtlarının Paratika'daki gerçek durumla karşılaştırılması
(salt okunur önizleme) ve yönetici onayıyla tek seferlik geçiş. Sihirbaz modeli
``sanal.pos.refund.approval.wizard``; ``action_compare()`` hiçbir iş verisi yazmaz,
``action_apply()`` ödeme başına kilitli, yeniden sorgulu ve idempotent çalışır.
"""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import html2plaintext

from .common import qt_body, timeout_exc, tran
from .test_refund import RefundCase

WIZ = 'sanal.pos.refund.approval.wizard'
PAYMENT = 'sanal.pos.payment'
REFUND = 'sanal.pos.refund'
ICP_KEY = 'sanal_pos.refund_approval_migration_at'
MENU_NAME = 'İade Onay Geçişi'


def rt(status, amount, ref, **extra):
    return tran(status, 'REFUND', '%.2f' % amount, ref, **extra)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundApprovalMigration(RefundCase):

    def setUp(self):
        super().setUp()
        self.assertIn(WIZ, self.env, 'Özellik yok: geçiş sihirbazı modeli tanımlı değil')
        self.responses = {}
        self.mock.default('QUERYTRANSACTION', self._answer)
        self.build()

    # ------------------------------------------------------------------ kurulum
    def _answer(self, params):
        result = self.responses.get(params.get('MERCHANTPAYMENTID'))
        if result is None:
            return qt_body()
        return result

    def case(self, inv, lines, query):
        """Ödenmiş kayıt + done iade satırları. ``query``: Paratika'nın döneceği iade işlemleri
        (Exception örneği ise sorgu hatası)."""
        payment = self.paid(invoice_no=inv)
        made = []
        for amount, ref, extra in lines:
            made.append(self.make_refund_line(payment, amount, state=extra.pop('state', 'done'),
                                              provider_ref=ref, **extra))
        payment._recompute_refund_state()
        if isinstance(query, BaseException):
            self.responses[payment.merchant_payment_id] = query
        else:
            self.responses[payment.merchant_payment_id] = qt_body(
                tran('AP', 'SALE', '9000.00', 'T1'), *query)
        return payment, made

    def build(self):
        self.p1, (self.l1,) = self.case('MIG-P1', [(2500.0, 'R-P1', {})], [rt('IP', 2500.0, 'R-P1')])
        self.p2, (self.l2,) = self.case('MIG-P2', [(1000.0, 'R-P2', {})], [rt('AP', 1000.0, 'R-P2')])
        self.p3, (self.l3,) = self.case(
            'MIG-P3', [(1500.0, 'R-P3', {})], [rt('FA', 1500.0, 'R-P3', errorCode='ERR10153')])
        self.p4, (self.l4a, self.l4b) = self.case(
            'MIG-P4', [(100.0, 'R-P4A', {}), (200.0, 'R-P4B', {})],
            [rt('IP', 100.0, 'R-P4A'), rt('IP', 200.0, 'R-P4B')])
        self.p6, (self.l6, self.l6u) = self.case(
            'MIG-P6', [(300.0, 'R-P6', {}), (400.0, False, {'state': 'unknown'})],
            [rt('IP', 300.0, 'R-P6')])
        self.p8, (self.l8,) = self.case('MIG-P8', [(500.0, 'R-P8', {})], timeout_exc())
        # aday olmayanlar: panel kaynaklı done ve iptal (void) satırı
        self.p10, (self.l10,) = self.case(
            'MIG-P10', [(600.0, 'R-P10', {'source': 'panel'})], [rt('IP', 600.0, 'R-P10')])
        self.p11 = self.paid(invoice_no='MIG-P11')
        self.l11 = self.make_refund_line(self.p11, 9000.0, kind='void', state='done',
                                         provider_ref='V-P11')
        self.p11._recompute_refund_state()
        self.responses[self.p11.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), tran('IP', 'VOID', '9000.00', 'V-P11'))
        # P9: durum 'paid' ama 9000 done panel satırı var -> yalnız tutarsızlık bölümünde
        self.p9 = self.paid(invoice_no='MIG-P9')
        self.l9 = self.make_refund_line(self.p9, 9000.0, state='done', source='panel',
                                        provider_ref='R-P9')
        self.p9.sudo().write({'state': 'paid'})
        self.responses[self.p9.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), rt('AP', 9000.0, 'R-P9'))
        self.env.flush_all()
        self.migrated = self.p1 | self.p3
        # paid() her çağrıda QUERYTRANSACTION varsayılanını yalnız-satış yanıtıyla ezer; ödeme
        # başına yanıt veren yanıtlayıcıyı kurulumun SONUNDA yeniden bağla
        self.mock.default('QUERYTRANSACTION', self._answer)

    def new_wizard(self, user=None):
        return self.env[WIZ].with_user(user or self.user_mgr).create({})

    def snapshot(self):
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("SELECT * FROM sanal_pos_refund ORDER BY id")
        refunds = cr.fetchall()
        cr.execute("SELECT * FROM sanal_pos_payment ORDER BY id")
        payments = cr.fetchall()
        cr.execute("SELECT count(*) FROM mail_message WHERE model = %s", [PAYMENT])
        return refunds, payments, cr.fetchone()[0]

    def compact(self):
        """Idempotans karşılaştırması: write_date gibi zaman damgalarından bağımsız görüntü."""
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT id, state, provider_ref, provider_status, done_at, error_code, error_message, "
            "pending_alert_sent FROM sanal_pos_refund ORDER BY id")
        refunds = self.env.cr.fetchall()
        self.env.cr.execute("SELECT id, state FROM sanal_pos_payment ORDER BY id")
        return refunds, self.env.cr.fetchall()

    def report(self, wiz):
        wiz.invalidate_recordset()
        return html2plaintext(wiz.report_html or '')

    def migration_notes(self, payment):
        return self.chatter(payment).count('İade onay geçişi')

    def reload(self, *records):
        for rec in records:
            rec.invalidate_recordset()

    # ------------------------------------------------------------------ KK-15: karşılaştırma
    def test_kk15_karsilastirma_hicbir_veri_yazmaz(self):
        wiz = self.new_wizard()
        before = self.snapshot()
        self.mock.calls.clear()
        wiz.action_compare()
        self.assertEqual(self.snapshot(), before, 'karşılaştırma iş verisi yazmamalı')
        self.assertEqual(wiz.state, 'compared')
        self.assertEqual(self.mock.count('REFUND', 'VOID'), 0)
        self.assertGreaterEqual(self.mock.count('QUERYTRANSACTION'), 6, 'her aday için salt okunur sorgu')

    def test_kk15_karsilastirma_commit_etmez_ve_icp_yazmaz(self):
        wiz = self.new_wizard()
        commits = self.commit_count
        wiz.action_compare()
        self.assertEqual(self.commit_count, commits)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param(ICP_KEY))

    def test_kk15_rapor_icerigi_planlanan_eylemler(self):
        wiz = self.new_wizard()
        wiz.action_compare()
        text = self.report(wiz)
        for needle in ('MIG-P1', 'MIG-P2', 'MIG-P3', 'MIG-P4', 'MIG-P6', 'MIG-P8', 'MIG-P9',
                       'Değişmez (AP)', "Onay bekliyor'a alınacak", 'Atlanacak', 'IP', 'FA'):
            with self.subTest(icerik=needle):
                self.assertIn(needle, text)
        for payment in (self.p1, self.p2, self.p3):
            self.assertIn(payment.name, text, 'Talep No raporda görünmeli')

    def test_kk15_rapor_satir_bazinda_dogru_eylem(self):
        wiz = self.new_wizard()
        wiz.action_compare()
        lines = [l for l in self.report(wiz).splitlines() if l.strip()]

        def row(marker):
            found = [l for l in lines if marker in l]
            self.assertTrue(found, '%s raporda yok' % marker)
            return ' '.join(found)

        self.assertIn("Onay bekliyor'a alınacak", row('MIG-P1'))
        self.assertIn('Değişmez (AP)', row('MIG-P2'))
        self.assertIn("Onay bekliyor'a alınacak", row('MIG-P3'))
        for marker in ('MIG-P4', 'MIG-P6', 'MIG-P8'):
            self.assertIn('Atlanacak', row(marker), marker)

    def test_kk15_panel_ve_void_satirlari_aday_degildir(self):
        wiz = self.new_wizard()
        wiz.action_compare()
        text = self.report(wiz)
        self.assertNotIn('R-P10', text, 'panel kaynaklı satır dönüştürülecekler arasında olmamalı')
        self.assertNotIn('V-P11', text)

    def test_kk15_tutarsiz_kayit_ikinci_bolumde(self):
        wiz = self.new_wizard()
        wiz.action_compare()
        text = self.report(wiz)
        self.assertIn('MIG-P9', text)
        self.assertEqual(self.p9.state, 'paid', 'rapor yalnız bildirir, düzeltmez')

    def test_kk15_yetki_yalniz_yonetici(self):
        for user in (self.user_sp, self.user_plain):
            with self.subTest(kullanici=user.login):
                with self.assertRaises(AccessError):
                    self.env[WIZ].with_user(user).create({})

    def test_kk15_yetkisiz_kullanici_sudo_olusturulan_sihirbazi_calistiramaz(self):
        wiz = self.env[WIZ].sudo().create({})
        before = self.snapshot()
        for user in (self.user_sp, self.user_plain):
            with self.subTest(kullanici=user.login):
                with self.assertRaises(UserError):  # AccessError de UserError alt sınıfı; Odoo assertRaises demet almaz
                    wiz.with_user(user).action_compare()
                with self.assertRaises(UserError):  # AccessError de UserError alt sınıfı; Odoo assertRaises demet almaz
                    wiz.with_user(user).action_apply()
        self.assertEqual(self.snapshot(), before)

    def test_kk15_sihirbaz_kaydi_yalniz_olusturana_gorunur(self):
        mgr2 = self._make_user('sp_manager2', ['sanal_pos.group_sanal_pos_manager'])
        wiz = self.new_wizard()
        with self.assertRaises(AccessError):
            wiz.with_user(mgr2).read(['state'])
        self.assertTrue(wiz.read(['state']))

    def test_kk15_acl_ve_menu_yalniz_yonetici(self):
        model = self.env['ir.model']._get(WIZ)
        accesses = self.env['ir.model.access'].sudo().search([('model_id', '=', model.id)])
        self.assertTrue(accesses)
        manager_group = self.env.ref('sanal_pos.group_sanal_pos_manager')
        for access in accesses:
            self.assertEqual(access.group_id, manager_group, 'yalnız yönetici grubu')
            self.assertFalse(access.perm_unlink)
            self.assertTrue(access.perm_read and access.perm_write and access.perm_create)
        menus = self.env['ir.ui.menu'].sudo().search([('name', '=', MENU_NAME)])
        self.assertEqual(len(menus), 1, 'menü yok')
        field = 'group_ids' if 'group_ids' in menus._fields else 'groups_id'
        self.assertEqual(menus[field], manager_group)
        Menu = self.env['ir.ui.menu']
        self.assertIn(menus.id, Menu.with_user(self.user_mgr)._visible_menu_ids())
        self.assertNotIn(menus.id, Menu.with_user(self.user_sp)._visible_menu_ids())

    # ------------------------------------------------------------------ KK-16: uygulama
    def apply(self, user=None):
        wiz = self.new_wizard(user)
        wiz.action_compare()
        wiz.action_apply()
        return wiz

    def test_kk16_uygula_ap_olmayan_done_satirlarini_bekletir(self):
        wiz = self.apply()
        self.reload(self.l1, self.p1)
        self.assertEqual(self.l1.state, 'pending_approval')
        self.assertFalse(self.l1.done_at)
        self.assertFalse(self.l1.pending_alert_sent)
        self.assertEqual(self.l1.provider_status, 'IP')
        self.assertEqual(self.l1.provider_ref, 'R-P1')
        self.assertEqual(self.p1.state, 'refund_pending')
        self.assertEqual(self.p1.refunded_amount, 0.0)
        self.assertEqual(self.p1.refundable_amount, 6500.0)
        self.assertEqual(self.migration_notes(self.p1), 1)
        self.assertEqual(wiz.state, 'applied')

    def test_kk16_ap_olan_satir_degismez(self):
        before_done_at = self.l2.done_at
        self.apply()
        self.reload(self.l2, self.p2)
        self.assertEqual(self.l2.state, 'done')
        self.assertEqual(self.l2.done_at, before_done_at)
        self.assertEqual(self.p2.state, 'partial_refund')
        self.assertEqual(self.p2.refunded_amount, 1000.0)
        self.assertEqual(self.migration_notes(self.p2), 0)

    def test_kk16_reddedilmis_iade_rejected_olur_odeme_paid(self):
        self.apply()
        self.reload(self.l3, self.p3)
        self.assertEqual(self.l3.state, 'rejected')
        self.assertEqual(self.l3.error_code, 'ERR10153')
        self.assertIn('Finans ekibi tarafından reddedildi', self.l3.error_message)
        self.assertEqual(self.p3.state, 'paid')
        self.assertEqual(self.p3.refunded_amount, 0.0)
        self.assertEqual(self.p3.refundable_amount, 9000.0)
        self.assertEqual(self.migration_notes(self.p3), 1)

    def test_kk16_atlananlar_degismez(self):
        before = {rec: rec.state for rec in (self.l4a | self.l4b | self.l6 | self.l6u | self.l8
                                             | self.l10 | self.l11 | self.l9)}
        payments_before = {p: p.state for p in (self.p4, self.p6, self.p8, self.p10, self.p11, self.p9)}
        self.apply()
        for rec, state in before.items():
            self.reload(rec)
            self.assertEqual(rec.state, state, '%s değişmemeli' % rec.provider_ref)
        for payment, state in payments_before.items():
            self.reload(payment)
            self.assertEqual(payment.state, state)
        for payment in (self.p4, self.p6, self.p8):
            self.assertEqual(self.migration_notes(payment), 0)

    def test_kk16_atlama_sebepleri_raporda(self):
        wiz = self.apply()
        text = self.report(wiz).lower()
        self.assertIn('atla', text)

    def test_kk16_commit_odeme_basina_ve_icp_damgasi(self):
        commits = self.commit_count
        self.apply()
        self.assertGreaterEqual(self.commit_count - commits, len(self.migrated),
                                'ödeme başına commit (kilit kısa tutulur)')
        self.assertTrue(self.env['ir.config_parameter'].sudo().get_param(ICP_KEY))

    def test_kk16_uygulama_paratikaya_iade_ya_da_iptal_gondermez(self):
        self.mock.calls.clear()
        self.apply()
        self.assertEqual(self.mock.count('REFUND', 'VOID'), 0)

    def test_kk16_ikinci_uygulama_idempotent(self):
        self.apply()
        first = self.compact()
        notes = {p: self.migration_notes(p) for p in (self.p1, self.p3)}
        wiz = self.apply()
        self.assertEqual(self.compact(), first, 'ikinci uygulama hiçbir şeyi değiştirmemeli')
        for payment, count in notes.items():
            self.assertEqual(self.migration_notes(payment), count, 'chatter çoğalmamalı')
        self.assertEqual(wiz.state, 'applied')

    def test_kk16_gecis_sonrasi_normal_senkron_pending_i_onaylar(self):
        self.apply()
        self.responses[self.p1.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), rt('AP', 2500.0, 'R-P1'))
        self.p1.sudo()._sync_status()
        self.reload(self.l1, self.p1)
        self.assertEqual(self.l1.state, 'done')
        self.assertEqual(self.p1.state, 'partial_refund')

    def test_kk16_kilit_alinamayan_odeme_atlanir(self):
        model = type(self.env[PAYMENT])
        wiz = self.new_wizard()
        wiz.action_compare()
        with patch.object(model, '_try_lock_nowait', return_value=False):
            wiz.action_apply()
        self.reload(self.l1, self.l3, self.p1)
        self.assertEqual(self.l1.state, 'done', 'kilit yoksa dokunulmaz')
        self.assertEqual(self.l3.state, 'done')
        self.assertEqual(self.p1.state, 'partial_refund')
        self.assertIn('atla', self.report(wiz).lower())

    def test_kk16_uygulama_sirasinda_paratika_durumu_degisirse_yeniden_sorgu(self):
        wiz = self.new_wizard()
        wiz.action_compare()
        # önizlemeden sonra Paratika P1'i onayladı: uygulama yeniden sorgular, dönüştürmez
        self.responses[self.p1.merchant_payment_id] = qt_body(
            tran('AP', 'SALE', '9000.00', 'T1'), rt('AP', 2500.0, 'R-P1'))
        wiz.action_apply()
        self.reload(self.l1, self.p1)
        self.assertEqual(self.l1.state, 'done', 'AP olan satır bekletilmemeli')
        self.assertEqual(self.p1.state, 'partial_refund')
        self.assertEqual(self.migration_notes(self.p1), 0)

    def test_kk16_yetkisiz_uygulama_hicbir_sey_degistirmez(self):
        wiz = self.env[WIZ].sudo().create({})
        wiz.sudo().action_compare()
        before = self.compact()
        with self.assertRaises(UserError):  # AccessError de UserError alt sınıfı; Odoo assertRaises demet almaz
            wiz.with_user(self.user_sp).action_apply()
        self.assertEqual(self.compact(), before)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param(ICP_KEY))

    # Test raporu M19: yönetici denetimi her iki eylemde de kendi mesajıyla (ACL değil) devrede
    def test_m19_sudo_olusturulmus_sihirbaz_yonetici_olmayan_kullanicida_calismaz(self):
        wiz = self.env[WIZ].sudo().create({})
        before = self.compact()
        with self.assertRaisesRegex(AccessError, 'yönetici yetkisi'):
            wiz.with_user(self.user_sp).action_compare()
        wiz.sudo().action_compare()
        with self.assertRaisesRegex(AccessError, 'yönetici yetkisi'):
            wiz.with_user(self.user_sp).action_apply()
        self.assertEqual(self.compact(), before)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param(ICP_KEY))

    # Güvenlik D-1: aşama ve rapor istemciden yazılamaz; karşılaştırma atlanamaz
    def test_d1_istemci_asama_ve_raporu_yazamaz_karsilastirma_atlanamaz(self):
        wiz = self.env[WIZ].with_user(self.user_mgr).create(
            {'state': 'compared', 'report_html': '<p>sahte rapor</p>'})
        wiz.invalidate_recordset()
        self.assertEqual(wiz.state, 'draft')
        self.assertNotIn('sahte', self.report(wiz))
        wiz.write({'state': 'compared', 'report_html': '<p>sahte rapor</p>'})
        wiz.invalidate_recordset()
        self.assertEqual(wiz.state, 'draft')
        self.assertNotIn('sahte', self.report(wiz))
        before = self.compact()
        with self.assertRaisesRegex(UserError, 'Karşılaştır'):
            wiz.action_apply()
        self.assertEqual(self.compact(), before)

    def test_d1_default_baglamiyla_da_asama_ve_rapor_yazilamaz(self):
        # RPC context'i istemcidedir: default_* create'te süzmeden SONRA uygulanır (düzeltme turu #2)
        ctx = {'default_state': 'compared', 'default_report_html': '<p>sahte rapor</p>'}
        Wiz = self.env[WIZ].with_user(self.user_mgr).with_context(**ctx)
        defaults = Wiz.default_get(['state', 'report_html'])
        self.assertEqual(defaults.get('state'), 'draft')
        self.assertFalse(defaults.get('report_html'))
        wiz = Wiz.create({})
        wiz.invalidate_recordset()
        self.assertEqual(wiz.state, 'draft')
        self.assertNotIn('sahte', self.report(wiz))
        before = self.compact()
        with self.assertRaisesRegex(UserError, 'Karşılaştır'):
            wiz.action_apply()
        self.assertEqual(self.compact(), before)

    def test_kk16_migrations_klasoru_yok(self):
        from odoo.tools import file_path
        import os
        manifest = file_path('sanal_pos/__manifest__.py')
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(manifest), 'migrations')),
                         'dış API çağıran migrate betiği olmamalı (sihirbaz kullanılır)')

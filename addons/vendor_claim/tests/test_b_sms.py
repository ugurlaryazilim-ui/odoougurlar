"""KK-B7, B8, B11..B15, B19, B20, B23 ve KK-A8 (vendor yanı): vendor_claim SMS davranışları.

Not: otomatik durum SMS'i (sms_<durum>_enabled) ile elle SMS ucundaki 60 sn aynı-şablon koruması çakışabilir;
elle SMS testleri otomatik durum SMS'ini kapatır (vc_setup(auto_sms=False) varsayılanı).
"""
import time
from unittest.mock import patch

import requests
from lxml import etree
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.tools.safe_eval import safe_eval

from .common import PIXEL, VcCase

SENDING = ('queued', 'sending', 'sent', 'test')


@tagged('post_install', '-at_install')
class TestManualSms(VcCase):

    # ── KK-B7 (K4) ──
    def test_kk_b7_60_sn_icinde_ayni_sablon_ikinci_kayit_olusturmaz(self):
        claim = self.make_claim()
        first = self.controller('send_sms', claim_id=claim.id)
        self.assertTrue(first.get('ok'), first)
        self.assertEqual(len(self.claim_sms(claim)), 1)
        second = self.controller('send_sms', claim_id=claim.id)
        self.assertIn('error', second, 'ikinci cihazdan aynı SMS engellenmeli')
        self.assertIn('Bu kayıt için az önce SMS gönderildi', second['error'])
        self.assertEqual(len(self.claim_sms(claim)), 1, 'yeni SMS kaydı oluşmamalı')

    def test_kk_b7_canli_modda_queued_kayit_da_korumayi_tetikler(self):
        self.set_param('test_mode', 'False')
        claim = self.make_claim()
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        self.assertEqual(self.net.turatel_calls, [], 'HTTP isteği içinde sağlayıcı çağrısı yok')
        self.assertIn('az önce', self.controller('send_sms', claim_id=claim.id).get('error', ''))
        self.assertEqual(len(self.claim_sms(claim)), 1)

    def test_kk_b7_60_sn_sonra_ve_farkli_sablonla_yeniden_gonderilebilir(self):
        claim = self.make_claim()
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        self.set_create_date(self.claim_sms(claim), 2)   # 2 dk önce
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        self.assertEqual(len(self.claim_sms(claim)), 2)
        self.force_state(claim, 'sent')   # durum değişti: farklı şablon
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        self.assertEqual(len(self.claim_sms(claim)), 3)

    def test_kk_b7_hatali_onceki_kayit_korumayi_tetiklemez(self):
        claim = self.make_claim()
        self.make_message(state='error', res_model='vendor.claim', res_id=claim.id, number='5321234567')
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))

    # ── KK-B8 + KK-A8 (vendor) ──
    def test_kk_b8_sinir_dolunca_hata_ve_sifir_kayit(self):
        self.set_param('user_daily_limit', '2')
        claims = [self.make_claim(customer_mobile='0532123456%d' % i) for i in range(3)]
        for claim in claims[:2]:
            self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        res = self.controller('send_sms', claim_id=claims[2].id)
        self.assertIn('error', res)
        self.assertTrue(res['error'])
        self.assertFalse(self.claim_sms(claims[2]), 'sınır dolunca 0 kayıt oluşmalı')

    def test_kk_b8_sms_yoneticisi_sinirdan_muaf(self):
        self.set_param('user_daily_limit', '1')
        claims = [self.make_claim(customer_mobile='0532123456%d' % i) for i in range(3)]
        for claim in claims:
            self.assertTrue(self.controller('send_sms', user=self.sms_manager, claim_id=claim.id).get('ok'))
        self.assertTrue(all(self.claim_sms(c) for c in claims))

    def test_kk_a8_mobil_sms_numara_basina_1_kayit_ve_user_id(self):
        claim = self.make_claim()
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        msgs = self.claim_sms(claim)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs.number, '5321234567')
        self.assertEqual(msgs.user_id, self.user)

    # ── KK-B15 (sunucu tarafı) ──
    def test_kk_b15_test_modunda_mesaj_test_modu_yazar(self):
        claim = self.make_claim()
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertTrue(res.get('ok'), res)
        self.assertIn('Test modu: SMS gönderilmedi', res['message'])
        self.assertNotIn('SMS gönderildi', res['message'])
        self.assertEqual(self.claim_sms(claim).state, 'test')
        self.assertEqual(self.net.calls, [])

    def test_kk_b15_canli_modda_sms_gonderildi_yazar_ama_saglayici_cagrisi_yok(self):
        self.set_param('test_mode', 'False')
        claim = self.make_claim()
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertTrue(res.get('ok'), res)
        self.assertNotIn('Test modu', res['message'])
        self.assertEqual(self.net.turatel_calls, [], 'HTTP isteği sırasında sağlayıcıya gidilmemeli (kuyruk)')
        self.assertEqual(self.claim_sms(claim).state, 'queued')


@tagged('post_install', '-at_install')
class TestStateSms(VcCase):

    def setUp(self):
        super().setUp()
        self.vc_setup(test_mode='False', auto_sms=True)

    # ── KK-B11 ──
    def _bulk_send(self, count=40):
        claims = [self.make_claim(customer_mobile='05321%06d' % i) for i in range(count)]
        self.assertEqual(self.net.turatel_calls, [], 'kayıt oluşturma sırasında sağlayıcı çağrısı yok')
        self.net.turatel_script = [requests.exceptions.ConnectTimeout()] * (count * 3)
        started = time.monotonic()
        res = self.controller('bulk', claim_ids=[c.id for c in claims], action='send')
        elapsed = time.monotonic() - started
        return claims, res, elapsed

    def test_kk_b11_bulk_40_kayit_istek_suresince_saglayici_cagrisi_0(self):
        before = len(self.net.turatel_calls)
        claims, res, elapsed = self._bulk_send()
        self.assertEqual([r['ok'] for r in res['results']], [True] * 40)
        self.assertEqual(len(self.net.turatel_calls), before, 'bulk isteği sağlayıcıyı çağırmamalı')
        self.assertLess(elapsed, 5)
        states = set(self.claim_sms(claims[0]).mapped('state')) | set(self.claim_sms(claims[-1]).mapped('state'))
        self.assertEqual(states, {'queued'})

    def test_kk_b11_test_modunda_kayitlar_test_olur(self):
        self.set_param('test_mode', 'True')
        claims, res, elapsed = self._bulk_send()
        self.assertEqual(self.net.calls, [])
        self.assertEqual(set(self.claim_sms(claims[0]).mapped('state')), {'test'})

    def test_kk_b11_commit_sonrasi_kuyruk_cron_gonderir(self):
        self.net.turatel_script = []
        claims = [self.make_claim(customer_mobile='05321%06d' % i) for i in range(5)]
        self.assertEqual(self.net.turatel_calls, [])
        queued = self.claim_sms(claims[0]) | self.claim_sms(claims[1])
        self.assertEqual(set(queued.mapped('state')), {'queued'})
        cron = getattr(self.env['sms.system.message'], '_cron_send_queued', None)
        if cron is None:
            self.fail('ARAYÜZ YOK: sms.system.message._cron_send_queued')
        cron()
        self.env.invalidate_all()
        self.assertEqual(set(self.claim_sms(c).state for c in claims), {'sent'})
        self.assertEqual(len(self.net.sent_numbers), 5)

    # ── KK-B12 ──
    def test_kk_b12_foto_hatasi_sms_kaydi_ve_cagri_birakmaz(self):
        before = self.env['sms.system.message'].sudo().search_count([])
        res = self.controller('create_claim', data={
            'customer_name': 'Foto Hata', 'customer_mobile': '05321234567', 'product_barcode': '8690000000311',
            'defect_description': 'x'}, photos=['data:image/png;base64,abc'])   # eksik dolgu: çözme hatası
        self.assertIn('error', res)
        self.assertFalse(self.Claim.sudo().search([('customer_name', '=', 'Foto Hata')]))
        self.assertEqual(self.env['sms.system.message'].sudo().search_count([]), before, 'SMS kaydı kalmamalı')
        self.assertEqual(self.net.calls, [], 'sağlayıcı çağrısı yapılmamalı')

    def test_kk_b12_fotograflar_sms_kaydindan_once_eklenir(self):
        seen = []
        Message = self.env['sms.system.message']
        real = type(Message).send_sms

        def spy(this, *args, **kwargs):
            record = kwargs.get('record')
            seen.append(len(record.photo_ids) if record else None)
            return real(this, *args, **kwargs)

        from unittest.mock import patch
        with patch.object(type(Message), 'send_sms', spy):
            res = self.controller('create_claim', data={
                'customer_name': 'Foto Tamam', 'customer_mobile': '05321234567',
                'product_barcode': '8690000000311', 'defect_description': 'x'},
                photos=['data:image/png;base64,' + PIXEL])
        self.assertIn('id', res, res)
        self.assertEqual(seen, [1], 'SMS çağrısı anında fotoğraf kayda bağlı olmalı')
        self.assertEqual(self.claim_sms(self.Claim.browse(res['id'])).mapped('state'), ['queued'])

    # ── KK-B13 ──
    def test_kk_b13_gecis_basina_en_cok_1_kuyruga_alma(self):
        claim = self.make_claim()
        result = claim._notify_state_sms()
        self.assertIsInstance(result, dict, '_notify_state_sms {id: {state, error}} döndürmeli')
        self.assertEqual(result[claim.id]['state'], 'queued')
        self.assertEqual(len(self.claim_sms(claim)), 1)
        for _i in range(3):
            claim._notify_state_sms()
        self.assertEqual(len(self.claim_sms(claim)), 1, 'aynı geçiş tekrar tetiklense de ikinci kayıt oluşmamalı')
        self.assertTrue(claim.sms_received_sent)
        claim.action_send_to_vendor()
        claim._notify_state_sms()
        self.assertEqual(len(self.claim_sms(claim)), 2)
        self.assertEqual(set(self.claim_sms(claim).mapped('state')), {'queued'})

    def test_kk_b13_bayrak_kuyruga_alinca_set_edilir(self):
        claim = self.make_claim()
        claim.action_send_to_vendor()
        self.assertTrue(claim.sms_sent_sent, 'queued kayıtta bayrak işaretlenmeli')
        self.assertEqual(self.claim_sms(claim).mapped('state'), ['queued', 'queued'])

    # ── KK-B14 (sunucu yanıtı) ──
    def test_kk_b14_create_yaniti_sms_durumu_tasir(self):
        data = {'customer_name': 'Yanit', 'customer_mobile': '05321234567', 'product_barcode': '8690000000311',
                'defect_description': 'x'}
        res = self.controller('create_claim', data=dict(data))
        self.assertEqual(res.get('sms', {}).get('state'), 'queued', res)
        self.set_param('test_mode', 'True')
        res = self.controller('create_claim', data=dict(data))
        self.assertEqual(res['sms']['state'], 'test')
        res = self.controller('create_claim', data=dict(data, customer_mobile=''))
        self.assertEqual(res['sms']['state'], 'none')

    def test_kk_b14_hata_durumunda_error_metni_doner(self):
        self.set_param('turatel_originator', '')   # başlık yok: kayıt error olur
        res = self.controller('create_claim', data={
            'customer_name': 'Hata', 'customer_mobile': '05321234567', 'product_barcode': '8690000000311',
            'defect_description': 'x'})
        self.assertEqual(res.get('sms', {}).get('state'), 'error', res)
        self.assertTrue(res['sms']['error'])

    def test_kk_b14_action_ve_bulk_yaniti_sms_tasir(self):
        claim = self.make_claim()
        detail = self.controller('action', claim_id=claim.id, action='send')
        self.assertEqual(detail.get('sms', {}).get('state'), 'queued', detail)
        other = self.make_claim(customer_mobile='')
        bulk = self.controller('bulk', claim_ids=[other.id], action='send')
        self.assertEqual(bulk['results'][0]['sms']['state'], 'none')
        third = self.make_claim(customer_mobile='05329990000')
        bulk = self.controller('bulk', claim_ids=[third.id], action='send')
        self.assertEqual(bulk['results'][0]['sms']['state'], 'queued')

    def test_kk_b14_otomatik_sms_kapaliysa_none(self):
        self.vc_setup(test_mode='False', auto_sms=False)
        claim = self.make_claim()
        detail = self.controller('action', claim_id=claim.id, action='send')
        self.assertEqual(detail.get('sms', {}).get('state'), 'none', detail)


@tagged('post_install', '-at_install')
class TestReminders(VcCase):

    def _returned(self, mobile='05321234567', days=5, **extra):
        claim = self.make_claim(customer_mobile=mobile)
        self.force_state(claim, 'returned', sent_at=self.ago(days=days + 2), returned_at=self.ago(days=days),
                         result='repaired', **extra)
        return claim

    def _enable_reminders(self):
        self.icp.set_param('vendor_claim.sms_reminder_enabled', 'True')

    # ── KK-B19 ──
    def test_kk_b19_yeniden_gonderilince_sayaclar_sifirlanir(self):
        claim = self._returned(reminder_count=2, last_reminder_at=self.ago(days=1))
        claim.action_send_to_vendor()
        self.assertEqual(claim.reminder_count, 0)
        self.assertFalse(claim.last_reminder_at)

    def test_kk_b19_donunce_cron_tanimli_sayi_kadar_yeniden_hatirlatir(self):
        self._enable_reminders()
        claim = self._returned(reminder_count=2, last_reminder_at=self.ago(days=4))
        claim.action_send_to_vendor()
        self.force_state(claim, 'returned', returned_at=self.ago(days=5), result='repaired')
        before = len(self.claim_sms(claim))
        for expected in (1, 2, 2):
            self.Claim._cron_return_reminders()
            claim.invalidate_recordset()
            self.assertEqual(claim.reminder_count, expected)
            claim.sudo().last_reminder_at = self.ago(days=4)
        self.assertEqual(len(self.claim_sms(claim)), before + 2, 'en çok tanımlı sayı (2) kadar hatırlatma')

    # ── KK-B20 ──
    def test_kk_b20_mobil_hatirlatma_sayaci_arttirir_ve_cron_ayni_gun_gondermez(self):
        self._enable_reminders()
        claim = self._returned(sms_returned_sent=True)
        before = len(self.claim_sms(claim))
        res = self.controller('send_sms', claim_id=claim.id)
        self.assertTrue(res.get('ok'), res)
        claim.invalidate_recordset()
        self.assertEqual(claim.reminder_count, 1)
        self.assertTrue(claim.last_reminder_at)
        self.assertLess(abs((claim.last_reminder_at - self.ago()).total_seconds()), 120)
        self.assertEqual(len(self.claim_sms(claim)), before + 1)
        self.Claim._cron_return_reminders()
        claim.invalidate_recordset()
        self.assertEqual(claim.reminder_count, 1, 'aynı gün cron ikinci hatırlatma göndermemeli')
        self.assertEqual(len(self.claim_sms(claim)), before + 1)

    def test_kk_b20_ilk_sms_hatirlatma_degilse_sayac_artmaz(self):
        claim = self._returned()   # returned SMS daha gönderilmedi: şablon 'returned'
        self.assertTrue(self.controller('send_sms', claim_id=claim.id).get('ok'))
        claim.invalidate_recordset()
        self.assertEqual(claim.reminder_count, 0)

    # ── KK-B23 ──
    def test_kk_b23_kesinti_olsa_da_gonderilen_sayaclar_kalici(self):
        self._enable_reminders()
        claims = [self._returned('05321%06d' % i) for i in range(5)]
        ids = tuple(c.id for c in claims)
        snapshots = []
        count = {'n': 0}
        env = self.env

        def fake_commit(cron, processed=0, *, remaining=None, deactivate=False):
            cron.env.flush_all()
            env.cr.execute('SELECT id, reminder_count FROM vendor_claim WHERE id IN %s', (ids,))
            snapshots.append(dict(env.cr.fetchall()))
            count['n'] += 1
            if count['n'] == 4:
                raise RuntimeError('kesinti')
            return 1000.0

        from unittest.mock import patch
        with patch.object(self.env.registry['ir.cron'], '_commit_progress', fake_commit):
            try:
                self.Claim._cron_return_reminders()
            except RuntimeError:
                pass
        if not snapshots:
            self.fail('_cron_return_reminders ir.cron._commit_progress çağırmıyor (kayıt başına commit yok)')
        self.assertEqual(len(snapshots), 4, 'her kayıttan sonra commit edilmeli (kesinti 4. çağrıda)')
        self.assertEqual(sum(snapshots[2].values()), 3, '3. kayıttan sonra 3 sayaç kalıcı olmalı')
        done = [c for c in claims if self.env['vendor.claim'].browse(c.id).reminder_count == 1]
        self.assertGreaterEqual(len(done), 3)
        before = {c.id: len(self.claim_sms(c)) for c in done}
        self.Claim._cron_return_reminders()   # kaldığı yerden
        for claim in claims:
            claim.invalidate_recordset()
            self.assertEqual(claim.reminder_count, 1)
        for claim in done:
            self.assertEqual(len(self.claim_sms(claim)), before[claim.id], 'gönderilen müşteriye yeniden gönderilmemeli')
        self.assertTrue(all(self.claim_sms(c) for c in claims))

    def test_kk_b23_cron_kuyruga_alir_dogrudan_gonderim_yok(self):
        self.set_param('test_mode', 'False')
        self._enable_reminders()
        claim = self._returned()
        self.Claim._cron_return_reminders()
        self.assertEqual(self.net.turatel_calls, [], 'hatırlatma cron\'u sağlayıcıyı doğrudan çağırmamalı')
        self.assertEqual(self.claim_sms(claim).mapped('state'), ['queued'])


@tagged('post_install', '-at_install')
class TestStrictAndLinks(VcCase):

    # ── KK-B5 (regresyon) ──
    def test_kk_b5_backend_yonetici_serbest_gecis_normal_kullanici_kurallari_ayni(self):
        claim = self.make_claim()
        claim.with_user(self.manager).action_mark_delivered()
        self.assertEqual(claim.state, 'delivered')
        claim2 = self.make_claim()
        claim2.with_user(self.manager).write({'state': 'returned'})
        self.assertEqual(claim2.state, 'returned')
        claim3 = self.make_claim()
        with self.assertRaises(UserError):
            claim3.action_mark_delivered()
        with self.assertRaises(UserError):
            claim3.write({'state': 'returned'})

    # ── KK-B21 ──
    def _orphan(self, user=None, **vals):
        base = {'name': 'x.jpg', 'datas': 'eA==', 'mimetype': 'image/jpeg'}
        base.update(vals)
        return self.env['ir.attachment'].with_user(user or self.user2).sudo().create(base)

    def test_kk_b21_baska_kullanicinin_sahipsiz_eki_baglanmaz(self):
        claim = self.make_claim()
        foreign = self._orphan(self.user2)
        self.assertFalse(foreign.res_model)
        claim.sudo().write({'photo_ids': [(4, foreign.id)]})
        foreign.invalidate_recordset()
        self.assertFalse(foreign.res_model, 'başkasının sahipsiz eki kayda bağlanmamalı')
        self.assertFalse(foreign.res_id)

    def test_kk_b21_vendor_report_ids_icin_de_gecerli(self):
        claim = self.make_claim()
        foreign = self._orphan(self.user2)
        claim.sudo().write({'vendor_report_ids': [(4, foreign.id)]})
        foreign.invalidate_recordset()
        self.assertFalse(foreign.res_model)

    def test_kk_b21_kullanicinin_kendi_sahipsiz_eki_baglanir(self):
        claim = self.make_claim()
        own = self._orphan(self.user)
        claim.sudo().write({'photo_ids': [(4, own.id)]})
        own.invalidate_recordset()
        self.assertEqual((own.res_model, own.res_id), ('vendor.claim', claim.id))

    def test_kk_b21_vendor_claim_res_id_bos_ek_baglanir(self):
        claim = self.make_claim()
        pending = self._orphan(self.user, res_model='vendor.claim', res_id=0)   # formda yüklenip kaydedilmemiş
        claim.sudo().write({'photo_ids': [(4, pending.id)]})
        pending.invalidate_recordset()
        self.assertEqual((pending.res_model, pending.res_id), ('vendor.claim', claim.id))

    def test_g2_baska_kullanicinin_vendor_claim_res_id_bos_eki_baglanmaz(self):
        claim = self.make_claim()
        for field in ('photo_ids', 'vendor_report_ids'):
            with self.subTest(alan=field):
                foreign = self._orphan(self.user2, res_model='vendor.claim', res_id=0)
                claim.sudo().write({field: [(4, foreign.id)]})
                foreign.invalidate_recordset()
                self.assertEqual((foreign.res_model, foreign.res_id), ('vendor.claim', 0),
                                 'başkasının kaydedilmemiş eki kayda bağlanmamalı')

    def test_kk_b21_baska_modele_ait_ek_dokunulmaz(self):
        claim = self.make_claim()
        partner = self.env['res.partner'].create({'name': 'P'})
        other = self._orphan(self.user2, res_model='res.partner', res_id=partner.id)
        claim.sudo().write({'photo_ids': [(4, other.id)]})
        other.invalidate_recordset()
        self.assertEqual((other.res_model, other.res_id), ('res.partner', partner.id))


@tagged('post_install', '-at_install')
class TestCancelButtonVisibility(VcCase):
    """KK-B18 + B-2: form başlığında her durumda en çok bir 'İptal Et' düğmesi görünür."""

    def _visible_cancel_buttons(self, user, state):
        arch = self.Claim.with_user(user).get_view(view_type='form')['arch']
        buttons = etree.fromstring(arch).xpath("//header/button[@name='action_cancel']")
        return [b for b in buttons if not safe_eval(b.get('invisible') or 'False', {'state': state})]

    def test_b18_b2_yonetici_icin_tek_iptal_dugmesi(self):
        for state, expected in (('received', 1), ('sent', 1), ('returned', 1), ('delivered', 0), ('cancelled', 0)):
            with self.subTest(state=state):
                self.assertEqual(len(self._visible_cancel_buttons(self.manager, state)), expected)

    def test_b18_normal_kullanici_yalniz_received_ve_sent(self):
        for state, expected in (('received', 1), ('sent', 1), ('returned', 0), ('delivered', 0), ('cancelled', 0)):
            with self.subTest(state=state):
                self.assertEqual(len(self._visible_cancel_buttons(self.user, state)), expected)

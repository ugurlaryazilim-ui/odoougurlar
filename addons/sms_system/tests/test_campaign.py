"""KK-A9..A14 (yeniden gönderim, belirsiz), KK-A18..A20 (İYS kapsamı ve notları), KK-A26/A27 (kampanya yolları)."""
import json
from datetime import timedelta

import requests
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.tools import html2plaintext

from .common import FakeResponse, SmsTestCase, smart_error

MAX_RETRY = 3


class CampaignMixin:

    @property
    def Campaign(self):
        return self.env['sms.system.campaign']

    @property
    def Contact(self):
        return self.env['sms.system.contact']

    def ago(self, **kw):
        return fields.Datetime.now() - timedelta(**kw)

    def make_list(self, name='Liste'):
        return self.env['sms.system.list'].create({'name': name})

    def make_contact(self, mobile, lst, **vals):
        vals.setdefault('iys_status', 'unknown')
        return self.Contact.create(dict(vals, mobile=mobile, list_ids=[(6, 0, lst.ids)]))

    def make_campaign(self, lst, message_type='info', state='done', **vals):
        base = {'name': 'Kampanya', 'message_type': message_type, 'list_ids': [(6, 0, lst.ids)],
                'body': 'Kampanya metni', 'state': state}
        base.update(vals)
        return self.Campaign.create(base)

    def campaign_message(self, camp, contact, state='error', **vals):
        base = {'number': contact.mobile, 'body': 'Kampanya metni', 'originator': 'TESTBASLIK',
                'campaign_id': camp.id, 'contact_id': contact.id, 'res_model': camp._name, 'res_id': camp.id}
        base.update(vals)
        return self.make_message(state=state, **base)

    def run_queue(self, times=1):
        for _i in range(times):
            self.Campaign._cron_process_queue()

    def refresh(self, *records):
        for rec in records:
            rec.invalidate_recordset()

    def new_notes(self, camp, before_ids):
        camp.invalidate_recordset(['message_ids'])
        new = camp.message_ids.filtered(lambda m: m.id not in before_ids)
        return new.filtered(lambda m: html2plaintext(m.body or '').strip())

    def uncertain_count(self, camp):
        camp.invalidate_recordset()
        if 'uncertain_count' not in camp._fields:
            self.fail('ARAYÜZ YOK: sms.system.campaign.uncertain_count')
        return camp.uncertain_count


@tagged('post_install', '-at_install')
class TestCampaignRetry(CampaignMixin, SmsTestCase):

    # ── KK-A9 ──
    def _commercial_fixture(self):
        self.configure_sms(iys=True)
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial')
        recent = self.ago(hours=1)
        old = self.ago(days=3)
        c = {
            'optout': self.make_contact('5320000001', lst, iys_status='approved', iys_checked_at=recent, opt_out=True),
            'rejected': self.make_contact('5320000002', lst, iys_status='rejected', iys_checked_at=recent),
            'unknown': self.make_contact('5320000003', lst, iys_status='unknown', iys_checked_at=recent),
            'stale': self.make_contact('5320000004', lst, iys_status='approved', iys_checked_at=old),
            'ok': self.make_contact('5320000005', lst, iys_status='approved', iys_checked_at=recent),
        }
        msgs = {key: self.campaign_message(camp, contact) for key, contact in c.items()}
        return camp, c, msgs

    def test_kk_a9_onaysiz_numaralara_saglayici_cagrisi_yok_gerekceli_hata(self):
        camp, c, msgs = self._commercial_fixture()
        camp.action_retry_errors()
        self.run_queue()
        self.assertEqual(sorted(self.net.sent_numbers), sorted([c['stale'].mobile, c['ok'].mobile]))
        self.refresh(*msgs.values())
        for key in ('optout', 'rejected', 'unknown'):
            self.assertEqual(msgs[key].state, 'error', key)
            self.assertTrue(msgs[key].error, '%s: gerekçe metni olmalı' % key)
        self.assertIn('Kara liste', msgs['optout'].error)
        self.assertIn('İYS', msgs['rejected'].error)
        self.assertIn('İYS', msgs['unknown'].error)
        self.assertNotIn(c['optout'].mobile, self.net.sent_numbers)

    def test_kk_a9_eski_onayli_numara_gondermeden_once_iysden_sorgulanir(self):
        camp, c, msgs = self._commercial_fixture()
        camp.action_retry_errors()
        self.run_queue()
        self.assertEqual(self.net.queried, [c['stale'].mobile],
                         'Yalnız 24 saatten eski onaylı numara sorgulanmalı (taze onaylı sorgulanmaz)')
        self.refresh(msgs['stale'], msgs['ok'])
        self.assertEqual(msgs['stale'].state, 'sent')
        self.assertEqual(msgs['ok'].state, 'sent')

    def test_kk_a9_iys_sorgusunda_ret_cikan_numara_gonderilmez(self):
        camp, c, msgs = self._commercial_fixture()
        self.net.iys[c['stale'].mobile] = '0'
        camp.action_retry_errors()
        self.run_queue()
        self.assertEqual(self.net.sent_numbers, [c['ok'].mobile])
        self.refresh(msgs['stale'])
        self.assertEqual(msgs['stale'].state, 'error')
        self.assertIn('İYS', msgs['stale'].error)

    def test_kk_a9_iys_sorgusu_hata_verirse_paket_gonderilmez(self):
        camp, c, msgs = self._commercial_fixture()
        self.net.smart_session = smart_error(-1, -1)   # yanlış şifre: kalıcı hata
        camp.action_retry_errors()
        self.run_queue()
        self.assertEqual(self.net.turatel_calls, [], 'İYS doğrulanamadan ticari paket gönderildi')
        self.refresh(msgs['stale'], msgs['ok'])
        self.assertEqual(msgs['stale'].state, 'queued')
        self.assertEqual(msgs['ok'].state, 'queued')

    # ── KK-A10 (K1) ──
    def test_kk_a10_bilgilendirme_ve_personel_opt_out_haric_iys_sorgusu_yok(self):
        self.configure_sms(iys=True)
        for message_type in ('info', 'staff'):
            with self.subTest(tur=message_type):
                self.net.calls.clear()
                lst = self.make_list(message_type)
                camp = self.make_campaign(lst, message_type)
                unknown = self.make_contact('5321%06d' % (1 if message_type == 'info' else 11), lst)
                rejected = self.make_contact('5321%06d' % (2 if message_type == 'info' else 12), lst,
                                             iys_status='rejected')
                optout = self.make_contact('5321%06d' % (3 if message_type == 'info' else 13), lst, opt_out=True)
                msgs = [self.campaign_message(camp, ct) for ct in (unknown, rejected, optout)]
                camp.action_retry_errors()
                self.run_queue()
                self.assertEqual(self.net.smartadm_calls, [], 'İYS sorgusu yapıldı')
                self.assertEqual(sorted(self.net.sent_numbers), sorted([unknown.mobile, rejected.mobile]))
                self.refresh(*msgs)
                self.assertEqual([m.state for m in msgs], ['sent', 'sent', 'error'])
                self.assertIn('Kara liste', msgs[2].error)

    # ── KK-A11 ──
    def test_kk_a11_gunluk_sinir_asilirsa_user_error_ve_hicbir_durum_degismez(self):
        self.set_param('daily_limit', '1000')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        other = self.make_campaign(lst, 'info', name='Önceki')
        used_contacts = self.Contact.create([{'mobile': '5322%06d' % i} for i in range(900)])
        self.Message.create([{
            'number': ct.mobile, 'body': 'x', 'originator': 'TESTBASLIK', 'state': 'sent',
            'campaign_id': other.id} for ct in used_contacts])
        contacts = self.Contact.create([{'mobile': '5323%06d' % i, 'list_ids': [(6, 0, lst.ids)]}
                                        for i in range(150)])
        errors = self.Message.create([{
            'number': ct.mobile, 'body': 'x', 'originator': 'TESTBASLIK', 'state': 'error',
            'campaign_id': camp.id, 'contact_id': ct.id} for ct in contacts])
        with self.assertRaises(UserError):
            camp.action_retry_errors()
        self.refresh(errors, camp)
        self.assertEqual(set(errors.mapped('state')), {'error'})
        self.assertEqual(camp.state, 'done')
        self.assertEqual(self.net.calls, [])

    def test_kk_a11_sinir_icindeyse_kuyruga_alinir(self):
        self.set_param('daily_limit', '1000')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        contacts = self.Contact.create([{'mobile': '5323%06d' % i, 'list_ids': [(6, 0, lst.ids)]} for i in range(5)])
        errors = self.Message.create([{
            'number': ct.mobile, 'body': 'x', 'originator': 'TESTBASLIK', 'state': 'error',
            'campaign_id': camp.id, 'contact_id': ct.id} for ct in contacts])
        camp.action_retry_errors()
        self.refresh(errors, camp)
        self.assertEqual(set(errors.mapped('state')), {'queued'})
        self.assertEqual(camp.state, 'sending')

    # ── KK-A12 ──
    def test_kk_a12_iys_kapaliyken_ticari_yeniden_gonderim_user_error(self):
        self.configure_sms(iys=False)
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial')
        contact = self.make_contact('5320000009', lst, iys_status='approved', iys_checked_at=self.ago(hours=1))
        msg = self.campaign_message(camp, contact)
        with self.assertRaises(UserError):
            camp.action_retry_errors()
        self.refresh(msg, camp)
        self.assertEqual(msg.state, 'error')
        self.assertEqual(camp.state, 'done')
        self.assertFalse(self.Message.search([('campaign_id', '=', camp.id), ('state', '=', 'queued')]))
        self.assertEqual(self.net.calls, [])


@tagged('post_install', '-at_install')
class TestCampaignUncertain(CampaignMixin, SmsTestCase):

    # ── KK-A13 ──
    def test_kk_a13_15_dk_sending_kayit_belirsiz_olur_ve_sayaci_ayridir(self):
        self.require_state('uncertain')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info', state='sending')
        stuck = self.campaign_message(camp, self.make_contact('5320000011', lst), state='sending')
        recent = self.campaign_message(camp, self.make_contact('5320000012', lst), state='sending')
        err = self.campaign_message(camp, self.make_contact('5320000013', lst), state='error')
        self.set_write_date(stuck, 16)
        self.set_write_date(recent, 14)
        self.run_queue()
        self.refresh(stuck, recent, err)
        self.assertEqual(stuck.state, 'uncertain')
        self.assertEqual(recent.state, 'sending', '15 dk dolmadan belirsiz sayılmamalı')
        self.assertEqual(err.state, 'error')
        self.assertEqual(self.uncertain_count(camp), 1)
        self.assertEqual(camp.error_count, 1, 'error_count belirsizleri saymamalı')
        self.assertEqual(self.net.calls, [], 'Takılı kayıt yeniden gönderilmemeli')

    def test_kk_a13_belirsiz_ilerlemeye_sayilir(self):
        self.require_state('uncertain')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info', state='sending')
        for i, state in enumerate(('sent', 'error', 'uncertain', 'queued')):
            self.campaign_message(camp, self.make_contact('532000002%d' % i, lst), state=state)
        camp.invalidate_recordset()
        self.assertEqual((camp.sent_count, camp.error_count, camp.uncertain_count), (1, 1, 1))
        self.assertAlmostEqual(camp.progress, 75.0)

    def test_kk_a13_belirsiz_kaydi_biten_kampanya_tamamlanir(self):
        self.require_state('uncertain')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info', state='sending')
        stuck = self.campaign_message(camp, self.make_contact('5320000031', lst), state='sending')
        self.set_write_date(stuck, 20)
        self.run_queue()
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'done')

    # ── KK-A14 ──
    def _uncertain_fixture(self, errors, uncertain):
        self.require_state('uncertain')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        err = [self.campaign_message(camp, self.make_contact('53200001%02d' % i, lst), state='error')
               for i in range(errors)]
        unc = [self.campaign_message(camp, self.make_contact('53200002%02d' % i, lst), state='uncertain',
                                     retry_count=MAX_RETRY) for i in range(uncertain)]
        return camp, err, unc

    def test_kk_a14_yalniz_hatalilar_kuyruga_alinir_mukerrer_mesaji(self):
        camp, err, unc = self._uncertain_fixture(3, 5)
        result = camp.action_retry_errors()
        self.refresh(*(err + unc))
        self.assertEqual([m.state for m in err], ['queued'] * 3)
        self.assertEqual([m.state for m in unc], ['uncertain'] * 5)
        self.assertIn('mükerrer', json.dumps(result, ensure_ascii=False))
        self.assertIn('5', json.dumps(result, ensure_ascii=False))

    def test_kk_a14_belirsizler_cron_ile_de_gonderilmez(self):
        camp, err, unc = self._uncertain_fixture(3, 5)
        camp.action_retry_errors()
        self.run_queue(2)
        self.assertEqual(len(self.net.sent_numbers), 3)
        self.assertFalse(set(self.net.sent_numbers) & {m.number for m in unc})
        self.refresh(*unc)
        self.assertEqual([m.state for m in unc], ['uncertain'] * 5)

    def test_kk_a14_yalniz_belirsiz_varsa_user_error_ve_cagri_yok(self):
        camp, err, unc = self._uncertain_fixture(0, 5)
        with self.assertRaises(UserError) as ctx:
            camp.action_retry_errors()
        self.assertIn('mükerrer', str(ctx.exception))
        self.run_queue()
        self.refresh(*unc)
        self.assertEqual([m.state for m in unc], ['uncertain'] * 5)
        self.assertEqual(self.net.calls, [])

    def test_kk_a16_kampanya_paketinde_read_timeout_belirsiz_olur(self):
        self.require_state('uncertain')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info', state='sending')
        msgs = [self.campaign_message(camp, self.make_contact('53200003%02d' % i, lst), state='queued')
                for i in range(3)]
        self.net.turatel_script = [requests.exceptions.ReadTimeout()]
        self.run_queue()
        self.refresh(*msgs)
        self.assertEqual([m.state for m in msgs], ['uncertain'] * 3, 'Gidip gitmediği belirsiz paket belirsiz olmalı')
        camp.invalidate_recordset()
        self.run_queue(2)
        with self.assertRaises(UserError):
            camp.action_retry_errors()
        self.assertEqual(len(self.net.turatel_calls), 1, 'Belirsiz paket yeniden gönderildi')


@tagged('post_install', '-at_install')
class TestIysScope(CampaignMixin, SmsTestCase):

    def _bulk_contacts(self, lst):
        """5.020 kişi (SQL ile hızlı): 500 onaylı+eski, 4.500 unknown (2-3 gün önce sorgulanmış), 20 hiç sorgulanmamış."""
        cr = self.env.cr
        self.env.flush_all()
        cr.execute("""
            INSERT INTO sms_system_contact
                (mobile, source, iys_status, iys_checked_at, opt_out, active,
                 create_uid, write_uid, create_date, write_date)
            SELECT '59' || lpad(i::text, 8, '0'), 'manual',
                   CASE WHEN i <= 500 THEN 'approved' ELSE 'unknown' END,
                   CASE WHEN i <= 500 THEN now() at time zone 'utc' - interval '2 days'
                        WHEN i <= 5000 THEN now() at time zone 'utc' - interval '3 days'
                        ELSE NULL END,
                   false, true, 1, 1, now() at time zone 'utc', now() at time zone 'utc'
              FROM generate_series(1, 5020) AS i
        """)
        cr.execute("""
            INSERT INTO sms_system_contact_list_rel (contact_id, list_id)
            SELECT id, %s FROM sms_system_contact WHERE mobile LIKE '59%%'
        """, (lst.id,))
        self.env.invalidate_all()

    @staticmethod
    def _number(i):
        return '59%08d' % i

    # ── KK-A18 ──
    def test_kk_a18_yalniz_520_kisi_sorgulanir_unknown_gonderilmez(self):
        self.configure_sms(iys=True)
        lst = self.make_list('Büyük')
        self._bulk_contacts(lst)
        self.net.query_cap = 600   # kırmızı koşuyu kısaltır: 600 sorgudan sonra zaman aşımı
        camp = self.make_campaign(lst, 'commercial', state='scheduled', scheduled_at=self.ago(minutes=1))
        self.assertEqual(len(camp._iys_stale()), 520, '_iys_stale kapsamı')
        self.run_queue()
        self.assertEqual(len(self.net.queried), 520, 'Yalnız 500 eski onaylı + 20 hiç sorgulanmamış sorgulanmalı')
        queried = set(self.net.queried)
        expected = {self._number(i) for i in list(range(1, 501)) + list(range(5001, 5021))}
        self.assertEqual(queried, expected)
        sent = set(self.net.sent_numbers)
        self.assertEqual(sent, expected, 'unknown kişilere gönderilmemeli')
        self.assertFalse(sent & {self._number(i) for i in range(501, 5001)})

    def test_kk_a18_iys_stale_kapsami_kucuk_tablo(self):
        self.configure_sms(iys=True)
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial', state='draft')
        approved_old = self.make_contact('5320100001', lst, iys_status='approved', iys_checked_at=self.ago(days=2))
        approved_new = self.make_contact('5320100002', lst, iys_status='approved', iys_checked_at=self.ago(hours=2))
        unknown_old = self.make_contact('5320100003', lst, iys_status='unknown', iys_checked_at=self.ago(days=5))
        rejected_old = self.make_contact('5320100004', lst, iys_status='rejected', iys_checked_at=self.ago(days=5))
        never = self.make_contact('5320100005', lst)
        optout = self.make_contact('5320100006', lst, opt_out=True)
        stale = camp._iys_stale()
        self.assertEqual(set(stale.ids), {approved_old.id, never.id})
        self.assertFalse(stale & (approved_new | unknown_old | rejected_old | optout))


@tagged('post_install', '-at_install')
class TestIysErrorNotes(CampaignMixin, SmsTestCase):

    def _scheduled_commercial(self):
        self.configure_sms(iys=True)
        lst = self.make_list()
        self.make_contact('5320200001', lst)   # hiç sorgulanmamış: İYS tazelemesi gerekir
        camp = self.make_campaign(lst, 'commercial', state='scheduled', scheduled_at=self.ago(minutes=1))
        return camp

    # ── KK-A19 ──
    def test_kk_a19_kalici_hata_taslaga_doner_ve_tam_1_not(self):
        camp = self._scheduled_commercial()
        self.net.smart_session = smart_error(-1, -1)   # yanlış şifre
        before = set(camp.message_ids.ids)
        self.run_queue()
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'draft')
        self.assertEqual(len(self.new_notes(camp, before)), 1)
        self.run_queue(2)
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'draft')
        self.assertEqual(len(self.new_notes(camp, before)), 1, 'Sonraki çalışmalarda yeni not düşmemeli')
        self.assertEqual(self.net.turatel_calls, [])

    # ── KK-A20 ──
    def test_kk_a20_gecici_hata_3_calismada_scheduled_ve_tam_1_not(self):
        camp = self._scheduled_commercial()
        self.net.smart_query = FakeResponse(503, 'Service Unavailable')
        before = set(camp.message_ids.ids)
        self.run_queue(3)
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'scheduled')
        self.assertEqual(len(self.new_notes(camp, before)), 1, 'Aynı geçici hata için tam 1 not olmalı')
        self.assertEqual(self.net.turatel_calls, [])

    def test_kk_a20_beklenmeyen_istisna_3_calismada_scheduled_ve_tam_1_not(self):
        camp = self._scheduled_commercial()
        Iys = self.env['sms.system.iys']

        def boom(this, *args, **kwargs):
            raise RuntimeError('beklenmeyen patlama')

        from unittest.mock import patch
        before = set(camp.message_ids.ids)
        with patch.object(type(Iys), 'refresh_contacts', boom):
            self.run_queue(3)
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'scheduled')
        notes = self.new_notes(camp, before)
        self.assertEqual(len(notes), 1, 'Beklenmeyen istisna için tam 1 not olmalı (sessiz yutulmamalı)')
        self.assertEqual(self.net.turatel_calls, [])

    def test_kk_a20_hata_degisirse_yeni_not_dusebilir_ama_ayni_hata_tekrarlanmaz(self):
        camp = self._scheduled_commercial()
        before = set(camp.message_ids.ids)
        self.net.smart_query = FakeResponse(503, 'x')
        self.run_queue(2)
        self.assertEqual(len(self.new_notes(camp, before)), 1)
        self.net.smart_query = FakeResponse(429, 'x')   # farklı geçici hata
        self.run_queue(2)
        self.assertEqual(len(self.new_notes(camp, before)), 2)


@tagged('post_install', '-at_install')
class TestCampaignSingleInvariants(CampaignMixin, SmsTestCase):

    _seq = 0

    def _info_campaign(self, count=3):
        type(self)._seq += 1
        lst = self.make_list()
        for i in range(count):
            self.make_contact('5320%02d%04d' % (type(self)._seq, i), lst)
        return self.make_campaign(lst, 'info', state='draft')

    # ── KK-A27 (K2): kampanya paketi ve deneme gönderimi ──
    def test_kk_a27_test_modunda_kampanya_paketi_cagri_yapmaz(self):
        for value in ('True', None, '0', 'false', ''):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                camp = self._info_campaign()
                camp.action_send()
                self.run_queue()
                msgs = self.Message.search([('campaign_id', '=', camp.id)])
                self.assertEqual(len(msgs), 3)
                self.assertEqual(set(msgs.mapped('state')), {'test'})
                self.assertEqual(self.net.calls, [])

    def test_kk_a27_test_modu_kapaliyken_kampanya_paketi_gonderir(self):
        camp = self._info_campaign()
        camp.action_send()
        self.run_queue()
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(len(self.net.sent_numbers), 3)

    def test_kk_a27_test_modunda_kampanya_yeniden_gonderimi_cagri_yapmaz(self):
        self.set_param('test_mode', 'True')
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        contact = self.make_contact('5320990050', lst)
        msg = self.campaign_message(camp, contact)
        camp.action_retry_errors()
        self.run_queue()
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'test')
        self.assertEqual(self.net.calls, [])

    def _test_to_me(self, camp):
        user = self.sms_manager
        user.partner_id.phone = '05321234567'
        return camp.with_user(user).action_send_test_to_me()

    def test_kk_a27_test_modunda_deneme_gonderimi_cagri_yapmaz(self):
        for value in ('True', None, '0', 'false'):
            with self.subTest(deger=value):
                self.set_param('test_mode', value)
                self._test_to_me(self._info_campaign())
                self.assertEqual(self.net.calls, [])
        msgs = self.Message.search([('number', '=', '5321234567')])
        self.assertEqual(set(msgs.mapped('state')), {'test'})

    # ── KK-A26 (K1): kampanya deneme gönderimi SmartADM çağırmaz ──
    def test_kk_a26_deneme_gonderimi_smartadm_cagirmaz(self):
        self.configure_sms(iys=True)
        camp = self._info_campaign()
        self._test_to_me(camp)
        self.assertEqual(len(self.net.turatel_calls), 1)
        self.assertEqual(self.net.smartadm_calls, [])


@tagged('post_install', '-at_install')
class TestCampaignGuardAndMigration(CampaignMixin, SmsTestCase):

    # ── S-6: kayıtsız numaralar korumalı sorgulanır, koruma devreye girince kampanya bekler ──
    def test_s6_kayitsiz_numaralar_korumali_sorgulanir_ve_kampanya_bekler(self):
        self.configure_sms(iys=True)
        lst = self.make_list()
        for i in range(30):
            self.make_contact('5320300%03d' % i, lst)   # hiç sorgulanmamış, İYS'de kayıtsız
        self.net.default_iys = 'missing'
        camp = self.make_campaign(lst, 'commercial', state='scheduled', scheduled_at=self.ago(minutes=1))
        self.run_queue()
        self.assertEqual(len(self.net.queried), 20, 'hata oranı koruması 20 sorgudan sonra durdurmalı')
        self.assertTrue(self.env['sms.system.iys']._paused_until())
        camp.invalidate_recordset()
        self.assertEqual(camp.state, 'scheduled')
        self.run_queue(2)
        self.assertEqual(len(self.net.queried), 20, 'koruma süresince yeni sorgu yapılmamalı')
        self.assertEqual(self.net.turatel_calls, [])

    # ── Gönderim anı kapısı: İYS kapanırsa ticari paket gitmez ──
    def test_ticari_paket_iys_kapaliysa_gonderilmez_ve_kuyrukta_kalir(self):
        self.configure_sms(iys=False)
        lst = self.make_list()
        camp = self.make_campaign(lst, 'commercial', state='sending')
        contact = self.make_contact('5320400001', lst, iys_status='approved', iys_checked_at=self.ago(hours=1))
        msg = self.campaign_message(camp, contact, state='queued')
        before = set(camp.message_ids.ids)
        self.run_queue(2)
        self.refresh(msg, camp)
        self.assertEqual(msg.state, 'queued')
        self.assertEqual(camp.state, 'sending')
        self.assertEqual(self.net.calls, [])
        self.assertEqual(len(self.new_notes(camp, before)), 1, 'aynı bekletme notu tekrarlanmamalı')

    # ── Migration (yalnız veri) ──
    def _migrate(self):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / 'migrations' / '19.0.1.7.0' / 'post-migrate.py'
        spec = importlib.util.spec_from_file_location('sms_post_migrate_1_7_0', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.6.0')
        self.env.invalidate_all()

    def test_migration_eski_takili_kampanya_hatalarini_belirsiz_yapar(self):
        lst = self.make_list()
        camp = self.make_campaign(lst, 'info')
        stuck_text = ('Gönderim yarıda kesildi; iletilip iletilmediği belirsiz. '
                      'Tekrar gönderilmedi (mükerrer olmasın diye).')
        stuck = self.campaign_message(camp, self.make_contact('5320500001', lst), error=stuck_text)
        other = self.campaign_message(camp, self.make_contact('5320500002', lst), error='Turatel hatası: kredi')
        single = self.make_message(number='5320500003', state='error', error=stuck_text)
        sent = self.campaign_message(camp, self.make_contact('5320500004', lst), state='sent')
        icp_before = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        self._migrate()
        self.assertEqual((stuck.state, stuck.retry_count), ('uncertain', 3))
        self.assertEqual(other.state, 'error')
        self.assertEqual(single.state, 'error', 'kampanyasız kayıt değişmemeli')
        self.assertEqual(sent.state, 'sent')
        self._migrate()   # idempotent
        self.assertEqual(stuck.state, 'uncertain')
        icp_after = {r.key: r.value for r in self.icp.search([('key', '=like', 'sms_system.%')])}
        self.assertEqual(icp_after, icp_before, 'migration ayarlara dokunmamalı')
        camp.invalidate_recordset()
        self.assertEqual(camp.uncertain_count, 1)
        camp.action_retry_errors()   # yalnız diğer hata kuyruğa alınır, belirsiz kayıt alınmaz
        self.assertEqual((other.state, stuck.state), ('queued', 'uncertain'))

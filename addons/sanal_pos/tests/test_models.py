# -*- coding: utf-8 -*-
"""G4 / modeller, kısıtlar, ACL, durum kümeleri. KK-5 (ACL ayağı), KK-21 (DB kısıtı), KK-35,
KK-39 (log ACL), KK-45 (DB düzeyi), KK-48, KK-10 (savunma), KK-17 (link_url).
"""
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from psycopg2 import IntegrityError
from psycopg2.errors import ForeignKeyViolation

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import INV_NO, OPEN_STATES, PAID_STATES, REUSABLE_STATES, SanalPosCase

ALL_STATES = {'sending', 'sent', 'unknown', 'error', 'expired', 'link_cancelled', 'paid',
              'review', 'refund_pending', 'partial_refund', 'refunded', 'voided'}


class ModelCase(SanalPosCase):

    def assertDbRejects(self, func, exc=IntegrityError, msg=None):
        with self.assertRaises(exc, msg=msg), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            func()


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPaymentModel(ModelCase):

    def test_durum_degerleri(self):
        """§4: 12 durum (K-12: + refund_pending)."""
        keys = {k for k, _label in self.env['sanal.pos.payment']._fields['state'].selection}
        self.assertEqual(keys, ALL_STATES)

    def test_durum_kumeleri_test_sabitleri_tutarli(self):
        self.assertEqual(set(OPEN_STATES) | set(PAID_STATES) | set(REUSABLE_STATES), ALL_STATES)
        self.assertFalse(set(OPEN_STATES) & set(PAID_STATES))
        self.assertFalse(set(PAID_STATES) & set(REUSABLE_STATES))

    def test_saglayici_secenegi(self):
        keys = {k for k, _l in self.env['sanal.pos.payment']._fields['provider'].selection}
        self.assertIn('paratika', keys)

    def test_sira_numarasi(self):
        """§3.1: SP/<yıl>/00001 biçimi."""
        payment = self.make_payment()
        self.assertRegex(payment.name, r'^SP/\d{4}/\d{5}$')
        other = self.make_payment(invoice_no='ZZZ1', merchant_payment_id='ZZZ1-1')
        self.assertNotEqual(payment.name, other.name)

    def test_mpid_benzersiz(self):
        self.make_payment(state='expired')
        self.assertDbRejects(lambda: self.make_payment(state='expired'))

    def test_kk21_ayni_faturaya_iki_acik_kayit_db_reddeder(self):
        """KK-21: kısmi benzersiz indeks: açık durumda (sending/sent/unknown) ikinci kayıt olamaz."""
        for i, first in enumerate(OPEN_STATES):
            for j, second in enumerate(OPEN_STATES):
                with self.subTest(first=first, second=second):
                    inv = 'DUP%d%d' % (i, j)
                    self.make_payment(invoice_no=inv, state=first, attempt_no=1,
                                      merchant_payment_id='%s-1' % inv)
                    self.assertDbRejects(lambda: self.make_payment(
                        invoice_no=inv, state=second, attempt_no=2,
                        merchant_payment_id='%s-2' % inv))

    def test_kk21_kapali_kayitlar_cogalabilir(self):
        for n, state in enumerate(REUSABLE_STATES, start=1):
            self.make_payment(invoice_no='CLS1', state=state, attempt_no=n,
                              merchant_payment_id='CLS1-%d' % n)
        self.make_payment(invoice_no='CLS1', state='sent', attempt_no=10, merchant_payment_id='CLS1-10')
        self.assertEqual(len(self.payments('CLS1')), len(REUSABLE_STATES) + 1)

    def test_kk19_odenmis_kayit_yanina_acik_kayit_db_duzeyinde_engellenmez(self):
        """§3.1 notu: geç ödeme senaryosu için ödenmiş + açık birlikte var olabilir (uygulama kontrolü)."""
        self.make_payment(invoice_no='LATE1', state='paid', merchant_payment_id='LATE1-1')
        self.make_payment(invoice_no='LATE1', state='sent', attempt_no=2, merchant_payment_id='LATE1-2')
        self.assertEqual(len(self.payments('LATE1')), 2)

    def test_check_sure_araligi(self):
        for hours in (0, -1, 169, 1000):
            with self.subTest(hours=hours):
                self.assertDbRejects(lambda: self.make_payment(
                    invoice_no='H%d' % hours, expiry_hours=hours, merchant_payment_id='H%d-1' % hours))
        for hours in (1, 168):
            self.make_payment(invoice_no='HOK%d' % hours, expiry_hours=hours,
                              merchant_payment_id='HOK%d-1' % hours, state='expired')

    def test_check_tutar_pozitif(self):
        for amount in (0, -1, -0.01):
            with self.subTest(amount=amount):
                self.assertDbRejects(lambda: self.make_payment(
                    invoice_no='A%s' % abs(amount), amount=amount, merchant_payment_id='A%s-1' % abs(amount)))

    def test_kk10_uzunluk_sinirlari_modelde_savunma(self):
        """KK-10: sınır aşan alan model düzeyinde de reddedilir (sessiz kırpma yok)."""
        cases = {
            'customer_name': 129, 'customer_email': 65, 'customer_address': 256,
            'customer_city': 33, 'customer_zip': 17,
        }
        for field, size in cases.items():
            with self.subTest(field=field):
                self.assertDbRejects(
                    lambda: self.make_payment(
                        invoice_no='LEN-%s' % field, merchant_payment_id='LEN-%s-1' % field,
                        **{field: 'a' * size}),
                    exc=ValidationError)

    def test_kk10_sinirda_deger_kabul(self):
        cases = {'customer_name': 128, 'customer_address': 255, 'customer_city': 32, 'customer_zip': 16}
        payment = self.make_payment(
            state='expired', invoice_no='LENOK', merchant_payment_id='LENOK-1',
            **{k: 'a' * v for k, v in cases.items()})
        for field, size in cases.items():
            self.assertEqual(len(payment[field]), size)

    def test_kanal_gosterimi(self):
        both = self.make_payment(invoice_no='CD1', merchant_payment_id='CD1-1', state='expired')
        sms = self.make_payment(invoice_no='CD2', merchant_payment_id='CD2-1', state='expired',
                                channel_email=False)
        mail = self.make_payment(invoice_no='CD3', merchant_payment_id='CD3-1', state='expired',
                                 channel_sms=False)
        self.assertEqual(both.channels_display, 'SMS+E-posta')
        self.assertEqual(sms.channels_display, 'SMS')
        self.assertEqual(mail.channels_display, 'E-posta')

    def test_is_test(self):
        self.assertTrue(self.make_payment(invoice_no='T1', merchant_payment_id='T1-1',
                                          state='expired', environment='test').is_test)
        self.assertFalse(self.make_payment(invoice_no='T2', merchant_payment_id='T2-1',
                                           state='expired', environment='live').is_test)

    def test_saglayici_ayari_varsayilani_belirler(self):
        """sanal_pos.provider ayarı yeni kaydın sağlayıcısıdır; geçersiz değer -> paratika."""
        Payment = self.env['sanal.pos.payment']
        ICP = self.env['ir.config_parameter'].sudo()
        calls = []
        real = type(ICP).get_param

        def spy(model, key, default=False):
            calls.append(key)
            return 'yok_boyle' if key == 'sanal_pos.provider' else real(model, key, default)
        with patch.object(type(ICP), 'get_param', spy):
            self.assertEqual(Payment._default_provider(), 'paratika')
        self.assertIn('sanal_pos.provider', calls)
        self.assertEqual(Payment._fields['provider'].default(Payment), 'paratika')

    def test_kk17_link_adresi_varsayilan_gizli(self):
        payment = self.make_payment(provider_token='TOK-LINK-1')
        self.assertFalse(payment.link_url)

    def test_kk17_link_adresi_ayar_acikken_gorunur(self):
        self.set_setting('paratika_show_link_url', True)
        payment = self.make_payment(provider_token='TOK-LINK-1')
        self.assertIn('TOK-LINK-1', payment.link_url or '')
        self.assertTrue((payment.link_url or '').startswith('https://'))

    def test_oe_link_adresi_saglayicidan_gelir(self):
        """Ö-E: adres kalıbı tek yerde (sağlayıcının ``_link_url``'i); model kopya kurmaz."""
        self.set_setting('paratika_show_link_url', True)
        provider_cls = type(self.env['sanal.pos.provider.paratika'])
        with patch.object(provider_cls, '_link_url', autospec=True,
                          return_value='https://odeme.example/p/TOK-LINK-2') as spy:
            payment = self.make_payment(provider_token='TOK-LINK-2', environment='live')
            self.assertEqual(payment.link_url, 'https://odeme.example/p/TOK-LINK-2')
        self.assertEqual(spy.call_args.args[1:], (payment, 'TOK-LINK-2'))

    def test_oe_link_adresi_saglayici_ile_ayni(self):
        self.set_setting('paratika_show_link_url', True)
        self.env['ir.config_parameter'].sudo().set_param(
            'sanal_pos.paratika_live_url', '  https://vpos.example/paratika/api/v2/  ')
        payment = self.make_payment(provider_token='TOK-LINK-3', environment='live')
        expected = self.env['sanal.pos.provider.paratika']._link_url(payment, 'TOK-LINK-3')
        self.assertEqual(expected, 'https://vpos.example/payment/TOK-LINK-3?lang=tr')
        self.assertEqual(payment.link_url, expected)

    def test_kk17_token_yoksa_link_yok(self):
        self.set_setting('paratika_show_link_url', True)
        payment = self.make_payment(provider_token=False, state='sending')
        self.assertFalse(payment.link_url)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundAmounts(ModelCase):

    def setUp(self):
        super().setUp()
        self.paid = self.make_paid(tran_ref='T1')

    def test_iade_toplami_yalniz_basarili_satirlar(self):
        self.make_refund_line(self.paid, 2500.0, state='done', provider_ref='R1')
        self.make_refund_line(self.paid, 100.0, state='failed', provider_ref='R2')
        self.make_refund_line(self.paid, 50.0, state='done', kind='refund', provider_ref='R3')
        self.paid.invalidate_recordset()
        self.assertEqual(self.paid.refunded_amount, 2550.0)
        self.assertEqual(self.paid.refundable_amount, 6450.0)

    def test_islemdeki_satir_toplama_katilmaz(self):
        self.make_refund_line(self.paid, 1000.0, state='processing', provider_ref='R1')
        self.paid.invalidate_recordset()
        self.assertEqual(self.paid.refunded_amount, 0)
        self.assertEqual(self.paid.refundable_amount, 9000.0)

    def test_belirsiz_satir_toplama_katilmaz(self):
        self.make_refund_line(self.paid, 1000.0, state='unknown', provider_ref=None)
        self.paid.invalidate_recordset()
        self.assertEqual(self.paid.refunded_amount, 0)

    def test_satir_durumu_degisince_toplam_guncellenir(self):
        line = self.make_refund_line(self.paid, 700.0, state='processing', provider_ref='R1')
        self.paid.invalidate_recordset()
        self.assertEqual(self.paid.refunded_amount, 0)
        line.sudo().write({'state': 'done'})
        self.paid.invalidate_recordset()
        self.assertEqual(self.paid.refunded_amount, 700.0)

    def test_durum_hesabi_kismi_sonra_tam(self):
        """§4 _recompute_refund_state: paid -> partial_refund -> refunded."""
        self.make_refund_line(self.paid, 2500.0, provider_ref='R1')
        self.paid._recompute_refund_state()
        self.assertEqual(self.paid.state, 'partial_refund')
        self.make_refund_line(self.paid, 6500.0, provider_ref='R2')
        self.paid._recompute_refund_state()
        self.assertEqual(self.paid.state, 'refunded')

    def test_durum_hesabi_void(self):
        self.make_refund_line(self.paid, 9000.0, kind='void', provider_ref='V1')
        self.paid._recompute_refund_state()
        self.assertEqual(self.paid.state, 'voided')

    def test_durum_hesabi_iade_yoksa_paid_kalir(self):
        self.paid._recompute_refund_state()
        self.assertEqual(self.paid.state, 'paid')

    def test_durum_hesabi_basarisiz_satir_etkilemez(self):
        self.make_refund_line(self.paid, 9000.0, state='failed', provider_ref='R1')
        self.paid._recompute_refund_state()
        self.assertEqual(self.paid.state, 'paid')

    def test_durum_hesabi_paid_olmayan_kayda_uygulanmaz(self):
        sent = self.make_payment(invoice_no='NOP1', merchant_payment_id='NOP1-1')
        self.make_refund_line(sent, 100.0, provider_ref='R1')
        sent._recompute_refund_state()
        self.assertEqual(sent.state, 'sent')

    def test_kk44_kurus_hassasiyeti_6500_01(self):
        self.make_refund_line(self.paid, 2499.99, provider_ref='R1')
        self.paid.invalidate_recordset()
        self.assertEqual(round(self.paid.refundable_amount, 2), 6500.01)

    def test_kk41_can_void(self):
        """KK-41: aynı gün (Europe/Istanbul) ve iadesiz."""
        tz = ZoneInfo('Europe/Istanbul')
        now_ist = datetime.now(tz)
        midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        to_utc = lambda dt: dt.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)  # noqa: E731

        today = self.make_paid(self.make_payment(invoice_no='CV1', merchant_payment_id='CV1-1'),
                               paid_at=datetime.utcnow())
        yesterday_late = self.make_paid(
            self.make_payment(invoice_no='CV2', merchant_payment_id='CV2-1'),
            paid_at=to_utc(midnight - timedelta(minutes=1)))
        old = self.make_paid(self.make_payment(invoice_no='CV3', merchant_payment_id='CV3-1'),
                             paid_at=datetime.utcnow() - timedelta(days=3))
        for p in (today, yesterday_late, old):
            p.invalidate_recordset()
        self.assertTrue(today.can_void, 'bugün ödenen iptal edilebilmeli')
        self.assertFalse(yesterday_late.can_void, 'Istanbul gece yarısından önce ödenen iptal edilemez')
        self.assertFalse(old.can_void)
        if now_ist >= midnight + timedelta(seconds=1):
            early_today = self.make_paid(
                self.make_payment(invoice_no='CV4', merchant_payment_id='CV4-1'),
                paid_at=to_utc(midnight + timedelta(seconds=1)))
            self.assertTrue(early_today.can_void)

    def test_kk41_can_void_iadesi_olan_kayitta_yok(self):
        self.make_refund_line(self.paid, 100.0, provider_ref='R1')
        self.paid._recompute_refund_state()
        self.paid.invalidate_recordset()
        self.assertFalse(self.paid.can_void)

    def test_kk41_can_void_paid_olmayanda_yok(self):
        self.assertFalse(self.make_payment(invoice_no='CVS', merchant_payment_id='CVS-1').can_void)

    def test_kk45_can_refund(self):
        self.assertTrue(self.paid.can_refund)
        self.make_refund_line(self.paid, 9000.0, kind='void', provider_ref='V1')
        self.paid._recompute_refund_state()
        self.paid.invalidate_recordset()
        self.assertFalse(self.paid.can_refund)
        self.assertFalse(self.paid.can_void)

    def test_kk45_islemde_satir_varken_can_refund_false(self):
        self.make_refund_line(self.paid, 100.0, state='processing', provider_ref=None)
        self.paid.invalidate_recordset()
        self.assertFalse(self.paid.can_refund)
        self.assertFalse(self.paid.can_void)

    def test_kk45_sent_kayitta_can_refund_yok(self):
        self.assertFalse(self.make_payment(invoice_no='CRS', merchant_payment_id='CRS-1').can_refund)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundModel(ModelCase):

    def setUp(self):
        super().setUp()
        self.paid = self.make_paid(tran_ref='T1')

    def test_kk45_tek_devam_eden_islem_db_duzeyinde(self):
        """KK-45: aynı ödemede iki 'processing'/'unknown' satır olamaz."""
        for first, second in (('processing', 'processing'), ('processing', 'unknown'),
                              ('unknown', 'processing'), ('unknown', 'unknown')):
            with self.subTest(first=first, second=second):
                paid = self.make_paid(self.make_payment(
                    invoice_no='PR-%s-%s' % (first, second), merchant_payment_id='PR-%s-%s-1' % (first, second)))
                self.make_refund_line(paid, 10.0, state=first, provider_ref=None)
                self.assertDbRejects(lambda: self.make_refund_line(paid, 10.0, state=second, provider_ref=None))

    def test_kk45_biten_satirlar_yeni_islemi_engellemez(self):
        self.make_refund_line(self.paid, 10.0, state='done', provider_ref='R1')
        self.make_refund_line(self.paid, 10.0, state='failed', provider_ref='R2')
        self.make_refund_line(self.paid, 10.0, state='processing', provider_ref=None)

    def test_kk27_ayni_provider_ref_iki_kez_eklenemez(self):
        self.make_refund_line(self.paid, 10.0, provider_ref='R-SAME')
        self.assertDbRejects(lambda: self.make_refund_line(self.paid, 10.0, provider_ref='R-SAME'))

    def test_kk27_ayni_ref_baska_odemede_olabilir(self):
        other = self.make_paid(self.make_payment(invoice_no='OTH1', merchant_payment_id='OTH1-1'))
        self.make_refund_line(self.paid, 10.0, provider_ref='R-X')
        self.make_refund_line(other, 10.0, provider_ref='R-X')

    def test_kk27_provider_ref_bos_olan_satirlar_cogalabilir(self):
        self.make_refund_line(self.paid, 10.0, state='failed', provider_ref=None)
        self.make_refund_line(self.paid, 10.0, state='failed', provider_ref=None)

    def test_kk48_satir_degistirilemez_ve_silinemez(self):
        """KK-48: yönetici dahil kimse satırı değiştiremez/silemez."""
        line = self.make_refund_line(self.paid, 100.0, provider_ref='R1')
        for user in (self.user_mgr, self.user_sp, self.user_sys):
            with self.subTest(user=user.login):
                env_line = line.with_user(user)
                with self.assertRaises(UserError):
                    env_line.write({'amount': 1.0})
                with self.assertRaises(UserError):
                    env_line.unlink()
        line.invalidate_recordset()
        self.assertEqual(line.amount, 100.0)

    def test_kk48_olusturma_kullanicidan_reddedilir(self):
        with self.assertRaises(AccessError):
            self.env['sanal.pos.refund'].with_user(self.user_mgr).create({
                'payment_id': self.paid.id, 'kind': 'refund', 'amount': 1.0, 'state': 'done',
                'source': 'odoo', 'reason': 'x' * 6})

    def test_kk48_iade_gecmisi_okuma(self):
        line = self.make_refund_line(self.paid, 100.0, provider_ref='R1', reason='Müşteri talebi')
        for user in (self.user_sp, self.user_mgr):
            data = line.with_user(user).read(['kind', 'amount', 'state', 'source', 'reason', 'user_id',
                                              'provider_ref', 'create_date'])[0]
            self.assertEqual(data['reason'], 'Müşteri talebi')
            self.assertEqual(data['source'], 'odoo')
        with self.assertRaises(AccessError):
            line.with_user(self.user_plain).read(['amount'])

    def test_kk48_ondelete_restrict(self):
        """İade satırı olan ödeme kaydı silinemez (finansal iz)."""
        self.make_refund_line(self.paid, 100.0, provider_ref='R1')
        self.assertDbRejects(lambda: self.paid.sudo().unlink(), exc=ForeignKeyViolation)

    def test_kk48_alanlar_ve_durum_degerleri(self):
        fields = self.env['sanal.pos.refund']._fields
        for name in ('payment_id', 'kind', 'amount', 'state', 'source', 'reason', 'user_id',
                     'provider_ref', 'error_code', 'error_message', 'done_at'):
            self.assertIn(name, fields)
        self.assertEqual({k for k, _l in fields['state'].selection},
                         {'processing', 'pending_approval', 'done', 'rejected', 'failed', 'unknown'})
        self.assertEqual({k for k, _l in fields['kind'].selection}, {'void', 'refund'})
        self.assertEqual({k for k, _l in fields['source'].selection}, {'odoo', 'panel'})


@tagged('post_install', '-at_install', 'sanal_pos')
class TestAccessRights(ModelCase):

    def setUp(self):
        super().setUp()
        self.payment = self.make_payment()

    def test_kk35_grupsuz_kullanici_okuyamaz(self):
        """KK-35: grupsuz iç kullanıcı RPC ile erişemez."""
        env = self.env(user=self.user_plain)
        with self.assertRaises(AccessError):
            env['sanal.pos.payment'].search([])
        with self.assertRaises(AccessError):
            self.payment.with_user(self.user_plain).read(['invoice_no'])
        with self.assertRaises(AccessError):
            env['sanal.pos.refund'].search([])
        with self.assertRaises(AccessError):
            env['sanal.pos.log'].search([])
        with self.assertRaises(AccessError):
            env['sanal.pos.payment.create.wizard'].create({'invoice_no': INV_NO})

    def test_kk35_kullanici_tum_talepleri_gorur(self):
        """KK-35/S-4: kullanıcı başkasının talebini de görür."""
        other = self.make_payment(invoice_no='OTHR1', merchant_payment_id='OTHR1-1', user_id=self.user_sp2.id)
        visible = self.env['sanal.pos.payment'].with_user(self.user_sp).search([])
        self.assertIn(other, visible)
        self.assertIn(self.payment, visible)

    def test_kk35_kullanici_yazamaz_olusturamaz_silemez(self):
        """KK-5/KK-35: durum, tutar, ad RPC ile değiştirilemez."""
        rec = self.payment.with_user(self.user_sp)
        for vals in ({'state': 'paid'}, {'amount': 1.0}, {'customer_name': 'X'},
                     {'paid_amount': 9000.0}, {'merchant_payment_id': 'HACK-1'}):
            with self.subTest(vals=vals):
                with self.assertRaises(AccessError):
                    rec.write(vals)
        with self.assertRaises(AccessError):
            rec.unlink()
        with self.assertRaises(AccessError):
            self.env['sanal.pos.payment'].with_user(self.user_sp).create({
                'invoice_no': 'NEW1', 'amount': 1.0, 'provider': 'paratika'})
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, 'sent')
        self.assertEqual(self.payment.amount, 9000.0)

    def test_kk35_yonetici_de_dogrudan_yazamaz_silemez(self):
        rec = self.payment.with_user(self.user_mgr)
        with self.assertRaises(AccessError):
            rec.write({'state': 'paid'})
        with self.assertRaises(AccessError):
            rec.unlink()

    def test_kk35_kullanici_zinciri_chatter_notu_yazabilir(self):
        """Tasarım §3.1: _mail_post_access='read' -> kullanıcı kayda not yazabilir."""
        self.payment.with_user(self.user_sp).message_post(body='Müşteri aradı')
        self.assertIn('Müşteri aradı', self.chatter(self.payment))

    def test_kk39_log_yalniz_yoneticiye_acik(self):
        log = self.env['sanal.pos.log'].sudo().create({
            'action': 'QUERYTRANSACTION', 'provider': 'paratika', 'environment': 'test',
            'payment_id': self.payment.id, 'success': True})
        with self.assertRaises(AccessError):
            log.with_user(self.user_sp).read(['action'])
        self.assertEqual(log.with_user(self.user_mgr).read(['action'])[0]['action'], 'QUERYTRANSACTION')
        with self.assertRaises(AccessError):
            log.with_user(self.user_mgr).write({'success': False})
        with self.assertRaises(AccessError):
            log.with_user(self.user_mgr).unlink()

    def test_kk52_iade_sihirbazi_kullaniciya_kapali(self):
        Wiz = self.env['sanal.pos.payment.refund.wizard']
        with self.assertRaises(AccessError):
            Wiz.with_user(self.user_sp).create({'payment_id': self.payment.id, 'kind': 'refund'})

    def test_sihirbazlar_kullaniciya_acik(self):
        wiz = self.env['sanal.pos.payment.create.wizard'].with_user(self.user_sp).create({'invoice_no': INV_NO})
        self.assertTrue(wiz.exists())

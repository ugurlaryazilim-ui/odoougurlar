# -*- coding: utf-8 -*-
"""G10 / ödeme iptali (VOID) ve iade (REFUND). KK-27, KK-40..KK-47, KK-49..KK-52.

Para çıkışı yolu: yönetici yetkisi, tutar sınırı, iade öncesi senkron, mükerrer iade
engeli, belirsiz zaman aşımı ve uzlaştırma burada sınanır. Paratika taklit edilir.
Gerçek çift-cursor kilit (FOR UPDATE NOWAIT) yarışı TransactionCase'de kurulamaz;
04-kabul-testleri.md "otomatik kapsanamayanlar" bölümünde belirtilmiştir.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import (
    CRON_SYNC, CUSTOMER_NAME, INV_NO, LIVE_URL_PREFIX, TEST_URL_PREFIX, SanalPosCase,
    err_body, timeout_exc, tran,
)

WIZARD = 'sanal.pos.payment.refund.wizard'
BUSY_MSG = 'Bu ödeme için devam eden bir iade/iptal işlemi var.'
NOTHING_LEFT = 'İade edilebilir tutar kalmadı.'
UNKNOWN_MSG = ('Paratika yanıt vermedi; iade gerçekleşmiş olabilir. '
               'Durum otomatik kontrol edilecek, tekrar denemeyin.')
END_OF_DAY_MSG = 'Gün sonu geçtiği için iptal edilemedi; iade (REFUND) yapın.'


class RefundCase(SanalPosCase):

    # ------------------------------------------------------------- kurulum
    def paid(self, amount=9000.0, paid_at=None, **vals):
        """Ödenmiş kayıt (T1) ve Paratika'da aynı satış kaydı."""
        payment = self.make_payment(amount=amount, **vals)
        self.make_paid(payment, paid_at=paid_at, tran_ref='T1')
        self.set_query_transactions(tran('AP', 'SALE', '%.2f' % amount, 'T1'))
        return payment

    def mgr(self, payment):
        return payment.with_user(self.user_mgr)

    def attempt(self, payment, method, *args, user=None):
        """Eylemi çalıştırır; (sonuç, hata mesajı) döndürür. UserError yutulur."""
        target = payment.with_user(user or self.user_mgr)
        try:
            return getattr(target, method)(*args), None
        except UserError as exc:
            return None, str(exc.args[0])

    def shown(self, payment, result, message):
        """Kullanıcıya/kayda yansıyan tüm metin (uyarı, hata, chatter, satır hata alanları)."""
        payment.invalidate_recordset()
        parts = [str(result or ''), message or '', payment.last_error_message or '', self.chatter(payment)]
        for line in payment.refund_ids:
            parts += [line.error_message or '', line.error_code or '']
        return '\n'.join(parts)

    def refund(self, payment, amount, reason='Müşteri talebi', **kw):
        return self.attempt(payment, 'action_refund', amount, reason, **kw)

    def void(self, payment, reason='Müşteri vazgeçti', **kw):
        return self.attempt(payment, 'action_void', reason, **kw)

    def lines(self, payment, **filters):
        payment.invalidate_recordset()
        recs = payment.refund_ids
        for key, value in filters.items():
            recs = recs.filtered(lambda r, k=key, v=value: r[k] == v)
        return recs

    def age_line(self, line, minutes):
        """Belirsiz satırı geriye yaşlandırır: create_date ve ilk belirsizlik anı (unknown_since)."""
        # Saniye hassasiyeti: kod fields.Datetime.now() (mikrosaniyesiz) ile karşılaştırır
        when = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=minutes)
        self.env.cr.execute(
            "UPDATE sanal_pos_refund SET create_date = %s, unknown_since = %s WHERE id IN %s",
            [when, when, tuple(line.ids)])
        line.invalidate_recordset()

    def assertRejected(self, payment, method, *args, text=None, exc=UserError, user=None):
        target = payment.with_user(user or self.user_mgr)
        before_lines = len(payment.refund_ids)
        self.mock.calls.clear()
        with self.assertRaises(exc) as ctx:
            getattr(target, method)(*args)
        if text:
            self.assertIn(text, str(ctx.exception.args[0]))
        self.assertEqual(self.mock.count('VOID', 'REFUND'), 0, 'reddedilen işlemde Paratika’ya iade/iptal gitti')
        payment.invalidate_recordset()
        self.assertEqual(len(payment.refund_ids), before_lines, 'reddedilen işlemde satır oluştu')
        return str(ctx.exception.args[0])


@tagged('post_install', '-at_install', 'sanal_pos')
class TestVoid(RefundCase):

    def test_kk40_iptal_basarili(self):
        payment = self.paid()
        result, message = self.void(payment, 'Müşteri vazgeçti')
        self.assertIsNone(message)
        call = self.mock.last('VOID')
        self.assertIsNotNone(call)
        self.assertEqual(call.params['PGTRANID'], 'T1')
        self.assertEqual(call.params['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertNotIn('REFLECTCOMMISSION', call.params)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')
        line = self.lines(payment)
        self.assertEqual(len(line), 1)
        self.assertEqual((line.kind, line.state, line.source, line.amount, line.reason),
                         ('void', 'done', 'odoo', 9000.0, 'Müşteri vazgeçti'))
        self.assertTrue(line.provider_ref)
        self.assertEqual(line.user_id, self.user_mgr)
        note = self.chatter(payment)
        self.assertIn('Müşteri vazgeçti', note)

    def test_kk40_iptalde_aktif_senkron_once_calisir(self):
        payment = self.paid()
        self.void(payment)
        actions = self.mock.actions
        self.assertLess(actions.index('QUERYTRANSACTION'), actions.index('VOID'))

    def test_kk40_neden_en_az_5_karakter(self):
        payment = self.paid()
        for reason in ('', '    ', 'abc', 'abcd', ' a b '):
            with self.subTest(reason=reason):
                self.assertRejected(payment, 'action_void', reason)
        self.assertEqual(payment.state, 'paid')

    def test_kk40_neden_bes_karakter_kabul(self):
        payment = self.paid()
        _, message = self.void(payment, 'abcde')
        self.assertIsNone(message)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')

    def test_kk41_aynı_gun_degilse_iptal_yok(self):
        payment = self.paid(paid_at=datetime.utcnow() - timedelta(days=2))
        self.assertRejected(payment, 'action_void', 'Müşteri vazgeçti')
        self.assertEqual(payment.state, 'paid')

    def test_kk41_iadesi_olan_kayitta_iptal_yok(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='done', provider_ref='R-X')
        payment._recompute_refund_state()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'), tran('AP', 'REFUND', '100.00', 'R-X'))
        self.assertRejected(payment, 'action_void', 'Müşteri vazgeçti')

    def test_kk41_err10033_odendi_kalir_mesaj_ve_otomatik_iade_yok(self):
        payment = self.paid()
        self.mock.queue('VOID', err_body('ERR10033', 'cannot void'))
        result, message = self.void(payment)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertIn(END_OF_DAY_MSG, self.shown(payment, result, message))
        self.assertEqual(self.mock.count('REFUND'), 0, 'otomatik iadeye geçilmemeli')
        failed = self.lines(payment, state='failed')
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed.error_code, 'ERR10033')
        self.assertEqual(payment.refunded_amount, 0.0)

    def test_kk46_iptal_hatasinda_tekrar_denenebilir(self):
        payment = self.paid()
        self.mock.queue('VOID', err_body('ERR10033', 'cannot void'))
        self.void(payment)
        _, message = self.void(payment, 'Tekrar deniyorum')
        self.assertIsNone(message)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')
        self.assertEqual(len(self.lines(payment)), 2)

    def test_kk51_iptalde_olusturana_bildirim(self):
        payment = self.paid()
        self.void(payment)
        text = self.notification_texts(payment, self.user_sp.partner_id)
        self.assertIn(INV_NO, text)
        self.assertIn('9.000,00 TL', text)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundSuccess(RefundCase):

    def test_kk42_tam_iade(self):
        payment = self.paid()
        _, message = self.refund(payment, 9000.0, 'Ürün iadesi')
        self.assertIsNone(message)
        call = self.mock.last('REFUND')
        self.assertEqual(call.params['PGTRANID'], 'T1')
        self.assertEqual(call.params['MERCHANTPAYMENTID'], payment.merchant_payment_id)
        self.assertEqual(call.params['AMOUNT'], '9000.00')
        self.assertEqual(call.params['CURRENCY'], 'TRY')
        self.assertNotIn('REFLECTCOMMISSION', call.params)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 9000.0)
        self.assertEqual(payment.refundable_amount, 0.0)
        line = self.lines(payment)
        self.assertEqual((line.kind, line.state, line.source, line.amount, line.reason, line.user_id),
                         ('refund', 'done', 'odoo', 9000.0, 'Ürün iadesi', self.user_mgr))
        self.assertTrue(line.provider_ref)

    def test_kk43_kismi_sonra_kalan_iade(self):
        payment = self.paid()
        self.refund(payment, 2500.0)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '2500.00')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 2500.0)
        self.assertEqual(payment.refundable_amount, 6500.0)
        self.refund(payment, 6500.0, 'Kalan iade')
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '6500.00')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 9000.0)
        self.assertEqual(len(self.lines(payment, state='done')), 2)

    def test_kk43_ondalikli_tutar_iki_hane_ile_gider(self):
        payment = self.paid()
        self.refund(payment, 2500.5)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '2500.50')
        self.refund(payment, 0.01)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '0.01')
        payment.invalidate_recordset()
        self.assertEqual(payment.refunded_amount, 2500.51)

    def test_kk43_iade_sonrasi_senkron_durumu_bozmaz(self):
        payment = self.paid()
        self.refund(payment, 2500.0)
        refund_ref = self.lines(payment).provider_ref
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', refund_ref))
        payment.sudo()._sync_status()
        payment.invalidate_recordset()
        self.assertEqual(len(self.lines(payment)), 1, 'kendi iademiz panel iadesi olarak tekrar eklenmemeli')
        self.assertEqual(payment.refunded_amount, 2500.0)

    def test_kk44_islemden_once_senkron(self):
        payment = self.paid()
        self.refund(payment, 100.0)
        actions = self.mock.actions
        self.assertLess(actions.index('QUERYTRANSACTION'), actions.index('REFUND'))

    def test_kk44_panel_iadesi_kalandan_dusulur(self):
        payment = self.paid()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'), tran('AP', 'REFUND', '3000.00', 'PANEL-1'))
        self.assertRejected(payment, 'action_refund', 6500.0, 'Fazla tutar',
                            text='İade tutarı 0,01 ile 6.000,00 TL arasında olmalı.')
        _, message = self.refund(payment, 6000.0)
        self.assertIsNone(message)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 9000.0)

    def test_kk44_senkron_ulasilamazsa_iade_yapilmaz(self):
        payment = self.paid()
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        result, message = self.refund(payment, 100.0)
        self.assertIn('Paratika\'ya ulaşılamadı; iade/iptal yapılmadı.', self.shown(payment, result, message))
        self.assertEqual(self.mock.count('REFUND'), 0)
        self.assertFalse(self.lines(payment))

    def test_kk44_senkron_kaydin_iptal_edildigini_gosterirse_iade_olmaz(self):
        # Yönetici onaylı düzeltme (G11, TEST ÇELİŞKİSİ): senkron sonucu commit edilip ardından
        # UserError verilir; assertRaises'in savepoint'i bu yazımı test içinde geri alır. Bu yüzden
        # "voided" durumu commit anında (_sp_commit) yakalanır; niyet aynı: iade gitmez, kayıt
        # iptal edildi olarak saklanır.
        payment = self.paid()
        self.set_query_transactions(tran('VD', 'SALE', '9000.00', 'T1'))
        seen = []
        model = type(self.env['sanal.pos.payment'])

        def spy_commit(this):
            this.env.flush_all()
            seen.append(payment.sudo().state)
        with patch.object(model, '_sp_commit', spy_commit):
            self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi')
        self.assertIn('voided', seen, 'senkron "iptal edildi" sonucu commit edilmeli')

    def test_kk51_iadede_olusturana_bildirim(self):
        payment = self.paid()
        self.refund(payment, 2500.0)
        text = self.notification_texts(payment, self.user_sp.partner_id)
        self.assertIn('%s – 2.500,00 TL iade edildi' % INV_NO, text)
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))

    def test_kk51_basarisiz_iadede_bildirim_yok(self):
        payment = self.paid()
        self.mock.queue('REFUND', err_body('ERR10031', 'x'))
        self.refund(payment, 2500.0)
        self.assertNotIn('iade edildi', self.notification_texts(payment, self.user_sp.partner_id))

    def test_chatter_iade_notu_tutar_ve_neden(self):
        payment = self.paid()
        self.refund(payment, 2500.0, 'Beden uymadı')
        note = self.chatter(payment)
        self.assertIn('2.500,00 TL', note)
        self.assertIn('Beden uymadı', note)

    def test_kk39_iade_ve_iptal_loglari_mali_isaretli(self):
        payment = self.paid()
        self.refund(payment, 100.0)
        logs = self.env['sanal.pos.log'].sudo()
        refund_logs = logs.search([('action', '=', 'REFUND')])
        query_logs = logs.search([('action', '=', 'QUERYTRANSACTION')])
        self.assertTrue(refund_logs)
        self.assertTrue(all(refund_logs.mapped('is_financial')))
        self.assertTrue(query_logs)
        self.assertFalse(any(query_logs.mapped('is_financial')))

    def test_kk52_test_ortami_test_adresine_gider(self):
        payment = self.paid()
        self.refund(payment, 100.0)
        self.assertTrue(self.mock.last('REFUND').url.startswith(TEST_URL_PREFIX))

    def test_kk52_canli_kayit_canli_adrese_gider(self):
        payment = self.paid(environment='live')
        self.refund(payment, 100.0)
        for action in ('QUERYTRANSACTION', 'REFUND'):
            self.assertTrue(self.mock.last(action).url.startswith(LIVE_URL_PREFIX), action)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundAmountValidation(RefundCase):

    def setUp(self):
        super().setUp()
        self.payment = self.paid()
        self.refund(self.payment, 2500.0)       # kalan 6500
        self.mock.calls.clear()
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '2500.00', self.lines(self.payment).provider_ref))

    def test_kk44_gecersiz_tutarlar(self):
        for amount in (6500.01, 0, 0.0, -1, -6500, 10.005, 100000):
            with self.subTest(amount=amount):
                self.assertRejected(self.payment, 'action_refund', amount, 'Müşteri talebi',
                                    text='İade tutarı 0,01 ile 6.500,00 TL arasında olmalı.')
        self.assertEqual(self.payment.refunded_amount, 2500.0)

    def test_kk44_sinir_degerleri_gecerli(self):
        _, message = self.refund(self.payment, 0.01)
        self.assertIsNone(message)
        _, message = self.refund(self.payment, 6499.99)
        self.assertIsNone(message)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, 'refunded')

    def test_kk44_tam_kalan_tutar(self):
        _, message = self.refund(self.payment, 6500.0)
        self.assertIsNone(message)
        self.payment.invalidate_recordset()
        self.assertEqual(self.payment.state, 'refunded')

    def test_kk44_iki_ondalik_siniri(self):
        for amount in (1.001, 1.005, 100.123):
            with self.subTest(amount=amount):
                self.assertRejected(self.payment, 'action_refund', amount, 'Müşteri talebi')

    def test_kk44_neden_zorunlu(self):
        for reason in ('', '    ', 'abc'):
            with self.subTest(reason=reason):
                self.assertRejected(self.payment, 'action_refund', 100.0, reason)

    def test_kk45_kalan_yoksa_mesaj(self):
        _, message = self.refund(self.payment, 6500.0)
        self.assertIsNone(message)
        self.assertRejected(self.payment, 'action_refund', 1.0, 'Tekrar', text=NOTHING_LEFT)

    def test_kk45_iptal_edilmis_kayitta_iade_yok(self):
        payment = self.paid(invoice_no='VOIDED1')
        self.void(payment)
        self.assertRejected(payment, 'action_refund', 1.0, 'Müşteri talebi', text=NOTHING_LEFT)

    def test_odenmemis_durumlarda_iade_yok(self):
        for i, state in enumerate(('sent', 'expired', 'error', 'link_cancelled', 'unknown', 'review')):
            with self.subTest(state=state):
                payment = self.make_payment(state=state, invoice_no='NP%d' % i, provider_tran_ref='T9')
                self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi')
                self.assertRejected(payment, 'action_void', 'Müşteri talebi')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundFailures(RefundCase):

    def test_kk46_bilinen_kodlar_turkce_ve_durum_degismez(self):
        expected = {
            'ERR20040': 'Gün sonu geçmeden iade yapılamaz',
            'ERR10262': 'kısmi iade yapılamıyor',
            'ERR10031': None,
            'ERR10030': None,
            'ERR10033': None,
        }
        for i, (code, text) in enumerate(expected.items()):
            with self.subTest(code=code):
                payment = self.paid(invoice_no='RF%d' % i)
                self.mock.queue('REFUND', err_body(code, 'English only message'))
                result, message = self.refund(payment, 1000.0)
                shown = self.shown(payment, result, message)
                if text:
                    self.assertIn(text, shown)
                self.assertNotIn('English only message', shown, 'Türkçe karşılık gösterilmeli')
                failed = self.lines(payment, state='failed')
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed.error_code, code)
                self.assertEqual(payment.refunded_amount, 0.0)
                self.assertEqual(payment.state, 'paid')

    def test_kk46_basarisiz_satir_yeniden_denemeyi_engellemez(self):
        payment = self.paid()
        self.mock.queue('REFUND', err_body('ERR10031', 'x'))
        self.refund(payment, 1000.0)
        _, message = self.refund(payment, 1000.0)
        self.assertIsNone(message)
        payment.invalidate_recordset()
        self.assertEqual(payment.refunded_amount, 1000.0)
        self.assertEqual(len(self.lines(payment)), 2)

    def test_kk45_err10032_kaydi_senkronlar_ve_hata_gosterir(self):
        payment = self.paid()
        # Paratika tarafında aslında iade edilmiş: ilk sorgu bilmiyor, hata sonrası sorgu biliyor.
        self.mock.queue('QUERYTRANSACTION',
                        {'responseCode': '00', 'transactionList': [tran('AP', 'SALE', '9000.00', 'T1')]})
        self.mock.queue('REFUND', err_body('ERR10032', 'already refunded'))
        self.mock.queue('QUERYTRANSACTION',
                        {'responseCode': '00', 'transactionList': [tran('AP', 'SALE', '9000.00', 'T1'),
                                                                   tran('AP', 'REFUND', '9000.00', 'PANEL-R')]})
        result, message = self.refund(payment, 9000.0)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 2, 'ERR10032 sonrası yeniden senkron gerekir')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'refunded')
        self.assertTrue(self.lines(payment, source='panel'))
        self.assertTrue(self.shown(payment, result, message).strip())

    def test_kk47_zaman_asimi_belirsiz_satir(self):
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        before = self.cron_trigger_count(CRON_SYNC)
        result, message = self.refund(payment, 2500.0)
        line = self.lines(payment)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.state, 'unknown')
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.refunded_amount, 0.0, 'belirsiz iade toplama katılmaz')
        self.assertIn(UNKNOWN_MSG, self.shown(payment, result, message))
        self.assertGreater(self.cron_trigger_count(CRON_SYNC), before, 'uzlaştırma tetiği kurulmalı')

    def test_kk47_belirsizken_yeni_iade_veya_iptal_yok(self):
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, 2500.0)
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar', text=BUSY_MSG)
        self.assertRejected(payment, 'action_void', 'Tekrar deniyorum', text=BUSY_MSG)

    def test_kk47_iptal_zaman_asimi(self):
        payment = self.paid()
        self.mock.queue('VOID', timeout_exc())
        result, message = self.void(payment)
        self.assertEqual(self.lines(payment).state, 'unknown')
        self.assertIn(UNKNOWN_MSG, self.shown(payment, result, message))
        self.assertEqual(payment.state, 'paid')

    def test_kk47_http_500_de_belirsiz(self):
        from .common import RawResponse
        payment = self.paid()
        self.mock.queue('REFUND', RawResponse(500, 'oops'))
        self.refund(payment, 100.0)
        self.assertEqual(self.lines(payment).state, 'unknown')

    def test_kk47_uzlastirma_eslesen_islem_bulunursa_basarili(self):
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, 2500.0)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'), tran('AP', 'REFUND', '2500.00', 'R-FOUND'))
        self.run_cron(CRON_SYNC)
        line = self.lines(payment)
        payment.invalidate_recordset()
        self.assertEqual(len(line), 1, 'eşleşen işlem yeni panel satırı açmamalı')
        self.assertEqual((line.state, line.provider_ref, line.source), ('done', 'R-FOUND', 'odoo'))
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 2500.0)

    def test_kk47_uzlastirma_farkli_tutar_eslesmez(self):
        # Yönetici onaylı düzeltme (G11 şart 1): belirsiz satır tek sorguyla başarısız olmaz;
        # ≥2 ayrı sorgu + bekleyen işlem yok + ilk belirsizlikten ≥15 dk gerekir.
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, 2500.0)
        self.age_line(self.lines(payment), 20)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'), tran('AP', 'REFUND', '999.00', 'R-OTHER'))
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.lines(payment, source='odoo').state, 'unknown', 'tek sorgu yetmez')
        self.assertEqual(self.lines(payment, source='panel').provider_ref, 'R-OTHER')
        self.run_cron(CRON_SYNC)
        by_state = {l.provider_ref or 'x': l.state for l in self.lines(payment)}
        self.assertEqual(self.lines(payment, source='odoo').state, 'failed')
        self.assertEqual(self.lines(payment, source='panel').provider_ref, 'R-OTHER')
        self.assertEqual(payment.refunded_amount, 999.0, by_state)

    def test_kk47_uzlastirma_bulunamazsa_2_sorgu_ve_15_dk_sonra_basarisiz(self):
        # Yönetici onaylı düzeltme (G11 şart 1): eşik 10 dk değil; ≥2 sorgu + ≥15 dk.
        payment = self.paid()
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, 2500.0)
        # 15 dk dolmadan: belirsiz kalır (1. sorgu)
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.lines(payment).state, 'unknown')
        self.age_line(self.lines(payment), 15)
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.lines(payment).state, 'failed')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.refunded_amount, 0.0)
        # artık yeni iade yapılabilir
        _, message = self.refund(payment, 2500.0)
        self.assertIsNone(message)

    def test_kk47_belirsiz_iptal_uzlastirma(self):
        payment = self.paid()
        self.mock.queue('VOID', timeout_exc())
        self.void(payment)
        self.set_query_transactions(tran('VD', 'SALE', '9000.00', 'T1'))
        self.run_cron(CRON_SYNC)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')
        self.assertEqual(self.lines(payment, kind='void')[:1].state, 'done')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestDuplicateRefund(RefundCase):
    """KK-45: tek devam eden işlem, çift tıklama, ikinci yönetici."""

    def test_kk45_islemdeki_satir_varken_yeni_istek_reddedilir(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='processing')
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar', text=BUSY_MSG)
        self.assertRejected(payment, 'action_void', 'Tekrar deniyorum', text=BUSY_MSG)

    def test_kk45_belirsiz_satir_varken_yeni_istek_reddedilir(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='unknown')
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar', text=BUSY_MSG)

    def test_kk45_cift_tiklama_tam_iade_tek_istek(self):
        payment = self.paid()
        first = self.refund(payment, 9000.0)
        second = self.refund(payment, 9000.0)
        self.assertIsNone(first[1])
        self.assertIn(NOTHING_LEFT, second[1] or '')
        self.assertEqual(self.mock.count('REFUND'), 1)
        self.assertEqual(len(self.lines(payment)), 1)

    def test_kk45_ikinci_yonetici_ayni_tutari_tekrar_iade_edemez(self):
        payment = self.paid()
        manager2 = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Test manager 2', 'login': 'sp_manager2', 'email': 'sp_manager2@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('sanal_pos.group_sanal_pos_manager').id])],
        })
        self.refund(payment, 6000.0)
        self.set_query_transactions(tran('AP', 'SALE', '9000.00', 'T1'),
                                    tran('AP', 'REFUND', '6000.00', self.lines(payment).provider_ref))
        _, message = self.attempt(payment, 'action_refund', 6000.0, 'İkinci yönetici', user=manager2)
        self.assertIsNotNone(message, 'toplam iade ödenen tutarı aşamaz')
        self.assertEqual(self.mock.count('REFUND'), 1)
        payment.invalidate_recordset()
        self.assertLessEqual(payment.refunded_amount, 9000.0)

    def test_kk45_iptal_sonrasi_iade_ve_tersi_yok(self):
        payment = self.paid()
        self.void(payment)
        # Yönetici onaylı düzeltme (G11, TEST ÇELİŞKİSİ): assertRejected çağrı listesini temizler;
        # sayım ondan önce yapılır. Reddedilen denemelerde VOID/REFUND gitmediğini assertRejected sınar.
        self.assertEqual(self.mock.count('VOID'), 1)
        self.assertRejected(payment, 'action_void', 'Tekrar deniyorum')
        self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar deniyorum', text=NOTHING_LEFT)

    def test_kk45_toplam_iade_odenen_tutari_asamaz(self):
        payment = self.paid()
        for amount in (4000.0, 4000.0, 1000.0):
            self.refund(payment, amount)
            payment.invalidate_recordset()
            self.set_query_transactions(
                tran('AP', 'SALE', '9000.00', 'T1'),
                *[tran('AP', 'REFUND', '%.2f' % l.amount, l.provider_ref) for l in self.lines(payment, state='done')])
        self.assertEqual(payment.refunded_amount, 9000.0)
        self.assertEqual(payment.state, 'refunded')
        self.assertRejected(payment, 'action_refund', 0.01, 'Fazla', text=NOTHING_LEFT)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundPermissions(RefundCase):

    def test_kk49_kullanici_iptal_ve_iade_yapamaz(self):
        payment = self.paid()
        self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi', exc=AccessError, user=self.user_sp)
        self.assertRejected(payment, 'action_void', 'Müşteri talebi', exc=AccessError, user=self.user_sp)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'paid')

    def test_kk49_grupsuz_kullanici(self):
        payment = self.paid()
        self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi', exc=AccessError, user=self.user_plain)
        self.assertRejected(payment, 'action_void', 'Müşteri talebi', exc=AccessError, user=self.user_plain)

    def test_u3_sistem_yoneticisi_otomatik_iade_yetkilisi_degil(self):
        payment = self.paid()
        self.assertRejected(payment, 'action_refund', 100.0, 'Müşteri talebi', exc=AccessError, user=self.user_sys)
        self.assertRejected(payment, 'action_void', 'Müşteri talebi', exc=AccessError, user=self.user_sys)

    def test_kk49_yetkisiz_denemede_paratika_cagrisi_yok(self):
        payment = self.paid()
        self.mock.calls.clear()
        with self.assertRaises(AccessError):
            payment.with_user(self.user_sp).action_refund(100.0, 'Müşteri talebi')
        self.assertNoParatikaCalls()

    def test_kk49_yonetici_yapabilir(self):
        payment = self.paid()
        _, message = self.refund(payment, 100.0)
        self.assertIsNone(message)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundWizard(RefundCase):
    """KK-50: onay penceresi bilgileri; düğmeye basmadan istek gitmez. KK-52: test uyarısı."""

    def make(self, payment, kind='refund', **vals):
        data = {'payment_id': payment.id, 'kind': kind}
        data.update(vals)
        return self.env[WIZARD].with_user(self.user_mgr).create(data)

    def confirm(self, wiz):
        for name in ('action_confirm', 'action_refund', 'action_void', 'action_submit', 'action_apply'):
            if hasattr(wiz, name):
                return getattr(wiz, name)()
        self.fail('Sihirbazda onay düğmesi eylemi bulunamadı (action_confirm bekleniyor)')

    def test_kk50_ozet_alanlari(self):
        payment = self.paid()
        wiz = self.make(payment, amount=2500.0, reason='Müşteri talebi')
        summary = wiz.summary or ''
        for needle in (INV_NO, CUSTOMER_NAME, '2.500,00 TL'):
            self.assertIn(needle, summary)
        self.assertTrue(('İade' in summary) or ('iade' in summary.lower()))

    def test_kk50_iptal_ozeti_tam_tutar(self):
        payment = self.paid()
        wiz = self.make(payment, kind='void', reason='Müşteri vazgeçti')
        self.assertEqual(wiz.amount, 9000.0)
        self.assertIn('9.000,00 TL', wiz.summary or '')
        self.assertIn('iptal', (wiz.summary or '').lower())

    def test_kk50_varsayilan_tutar_kalan(self):
        payment = self.paid()
        self.refund(payment, 2500.0)
        wiz = self.env[WIZARD].with_user(self.user_mgr).with_context(
            default_payment_id=payment.id, default_kind='refund').create({'payment_id': payment.id, 'kind': 'refund'})
        self.assertEqual(wiz.amount, 6500.0)

    def test_kk50_olusturmak_istek_gondermez(self):
        payment = self.paid()
        self.mock.calls.clear()
        self.make(payment, amount=100.0, reason='Müşteri talebi')
        self.assertEqual(self.mock.count('VOID', 'REFUND'), 0)

    def test_kk50_onay_iade_yapar(self):
        payment = self.paid()
        wiz = self.make(payment, amount=2500.0, reason='Beden uymadı')
        self.confirm(wiz)
        self.assertEqual(self.mock.last('REFUND').params['AMOUNT'], '2500.00')
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk50_onay_iptal_yapar(self):
        payment = self.paid()
        wiz = self.make(payment, kind='void', reason='Müşteri vazgeçti')
        self.confirm(wiz)
        self.assertEqual(self.mock.count('VOID'), 1)
        payment.invalidate_recordset()
        self.assertEqual(payment.state, 'voided')

    def test_kk50_sihirbaz_neden_ve_tutar_dogrular(self):
        payment = self.paid()
        with self.assertRaises(UserError):
            self.confirm(self.make(payment, amount=100.0, reason='abc'))
        with self.assertRaises(UserError):
            self.confirm(self.make(payment, amount=9000.01, reason='Müşteri talebi'))
        self.assertEqual(self.mock.count('VOID', 'REFUND'), 0)

    def test_kk52_test_ortami_uyarisi(self):
        payment = self.paid()
        self.assertTrue(self.make(payment).is_test)
        live = self.paid(environment='live', invoice_no='LIVE1')
        self.assertFalse(self.make(live).is_test)

    def test_kk49_kullanici_sihirbazi_acamaz(self):
        payment = self.paid()
        with self.assertRaises(AccessError):
            self.env[WIZARD].with_user(self.user_sp).create({'payment_id': payment.id, 'kind': 'refund'})

# -*- coding: utf-8 -*-
"""Paratika iade onayı (KK-1..KK-14, KK-17, KK-18): "Onay bekliyor" ara durumu.

Tasarım: .ekip/20261023-paratika-iade-onay/02-tasarim.md (§2 durum makinesi, §5 senkron,
§12 kabul kriterleri). REFUND ``responseCode=00`` artık "iade edildi" değil "Paratika isteği
kabul etti" demektir: satır ``pending_approval``, ödeme ``refund_pending``. Kesin sonucu
QUERYTRANSACTION senkronu verir (AP -> done, açık red -> rejected, diğer her şey bekler).

Testler dışarıdan gözlenen davranışı sınar: durumlar, tutarlar, engeller, chatter/bildirim
içeriği. Paratika HTTP'si taklit edilir (``tests/mocks.py``). Geçiş sihirbazı (KK-15, KK-16)
``test_refund_migration.py`` içindedir.
"""
import importlib
import json
from datetime import datetime, timedelta, timezone

from lxml import etree
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import file_open, mute_logger
from odoo.tools import html2plaintext

from .common import (
    CRON_DAILY, CRON_SYNC, INV_NO, ok_body, timeout_exc, tran,
)
from .test_refund import RefundCase

PAYMENT = 'sanal.pos.payment'
REFUND = 'sanal.pos.refund'
PROVIDER = 'sanal.pos.provider.paratika'

PENDING_MSG_PART = 'finans onayı bekleyen bir iade'          # REFUND_PENDING_MSG
PAID_MSG = 'Bu fatura için ödeme alınmış/incelemede; yeni link oluşturulamaz.'
ALLOWED_DETAIL_KEYS = {'raw_type', 'raw_status', 'return_code', 'error_code',
                       'raw_message', 'amount', 'time', 'ref'}


def utcnow():
    return datetime.utcnow().replace(microsecond=0)


def ms(when):
    """Naive UTC datetime -> epoch milisaniye (``timeCreated``; saat dilimi belirsizliği yok)."""
    return int(when.replace(tzinfo=timezone.utc).timestamp() * 1000)


def rt(status, amount, ref, **extra):
    """QUERYTRANSACTION içindeki bir REFUND işlemi."""
    return tran(status, 'REFUND', '%.2f' % amount, ref, **extra)


class ApprovalCase(RefundCase):
    """Ortak yardımcılar. Özellik yoksa her test doğru sebeple (seçim değeri yok) kırmızıdır."""

    def setUp(self):
        super().setUp()
        refund_states = {k for k, _l in self.env[REFUND]._fields['state'].selection}
        payment_states = {k for k, _l in self.env[PAYMENT]._fields['state'].selection}
        missing = ({'pending_approval', 'rejected'} - refund_states) \
            | ({'refund_pending'} - payment_states)
        self.assertFalse(missing, 'Özellik yok: seçim değerleri eksik %s' % sorted(missing))

    # ------------------------------------------------------------------ kurulum
    def request_refund(self, payment, amount=2500.0, reason='Müşteri talebi', ref='auto'):
        """Gerçek akıştan REFUND 00 -> bekleyen satır. ``ref=None``: yanıtta pgTranId yok."""
        if ref is None:
            self.mock.queue('REFUND', ok_body(merchantPaymentId=payment.merchant_payment_id))
        elif ref != 'auto':
            self.mock.queue('REFUND', ok_body(pgTranId=ref,
                                              merchantPaymentId=payment.merchant_payment_id))
        _result, message = self.refund(payment, amount, reason)
        self.assertIsNone(message, 'iade isteği hata verdi: %s' % message)
        return self.last_line(payment)

    def last_line(self, payment):
        payment.invalidate_recordset()
        return payment.refund_ids.sorted('id')[-1:]

    def query(self, payment, *items):
        """QUERYTRANSACTION kalıcı yanıtı: ödemenin satışı (AP) + verilen iade/iptal işlemleri."""
        self.set_query_transactions(
            tran('AP', 'SALE', '%.2f' % payment.paid_amount, 'T1'), *items)

    def sync(self, payment):
        payment.sudo()._sync_status()
        payment.invalidate_recordset()
        return payment

    def age(self, line, **delta):
        """Satırın create_date'ini geriye alır; (yeni create_date) döner."""
        when = utcnow() - timedelta(**delta)
        self.set_create_date(line, when)
        return when

    def pending_payment(self, amount=2500.0, ref='R-P1', paid=9000.0, **vals):
        payment = self.paid(amount=paid, **vals)
        line = self.request_refund(payment, amount, ref=ref)
        self.assertEqual(line.state, 'pending_approval')
        return payment, line

    def messages_with(self, payment, text):
        msgs = self.env['mail.message'].sudo().search([
            ('model', '=', PAYMENT), ('res_id', '=', payment.id)])
        return msgs.filtered(lambda m: text in html2plaintext(m.body or ''))

    def notified_text(self, payment, user):
        return self.notification_texts(payment, user.partner_id)

    def refresh(self, *records):
        for rec in records:
            rec.invalidate_recordset()


# ---------------------------------------------------------------------------------------
# KK-2: VOID bugünkü gibi (özellik yokken de GEÇER; gerilemeyi yakalar)
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestVoidUnchanged(RefundCase):

    def test_kk2_void_00_done_ve_voided(self):
        payment = self.paid()
        _r, message = self.void(payment, 'Müşteri vazgeçti')
        self.assertIsNone(message)
        payment.invalidate_recordset()
        line = self.lines(payment)
        self.assertEqual((line.kind, line.state), ('void', 'done'))
        self.assertTrue(line.done_at)
        self.assertEqual(payment.state, 'voided')
        text = self.chatter(payment)
        self.assertIn('ödeme iptal edildi', text)
        self.assertNotIn('finans onayı', text, 'VOID onay beklemez')
        self.assertIn('ödeme iptal edildi', self.notification_texts(payment, self.user_sp.partner_id))


# ---------------------------------------------------------------------------------------
# KK-1, KK-4: REFUND 00 -> bekleyen satır, refund_pending, tutar düşer
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestRefundRequest(ApprovalCase):

    def test_kk1_refund_00_satir_bekler_odeme_refund_pending(self):
        payment = self.paid()
        before = self.cron_trigger_count(CRON_SYNC)
        line = self.request_refund(payment, 2500.0, 'Beden uymadı')
        self.assertEqual((line.kind, line.state, line.source, line.amount),
                         ('refund', 'pending_approval', 'odoo', 2500.0))
        self.assertFalse(line.done_at, 'bekleyen satırda tamamlanma zamanı olmaz')
        self.assertTrue(line.provider_ref)
        self.assertFalse(line.error_code or line.error_message)
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(payment.refunded_amount, 0.0, 'refunded_amount yalnız done toplamıdır')
        self.assertEqual(self.mock.count('REFUND'), 1)
        self.assertGreater(self.cron_trigger_count(CRON_SYNC), before, 'senkron tetiği kurulmalı')

    def test_kk1_chatter_ve_olusturana_bildirim_onay_bekleniyor_der(self):
        payment = self.paid()
        self.request_refund(payment, 2500.0, 'Beden uymadı')
        note = self.chatter(payment)
        self.assertIn('%s – 2.500,00 TL iade talebi' % INV_NO, note)
        self.assertIn('iletildi', note)
        self.assertIn('finans onayı bekleniyor', note)
        self.assertIn('Beden uymadı', note)
        self.assertNotIn('iade edildi', note, 'henüz iade edilmedi; kullanıcı yanıltılmamalı')
        creator = self.notified_text(payment, self.user_sp)
        self.assertIn('%s – 2.500,00 TL iade talebi' % INV_NO, creator)
        self.assertIn('finans onayı bekleniyor', creator)
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))

    def test_kk1_tam_iade_de_beklemeye_girer(self):
        payment = self.paid()
        line = self.request_refund(payment, 9000.0, 'Ürün iadesi')
        self.assertEqual(line.state, 'pending_approval')
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(payment.refunded_amount, 0.0)
        self.assertEqual(payment.refundable_amount, 0.0)

    def test_kk4_bekleyen_tutar_iade_edilebilirden_duser(self):
        payment = self.paid()
        self.request_refund(payment, 2500.0)
        self.assertEqual(payment.refundable_amount, 6500.0)
        self.assertEqual(payment._refundable_cents(), 650000)
        self.assertEqual(payment.refunded_amount, 0.0)

    def test_kk4_diger_satir_durumlari_duser_ya_da_dusmez(self):
        payment = self.paid()
        done = self.make_refund_line(payment, 1000.0, state='done', provider_ref='R-D')
        self.make_refund_line(payment, 500.0, state='rejected', provider_ref='R-RJ')
        self.make_refund_line(payment, 400.0, state='failed', provider_ref='R-FL')
        pending = self.make_refund_line(payment, 2000.0, state='pending_approval', provider_ref='R-PD')
        payment.invalidate_recordset()
        self.assertEqual(payment.refundable_amount, 6000.0, 'done+bekleyen düşer; red/başarısız düşmez')
        self.assertEqual(payment._refundable_cents(), 600000)
        pending.sudo().write({'state': 'rejected'})
        self.assertEqual(payment.refundable_amount, 8000.0, 'red sonrası tutar geri döner')
        self.assertEqual(payment._refundable_cents(), 800000)
        self.assertEqual(done.state, 'done')

    def test_kk4_100_tl_30_done_70_bekleyen(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 30.0, state='done', provider_ref='R-D30')
        payment._recompute_refund_state()
        self.query(payment, rt('AP', 30.0, 'R-D30'))
        line = self.request_refund(payment, 70.0, ref='R-P70')
        self.assertEqual(line.state, 'pending_approval')
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(payment.refunded_amount, 30.0)
        self.assertEqual(payment.refundable_amount, 0.0)
        self.assertEqual(payment._refundable_cents(), 0)


# ---------------------------------------------------------------------------------------
# KK-3: bekleyen iade varken yeni iade / iptal / link engellenir; DB indeksi
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestPendingBlocks(ApprovalCase):

    def test_kk3_yeni_iade_reddedilir_paratika_cagrisi_yok(self):
        payment, _line = self.pending_payment()
        message = self.assertRejected(payment, 'action_refund', 100.0, 'Tekrar deniyorum')
        self.assertIn(PENDING_MSG_PART, message)
        self.assertEqual(self.mock.count('QUERYTRANSACTION', 'REFUND', 'VOID'), 0)

    def test_kk3_iptal_reddedilir_paratika_cagrisi_yok(self):
        payment, _line = self.pending_payment()
        message = self.assertRejected(payment, 'action_void', 'Müşteri vazgeçti')
        self.assertIn(PENDING_MSG_PART, message)
        self.assertEqual(self.mock.count('QUERYTRANSACTION', 'REFUND', 'VOID'), 0)

    def test_kk3_can_refund_ve_can_void_false(self):
        payment, _line = self.pending_payment()
        self.assertFalse(payment.can_refund)
        self.assertFalse(payment.can_void)

    def test_kk3_yeni_link_engellenir(self):
        payment, _line = self.pending_payment()
        # sihirbaz yolu: ödenmiş/incelemede mesajı
        wiz = self.wizard()
        self.assertIn(PAID_MSG, wiz.blocking_message or '')
        self.mock.calls.clear()
        with self.assertRaises(UserError) as ctx:
            wiz.action_create_link()
        self.assertIn(PAID_MSG, str(ctx.exception.args[0]))
        self.assertEqual(self.mock.count('PAYBYLINKPAYMENT'), 0)
        # 'Yeni Link Oluştur' düğmesi yolu: refund_pending yeniden kullanılabilir durum değildir
        with self.assertRaises(UserError):
            payment.with_user(self.user_sp).action_new_link()
        self.assertEqual(len(self.payments()), 1)

    def test_kk3_reddedilen_iade_sonrasi_yeni_link_hala_engelli_degil_durum_paid(self):
        # Red sonrası ödeme 'paid'e döner: yeni link yine PAID_MSG ile engellenir (para alınmış kayıt)
        payment, _line = self.pending_payment(ref='R-RJ')
        self.query(payment, rt('FA', 2500.0, 'R-RJ'))
        self.sync(payment)
        self.assertEqual(payment.state, 'paid')
        self.assertIn(PAID_MSG, self.wizard().blocking_message or '')

    def test_kk3_indeks_ikinci_bekleyen_satiri_reddeder(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='pending_approval', provider_ref='R-1')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.make_refund_line(payment, 200.0, state='pending_approval', provider_ref='R-2')

    def test_kk3_indeks_bekleyen_ile_devam_eden_satir_birlikte_olamaz(self):
        for other in ('processing', 'unknown'):
            with self.subTest(other=other):
                payment = self.paid(invoice_no='IDX-%s' % other)
                self.make_refund_line(payment, 100.0, state='pending_approval', provider_ref='R-1')
                with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), \
                        self.env.cr.savepoint():
                    self.make_refund_line(payment, 200.0, state=other, provider_ref=False)

    def test_kk3_indeks_done_failed_rejected_satirlari_engellemez(self):
        payment = self.paid()
        self.make_refund_line(payment, 100.0, state='pending_approval', provider_ref='R-1')
        for i, state in enumerate(('done', 'failed', 'rejected', 'done'), start=2):
            self.make_refund_line(payment, 10.0 * i, state=state, provider_ref='R-%d' % i)
        self.assertEqual(len(self.lines(payment)), 5)

    def test_kk3_indeks_tanimi_bekleyeni_kapsar(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'sanal_pos_refund' "
            "AND indexdef ILIKE '%pending_approval%'")
        rows = self.env.cr.fetchall()
        self.assertEqual(len(rows), 1, 'pending_approval kapsayan kısmi indeks yok')
        definition = rows[0][0]
        self.assertIn('processing', definition)
        self.assertIn('unknown', definition)
        self.assertIn('UNIQUE', definition.upper())


# ---------------------------------------------------------------------------------------
# KK-5: AP -> done
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestApproved(ApprovalCase):

    def test_kk5_ap_satiri_done_yapar_done_at_timecreated(self):
        payment, line = self.pending_payment(2500.0, ref='R-A1')
        created = self.age(line, hours=1)
        when = created + timedelta(minutes=10)
        self.query(payment, rt('AP', 2500.0, 'R-A1', timeCreated=ms(when)))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'done')
        self.assertEqual(line.done_at, when, 'done_at = Paratika işlem zamanı (timeCreated)')
        self.assertEqual(line.provider_ref, 'R-A1')
        self.assertEqual(line.provider_status, 'AP')
        self.assertFalse(line.error_code or line.error_message)
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 2500.0)
        self.assertEqual(payment.refundable_amount, 6500.0)
        self.assertEqual(len(self.lines(payment)), 1, 'panel kopyası açılmamalı')

    def test_kk5_tam_iade_onaylaninca_refunded(self):
        payment, line = self.pending_payment(9000.0, ref='R-A2')
        self.query(payment, rt('AP', 9000.0, 'R-A2'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'done')
        self.assertTrue(line.done_at, 'zaman alanı yoksa şimdi')
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 9000.0)
        self.assertEqual(payment.refundable_amount, 0.0)

    def test_kk5_30_done_70_bekleyen_onaylaninca_refunded(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 30.0, state='done', provider_ref='R-D30')
        payment._recompute_refund_state()
        self.query(payment, rt('AP', 30.0, 'R-D30'))
        line = self.request_refund(payment, 70.0, ref='R-P70')
        self.query(payment, rt('AP', 30.0, 'R-D30'), rt('AP', 70.0, 'R-P70'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'done')
        self.assertEqual(payment.state, 'refunded')
        self.assertEqual(payment.refunded_amount, 100.0)

    def test_kk5_onaylandi_bildirimi_olusturana_ve_iadeyi_yapana(self):
        payment, _line = self.pending_payment(2500.0, ref='R-A3')
        self.query(payment, rt('AP', 2500.0, 'R-A3'))
        self.sync(payment)
        expected = '%s – 2.500,00 TL iade Paratika tarafından onaylandı' % INV_NO
        self.assertIn(expected, self.chatter(payment))
        self.assertIn('R-A3', self.chatter(payment))
        for user in (self.user_sp, self.user_mgr):     # oluşturan + iadeyi yapan
            with self.subTest(user=user.login):
                self.assertIn(expected, self.notified_text(payment, user))
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))

    def test_kk5_onay_tekrar_bildirim_uretmez(self):
        payment, _line = self.pending_payment(2500.0, ref='R-A4')
        self.query(payment, rt('AP', 2500.0, 'R-A4'))
        self.sync(payment)
        count = len(self.messages_with(payment, 'tarafından onaylandı'))
        self.assertEqual(count, 1)
        self.sync(payment)
        self.assertEqual(len(self.messages_with(payment, 'tarafından onaylandı')), 1)

    def test_kk5_cron_yoluyla_da_onaylanir(self):
        payment, line = self.pending_payment(2500.0, ref='R-A5')
        self.query(payment, rt('AP', 2500.0, 'R-A5'))
        self.run_cron(CRON_SYNC)
        self.refresh(line, payment)
        self.assertEqual(line.state, 'done')
        self.assertEqual(payment.state, 'partial_refund')


# ---------------------------------------------------------------------------------------
# KK-6: açık red -> rejected + ret sebebi; tutar geri döner
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestRejected(ApprovalCase):

    def reject(self, amount=2500.0, ref='R-F1', paid=9000.0, **extra):
        payment, line = self.pending_payment(amount, ref=ref, paid=paid)
        self.query(payment, rt('FA', amount, ref, **extra))
        self.sync(payment)
        self.refresh(line)
        return payment, line

    def test_kk6_fa_ret_sebebi_satir_chatter_ve_bildirimde(self):
        payment, line = self.reject(errorCode='ERR55555', errorMsg='Kart hesabi kapali')
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(line.error_code, 'ERR55555')
        self.assertIn('Kart hesabi kapali', line.error_message)
        self.assertEqual(line.provider_status, 'FA')
        self.assertFalse(line.done_at)
        for label, text in (('chatter', self.chatter(payment)),
                            ('oluşturan', self.notified_text(payment, self.user_sp)),
                            ('iadeyi yapan', self.notified_text(payment, self.user_mgr))):
            with self.subTest(yer=label):
                self.assertIn('REDDEDİLDİ', text)
                self.assertIn('Kart hesabi kapali', text)
                self.assertIn('ERR55555', text)
                self.assertIn('%s – 2.500,00 TL iade' % INV_NO, text)

    def test_kk6_tutar_geri_doner_odeme_paid(self):
        payment, line = self.reject()
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.refunded_amount, 0.0)
        self.assertEqual(payment.refundable_amount, 9000.0)
        self.assertEqual(payment._refundable_cents(), 900000)
        self.assertTrue(payment.can_refund)

    def test_kk6_ret_sonrasi_yeni_iade_yapilabilir(self):
        payment, line = self.reject(ref='R-F1')
        self.mock.calls.clear()
        new_line = self.request_refund(payment, 2500.0)
        self.assertEqual(self.mock.count('REFUND'), 1)
        self.assertNotEqual(new_line.id, line.id)
        self.assertEqual(new_line.state, 'pending_approval')
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(self.refresh_state(line), 'rejected', 'eski satır reddedilmiş kalır')
        # eski FA işlemi yeni satırı reddetmez
        self.sync(payment)
        self.refresh(new_line)
        self.assertEqual(new_line.state, 'pending_approval')
        self.assertEqual(payment.state, 'refund_pending')

    def refresh_state(self, line):
        line.invalidate_recordset()
        return line.state

    def test_kk6_100_tl_30_done_70_red_partial_refund_ve_70_iade_edilebilir(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 30.0, state='done', provider_ref='R-D30')
        payment._recompute_refund_state()
        self.query(payment, rt('AP', 30.0, 'R-D30'))
        line = self.request_refund(payment, 70.0, ref='R-P70')
        self.assertEqual(payment.state, 'refund_pending')
        self.query(payment, rt('AP', 30.0, 'R-D30'), rt('FA', 70.0, 'R-P70'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 30.0)
        self.assertEqual(payment.refundable_amount, 70.0)
        self.assertEqual(payment._refundable_cents(), 7000)
        self.assertTrue(payment.can_refund)

    def test_kk6_err10153_turkce_sebep(self):
        payment, line = self.reject(errorCode='ERR10153', errorMsg='Refund denied by finance')
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(line.error_code, 'ERR10153')
        self.assertIn('Finans ekibi tarafından reddedildi', line.error_message)
        self.assertIn('Finans ekibi tarafından reddedildi', self.chatter(payment))
        self.assertIn('Finans ekibi tarafından reddedildi', self.notified_text(payment, self.user_sp))
        self.assertEqual(payment.state, 'paid')

    def test_kk6_err10153_durum_kodu_fa_olmasa_da_red(self):
        for status in ('IP', 'MR', 'AP'):
            with self.subTest(durum=status):
                payment, line = self.pending_payment(2500.0, ref='R-X-%s' % status,
                                                     invoice_no='ERR-%s' % status)
                self.query(payment, rt(status, 2500.0, 'R-X-%s' % status, errorCode='ERR10153'))
                self.sync(payment)
                self.refresh(line)
                self.assertEqual(line.state, 'rejected',
                                 'REFUND_REJECT_CODES açık red kanıtıdır (durum %s)' % status)
                self.assertEqual(payment.state, 'paid')

    def test_kk6_err10153_pgtranreturncode_icinde_de_red(self):
        payment, line = self.reject(pgTranReturnCode='ERR10153')
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(payment.state, 'paid')

    def test_kk6_kodsuz_fa_ham_durum_ve_varsayilan_mesaj(self):
        payment, line = self.reject()
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(line.error_code, 'FA')
        self.assertIn('FA', line.error_message)
        self.assertIn('REDDEDİLDİ', self.chatter(payment))

    def test_kk6_kodsuz_fa_return_code_varsa_kod_odur(self):
        _payment, line = self.reject(pgTranReturnCode='51')
        self.assertEqual(line.state, 'rejected')
        self.assertEqual(line.error_code, '51')

    def test_kk6_ret_sebebi_en_cok_250_karakter(self):
        _payment, line = self.reject(errorCode='ERR55555', errorMsg='x' * 400)
        self.assertEqual(line.state, 'rejected')
        self.assertLessEqual(len(line.error_message), 250)

    def test_kk6_ham_ayrinti_json_izinli_alanlar_kart_verisi_yok(self):
        _payment, line = self.reject(errorCode='ERR55555', errorMsg='Kart hesabi kapali',
                                     last4='9876', timeCreated=ms(utcnow()))
        detail = line.provider_status_detail
        self.assertTrue(detail)
        self.assertLessEqual(len(detail), 1000)
        data = json.loads(detail)
        self.assertLessEqual(set(data), ALLOWED_DETAIL_KEYS)
        self.assertEqual(data.get('raw_status'), 'FA')
        self.assertNotIn('9876', detail, 'kart son 4 yazılmaz')

    def test_kk6_red_tekrar_bildirim_uretmez(self):
        payment, _line = self.reject(errorCode='ERR55555', errorMsg='Kart hesabi kapali')
        self.assertEqual(len(self.messages_with(payment, 'REDDEDİLDİ')), 1)
        self.sync(payment)
        self.run_cron(CRON_SYNC)
        self.assertEqual(len(self.messages_with(payment, 'REDDEDİLDİ')), 1)

    def test_kk6_eski_failed_satir_degismez(self):
        # G11 §8: failed satır sonradan hiçbir sorguyla değişmez
        payment = self.paid()
        failed = self.make_refund_line(payment, 2500.0, state='failed', provider_ref='R-FAILED',
                                       error_code='ERR10031')
        self.query(payment, rt('AP', 2500.0, 'R-FAILED'))
        self.sync(payment)
        self.refresh(failed)
        self.assertEqual(failed.state, 'failed')


# ---------------------------------------------------------------------------------------
# KK-7, KK-8: diğer durumlar bekler; bulunamadı asla red değildir
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestWaiting(ApprovalCase):

    def test_kk7_bekleyen_durumlar_satiri_beklemede_tutar(self):
        for status in ('IP', 'MR', 'CA', 'VD', 'XY'):
            with self.subTest(durum=status):
                payment, line = self.pending_payment(2500.0, ref='R-W-%s' % status,
                                                     invoice_no='WAIT-%s' % status)
                self.query(payment, rt(status, 2500.0, 'R-W-%s' % status))
                self.sync(payment)
                self.refresh(line)
                self.assertEqual(line.state, 'pending_approval')
                self.assertEqual(line.provider_status, status, 'ham Paratika durumu saklanır')
                detail = json.loads(line.provider_status_detail)
                self.assertEqual(detail.get('raw_status'), status)
                self.assertEqual(payment.state, 'refund_pending')
                self.assertEqual(payment.refunded_amount, 0.0)
                self.assertFalse(line.error_code or line.error_message)
                self.assertEqual(len(self.lines(payment)), 1)

    def test_kk7_ayni_durum_tekrar_yazilmaz_chatter_gurultusu_yok(self):
        payment, line = self.pending_payment(2500.0, ref='R-W1')
        self.query(payment, rt('IP', 2500.0, 'R-W1'))
        self.sync(payment)
        self.refresh(line)
        chatter, write_date = self.chatter(payment), line.write_date
        for _ in range(3):
            self.sync(payment)
        self.refresh(line)
        self.assertEqual(self.chatter(payment), chatter, 'bekleyen satır için chatter notu düşülmez')
        self.assertEqual(line.write_date, write_date, 'ham durum yalnız değişince yazılır')

    def test_kk7_durum_degisince_ham_durum_guncellenir(self):
        payment, line = self.pending_payment(2500.0, ref='R-W2')
        self.query(payment, rt('IP', 2500.0, 'R-W2'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.provider_status, 'IP')
        self.query(payment, rt('MR', 2500.0, 'R-W2'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual((line.state, line.provider_status), ('pending_approval', 'MR'))

    def test_kk7_taninmayan_kod_warning_loglar_kisisel_veri_yok(self):
        payment, line = self.pending_payment(2500.0, ref='R-W3')
        self.query(payment, rt('XY', 2500.0, 'R-W3', last4='9876'))
        with self.assertLogs('odoo.addons.sanal_pos', level='WARNING') as logs:
            self.sync(payment)
        joined = '\n'.join(logs.output)
        self.assertIn('tanınmayan', joined)
        self.assertIn('XY', joined)
        self.assertNotIn('9876', joined, 'kart verisi loglanmaz')
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval')

    def test_kk7_taninan_kodlar_uyari_uretmez(self):
        payment, _line = self.pending_payment(2500.0, ref='R-W4')
        self.query(payment, rt('IP', 2500.0, 'R-W4'))
        with self.capture_logs() as records:
            self.sync(payment)
        self.assertFalse([r for r in records if 'tanınmayan' in r], records)

    def test_kk8_bulunamadi_hicbir_sayi_ve_yasta_basarisiz_yapmaz(self):
        payment, line = self.pending_payment(2500.0, ref='R-N1')
        self.age(line, days=20)
        self.env.cr.execute(
            "UPDATE sanal_pos_refund SET not_found_count = 9 WHERE id = %s", [line.id])
        self.refresh(line)
        self.query(payment)          # iade işlemi hiç yok
        for _ in range(5):
            self.sync(payment)
        for _ in range(3):
            self.run_cron(CRON_SYNC)
        self.refresh(line, payment)
        self.assertEqual(line.state, 'pending_approval')
        self.assertFalse(line.error_code)
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(payment.refunded_amount, 0.0)
        self.assertEqual(len(self.lines(payment)), 1)

    def test_kk8_baska_tutarli_ap_iade_bekleyeni_etkilemez_panel_satiri_acilir(self):
        payment, line = self.pending_payment(2500.0, ref='R-N2')
        self.query(payment, rt('AP', 1000.0, 'R-PANEL'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval')
        panel = self.lines(payment, source='panel')
        self.assertEqual((panel.state, panel.amount, panel.provider_ref), ('done', 1000.0, 'R-PANEL'))
        self.assertEqual(payment.state, 'refund_pending', 'bekleyen varken durum refund_pending kalır')
        self.assertEqual(payment.refunded_amount, 1000.0)

    def test_kk8_sorgu_hatasi_satiri_degistirmez(self):
        payment, line = self.pending_payment(2500.0, ref='R-N3')
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        payment.sudo()._sync_status()
        self.refresh(line, payment)
        self.assertEqual(line.state, 'pending_approval')
        self.assertEqual(payment.state, 'refund_pending')


# ---------------------------------------------------------------------------------------
# KK-9: eşleştirme
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMatching(ApprovalCase):

    def test_kk9_ref_degismisse_tur_tutar_ile_bulunur_ref_yeniden_baglanir(self):
        payment, line = self.pending_payment(2500.0, ref='R-OLD')
        self.query(payment, rt('AP', 2500.0, 'R-NEW'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(len(self.lines(payment)), 1, 'aynı iade ikinci satır açmamalı')
        self.assertEqual((line.state, line.provider_ref), ('done', 'R-NEW'))
        self.assertEqual(payment.refunded_amount, 2500.0)
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk9_refsiz_satir_tek_aday_ile_baglanir_bekleyen_durumda_kalir(self):
        payment, line = self.pending_payment(2500.0, ref=None)
        self.assertFalse(line.provider_ref)
        self.query(payment, rt('IP', 2500.0, 'R-Q'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual((line.state, line.provider_ref, line.provider_status),
                         ('pending_approval', 'R-Q', 'IP'))
        self.assertEqual(len(self.lines(payment)), 1)
        # bundan sonra takip ref ile: AP -> done, aynı satır
        self.query(payment, rt('AP', 2500.0, 'R-Q'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual((line.state, line.provider_ref), ('done', 'R-Q'))
        self.assertEqual(len(self.lines(payment)), 1)

    def test_kk9_zaman_toleransi_5_dk_oncesi_aday_sayilir(self):
        payment, line = self.pending_payment(2500.0, ref=None)
        created = self.age(line, hours=1)
        self.query(payment, rt('AP', 2500.0, 'R-TOL', timeCreated=ms(created - timedelta(minutes=3))))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual((line.state, line.provider_ref), ('done', 'R-TOL'))

    def test_kk9_cok_eski_islem_aday_degil_panel_satiri_da_acilmaz(self):
        payment, line = self.pending_payment(2500.0, ref='R-OLD2')
        created = self.age(line, hours=1)
        old = created - timedelta(hours=3)
        self.query(payment, rt('AP', 2500.0, 'R-ANCIENT', timeCreated=ms(old)))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval', 'eşleşmeyen AP satırı done yapmaz')
        self.assertEqual(len(self.lines(payment)), 1,
                         'eşleşmemiş AP bekleyen satır varken panel satırı açılmaz')
        self.assertEqual(payment.refunded_amount, 0.0)

    def test_kk9_onceki_basarisiz_denemenin_fa_islemi_yeni_satiri_reddetmez(self):
        payment, line = self.pending_payment(2500.0, ref=None)
        created = self.age(line, hours=1)
        self.query(
            payment,
            rt('FA', 2500.0, 'R-OLD-FA', timeCreated=ms(created - timedelta(minutes=2))),
            rt('IP', 2500.0, 'R-NEW-IP', timeCreated=ms(created + timedelta(minutes=1))))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval', 'önceki denemenin FA işlemi bu satırı reddetmemeli')
        self.assertEqual(line.provider_ref, 'R-NEW-IP')
        self.assertEqual(line.provider_status, 'IP')
        self.assertEqual(payment.state, 'refund_pending')
        self.assertEqual(len(self.lines(payment)), 1)

    def test_kk9_belirsiz_eslesmede_bagalanmaz_bekler_warning_panel_satiri_yok(self):
        payment, line = self.pending_payment(2500.0, ref=None)
        created = self.age(line, hours=1)
        self.query(
            payment,
            rt('FA', 2500.0, 'R-AMB-A', timeCreated=ms(created + timedelta(minutes=1))),
            rt('IP', 2500.0, 'R-AMB-B', timeCreated=ms(created + timedelta(minutes=2))))
        with self.assertLogs('odoo.addons.sanal_pos', level='WARNING'):
            self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval', 'belirsizde kırmızı bayrak (red) verilmez')
        self.assertFalse(line.provider_ref, 'belirsizde ref bağlanmaz')
        self.assertEqual(len(self.lines(payment)), 1)
        self.assertEqual(payment.state, 'refund_pending')

    def test_kk9_iki_ap_aday_belirsiz_done_olmaz_panel_satiri_acilmaz(self):
        payment, line = self.pending_payment(2500.0, ref=None)
        created = self.age(line, hours=1)
        self.query(
            payment,
            rt('AP', 2500.0, 'R-AMB-1', timeCreated=ms(created + timedelta(minutes=1))),
            rt('AP', 2500.0, 'R-AMB-2', timeCreated=ms(created + timedelta(minutes=2))))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval')
        self.assertEqual(len(self.lines(payment)), 1)
        self.assertEqual(payment.refunded_amount, 0.0)

    def test_kk9_baska_satirin_refi_aday_olmaz(self):
        payment = self.paid()
        done = self.make_refund_line(payment, 2500.0, state='done', provider_ref='R-USED')
        payment._recompute_refund_state()
        self.query(payment, rt('AP', 2500.0, 'R-USED'))
        # ilk iade onaylı; ikinci (aynı tutar) iade istenir
        line = self.request_refund(payment, 2500.0, ref=None)
        self.sync(payment)
        self.refresh(line, done)
        self.assertEqual(line.state, 'pending_approval', 'R-USED başka satıra ait; bu satıra bağlanmaz')
        self.assertFalse(line.provider_ref)
        self.assertEqual(done.provider_ref, 'R-USED')


# ---------------------------------------------------------------------------------------
# KK-10: güvenlik ağı
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestSafetyNet(ApprovalCase):

    def rejected(self, ref='R-SN'):
        payment, line = self.pending_payment(2500.0, ref=ref)
        self.query(payment, rt('FA', 2500.0, ref))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'rejected')
        return payment, line

    def test_kk10_rejected_ref_sonradan_ap_olursa_done_ve_yoneticiye_uyari(self):
        manager2 = self._make_user('sp_manager2', ['sanal_pos.group_sanal_pos_manager'])
        payment, line = self.rejected()
        self.assertEqual(payment.state, 'paid')
        self.query(payment, rt('AP', 2500.0, 'R-SN'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'done')
        self.assertFalse(line.error_code or line.error_message, 'ret sebebi temizlenir')
        self.assertEqual(payment.state, 'partial_refund')
        self.assertEqual(payment.refunded_amount, 2500.0)
        self.assertEqual(len(self.lines(payment)), 1)
        self.assertIn('DİKKAT', self.chatter(payment))
        for user in (self.user_sp, self.user_mgr, manager2):    # oluşturan, iadeyi yapan, yönetici grubu
            with self.subTest(user=user.login):
                text = self.notified_text(payment, user)
                self.assertIn('DİKKAT', text)
                self.assertIn('ONAYLI', text)
        self.assertNotIn(self.user_sp2.partner_id, self.notified_partners(payment))

    def test_kk10_arada_yeniden_iade_yapildiysa_cift_iade_uyarisi_icerir(self):
        payment, line = self.rejected()
        new_line = self.request_refund(payment, 2500.0)          # kullanıcı yeniden iade etti
        self.query(payment, rt('AP', 2500.0, 'R-SN'))
        self.sync(payment)
        self.refresh(line, new_line)
        self.assertEqual(line.state, 'done')
        self.assertEqual(new_line.state, 'pending_approval', 'yeni satır eski AP ile onaylanmaz')
        self.assertIn('çift iade', self.chatter(payment))

    def test_kk10_gunluk_cron_paid_a_donen_kaydi_izlemeye_devam_eder(self):
        payment, line = self.rejected()
        self.query(payment, rt('AP', 2500.0, 'R-SN'))
        self.run_cron(CRON_DAILY)
        self.refresh(line, payment)
        self.assertEqual(line.state, 'done')
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk10_yeniden_iade_oncesi_zorunlu_senkron_yakalar(self):
        payment, line = self.rejected()
        self.query(payment, rt('AP', 2500.0, 'R-SN'))            # Paratika aslında onaylamış
        self.mock.calls.clear()
        _r, message = self.refund(payment, 6500.0, 'Kalan iade')
        self.refresh(line, payment)
        self.assertEqual(line.state, 'done', 'iade öncesi senkron güvenlik ağını çalıştırır')
        self.assertLess(self.mock.actions.index('QUERYTRANSACTION'), self.mock.actions.index('REFUND'))
        # 2500 onaylı sayıldığı için 9000'in tamamı yeniden iade edilemezdi; 6500 serbestti
        self.assertIsNone(message)

    def test_kk10_rejected_satir_baska_islemle_done_olmaz(self):
        payment, line = self.rejected(ref='R-SN2')
        self.query(payment, rt('AP', 2500.0, 'R-BASKA'))          # farklı ref: bu satırın işlemi değil
        self.sync(payment)
        self.refresh(line)
        self.assertEqual(line.state, 'rejected')


# ---------------------------------------------------------------------------------------
# KK-11: izleme (cron adayı, Durumu Sorgula, yeniden hesap)
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestMonitoring(ApprovalCase):

    def test_kk11_bekleyen_odeme_cron_adayi_tetiksiz_de_bulunur(self):
        payment, _line = self.pending_payment()
        self.env['ir.cron.trigger'].sudo().search([]).unlink()
        self.assertIn(payment.id, self.env[PAYMENT].sudo()._sync_candidate_ids(50))
        self.mock.calls.clear()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)

    def test_kk11_cron_her_turda_sorgular_tek_sorgu_kayit_basina(self):
        payment, line = self.pending_payment(ref='R-M1')
        self.query(payment, rt('IP', 2500.0, 'R-M1'))
        self.mock.calls.clear()
        self.run_cron(CRON_SYNC)
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.refresh(line)
        self.assertEqual(line.provider_status, 'IP')

    def test_kk11_durumu_sorgula_30_gunden_eski_refund_pending_kayitta_calisir(self):
        payment, line = self.pending_payment(ref='R-M2')
        self.set_create_date(payment, utcnow() - timedelta(days=40))
        self.query(payment, rt('AP', 2500.0, 'R-M2'))
        self.mock.calls.clear()
        payment.with_user(self.user_sp).action_check_status()        # UserError olmamalı
        self.assertEqual(self.mock.count('QUERYTRANSACTION'), 1)
        self.refresh(line, payment)
        self.assertEqual(line.state, 'done')
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk11_30_gun_siniri_diger_kapali_kayitlar_icin_surer(self):
        payment = self.paid()
        self.set_create_date(payment, utcnow() - timedelta(days=40))
        with self.assertRaises(UserError):
            payment.with_user(self.user_sp).action_check_status()

    def test_kk11_expected_state_kural_sirasi(self):
        payment = self.paid(amount=100.0)
        pending = self.make_refund_line(payment, 70.0, state='pending_approval', provider_ref='R-1')
        self.make_refund_line(payment, 30.0, state='done', provider_ref='R-2')
        self.make_refund_line(payment, 10.0, state='rejected', provider_ref='R-3')
        self.make_refund_line(payment, 10.0, state='failed', provider_ref='R-4')
        payment.invalidate_recordset()
        self.assertEqual(payment._expected_refund_state(), 'refund_pending')
        pending.sudo().write({'state': 'rejected'})
        self.assertEqual(payment._expected_refund_state(), 'partial_refund')
        self.make_refund_line(payment, 70.0, state='done', provider_ref='R-5')
        payment.invalidate_recordset()
        self.assertEqual(payment._expected_refund_state(), 'refunded')

    def test_kk11_expected_state_void_bekleyenden_once_gelir(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 100.0, kind='void', state='done', provider_ref='V-1')
        self.make_refund_line(payment, 10.0, state='pending_approval', provider_ref='R-1')
        payment.invalidate_recordset()
        self.assertEqual(payment._expected_refund_state(), 'voided')

    def test_kk11_expected_state_yazmaz_recompute_yazar(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 40.0, state='pending_approval', provider_ref='R-1')
        payment.invalidate_recordset()
        self.assertEqual(payment._expected_refund_state(), 'refund_pending')
        self.assertEqual(payment.state, 'paid', 'saf fonksiyon veri yazmaz')
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refund_pending')

    def test_kk11_recompute_refund_pending_den_ve_refunded_den_calisir(self):
        payment = self.paid(amount=100.0)
        line = self.make_refund_line(payment, 40.0, state='pending_approval', provider_ref='R-1')
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refund_pending')
        line.sudo().write({'state': 'rejected'})
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'paid', 'red sonrası refund_pending, paid e döner')
        done = self.make_refund_line(payment, 100.0, state='done', provider_ref='R-2')
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refunded')
        self.make_refund_line(payment, 0.01, state='pending_approval', provider_ref='R-3')
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refund_pending', 'refunded da artık son durum değil')
        self.assertEqual(done.state, 'done')

    def test_kk11_done_satiri_olmayan_refunded_kayit_degismez(self):
        payment = self.paid(amount=100.0)
        payment.sudo().write({'state': 'refunded'})        # eski/test verisi: satır yok
        self.assertEqual(payment._expected_refund_state(), 'refunded')
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refunded', 'sessizce paid e düşmemeli')

    def test_kk11_voided_ve_diger_durumlarda_yeniden_hesap_calismaz(self):
        voided = self.paid(amount=100.0, invoice_no='VD-1')
        voided.sudo().write({'state': 'voided'})
        voided._recompute_refund_state()
        self.assertEqual(voided.state, 'voided')
        self.assertEqual(voided._expected_refund_state(), 'voided')
        sent = self.make_payment(invoice_no='SENT-1')
        self.make_refund_line(sent, 10.0, state='pending_approval', provider_ref='R-1')
        sent._recompute_refund_state()
        self.assertEqual(sent.state, 'sent')

    def test_kk11_belirsiz_ve_isleniyor_satirlar_yeniden_hesabi_etkilemez(self):
        payment = self.paid(amount=100.0)
        self.make_refund_line(payment, 40.0, state='unknown', provider_ref=False)
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'paid')


# ---------------------------------------------------------------------------------------
# KK-13: belirsiz satır + bekleyen işlem -> pending_approval; bulunamadı sayacı
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestUnknownToPending(ApprovalCase):

    def unknown_refund(self, amount=2500.0, **vals):
        payment = self.paid(**vals)
        self.mock.queue('REFUND', timeout_exc())
        self.refund(payment, amount)
        line = self.lines(payment)
        self.assertEqual(line.state, 'unknown')
        return payment, line

    def test_kk13_unknown_ve_bekleyen_eslesme_pending_approval_olur(self):
        for status in ('IP', 'MR', 'XY'):
            with self.subTest(durum=status):
                payment, line = self.unknown_refund(invoice_no='UNK-%s' % status)
                self.age_line(line, 30)
                self.query(payment, rt(status, 2500.0, 'R-U-%s' % status))
                self.sync(payment)
                self.refresh(line)
                self.assertEqual(line.state, 'pending_approval')
                self.assertEqual(line.provider_ref, 'R-U-%s' % status)
                self.assertEqual(line.provider_status, status)
                self.assertEqual(line.not_found_count, 0)
                self.assertFalse(line.unknown_since)
                self.assertFalse(line.error_code or line.error_message)
                self.assertEqual(payment.state, 'refund_pending')
                self.assertIn('finans onayı bekliyor görünüyor', self.chatter(payment))
                self.assertEqual(len(self.lines(payment)), 1)

    def test_kk13_unknown_pending_olduktan_sonra_bulunamadi_ile_dusmez(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 30)
        self.query(payment, rt('IP', 2500.0, 'R-U1'))
        self.sync(payment)
        self.query(payment)                                  # sonra işlem listede görünmez
        for _ in range(4):
            self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual(line.state, 'pending_approval')

    def test_kk13_unknown_ve_onayli_eslesme_bugunku_gibi_done(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 30)
        self.query(payment, rt('AP', 2500.0, 'R-U2'))
        self.sync(payment)
        self.refresh(line)
        self.assertEqual((line.state, line.provider_ref), ('done', 'R-U2'))
        self.assertEqual(payment.state, 'partial_refund')

    def test_kk13_sorguda_terminal_olmayan_islem_varken_sayac_calismaz(self):
        # başka tutarlı bekleyen / tanınmayan / iptal türü işlemler de "bekleyen işlem var" sayılır
        cases = (('IP', 'REFUND', 1000.0), ('XY', 'REFUND', 1000.0), ('MR', 'VOID', 2500.0))
        for status, ttype, amount in cases:
            with self.subTest(durum=status, tur=ttype):
                payment, line = self.unknown_refund(invoice_no='CNT-%s-%s' % (status, ttype))
                self.age_line(line, 30)
                self.query(payment, tran(status, ttype, '%.2f' % amount, 'R-OTHER'))
                for _ in range(3):
                    self.run_cron(CRON_SYNC)
                self.refresh(line)
                self.assertEqual((line.state, line.not_found_count), ('unknown', 0),
                                 'bekleyen işlem varken bulunamadı sayacı çalışmamalı')
                self.assertEqual(len(self.lines(payment)), 1)

    def test_kk13_yalniz_terminal_islemler_varsa_sayac_bugunku_gibi_calisir(self):
        payment, line = self.unknown_refund()
        self.age_line(line, 30)
        self.query(payment, rt('FA', 1000.0, 'R-OTHER-FA'))      # terminal: bekleyen işlem sayılmaz
        for _ in range(3):
            self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual((line.state, line.error_code), ('failed', 'NOT_FOUND'))


# ---------------------------------------------------------------------------------------
# KK-12: 72 saat uyarısı
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestLongPendingAlert(ApprovalCase):
    TEXT = '72 saattir Paratika finans onayı bekliyor'

    def aged_pending(self, hours, ref='R-72'):
        """İadeyi YÖNETİCİ OLMAYAN (sp_user2) yapmış bekleyen satır; ``hours`` saat önce."""
        payment = self.paid()
        line = self.make_refund_line(payment, 2500.0, state='pending_approval',
                                     provider_ref=ref, user_id=self.user_sp2.id)
        payment._recompute_refund_state()
        self.assertEqual(payment.state, 'refund_pending')
        self.set_create_date(line, utcnow() - timedelta(hours=hours))
        self.query(payment, rt('IP', 2500.0, ref))
        return payment, line

    def alerts(self, payment):
        return self.messages_with(payment, self.TEXT)

    def recipients(self, payment):
        msgs = self.alerts(payment)
        return msgs.partner_ids | msgs.notification_ids.res_partner_id

    def test_kk12_73_saat_ilk_cron_tek_mesaj_bayrak_alicilar(self):
        manager2 = self._make_user('sp_manager2', ['sanal_pos.group_sanal_pos_manager'])
        payment, line = self.aged_pending(73)
        self.run_cron(CRON_SYNC)
        self.refresh(line, payment)
        self.assertEqual(len(self.alerts(payment)), 1)
        self.assertTrue(line.pending_alert_sent)
        self.assertEqual(line.state, 'pending_approval', 'uyarı satırı sonuçlandırmaz')
        text = self.chatter(payment)
        self.assertIn(self.TEXT, text)
        self.assertIn('Paratika panelinden kontrol edin', text)
        self.assertIn(INV_NO, text)
        partners = self.recipients(payment)
        for user in (self.user_mgr, manager2, self.user_sp2):       # yönetici grubu + iadeyi yapan
            with self.subTest(user=user.login):
                self.assertIn(user.partner_id, partners)
        self.assertNotIn(self.user_plain.partner_id, partners)

    def test_kk12_ikinci_cron_yeni_mesaj_uretmez(self):
        payment, line = self.aged_pending(73)
        self.run_cron(CRON_SYNC)
        self.run_cron(CRON_SYNC)
        self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual(len(self.alerts(payment)), 1)
        self.assertTrue(line.pending_alert_sent)

    def test_kk12_71_saatte_mesaj_yok(self):
        payment, line = self.aged_pending(71)
        self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual(len(self.alerts(payment)), 0)
        self.assertFalse(line.pending_alert_sent)

    def test_kk12_bayrak_zaten_aciksa_tekrar_gonderilmez(self):
        payment, line = self.aged_pending(100)
        line.sudo().write({'pending_alert_sent': True})
        self.run_cron(CRON_SYNC)
        self.assertEqual(len(self.alerts(payment)), 0)

    def test_kk12_sorgu_basarisiz_olsa_da_uyari_gider(self):
        payment, line = self.aged_pending(73)
        self.mock.queue('QUERYTRANSACTION', timeout_exc())
        self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual(len(self.alerts(payment)), 1)
        self.assertTrue(line.pending_alert_sent)
        self.assertEqual(line.state, 'pending_approval')

    def test_kk12_ayni_turda_onaylanan_satir_icin_uyari_yok(self):
        payment, line = self.aged_pending(73)
        self.query(payment, rt('AP', 2500.0, 'R-72'))
        self.run_cron(CRON_SYNC)
        self.refresh(line)
        self.assertEqual(line.state, 'done')
        self.assertEqual(len(self.alerts(payment)), 0)

    def test_kk12_uyari_rapor_edilen_tutar_ve_fatura_icerir(self):
        payment, _line = self.aged_pending(80)
        self.run_cron(CRON_SYNC)
        self.assertIn('2.500,00 TL', self.chatter(payment))


# ---------------------------------------------------------------------------------------
# KK-6/7 (sağlayıcı katmanı): normalize
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestProviderNormalize(ApprovalCase):

    def norm(self, item):
        return self.env[PROVIDER]._normalize_transaction(item)

    def test_kk6_err10153_refund_ve_void_icin_failed(self):
        for ttype, kind in (('REFUND', 'refund'), ('VOID', 'void')):
            for extra in ({'errorCode': 'ERR10153'}, {'pgTranErrorCode': 'ERR10153'},
                          {'pgTranReturnCode': 'ERR10153'}):
                with self.subTest(tur=ttype, ek=extra):
                    result = self.norm(tran('AP', ttype, '10.00', 'R-1', **extra))
                    self.assertEqual((result['kind'], result['status']), (kind, 'failed'))

    def test_kk6_err10153_satis_islemini_etkilemez(self):
        result = self.norm(tran('AP', 'SALE', '10.00', 'T-1', errorCode='ERR10153'))
        self.assertEqual((result['kind'], result['status']), ('sale', 'approved'))

    def test_kk6_yeni_anahtarlar(self):
        result = self.norm(tran('FA', 'REFUND', '10.00', 'R-1', errorCode='ERR10153',
                                errorMsg='denied', pgTranReturnCode='05'))
        self.assertEqual(result['return_code'], '05')
        self.assertEqual(result['error_code'], 'ERR10153')
        self.assertEqual(result['raw_message'], 'denied')
        self.assertIn('Finans ekibi tarafından reddedildi', result['error_message'])
        # mevcut anahtarlar korunur
        for key in ('ref', 'kind', 'status', 'amount', 'currency', 'time', 'installment_count',
                    'card_last4', 'raw_type', 'raw_status'):
            self.assertIn(key, result)
        self.assertEqual(result['raw_status'], 'FA')

    def test_kk6_alternatif_alan_adlari(self):
        result = self.norm(tran('FA', 'REFUND', '10.00', 'R-1', pgTranErrorCode='ERR55555',
                                pgTranErrorText='Limit asildi'))
        self.assertEqual(result['error_code'], 'ERR55555')
        self.assertEqual(result['raw_message'], 'Limit asildi')
        self.assertIn('Limit asildi', result['error_message'])

    def test_kk6_hata_yoksa_alanlar_none(self):
        result = self.norm(tran('AP', 'REFUND', '10.00', 'R-1'))
        for key in ('return_code', 'error_code', 'raw_message', 'error_message'):
            self.assertIsNone(result[key], key)
        self.assertEqual(result['status'], 'approved')

    def test_kk6_yeni_hata_kodlarinin_turkce_karsiligi_var(self):
        provider = self.env[PROVIDER]
        for code in ('ERR10153', 'ERR10038', 'ERR10106'):
            with self.subTest(kod=code):
                text = provider._error_message(code, 'raw')
                self.assertNotIn('raw', text, 'Türkçe karşılığı olmalı: %s' % code)
        module = importlib.import_module('odoo.addons.sanal_pos.models.provider_paratika')
        self.assertEqual(getattr(module, 'REFUND_REJECT_CODES', None), ('ERR10153',))

    def test_kk7_taninmayan_kod_kucuk_harfle_gecer_ve_warning(self):
        with self.assertLogs('odoo.addons.sanal_pos', level='WARNING') as logs:
            result = self.norm(tran('XY', 'REFUND', '10.00', 'R-9', last4='9876'))
        self.assertEqual((result['status'], result['raw_status']), ('xy', 'XY'))
        joined = '\n'.join(logs.output)
        self.assertIn('XY', joined)
        self.assertNotIn('9876', joined)

    def test_kk7_taninan_kodlar_warning_uretmez(self):
        with self.capture_logs() as records:
            for code in ('AP', 'FA', 'CA', 'IP', 'MR', 'VD'):
                self.norm(tran(code, 'REFUND', '10.00', 'R-1'))
        self.assertFalse([r for r in records if 'tanınmayan' in r], records)


# ---------------------------------------------------------------------------------------
# KK-17: K-6 deseni
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestK6Pattern(ApprovalCase):

    def test_kk17_commit_cagridan_once_ve_sonra(self):
        payment = self.paid()
        seen = []
        original = self.mock.probe

        def probe():
            data = original()
            self.env.cr.execute(
                "SELECT state FROM sanal_pos_refund WHERE payment_id = %s", [payment.id])
            data['refund_states'] = [r[0] for r in self.env.cr.fetchall()]
            seen.append(data)
            return data

        self.mock.probe = probe
        self.request_refund(payment, 2500.0)
        call = self.mock.last('REFUND')
        self.assertGreaterEqual(call.probe['commits'], 1, 'commit #1 REFUND çağrısından önce')
        self.assertEqual(call.probe['refund_states'], ['processing'], 'çağrı anında satır işleniyor')
        self.assertGreater(self.commit_count, call.probe['commits'], 'commit #2 sonuçtan sonra')

    def test_kk17_sonuc_dalinda_hata_olursa_raise_yok_satir_belirsiz(self):
        payment = self.paid()
        model = type(self.env[PAYMENT])
        from unittest.mock import patch
        with patch.object(model, '_notify_creator', side_effect=RuntimeError('bildirim patladı')):
            _result, message = self.refund(payment, 2500.0, 'Müşteri talebi')
        self.assertIsNone(message, 'dış çağrıdan sonra raise olmamalı')
        self.assertEqual(self.mock.count('REFUND'), 1)
        line = self.lines(payment)
        self.assertEqual((line.state, line.error_code), ('unknown', 'APPLY_ERROR'))

    def test_kk17_sync_refunds_kilit_almaz_commit_etmez(self):
        from unittest.mock import patch
        payment, line = self.pending_payment(ref='R-K1')
        provider = self.env[PROVIDER]
        transactions = [provider._normalize_transaction(item) for item in (
            tran('AP', 'SALE', '9000.00', 'T1'), rt('AP', 2500.0, 'R-K1'))]
        model = type(self.env[PAYMENT])
        commits = self.commit_count
        with patch.object(model, '_try_lock_nowait', side_effect=AssertionError('kilit alınmamalı')), \
                patch.object(model, '_try_lock_skip_locked', side_effect=AssertionError('kilit alınmamalı')):
            payment.sudo()._sync_refunds(transactions)
        self.assertEqual(self.commit_count, commits, '_sync_refunds commit etmemeli')
        self.refresh(line)
        self.assertEqual(line.state, 'done')

    def test_kk17_satira_yalniz_sudo_yazar(self):
        _payment, line = self.pending_payment(ref='R-K2')
        rejected = self.make_refund_line(_payment, 10.0, state='rejected', provider_ref='R-K3')
        for record in (line, rejected):
            for user in (self.user_mgr, self.user_sp):
                with self.subTest(satir=record.state, kullanici=user.login):
                    with self.assertRaises((UserError, AccessError)):
                        record.with_user(user).write({'state': 'done'})
                    with self.assertRaises((UserError, AccessError)):
                        record.with_user(user).write({'provider_status': 'AP'})
                    with self.assertRaises((UserError, AccessError)):
                        record.with_user(user).unlink()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'pending_approval')


# ---------------------------------------------------------------------------------------
# KK-18: teslim parçaları (manifest sürümü, kolonlar, etiketler)
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestDeliveryArtifacts(ApprovalCase):

    def test_kk18_manifest_surumu_artti(self):
        import ast
        with file_open('sanal_pos/__manifest__.py') as handle:
            manifest = ast.literal_eval(handle.read())
        self.assertEqual(manifest['version'], '19.0.1.2.0')

    def test_kk18_yeni_kolonlar_olusur(self):
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'sanal_pos_refund'")
        columns = {row[0] for row in self.env.cr.fetchall()}
        for name in ('provider_status', 'provider_status_detail', 'pending_alert_sent'):
            self.assertIn(name, columns)

    def test_kk18_alan_turleri_ve_etiketler(self):
        fields_ = self.env[REFUND]._fields
        self.assertEqual(fields_['provider_status'].type, 'char')
        self.assertEqual(fields_['provider_status_detail'].type, 'text')
        self.assertEqual(fields_['pending_alert_sent'].type, 'boolean')
        for name in ('provider_status', 'provider_status_detail', 'pending_alert_sent'):
            self.assertTrue(fields_[name].store, name)
        self.assertEqual(fields_['error_code'].string, 'Hata / Ret Kodu')
        self.assertEqual(fields_['error_message'].string, 'Hata / Ret Sebebi')
        labels = dict(fields_['state'].selection)
        self.assertEqual(labels['pending_approval'], 'Onay bekliyor')
        self.assertEqual(labels['rejected'], 'Reddedildi')

    def test_kk18_odeme_durumu_etiketi_ve_sirasi(self):
        selection = self.env[PAYMENT]._fields['state'].selection
        keys = [k for k, _l in selection]
        self.assertEqual(dict(selection)['refund_pending'], 'İade onay bekliyor')
        self.assertLess(keys.index('refund_pending'), keys.index('partial_refund'))

    def test_kk18_bekleyen_satir_yeni_alan_varsayilanlari(self):
        payment = self.paid()
        line = self.make_refund_line(payment, 10.0, state='pending_approval', provider_ref='R-1')
        self.assertFalse(line.pending_alert_sent)
        self.assertFalse(line.provider_status)
        self.assertFalse(line.provider_status_detail)


# ---------------------------------------------------------------------------------------
# KK-14: görünümler (renkler/bant elle de doğrulanır; burada arch içeriği)
# ---------------------------------------------------------------------------------------
@tagged('post_install', '-at_install', 'sanal_pos')
class TestApprovalViews(ApprovalCase):

    def arch(self, view_type, user=None):
        result = self.env[PAYMENT].with_user(user or self.user_sp).get_views([(False, view_type)])
        return etree.fromstring(result['views'][view_type]['arch'].encode('utf-8'))

    def test_kk14_liste_rozeti_refund_pending_uyari_renginde(self):
        root = self.arch('list')
        decorations = [f.get('decoration-warning') or '' for f in root.xpath("//field[@name='state']")]
        self.assertTrue(any('refund_pending' in d for d in decorations), decorations)

    def test_kk14_form_rozeti_ve_statusbar(self):
        root = self.arch('form')
        bars = root.xpath("//field[@name='state'][@widget='statusbar']")
        self.assertTrue(bars)
        visible = (bars[0].get('statusbar_visible') or '').split(',')
        self.assertEqual(visible[:3], ['sent', 'paid', 'refund_pending'])
        self.assertLess(visible.index('refund_pending'), visible.index('partial_refund'))
        self.assertIn('refunded', visible)

    def test_kk14_form_uyari_bandi_yalniz_refund_pending(self):
        root = self.arch('form')
        nodes = root.xpath("//*[text()[contains(., 'finans onayı bekliyor')]]")
        self.assertTrue(nodes, 'uyarı bandı metni yok')
        chain = [nodes[0]] + list(nodes[0].iterancestors())
        self.assertTrue(any('refund_pending' in (n.get('invisible') or '') for n in chain),
                        'bant yalnız refund_pending iken görünmeli')

    def test_kk14_arama_filtresi(self):
        root = self.arch('search')
        filters = root.xpath("//filter[@name='refund_pending']")
        self.assertTrue(filters, 'refund_pending filtresi yok')
        self.assertIn('refund_pending', filters[0].get('domain') or '')

    def test_kk14_iade_gecmisi_sutunlari(self):
        for user in (self.user_sp, self.user_mgr):
            with self.subTest(kullanici=user.login):
                root = self.arch('form', user)
                lst = root.xpath("//field[@name='refund_ids']//list")
                self.assertTrue(lst, 'iade geçmişi listesi yok')
                cols = {f.get('name'): f for f in lst[0].xpath('.//field')}
                state = cols['state']
                self.assertEqual(state.get('widget'), 'badge')
                self.assertIn('pending_approval', state.get('decoration-warning') or '')
                self.assertIn('rejected', state.get('decoration-danger') or '')
                self.assertIn('done', state.get('decoration-success') or '')
                self.assertNotEqual(cols['error_message'].get('optional'), 'hide',
                                    'ret sebebi varsayılan görünür olmalı')
                self.assertEqual(cols['provider_status'].get('optional'), 'show')
                self.assertEqual(cols['provider_status_detail'].get('optional'), 'hide')
                self.assertEqual(cols['pending_alert_sent'].get('optional'), 'hide')

    def test_kk14_menu_ve_gorunum_yuklenir_refund_pending_kaydinda(self):
        payment, _line = self.pending_payment()
        record = payment.with_user(self.user_sp)
        self.assertEqual(record.state, 'refund_pending')
        self.assertTrue(record.read(['state', 'refunded_amount', 'refundable_amount', 'refund_ids']))
        self.assertFalse(record.can_refund)

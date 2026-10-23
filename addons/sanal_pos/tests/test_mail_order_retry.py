# -*- coding: utf-8 -*-
"""A3-G3: Tekrar dene / Link eylemlerinin kardeş yolları ve eşikte açık oturumu kapatma (güvenlik eki).

Kabul testleri ``test_mail_order_result`` (TestRetryLinkRoutes/Actions) içindedir; burada sözleşmedeki
(sozlesme-A3-G3.md) ek yollar sınanır. assertRaises yerine try/except: savepoint geri alması yazımı
silerdi (DERSLER).
"""
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models import sanal_pos_payment as payment_module
from ..models.sanal_pos_payment import BUSY_MSG, MO_ACTION_STATE_MSG
from .common import CUSTOMER_NAME, INV_NO, SanalPosCase, tran
from .test_mail_order_result import LINK_PATH, ResultCase, ResultMixin, fail_tran, utc_ago

PAYMENT = 'sanal.pos.payment'
WIZARD = 'sanal.pos.payment.create.wizard'
CLOSED_NOTE = 'Mail order oturumu kapatıldı'


def fails(prefix, n=3):
    return [fail_tran('%s-%d' % (prefix, i), minutes_ago=30 - i * 5) for i in range(n)]


def user_error(func):
    try:
        func()
    except UserError as exc:
        return str(exc)
    return None


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLimitClose(ResultMixin, SanalPosCase):
    """Güvenlik eki: eşik dolunca faturanın açık mail order oturumu kilit altında Odoo'da kapanır."""

    def payment_class(self):
        return type(self.env[PAYMENT])

    def test_esik_dolunca_acik_oturum_kapanir_token_temizlenir(self):
        payment = self.make_mail_order()
        self.sync(payment, *fails('LC', 2))
        self.assertTrue(payment.provider_token, '2 başarısızlıkta oturum açık kalır')
        self.sync(payment, *fails('LC'))
        self.assertFalse(payment.provider_token, 'token silinir')
        self.assertLessEqual(payment.expires_at, fields.Datetime.now())
        self.assertEqual(payment.state, 'sent', 'durum kararı normal senkronda verilir')
        self.assertTrue(payment.sent_at, 'K-15 / link bekleme penceresi korunur')
        self.assertTrue(user_error(payment.with_user(self.user_sp)._check_card_page_open),
                        'kart sayfası açılamaz')
        self.assertEqual(self.count_messages(payment, CLOSED_NOTE), 1)
        self.sync(payment, *fails('LC'))
        self.assertEqual(payment.state, 'expired', 'sonraki senkron: süresi dolmuş, ödeme yok')
        self.assertEqual(self.count_messages(payment, CLOSED_NOTE), 1, 'not bir kez')
        self.assertEqual(set(self.mock.actions), {'QUERYTRANSACTION'}, 'kapatma Paratika çağırmaz')

    def test_esik_bekleyen_islem_varken_kayit_acik_kalir(self):
        payment = self.make_mail_order()
        pending = tran('IP', 'SALE', '9000.00', 'LP-IP')
        self.sync(payment, *fails('LP'), pending)
        self.assertFalse(payment.provider_token)
        self.sync(payment, *fails('LP'), pending)
        self.assertEqual(payment.state, 'sent', 'bekleyen işlemde Kapat ile aynı fail-closed kural')

    def test_esik_sonrasi_ayni_mpid_onayi_odendi_olur(self):
        payment = self.make_mail_order()
        self.sync(payment, *fails('LA'))
        self.sync(payment, *fails('LA'), tran('AP', 'SALE', '9000.00', 'LA-AP', last4='4358'))
        self.assertEqual(payment.state, 'paid', 'aynı MPID onayı incelemeye düşmez (KK-3.7)')

    def test_limit_kapatma_paratika_cagrisi_ve_commit_yok(self):
        payment = self.make_mail_order()
        for i in range(3):
            self.add_attempt(payment, ref='LN-%d' % i)
        commits = self.commit_count
        payment.sudo()._mail_order_limit_close(False)
        self.assertFalse(payment.provider_token)
        self.assertEqual(self.commit_count, commits, 'commit yok (çağıranın işlemi)')
        self.assertNoParatikaCalls()

    def test_esik_altinda_kayit_degismez(self):
        payment = self.make_mail_order()
        token = payment.provider_token
        for i in range(2):
            self.add_attempt(payment, ref='LU-%d' % i)
        payment.sudo()._mail_order_limit_close(True)
        self.assertEqual(payment.provider_token, token)

    def siblings(self):
        older = self.make_mail_order(attempt_no=1, state='expired', provider_token=False,
                                     sent_at=utc_ago(hours=3), expires_at=utc_ago(hours=2))
        current = self.make_mail_order(attempt_no=2)
        return older, current

    def test_kardes_acik_kayit_bayraklanir_kendi_senkronunda_kapanir(self):
        older, current = self.siblings()
        self.sync(older, *fails('KO'))
        self.reload(current)
        self.assertTrue(current.sync_requested, 'aynı faturanın açık kaydı bayraklanır')
        self.assertTrue(current.provider_token, 'kardeşe doğrudan yazılmaz')
        self.sync(current)
        self.assertFalse(current.provider_token, 'kendi senkronunda aynı kuralla kapanır')

    def test_kardes_kilitliyse_atlanir_tutan_kendini_kapatir(self):
        older, current = self.siblings()
        with patch.object(self.payment_class(), '_lock_for_provider_call', lambda this: False):
            self.sync(older, *fails('KL'))
        self.reload(current)
        self.assertFalse(current.sync_requested, 'kilitli kardeş atlanır (NOWAIT, bekleme yok)')
        self.sync(current)
        self.assertFalse(current.provider_token, 'kilidi tutan senkron kendini kapatır')

    def test_baska_fatura_etkilenmez(self):
        other = self.make_mail_order(invoice_no='LX-OTHER')
        payment = self.make_mail_order()
        self.sync(payment, *fails('LX'))
        self.assertTrue(self.reload(other).provider_token)
        self.assertFalse(other.sync_requested)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestRetryActionPaths(ResultMixin, SanalPosCase):

    def test_iki_sekme_retry_ikincisi_mesgul_cagri_yok(self):
        payment = self.make_mail_order()
        token = payment.provider_token
        with patch.object(type(self.env[PAYMENT]), '_lock_for_provider_call', lambda this: False):
            error = user_error(payment.with_user(self.user_sp).action_mail_order_retry)
        self.assertEqual(error, BUSY_MSG)
        self.assertNoParatikaCalls()
        self.assertEqual((self.reload(payment).state, payment.provider_token), ('sent', token))

    def test_retry_ve_link_kapali_durumlarda_userror(self):
        for state in ('paid', 'review', 'sending', 'voided'):
            payment = self.make_mail_order(invoice_no='RP-%s' % state, state=state)
            for method in ('action_mail_order_retry', 'action_mail_order_to_link'):
                with self.subTest(state=state, method=method):
                    error = user_error(getattr(payment.with_user(self.user_sp), method))
                    self.assertEqual(error, MO_ACTION_STATE_MSG)
        self.assertNoParatikaCalls()

    def test_token_yeniden_kullanilabilirse_dogrudan_kart_sayfasi(self):
        payment = self.make_mail_order()
        with patch.object(payment_module, 'MO_TOKEN_REUSABLE_AFTER_FAIL', True):
            action = payment.with_user(self.user_sp).action_mail_order_retry()
        self.assertEqual(action['url'], '/sanal_pos/mail_order/pay/%d' % payment.id)
        self.assertNoParatikaCalls()

    def test_retry_baska_kullanicinin_kaydinda_calisir(self):
        payment = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        action = payment.with_user(self.user_sp2).action_mail_order_retry()
        self.assertEqual(action.get('type'), 'ir.actions.act_url', 'sahiplik denetimi yok; grup yeterli')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestLinkWizardRedirect(ResultCase):
    """Tasarım §5.5 'HTTP rotasından sihirbaza geçiş': 303 adresi web istemcisinde açılır, kayıt okunur.

    Görsel (ön dolu form) doğrulaması Mod 2'de Playwright ile yapılır.
    """

    def test_link_yonlendirmesi_web_istemcisinde_acilir_sihirbaz_okunur(self):
        payment = self.make_mail_order(state='expired', sent_at=utc_ago(hours=2), expires_at=utc_ago(hours=1))
        response = self.post_action(LINK_PATH, payment.id)
        self.assertEqual(response.status_code, 303)
        location = response.headers['Location']
        wizard_id = int(location.rsplit('/', 1)[1])
        self.assertEqual(self.url_open(location, allow_redirects=False).status_code, 200)
        action = self.make_jsonrpc_request('/web/action/load', {
            'action_id': 'sanal_pos.action_sanal_pos_payment_create_wizard'})
        self.assertEqual(action['res_model'], WIZARD)
        rows = self.make_jsonrpc_request('/web/dataset/call_kw/%s/web_read' % WIZARD, {
            'model': WIZARD, 'method': 'web_read', 'args': [[wizard_id]],
            'kwargs': {'specification': {'invoice_no': {}, 'customer_name': {}, 'amount': {}}}})
        self.assertEqual((rows[0]['invoice_no'], rows[0]['customer_name'], rows[0]['amount']),
                         (INV_NO, CUSTOMER_NAME, 9000.0))

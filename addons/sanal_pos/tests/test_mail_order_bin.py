# -*- coding: utf-8 -*-
"""Mail Order kart sayfası Aşama 2 (BIN ile kart türüne göre taksit) birim/model kabul testleri.

Kaynak: .ekip/20261023-mo-kart-pro/01-gereksinimler.md (KK-2.x), 02-tasarim.md §4, K-19,
spike-bin-sonuc.md. Özellik yazılmadan önce yazıldı: tasarımdaki arayüz adları kullanılır
(``provider_paratika.query_bin`` / ``query_card_installments``, ``sanal.pos.payment._mail_order_bin_lookup``,
``provider._log_call(..., fk_nowait=True)``, ``BIN_TIMEOUT``).

Tüm değerler SAHTE ya da herkese açık test değeridir (BIN ``LEAK_BIN`` = Paratika test kartının ilk 8
hanesi). Gerçek spike verisi (banka/merchant) bu dosyada yoktur.

HTTP ucu (``POST /sanal_pos/mail_order/bin``), CSP ``connect-src`` ve D-4 anahtarı:
``test_mail_order_bin_http.py``.
"""
import re
import time
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.service.model import get_public_method
from odoo.tests import tagged

from .common import (
    LEAK_BIN, LEAK_PAN, RawResponse, SanalPosCase, err_body, ok_body, paymentsystems_body, qt_body,
    querybin_body, timeout_exc, tran,
)

PROVIDER = 'sanal.pos.provider.paratika'
PAYMENT = 'sanal.pos.payment'
BIN_KEYS = {'ok', 'timeout', 'error_code', 'card_type', 'bank_code', 'network', 'brand', 'country'}


class BinCase(SanalPosCase):

    def provider(self):
        return self.env[PROVIDER]

    def queue_bin(self, *responses):
        self.mock.queue('QUERYBIN', *responses)

    def queue_systems(self, *responses):
        self.mock.queue('QUERYPAYMENTSYSTEMS', *responses)

    def logs(self, action=None):
        domain = [('action', '=', action)] if action else []
        return self.env['sanal.pos.log'].sudo().search(domain, order='id')

    def db_text_everywhere(self):
        """BIN'in düşebileceği tüm kalıcı yerlerin metni (KK-2.9): log, chatter/mesaj, ödeme metin sütunları."""
        parts = [self.all_log_text()]
        self.env.cr.execute("SELECT COALESCE(body, ''), COALESCE(subject, '') FROM mail_message")
        parts += ['%s %s' % row for row in self.env.cr.fetchall()]
        self.env.cr.execute("""SELECT column_name FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name = 'sanal_pos_payment'
                                  AND data_type IN ('text', 'character varying', 'jsonb')""")
        columns = [r[0] for r in self.env.cr.fetchall()]
        if columns:
            self.env.cr.execute('SELECT %s FROM sanal_pos_payment' % ', '.join('"%s"::text' % c for c in columns))
            for row in self.env.cr.fetchall():
                parts += [str(v) for v in row if v]
        return '\n'.join(parts)


# ======================================================================================
# provider_paratika.query_bin  (KK-2.1, KK-2.4, KK-2.9)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestQueryBin(BinCase):

    def test_kredi_karti_normalizasyonu(self):
        self.queue_bin(querybin_body('CREDIT', 'AKBANK', 'AXESS', 'VISA', 'TUR'))
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertTrue(res['ok'])
        self.assertFalse(res.get('timeout'))
        self.assertEqual(res['card_type'], 'credit')
        self.assertEqual(res['bank_code'], 'AKBANK')
        self.assertEqual(res['network'], 'AXESS')
        self.assertEqual(res['brand'], 'VISA')
        self.assertEqual(res['country'], 'TUR')

    def test_dondurulen_anahtarlar_bin_ve_serbest_metin_icermez(self):
        self.queue_bin(querybin_body())
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertLessEqual(BIN_KEYS, set(res))
        for forbidden in ('bin', 'data', 'issuer', 'cardName', 'card_name', 'raw'):
            self.assertNotIn(forbidden, res)
        self.assertNotIn(LEAK_BIN, repr(res), 'ham BIN dönüşe girmez (yalnız çağıran bilir)')
        self.assertNotIn('TEST BANKASI', repr(res), 'issuer/cardName serbest metni kullanılmaz')

    def test_kart_turu_eslemesi(self):
        cases = (('CREDIT', 'credit'), ('DEBIT', 'debit'), ('PREPAID', 'prepaid'),
                 ('', 'unknown'), ('CHARGE', 'unknown'), ('???', 'unknown'))
        for index, (raw, expected) in enumerate(cases):
            with self.subTest(cardType=raw):
                self.queue_bin(querybin_body(raw))
                payment = self.make_mail_order(invoice_no='QB-%d' % index, merchant_payment_id='QB-%d-1' % index)
                res = self.provider().query_bin(payment, LEAK_BIN)
                self.assertEqual(res['card_type'], expected)

    def test_kart_turu_alani_hic_yoksa_unknown(self):
        body = querybin_body()
        del body['bin']['cardType']
        self.queue_bin(body)
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertEqual(res['card_type'], 'unknown')

    def test_ulke_bos_ve_yabanci(self):
        for index, country in enumerate(('', 'USA', 'DEU')):
            with self.subTest(ulke=country):
                self.queue_bin(querybin_body(country=country))
                payment = self.make_mail_order(invoice_no='QC-%d' % index, merchant_payment_id='QC-%d-1' % index)
                self.assertEqual(self.provider().query_bin(payment, LEAK_BIN)['country'], country)

    def test_hesap_kartinda_program_dolu_gelir_ama_tur_debit(self):
        """Spike G: DEBIT kartta da ``cardNetwork`` dolu; kural türe bağlı, programa değil (K-19)."""
        self.queue_bin(querybin_body('DEBIT', 'AKBANK', 'AXESS', 'MC'))
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertEqual(res['card_type'], 'debit')
        self.assertEqual(res['network'], 'AXESS')

    def test_istek_biçimi_action_bin_zaman_asimi_kart_alani_yok(self):
        self.queue_bin(querybin_body())
        self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        call = self.mock.last('QUERYBIN')
        self.assertEqual(self.mock.actions, ['QUERYBIN'])
        self.assertEqual(call.params.get('BIN'), LEAK_BIN)
        self.assertEqual(call.params.get('ACTION'), 'QUERYBIN')
        self.assertEqual(tuple(call.timeout), (1.5, 2.0), 'BIN_TIMEOUT=(1.5, 2.0) (NFR-2.1)')
        for key in call.params:
            self.assertFalse(key.upper().startswith('CARD') or key.upper() in ('PAN', 'CVV'), key)
        self.assertNotIn(LEAK_PAN, call.body_text)

    def test_hata_bicimleri_ok_false_istisna_firlatmaz(self):
        cases = {
            'timeout': timeout_exc(),
            'http_500': RawResponse(500, 'sunucu hatasi'),
            'api_hatasi': err_body('ERR10010', 'hata'),
            'json_degil': RawResponse(200, 'tamam degil', 'text/plain'),
        }
        for index, (name, response) in enumerate(cases.items()):
            with self.subTest(durum=name):
                self.queue_bin(response)
                payment = self.make_mail_order(invoice_no='QE-%d' % index, merchant_payment_id='QE-%d-1' % index)
                res = self.provider().query_bin(payment, LEAK_BIN)
                self.assertFalse(res['ok'])
                self.assertEqual(res['card_type'], 'unknown')
                self.assertNotIn(LEAK_BIN, repr(res))

    def test_zaman_asimi_isaretlenir(self):
        self.queue_bin(timeout_exc())
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])

    def test_bin_nesnesi_yoksa_basarili_sayilmaz(self):
        self.queue_bin(ok_body())
        res = self.provider().query_bin(self.make_mail_order(), LEAK_BIN)
        self.assertFalse(res['ok'] and res['card_type'] != 'unknown',
                         '"bin" nesnesi olmayan yanıt kart türü üretemez')

    def test_yetkisiz_kullanici_rpc_ile_cagiramaz(self):
        provider = self.env(user=self.user_mgr)[PROVIDER]
        for name in ('query_bin', 'query_card_installments'):
            with self.subTest(yontem=name):
                with self.assertRaises(AccessError):
                    get_public_method(provider, name)

    def test_binsiz_query_installments_degismez(self):
        """A2 BIN'siz sayfa açılışı listesini (QUERYINSTALLMENT) değiştirmez: BIN gönderilmez."""
        self.provider().query_installments(self.make_mail_order())
        self.assertEqual(self.mock.actions, ['QUERYINSTALLMENT'])
        self.assertNotIn('BIN', self.mock.last('QUERYINSTALLMENT').params)
        self.assertEqual(tuple(self.mock.last('QUERYINSTALLMENT').timeout), (10, 30))


# ======================================================================================
# provider_paratika.query_card_installments (QUERYPAYMENTSYSTEMS)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestQueryCardInstallments(BinCase):

    def test_programin_taksitleri_ayrisir(self):
        self.queue_systems(paymentsystems_body([(2, 0), (3, 1.5), (6, 3.0), (9, 4.5), (12, 6)]))
        res = self.provider().query_card_installments(self.make_mail_order(), LEAK_BIN)
        self.assertTrue(res['ok'])
        self.assertEqual([o['count'] for o in res['options']], [2, 3, 6, 9, 12])
        self.assertTrue(all(isinstance(o['count'], int) for o in res['options']))
        by_count = {o['count']: o for o in res['options']}
        self.assertEqual(by_count[3]['rate'], 1.5)
        self.assertEqual(by_count[12]['rate'], 6.0)
        self.assertEqual(by_count[2]['rate'], 0.0)
        for option in res['options']:
            self.assertEqual(option['networks'], [], 'program ağ listesi satırda gösterilmez (detected satırı)')

    def test_istek_biçimi(self):
        self.queue_systems(paymentsystems_body([(2, 0)]))
        self.provider().query_card_installments(self.make_mail_order(), LEAK_BIN)
        call = self.mock.last('QUERYPAYMENTSYSTEMS')
        self.assertEqual(self.mock.actions, ['QUERYPAYMENTSYSTEMS'])
        self.assertEqual(call.params.get('BIN'), LEAK_BIN)
        self.assertEqual(tuple(call.timeout), (1.5, 2.0))
        self.assertNotIn('QUERYINSTALLMENT', self.mock.actions, 'BIN yolunda QUERYINSTALLMENT kullanılmaz (Q1)')

    def test_not_on_us_ve_bir_taksit_atlanir(self):
        self.queue_systems(paymentsystems_body(
            [(2, 0), ('NOT_ON_US', 0), (1, 0), (3, 1.5), ('abc', 0)]))
        res = self.provider().query_card_installments(self.make_mail_order(), LEAK_BIN)
        self.assertEqual([o['count'] for o in res['options']], [2, 3])

    def test_tek_cekim_pos_listesi_okunmaz(self):
        """``oneShotPaymentSystem`` (tek çekimin gideceği POS) taksit kaynağı değildir."""
        body = paymentsystems_body([(3, 1.5)])
        body['oneShotPaymentSystem']['installmentList'] = [{'count': '12', 'customerCostCommissionRate': 9}]
        self.queue_systems(body)
        res = self.provider().query_card_installments(self.make_mail_order(), LEAK_BIN)
        self.assertEqual([o['count'] for o in res['options']], [3])

    def test_liste_bos_ya_da_sistem_yok_ok_true_options_bos(self):
        variants = {
            'bos_liste': paymentsystems_body([]),
            'yalniz_not_on_us': paymentsystems_body([('NOT_ON_US', 0)]),
            'installmentPaymentSystem_yok': paymentsystems_body(installment_system=False),
        }
        for index, (name, body) in enumerate(variants.items()):
            with self.subTest(durum=name):
                self.queue_systems(body)
                payment = self.make_mail_order(invoice_no='QP-%d' % index, merchant_payment_id='QP-%d-1' % index)
                res = self.provider().query_card_installments(payment, LEAK_BIN)
                self.assertTrue(res['ok'], 'taksitsiz program hata değildir (KK-2.4)')
                self.assertEqual(res['options'], [])

    def test_hata_bicimleri_ok_false(self):
        for index, response in enumerate((timeout_exc(), RawResponse(500, 'x'), err_body('ERR1', 'x'),
                                          RawResponse(200, 'anlasilmaz', 'text/plain'))):
            with self.subTest(yanit=type(response).__name__ + str(index)):
                self.queue_systems(response)
                payment = self.make_mail_order(invoice_no='QS-%d' % index, merchant_payment_id='QS-%d-1' % index)
                res = self.provider().query_card_installments(payment, LEAK_BIN)
                self.assertFalse(res['ok'])
                self.assertEqual(res['options'], [])
        self.assertEqual(self.mock.actions.count('QUERYPAYMENTSYSTEMS'), 4)

    def test_zaman_asimi_isaretlenir(self):
        self.queue_systems(timeout_exc())
        res = self.provider().query_card_installments(self.make_mail_order(), LEAK_BIN)
        self.assertFalse(res['ok'])
        self.assertTrue(res['timeout'])


# ======================================================================================
# KK-2.9: BIN hiçbir kalıcı yere / loga / sohbete yazılmaz
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinNotStored(BinCase):

    def _run_both(self, payment=None):
        payment = payment or self.make_mail_order()
        self.queue_bin(querybin_body())
        self.queue_systems(paymentsystems_body([(2, 0), (3, 1.5)]))
        self.provider().query_bin(payment, LEAK_BIN)
        self.provider().query_card_installments(payment, LEAK_BIN)
        return payment

    def test_log_kayitlari_bin_icermez_istek_ve_yanit(self):
        payment = self._run_both()
        text = self.all_log_text()
        self.assertNotIn(LEAK_BIN, text)
        rows = self.logs('QUERYBIN')
        self.assertEqual(len(rows), 1, 'QUERYBIN çağrısı kaydedilir (hız sınırı sayacı)')
        self.assertIn('BIN', rows.request_body, 'parametre adı kayıtta var, değeri yok')
        self.assertIn('***', rows.request_body)
        self.assertTrue(rows.success)
        # Ö-3/KK-2.8: satır ödemeye FK ile bağlanmaz; ödeme yalnız request_body işaretiyle izlenir
        self.assertFalse(rows.payment_id, 'BIN log satırı payment_id=False yazılır (FK/FOR KEY SHARE yok)')
        self.assertTrue(rows.request_body.endswith('"_payment_id": %d}' % payment.id), rows.request_body)

    def test_querybin_yanitindaki_bin_yankisi_ve_kart_adi_maskelenir(self):
        self._run_both()
        body = self.logs('QUERYBIN').response_body
        self.assertNotIn(LEAK_BIN, body)
        self.assertNotIn('TEST BANKASI A.S. KART', body, 'cardName maskelenir (spike Q6)')

    def test_json_olmayan_ham_yanitta_bin_scrub_ile_silinir(self):
        payment = self.make_mail_order()
        self.queue_bin(RawResponse(200, 'Hata: bilinmeyen kart %s' % LEAK_BIN, 'text/plain'))
        self.queue_systems(RawResponse(502, '<html>%s gecersiz</html>' % LEAK_BIN))
        self.provider().query_bin(payment, LEAK_BIN)
        self.provider().query_card_installments(payment, LEAK_BIN)
        self.assertNotIn(LEAK_BIN, self.db_text_everywhere())

    def test_api_hata_mesaji_bin_yankilarsa_silinir(self):
        payment = self.make_mail_order()
        self.queue_bin(err_body('ERR10010', 'BIN %s bulunamadi' % LEAK_BIN))
        res = self.provider().query_bin(payment, LEAK_BIN)
        self.assertNotIn(LEAK_BIN, repr(res))
        self.assertNotIn(LEAK_BIN, self.db_text_everywhere())

    def test_hicbir_kalici_yerde_bin_yok_sohbet_odeme_log(self):
        payment = self._run_both()
        self.assertNotIn(LEAK_BIN, self.chatter(payment))
        self.assertNotIn(LEAK_BIN, self.db_text_everywhere())

    def test_uygulama_logger_ciktisinda_bin_yok(self):
        payment = self.make_mail_order()
        self.queue_bin(querybin_body(), RawResponse(200, 'x %s' % LEAK_BIN), timeout_exc())
        self.queue_systems(paymentsystems_body([(2, 0)]), RawResponse(500, LEAK_BIN))
        with self.capture_logs() as records:
            self.provider().query_bin(payment, LEAK_BIN)
            self.provider().query_card_installments(payment, LEAK_BIN)
            self.provider().query_bin(payment, LEAK_BIN)
            self.provider().query_card_installments(payment, LEAK_BIN)
            self.provider().query_bin(payment, LEAK_BIN)
        self.assertNotIn(LEAK_BIN, '\n'.join(records))

    def test_querytransaction_bin_alani_okunmaz_ve_loga_dusmez(self):
        """KK-2.9: QUERYTRANSACTION satırındaki ``bin`` alanı ``_normalize_transaction`` tarafından okunmaz."""
        payment = self.make_paid(self.make_payment(invoice_no='BIN-QT'), tran_ref='BQ1')
        self.mock.default('QUERYTRANSACTION', lambda p: qt_body(tran(ref='BQ1', **{'bin': LEAK_BIN})))
        result = self.provider().query_status(payment)
        self.assertNotIn(LEAK_BIN, repr(result))
        self.assertNotIn(LEAK_BIN, self.db_text_everywhere())

    def test_model_ve_sutunlarda_bin_alani_yok(self):
        bin_name = re.compile(r'(^|_)bin(_|$)', re.I)
        offenders = []
        for name, model in self.env.registry.items():
            if name.startswith('sanal.pos.'):
                offenders += ['%s.%s' % (name, f) for f in model._fields if bin_name.search(f)]
        self.assertEqual(offenders, [], 'BIN için model/sihirbaz alanı olmaz (K-13 daraltılmış istisnası: yalnız aktarım)')
        self.env.cr.execute("""SELECT table_name, column_name FROM information_schema.columns
                                WHERE table_schema = 'public' AND table_name LIKE 'sanal_pos_%'""")
        self.assertEqual(['%s.%s' % r for r in self.env.cr.fetchall() if bin_name.search(r[1])], [])


# ======================================================================================
# sanal.pos.log: kilit almama (KK-2.8) — fk_nowait
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestLogFkNowait(BinCase):

    def test_log_call_fk_nowait_imzasi_ve_varsayilan_davranis(self):
        import inspect
        params = inspect.signature(type(self.provider())._log_call).parameters
        self.assertIn('fk_nowait', params)
        self.assertIs(params['fk_nowait'].default, False, 'varsayılan davranış (diğer çağrılar) değişmez')

    def test_fk_nowait_true_kilit_yokken_kaydi_odemeye_baglar(self):
        payment = self.make_mail_order()
        self.queue_bin(querybin_body())
        self.provider().query_bin(payment, LEAK_BIN)
        row = self.logs('QUERYBIN')
        self.assertEqual(len(row), 1)
        self.assertFalse(row.payment_id, 'kilit olsun olmasın satır ödemeye FK ile bağlanmaz (KK-2.8)')
        self.assertTrue(row.request_body.endswith('"_payment_id": %d}' % payment.id), row.request_body)
        self.assertNotIn(LEAK_BIN, (row.request_body or '') + (row.response_body or ''))

    def test_lock_timeout_savepoint_icinde_set_local_ve_eski_deger_geri_gelir(self):
        """``SET LOCAL lock_timeout`` yalnız savepoint içindedir; çağrıdan sonra oturum değeri bozulmaz."""
        self.env.cr.execute('SHOW lock_timeout')
        before = self.env.cr.fetchone()[0]
        payment = self.make_mail_order()
        self.queue_bin(querybin_body())
        self.provider().query_bin(payment, LEAK_BIN)
        self.env.cr.execute('SHOW lock_timeout')
        self.assertEqual(self.env.cr.fetchone()[0], before)

    def test_lock_not_available_ise_payment_id_olmadan_yeniden_yazilir(self):
        """Kilit durumunu taklit eder: ilk create LockNotAvailable atar; satır ``payment_id=False`` ile yazılır.
        Gerçek ikinci bağlantıyla kilit senaryosu HTTP dosyasında (``TestBinEndpointLock``)."""
        from psycopg2 import errors
        payment = self.make_mail_order()
        self.queue_bin(querybin_body())
        Log = type(self.env['sanal.pos.log'])
        original = Log.create
        state = {'calls': 0}

        def create(this, vals_list):
            items = vals_list if isinstance(vals_list, list) else [vals_list]
            if any(v.get('action') == 'QUERYBIN' and v.get('payment_id') for v in items) and not state['calls']:
                state['calls'] += 1
                raise errors.LockNotAvailable('canceling statement due to lock timeout')
            return original(this, vals_list)

        with patch.object(Log, 'create', create):
            res = self.provider().query_bin(payment, LEAK_BIN)
        self.assertTrue(res['ok'], 'kilit nedeniyle sorgu başarısız olmaz')
        rows = self.logs('QUERYBIN')
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.payment_id, 'kilit alınamazsa satır payment_id olmadan yazılır')
        self.assertNotIn(LEAK_BIN, rows.request_body + (rows.response_body or ''))


# ======================================================================================
# sanal.pos.payment._mail_order_bin_lookup
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinLookupModel(BinCase):

    def lookup(self, payment, user=None, bin_digits=LEAK_BIN):
        return payment.with_user(user or self.user_sp)._mail_order_bin_lookup(bin_digits)

    def test_kredi_karti_sonucu(self):
        self.queue_bin(querybin_body('CREDIT', 'AKBANK', 'AXESS'))
        self.queue_systems(paymentsystems_body([(2, 0), (3, 1.5)]))
        res = self.lookup(self.make_mail_order())
        self.assertEqual(res['status'], 200)
        self.assertEqual(self.mock.actions, ['QUERYBIN', 'QUERYPAYMENTSYSTEMS'])

    def test_banka_karti_tek_paratika_cagrisi(self):
        self.queue_bin(querybin_body('DEBIT'))
        res = self.lookup(self.make_mail_order())
        self.assertEqual(res['status'], 200)
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

    def test_yetkisiz_access_error_paratika_yok(self):
        payment = self.make_mail_order()
        with self.assertRaises(AccessError):
            self.lookup(payment, self.user_plain)
        self.assertNoParatikaCalls()

    def test_kayit_yok_missing_error(self):
        payment = self.make_mail_order()
        ghost = self.env[PAYMENT].browse(payment.id + 987654)
        with self.assertRaises(MissingError):
            ghost.with_user(self.user_sp)._mail_order_bin_lookup(LEAK_BIN)
        self.assertNoParatikaCalls()

    def test_kapali_kayit_user_error_paratika_yok(self):
        for index, vals in enumerate(({'state': 'expired'}, {'state': 'paid'},
                                      {'expires_at': fields.Datetime.now() - timedelta(minutes=1)})):
            with self.subTest(durum=vals):
                payment = self.make_mail_order(invoice_no='BL-%d' % index, **vals)
                with self.assertRaises(UserError):
                    self.lookup(payment)
        self.assertNoParatikaCalls()

    def test_link_kaydi_kart_sayfasi_degil_user_error(self):
        payment = self.make_payment(invoice_no='BL-LINK')
        with self.assertRaises(UserError):
            self.lookup(payment)
        self.assertNoParatikaCalls()

    def test_kayda_yazmaz_state_ve_sohbet_degismez(self):
        payment = self.make_mail_order()
        self.env.cr.execute('SELECT * FROM sanal_pos_payment WHERE id = %s', [payment.id])
        before = self.env.cr.fetchone()
        messages = self.env['mail.message'].sudo().search_count([('model', '=', PAYMENT), ('res_id', '=', payment.id)])
        self.queue_bin(querybin_body('CREDIT'))
        self.queue_systems(paymentsystems_body([(2, 0)]))
        self.lookup(payment)
        self.env.cr.execute('SELECT * FROM sanal_pos_payment WHERE id = %s', [payment.id])
        self.assertEqual(self.env.cr.fetchone(), before, 'ödeme satırı hiç değişmez (write yok)')
        self.assertEqual(self.env['mail.message'].sudo().search_count(
            [('model', '=', PAYMENT), ('res_id', '=', payment.id)]), messages, 'chatter mesajı yok')

    def test_odeme_satiri_kilitlenmez_for_update_yok(self):
        """Statik: arama yolu SQL'inde ``FOR UPDATE`` / ``FOR NO KEY UPDATE`` yoktur."""
        statements = []
        original = type(self.env.cr).execute

        def spy(cr, query, *args, **kwargs):
            statements.append(str(query))
            return original(cr, query, *args, **kwargs)

        payment = self.make_mail_order()
        self.queue_bin(querybin_body('CREDIT'))
        self.queue_systems(paymentsystems_body([(2, 0)]))
        with patch.object(type(self.env.cr), 'execute', spy):
            self.lookup(payment)
        offenders = [s for s in statements if re.search(r'\bFOR\s+(NO\s+KEY\s+)?UPDATE\b', s, re.I)]
        self.assertEqual(offenders, [], 'KK-2.8: uç ödeme satırını kilitlemez')

    def test_kural_tablosu(self):
        cases = [
            # (QUERYBIN yanıtı, QUERYPAYMENTSYSTEMS yanıtı|None, beklenen status, installments)
            (querybin_body('CREDIT', country='TUR'), paymentsystems_body([(2, 0), (6, 3.0)]), 200, True),
            (querybin_body('CREDIT', country=''), paymentsystems_body([(2, 0)]), 200, True),
            (querybin_body('DEBIT'), None, 200, False),
            (querybin_body('PREPAID'), None, 200, False),
            (querybin_body('CREDIT', country='USA'), None, 200, False),
            (querybin_body('CREDIT', country='TUR'), paymentsystems_body([]), 200, False),
            (querybin_body('CHARGE'), None, 502, None),
            (err_body('ERR1', 'x'), None, 502, None),
        ]
        for index, (qbin, qps, status, installments) in enumerate(cases):
            with self.subTest(vaka=index):
                payment = self.make_mail_order(invoice_no='KT-%d' % index, merchant_payment_id='KT-%d-1' % index)
                before = len(self.mock.calls)
                self.queue_bin(qbin)
                if qps is not None:
                    self.queue_systems(qps)
                res = self.lookup(payment)
                self.assertEqual(res['status'], status)
                if status == 200:
                    self.assertIs(res['installments'], installments, 'installments bayrağı kural tablosuna uyar')
                else:
                    self.assertNotIn('installments', res)
                expected_calls = 2 if qps is not None else 1
                self.assertEqual(len(self.mock.calls) - before, expected_calls, self.mock.actions[before:])

    def test_yavas_ilk_cagri_ikinci_cagri_yapilmaz(self):
        offset = [0.0]
        real = time.monotonic

        def slow_bin(params):
            offset[0] += 1.2
            return querybin_body('CREDIT')

        self.queue_bin(slow_bin)
        with patch('time.monotonic', lambda: real() + offset[0]):
            res = self.lookup(self.make_mail_order())
        self.assertEqual(res['status'], 502)
        self.assertEqual(self.mock.actions, ['QUERYBIN'], 'ilk çağrı >1,0 sn: ikinci çağrı yok (NFR-2.1 bütçesi)')

    def test_hizli_ilk_cagri_ikinci_cagri_yapilir(self):
        offset = [0.0]
        real = time.monotonic

        def quick_bin(params):
            offset[0] += 0.3
            return querybin_body('CREDIT')

        self.queue_bin(quick_bin)
        self.queue_systems(paymentsystems_body([(2, 0)]))
        with patch('time.monotonic', lambda: real() + offset[0]):
            res = self.lookup(self.make_mail_order())
        self.assertEqual(res['status'], 200)
        self.assertEqual(self.mock.actions, ['QUERYBIN', 'QUERYPAYMENTSYSTEMS'])

    def test_kapali_anahtar_degil_model_yolu_sayac_duzenlemez(self):
        """Model yolu yalnız arama yapar; ödeme/iade/sync kuyruğu ya da cron tetiklenmez."""
        before = self.cron_trigger_count()
        self.queue_bin(querybin_body('DEBIT'))
        self.lookup(self.make_mail_order())
        self.assertEqual(self.cron_trigger_count(), before)

    def test_yabanci_kredi_kartinda_program_yazilmaz(self):
        """Ö-8 / §4.1: yabancı kredi kartı "Banka · Tür · Yurt dışı"; taksit programı geçmez."""
        self.queue_bin(querybin_body('CREDIT', 'AKBANK', 'AXESS', 'VISA', 'USA'))
        res = self.lookup(self.make_mail_order())
        self.assertEqual(res['detected'], 'Akbank · Kredi kartı · Yurt dışı')
        self.assertEqual(res['program'], '')
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

    def test_yurt_ici_kredi_kartinda_program_yazilir(self):
        """Olumlu çapa: yurt içi kredi kartında program kalır (R7 yalnız yabancı kartı değiştirir)."""
        self.queue_bin(querybin_body('CREDIT', 'AKBANK', 'AXESS', 'VISA', 'TUR'))
        self.queue_systems(paymentsystems_body([(2, 0)]))
        res = self.lookup(self.make_mail_order())
        self.assertEqual(res['detected'], 'Akbank · Axess · Kredi kartı')

    def test_kisa_pan_onekleri_model_yolunda_reddedilir(self):
        payment = self.make_mail_order()
        for value in ('36000000', '30012345', '38000000', '39000000', '34000000'):
            with self.subTest(bin=value):
                with self.assertRaises(ValueError):
                    self.lookup(payment, bin_digits=value)
        self.assertNoParatikaCalls()
        self.assertFalse(self.logs('QUERYBIN'))


# ======================================================================================
# Düzeltme turu #1: FK bağı yok (Ö-3/KK-2.8) ve BIN adres izin listesi (G2-3)
# ======================================================================================
@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinLogUnlinked(BinCase):

    def test_bin_satirlari_odemeye_baglanmaz_isaret_tasir(self):
        payment = self.make_mail_order()
        self.queue_bin(querybin_body('CREDIT'))
        self.queue_systems(paymentsystems_body([(2, 0)]))
        self.assertEqual(payment.with_user(self.user_sp)._mail_order_bin_lookup(LEAK_BIN)['status'], 200)
        mark = '"_payment_id": %d}' % payment.id
        for action in ('QUERYBIN', 'QUERYPAYMENTSYSTEMS'):
            with self.subTest(action=action):
                row = self.logs(action)
                self.assertEqual(len(row), 1)
                self.assertFalse(row.payment_id, 'FK yok: ödeme satırında FOR KEY SHARE alınmaz')
                self.assertTrue(row.request_body.endswith(mark), row.request_body)
                self.assertNotIn(LEAK_BIN, row.request_body)

    def test_diger_cagrilar_odemeye_bagli_kalir(self):
        """Kardeş yol: ``fk_nowait=False`` (varsayılan) çağrılarda satır ödemeye bağlanır, işaret yok."""
        payment = self.make_paid(self.make_payment(invoice_no='BIN-FK'), tran_ref='BF1')
        self.mock.default('QUERYTRANSACTION', lambda p: qt_body(tran(ref='BF1')))
        self.provider().query_status(payment)
        row = self.logs('QUERYTRANSACTION')[-1:]
        self.assertEqual(row.payment_id, payment)
        self.assertNotIn('_payment_id', row.request_body or '')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestBinUrlAllowList(BinCase):

    BAD_URLS = ('http://test.paratika.com.tr/paratika/api/v2', 'https://paratika.evil.example/paratika/api/v2',
                'https://test.paratika.com.tr:8443/paratika/api/v2',
                'https://x@test.paratika.com.tr/paratika/api/v2')

    def test_izinsiz_adreste_bin_gitmez_satir_yazilmaz_502(self):
        params = self.env['ir.config_parameter'].sudo()
        for index, url in enumerate(self.BAD_URLS):
            with self.subTest(url=url):
                params.set_param('sanal_pos.paratika_test_url', url)
                payment = self.make_mail_order(invoice_no='UA-%d' % index, merchant_payment_id='UA-%d-1' % index)
                self.assertFalse(self.provider().query_bin(payment, LEAK_BIN)['ok'])
                self.assertFalse(self.provider().query_card_installments(payment, LEAK_BIN)['ok'])
                self.assertEqual(payment.with_user(self.user_sp)._mail_order_bin_lookup(LEAK_BIN), {'status': 502})
        self.assertNoParatikaCalls()
        self.assertFalse(self.logs('QUERYBIN') | self.logs('QUERYPAYMENTSYSTEMS'), 'sayaç artmaz')

    def test_izinli_ozel_yol_calisir(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'sanal_pos.paratika_test_url', 'https://TEST.paratika.com.tr/ozel/api/v2/')
        self.queue_bin(querybin_body('DEBIT'))
        self.assertTrue(self.provider().query_bin(self.make_mail_order(), LEAK_BIN)['ok'])
        self.assertEqual(self.mock.actions, ['QUERYBIN'])

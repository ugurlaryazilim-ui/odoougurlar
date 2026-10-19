# -*- coding: utf-8 -*-
"""G3 / Nebim fatura kaynağı. KK-1, KK-1a, KK-1b, KK-2, KK-3, KK-4 (+ NFR-2/NFR-4 sır sızıntısı).

MSSQL'e bağlanılmaz: ``_fetch_rows(invoice_no)`` taklit edilir (common.py).
Arayüz (02-tasarim §10): ``find_invoice(invoice_no) -> dict`` anahtarları
invoice_no, invoice_ref, invoice_date, customer_code, name, phone, email,
address, city, amount (Decimal), currency.
"""
from decimal import Decimal

from odoo.exceptions import AccessError, UserError
from odoo.service.model import get_public_method
from odoo.tests import tagged

from .common import (
    CUSTOMER_NAME, INV_NO, MSSQL_PASSWORD, MSSQL_USER, PASSWORD, SECRET_KEY, SanalPosCase,
    invoice_rows,
)

SOURCE = 'sanal.pos.invoice.source.nebim'


@tagged('post_install', '-at_install', 'sanal_pos')
class TestFindInvoice(SanalPosCase):

    def find(self, invoice_no=INV_NO):
        return self.env[SOURCE].find_invoice(invoice_no)

    def assertFindError(self, text, invoice_no=INV_NO):
        with self.assertRaises(UserError) as ctx:
            self.find(invoice_no)
        self.assertIn(text, str(ctx.exception.args[0]))
        return ctx.exception

    # ---------------------------------------------------------------- KK-1
    def test_kk1_ornek_fatura(self):
        """KK-1: 3 satırlı fatura; tutar FaturaToplam (9000.00), satırlar toplanmaz."""
        res = self.find()
        self.assertEqual(res['invoice_no'], INV_NO)
        self.assertEqual(res['amount'], Decimal('9000.00'))
        self.assertIsInstance(res['amount'], Decimal)
        self.assertNotEqual(res['amount'], Decimal('27000.00'), 'FaturaToplam satır sayısıyla çarpılmış')
        self.assertNotEqual(res['amount'], Decimal('6000.00'), 'SatirTutari toplanmış')
        self.assertEqual(res['currency'], 'TRY')
        self.assertEqual(res['customer_code'], 'M-555')
        self.assertEqual(res['name'], CUSTOMER_NAME)
        self.assertEqual(res['phone'], '5321112233')
        self.assertFalse(res['email'])
        self.assertFalse(res['address'])
        self.assertEqual(res['invoice_ref'], '0A1B2C3D-0000-4000-8000-000000000001')

    def test_kk1_turkce_karakter_birebir(self):
        """KK-1/KK-15: ad karakter karakter korunur."""
        name = 'Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'
        self.set_invoice(invoice_rows(MusteriAdi=name))
        self.assertEqual(self.find()['name'], name)

    def test_kk1_tek_satirli_fatura(self):
        self.set_invoice(invoice_rows(lines=1, total='1250.50'))
        self.assertEqual(self.find()['amount'], Decimal('1250.50'))

    def test_kk1_tutar_ondalik_korunur(self):
        self.set_invoice(invoice_rows(total='6500.01'))
        self.assertEqual(self.find()['amount'], Decimal('6500.01'))

    def test_kk1_arama_tam_eslesme_ve_bosluk_kirpma(self):
        """KK-2/NFR: parametreli, tam eşleşme; başındaki/sonundaki boşluk kırpılır."""
        self.find('  %s  ' % INV_NO)
        self.assertEqual(len(self.mssql_calls), 1)
        self.assertEqual(self.mssql_calls[0].strip(), INV_NO)

    # --------------------------------------------------------------- KK-1a
    def test_kk1a_telefon_fatura_gsm_oncelikli(self):
        """KK-1a: FaturaGSMNo geçerli cep ise o kullanılır."""
        self.set_invoice(invoice_rows(FaturaGSMNo='+90 555 444 33 22'))
        self.assertEqual(self.find()['phone'], '5554443322')

    def test_kk1a_telefon_gsm_gecersizse_musteri_cep(self):
        """KK-1a: FaturaGSMNo cep değilse (sabit hat) MusteriCep'e düşülür."""
        self.set_invoice(invoice_rows(FaturaGSMNo='0212 111 22 33'))
        self.assertEqual(self.find()['phone'], '5321112233')

    def test_kk1a_telefon_ikisi_de_gecersizse_bos(self):
        self.set_invoice(invoice_rows(FaturaGSMNo='abc', MusteriCep='123'))
        self.assertFalse(self.find()['phone'])

    def test_kk1a_telefon_yoksa_bos(self):
        self.set_invoice(invoice_rows(FaturaGSMNo=None, MusteriCep=None))
        self.assertFalse(self.find()['phone'])

    def test_kk1a_eposta_ve_adres_gelir(self):
        self.set_invoice(invoice_rows(MusteriEposta='musteri@example.com',
                                      FaturaAdresi='Atatürk Cad. No:5 Kadıköy'))
        res = self.find()
        self.assertEqual(res['email'], 'musteri@example.com')
        self.assertEqual(res['address'], 'Atatürk Cad. No:5 Kadıköy')

    def test_kk1a_il_kodu_paratikaya_giden_alan_degildir(self):
        """KK-1a: il kodu eşlenemiyorsa ham kod il adı olarak döndürülmez."""
        self.set_invoice(invoice_rows(FaturaIlKodu='34', FaturaIlceKodu='1234'))
        city = self.find()['city']
        self.assertNotIn(city, ('34', '1234', ' 34'), 'il kodu ad yerine kullanılmış')

    def test_kk1a_il_yoksa_bos(self):
        self.assertFalse(self.find()['city'])

    # --------------------------------------------------------------- KK-1b
    def test_kk1b_satirlar_arasi_tutar_farki(self):
        """KK-1b: satırlarda farklı FaturaToplam -> hata, link yok."""
        rows = invoice_rows()
        rows[1]['FaturaToplam'] = Decimal('9000.01')
        self.set_invoice(rows)
        self.assertFindError('Fatura tutarı tutarsız; link oluşturulamaz.')

    def test_kk1b_satirlar_arasi_para_birimi_farki(self):
        rows = invoice_rows()
        rows[2]['ParaBirimi'] = 'USD'
        self.set_invoice(rows)
        self.assertFindError('Fatura tutarı tutarsız; link oluşturulamaz.')

    def test_kk1b_bir_satirda_null_digerlerinde_dolu(self):
        rows = invoice_rows()
        rows[0]['FaturaToplam'] = None
        self.set_invoice(rows)
        with self.assertRaises(UserError):
            self.find()

    def test_kk1b_tutarsizlikta_kayit_olusmaz(self):
        rows = invoice_rows()
        rows[1]['FaturaToplam'] = Decimal('8000.00')
        self.set_invoice(rows)
        with self.assertRaises(UserError):
            self.find()
        self.assertFalse(self.payments())

    # ---------------------------------------------------------------- KK-2
    def test_kk2_3_karakterden_kisa_kaynaga_sorgu_gitmez(self):
        for raw in ('', ' ', 'A', 'AB', '  A  ', ' AB '):
            with self.subTest(raw=raw):
                self.assertFindError('En az 3 karakter giriniz.', raw)
        self.assertEqual(self.mssql_calls, [], 'kısa numarada MSSQL sorgusu gitmemeli')

    def test_kk2_3_karakter_sinir_gecerli(self):
        self.set_invoice(invoice_rows(invoice_no='ABC'), invoice_no='ABC')
        self.assertEqual(self.find('ABC')['invoice_no'], 'ABC')

    def test_kk2_none_ve_false_patlamaz(self):
        for raw in (None, False):
            with self.subTest(raw=raw):
                with self.assertRaises(UserError):
                    self.find(raw)

    def test_kk2_fatura_bulunamadi(self):
        self.assertFindError('Fatura bulunamadı: UGR9999', 'UGR9999')
        self.assertFalse(self.payments('UGR9999'))

    # ---------------------------------------------------------------- KK-3
    def test_kk3_baglanti_hatasi_mesaji_ve_sir_sizmaz(self):
        """KK-3: bağlantı hatasında Türkçe mesaj; şifre/kullanıcı ne mesajda ne logda."""
        self.mssql_error = Exception(
            'Adaptive Server connection failed (mssql.invalid) user=%s password=%s'
            % (MSSQL_USER, MSSQL_PASSWORD))
        with self.capture_logs() as records:
            with self.assertRaises(UserError) as ctx:
                self.find()
        message = str(ctx.exception.args[0])
        self.assertIn('Fatura sistemine ulaşılamadı, daha sonra tekrar deneyin.', message)
        self.assertNotIn(MSSQL_PASSWORD, message)
        self.assertNotIn(MSSQL_PASSWORD, '\n'.join(records), 'MSSQL şifresi logda açık metin')
        self.assertFalse(self.payments(), 'hata sonrası kayıt oluşmamalı')

    def test_o6_paratika_sirlari_da_loga_girmez(self):
        """Ö-6: hata metnine Paratika şifresi/secretKey girerse de log satırında süzülür."""
        self.mssql_error = Exception('driver error pw=%s key=%s' % (PASSWORD, SECRET_KEY))
        with self.capture_logs() as records:
            with self.assertRaises(UserError):
                self.find()
        text = '\n'.join(records)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(SECRET_KEY, text)

    def test_kk3_zaman_asimi_ayni_mesaj(self):
        self.mssql_error = TimeoutError('timed out')
        self.assertFindError('Fatura sistemine ulaşılamadı, daha sonra tekrar deneyin.')

    def test_kk3_view_v2_degil(self):
        """Tasarım §10: v2 sütunu yoksa (view geri alınmış) anlaşılır mesaj."""
        self.mssql_error = Exception("Invalid column name 'FaturaToplam'.")
        exc = self.assertFindError('v2')
        self.assertNotIn(MSSQL_PASSWORD, str(exc))

    # ---------------------------------------------------------------- KK-4
    def test_kk4_gecersiz_tutarlar(self):
        """KK-4: NULL, 0, negatif tutar -> 'Faturanın tutarı geçersiz (<tutar>); link oluşturulamaz.'"""
        for total in (None, '0', '0.00', '-5.00'):
            with self.subTest(total=total):
                self.set_invoice(invoice_rows(total=total))
                self.assertFindError('Faturanın tutarı geçersiz')
                self.assertFindError('link oluşturulamaz.')

    def test_kk4_negatif_tutar_mesajda_gorunur(self):
        self.set_invoice(invoice_rows(total='-5.00'))
        self.assertFindError('-5')

    def test_kk4_try_disi_para_birimi(self):
        """KK-4: 'Yalnız TL faturalar için link oluşturulabilir (<para birimi>).'"""
        self.set_invoice(invoice_rows(currency='USD'))
        self.assertFindError('Yalnız TL faturalar için link oluşturulabilir (USD).')

    def test_kk4_bos_para_birimi(self):
        self.set_invoice(invoice_rows(currency=None))
        with self.assertRaises(UserError):
            self.find()


@tagged('post_install', '-at_install', 'sanal_pos')
class TestFindInvoiceAccess(SanalPosCase):
    """Güvenlik bulgusu: find_invoice müşteri PII'si döndürür ve MSSQL sorgusu tetikler;
    RPC'ye kapalı olmalı ve yalnız Sanal POS kullanıcıları çağırabilmeli."""

    def test_grupsuz_ic_kullanici_dogrudan_cagrida_accesserror_alir(self):
        env = self.env(user=self.user_plain)
        with self.assertRaises(AccessError):
            env[SOURCE].find_invoice(INV_NO)
        self.assertEqual(self.mssql_calls, [], 'yetkisiz çağrı MSSQL sorgusu tetiklememeli')

    def test_sanal_pos_kullanicisi_cagirabilir(self):
        for user in (self.user_sp, self.user_mgr):
            res = self.env(user=user)[SOURCE].find_invoice(INV_NO)
            self.assertEqual(res['invoice_no'], INV_NO)

    def test_rpc_ile_cagrilamaz(self):
        """call_kw yolu (get_public_method) find_invoice'u reddeder - yetkili kullanıcı için bile."""
        for user in (self.user_plain, self.user_sp, self.user_mgr):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    get_public_method(self.env(user=user)[SOURCE], 'find_invoice')
        self.assertEqual(self.mssql_calls, [])

    def test_saglayici_arayuzu_rpc_ile_cagrilamaz(self):
        """Dış çağrı tetikleyen sağlayıcı metotları (VOID/REFUND dahil) RPC'ye kapalı."""
        provider = self.env(user=self.user_mgr)['sanal.pos.provider.paratika']
        for name in ('create_link', 'resend', 'cancel_link', 'find_link', 'query_status',
                     'void', 'refund', 'parse_notification'):
            with self.subTest(method=name):
                with self.assertRaises(AccessError):
                    get_public_method(provider, name)

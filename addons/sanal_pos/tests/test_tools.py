# -*- coding: utf-8 -*-
"""G2 / tools.py saf yardımcıları. KK-6, KK-8, KK-11, KK-15, KK-30/44/50/51 (TL biçimi),
KK-37 + NFR-4 (maskeleme).

Arayüz: 02-tasarim.md §9. ``tools`` modülü ilk kullanımda içe aktarılır
(modül henüz yokken yalnız bu dosyanın testleri kırmızı olsun diye).
"""
from decimal import Decimal

from odoo.tests import TransactionCase, tagged


def _tools():
    from odoo.addons.sanal_pos import tools
    return tools


@tagged('post_install', '-at_install', 'sanal_pos')
class TestPhone(TransactionCase):

    def test_kk6_gecerli_biçimler_5321112233_olur(self):
        """KK-6: beş farklı yazım da 5321112233 olarak normalize edilir."""
        t = _tools()
        for raw in ('0532 111 22 33', '+90 532 111 22 33', '905321112233',
                    '(532) 111-22-33', '5321112233'):
            with self.subTest(raw=raw):
                self.assertEqual(t.normalize_phone(raw), '5321112233')

    def test_kk6_ek_gecerli_biçimler(self):
        """KK-6 (ek): 0 (532)..., +90(532)... gibi karışık biçimler."""
        t = _tools()
        for raw in ('0 (532) 111 22 33', '+90 (532) 111-22-33', '90 532 111 22 33',
                    '  0532.111.22.33  '):
            with self.subTest(raw=raw):
                self.assertEqual(t.normalize_phone(raw), '5321112233')

    def test_kk6_gecersiz_numaralar_false_doner(self):
        """KK-6: sabit hat, 9 hane ve 11 hane geçersizdir."""
        t = _tools()
        for raw in ('0212 111 22 33', '532111223', '53211122334'):
            with self.subTest(raw=raw):
                self.assertFalse(t.normalize_phone(raw))

    def test_kk6_sinir_ve_bozuk_girdiler(self):
        """KK-6 (sınır): boş, None, harf, 5 ile başlamayan 10 hane."""
        t = _tools()
        for raw in ('', None, False, 'abc', '4321112233', '05321112233 99', '+1 532 111 22 33'):
            with self.subTest(raw=raw):
                self.assertFalse(t.normalize_phone(raw))

    def test_kk6_saglayici_biçimleri(self):
        """KK-6/P-3: ayara göre 5XXXXXXXXX / 05... / 905... / +905... biçimi."""
        t = _tools()
        expected = {'10': '5321112233', '0': '05321112233',
                    '90': '905321112233', '+90': '+905321112233'}
        for fmt, value in expected.items():
            with self.subTest(fmt=fmt):
                self.assertEqual(t.format_phone_for_provider('5321112233', fmt), value)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestText(TransactionCase):

    def test_kk11_bosluk_temizligi_turkce_korunur(self):
        """KK-11: baş/son boşluk silinir, ardışık boşluk teke iner, Türkçe karakter korunur."""
        t = _tools()
        self.assertEqual(t.clean_text('  ÇAĞRI   ŞAHİN '), 'ÇAĞRI ŞAHİN')
        name = 'Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'
        self.assertEqual(t.clean_text(name), name)

    def test_kk15_ascii_donusumu_tam_tablo(self):
        """KK-15: ASCII modu dönüşümü örnek ad."""
        t = _tools()
        self.assertEqual(t.to_ascii('Çağrı Şükrü Öğüt İĞÜŞÖÇ ığüşöç'),
                         'Cagri Sukru Ogut IGUSOC igusoc')

    def test_kk15_ascii_tek_tek_harfler(self):
        t = _tools()
        table = {'İ': 'I', 'ı': 'i', 'Ğ': 'G', 'ğ': 'g', 'Ü': 'U', 'ü': 'u',
                 'Ş': 'S', 'ş': 's', 'Ö': 'O', 'ö': 'o', 'Ç': 'C', 'ç': 'c'}
        for src, dst in table.items():
            with self.subTest(harf=src):
                self.assertEqual(t.to_ascii(src), dst)

    def test_kk15_ascii_zaten_ascii_degismez(self):
        t = _tools()
        self.assertEqual(t.to_ascii('Mehmet Yilmaz 123 - Sok. No:5'), 'Mehmet Yilmaz 123 - Sok. No:5')


@tagged('post_install', '-at_install', 'sanal_pos')
class TestEmail(TransactionCase):

    def test_kk8_gecerli(self):
        t = _tools()
        for mail in ('musteri@example.com', 'a.b-c+d@alt.alan.com.tr'):
            with self.subTest(mail=mail):
                self.assertTrue(t.validate_email(mail))

    def test_kk8_gecersiz(self):
        """KK-8: '@' ve alan adı yok, boşluk, çift @ ..."""
        t = _tools()
        for mail in ('', 'abc', 'abc@', '@example.com', 'a@b', 'a b@example.com',
                     'a@@example.com', 'a@example'):
            with self.subTest(mail=mail):
                self.assertFalse(t.validate_email(mail))

    def test_kk8_64_karakter_siniri(self):
        """KK-8: 64 karakter geçerli, 65 geçersiz."""
        t = _tools()
        ok64 = 'a' * 59 + '@b.co'
        bad65 = 'a' * 60 + '@b.co'
        self.assertEqual(len(ok64), 64)
        self.assertEqual(len(bad65), 65)
        self.assertTrue(t.validate_email(ok64))
        self.assertFalse(t.validate_email(bad65))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestFormatTry(TransactionCase):

    def test_kk30_tl_biçimi(self):
        """KK-30/44/50/51: Türkçe binlik/ondalık ayıracı ve 'TL' soneki."""
        t = _tools()
        cases = {
            Decimal('9000'): '9.000,00 TL',
            Decimal('9000.00'): '9.000,00 TL',
            Decimal('2500'): '2.500,00 TL',
            Decimal('6500.01'): '6.500,01 TL',
            Decimal('0.5'): '0,50 TL',
            Decimal('1234567.8'): '1.234.567,80 TL',
            Decimal('0.01'): '0,01 TL',
        }
        for amount, text in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(t.format_try(amount), text)


@tagged('post_install', '-at_install', 'sanal_pos')
class TestMasking(TransactionCase):

    def test_kk37_telefon_son_4_hane(self):
        """KK-37/NFR-4: telefon yalnız son 4 hane görünür."""
        t = _tools()
        masked = t.mask_phone('5321112233')
        self.assertTrue(masked.endswith('2233'), masked)
        self.assertNotIn('5321', masked)
        self.assertNotIn('1112', masked)
        self.assertNotIn('532', masked)

    def test_kk37_telefon_bos_girdi_patlamaz(self):
        t = _tools()
        for raw in ('', None, False):
            with self.subTest(raw=raw):
                self.assertFalse(t.mask_phone(raw))

    def test_kk37_eposta_maskeleme(self):
        """KK-37: e-posta yerel kısmı gizlenir, alan adı kalır."""
        t = _tools()
        masked = t.mask_email('çağrı@alan.com')
        self.assertTrue(masked.endswith('@alan.com'), masked)
        self.assertNotIn('ağrı', masked)
        self.assertNotIn('çağrı', masked)

    def test_kk37_mask_params_gizli_anahtar_yildizli(self):
        """KK-37: gizli anahtarlar '***' olur, diğerleri korunur, girdi sözlüğü değişmez."""
        t = _tools()
        params = {'MERCHANTPASSWORD': 'Gizli!123', 'AMOUNT': '9000.00', 'ACTION': 'PAYBYLINKPAYMENT'}
        masked = t.mask_params(params, ['MERCHANTPASSWORD'])
        self.assertEqual(masked['MERCHANTPASSWORD'], '***')
        self.assertEqual(masked['AMOUNT'], '9000.00')
        self.assertEqual(masked['ACTION'], 'PAYBYLINKPAYMENT')
        self.assertEqual(params['MERCHANTPASSWORD'], 'Gizli!123', 'girdi sözlüğü değiştirilmemeli')

    def test_kk37_scrub_metinden_sirri_siler(self):
        """KK-37: hata metnindeki şifre/secretKey her geçtiği yerde '***' olur."""
        t = _tools()
        out = t.scrub('login failed for Gizli!123 ... retry with Gizli!123', ['Gizli!123'])
        self.assertNotIn('Gizli!123', out)
        self.assertIn('***', out)

    def test_kk37_scrub_bos_sir_metni_bozmaz(self):
        """KK-37 (sınır): boş/None sır değeri her karakter arasına '***' sokmamalı."""
        t = _tools()
        self.assertEqual(t.scrub('bağlantı hatası', ['', None, False]), 'bağlantı hatası')
        self.assertEqual(t.scrub('bağlantı hatası', []), 'bağlantı hatası')

    def test_kk37_scrub_none_metin(self):
        t = _tools()
        self.assertFalse(t.scrub(None, ['x']))

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
class TestInstallmentTable(TransactionCase):
    """Mail Order kart sayfası taksit tablosu: okunur ad, tekrarsız program, vade farkı toplamı."""

    def test_ag_adlari_eslenir_bilinmeyen_duzgun_harfle(self):
        t = _tools()
        self.assertEqual(t.network_label('PARAF'), 'Paraf')
        self.assertEqual(t.network_label('CARD_FNS'), 'CardFinans')
        self.assertEqual(t.network_label('KVY_NTW'), 'Kuveyt Türk (Sağlam Kart)')
        self.assertEqual(t.network_label('SOME_NEW'), 'Some New')

    def test_toplam_kurusa_yuvarlanir_half_up(self):
        t = _tools()
        self.assertEqual(t.installment_totals('1000', 2.5, 4), (Decimal('1025.00'), Decimal('256.25')))
        # 100.05 x 1.01 = 101.0505 -> 101.05 ; 0.5 kuruş yukarı: 10.05 x 1.05 = 10.5525 -> 10.55
        self.assertEqual(t.installment_totals(Decimal('100.05'), 1, 1)[0], Decimal('101.05'))
        self.assertEqual(t.installment_totals(Decimal('10.05'), 5, 1)[0], Decimal('10.55'))
        # tam yarım kuruş: 0.50 x 1.01 = 0.505 -> 0.51
        self.assertEqual(t.installment_totals(Decimal('0.50'), 1, 1)[0], Decimal('0.51'))
        self.assertEqual(t.installment_totals(1450, 0, 3), (Decimal('1450.00'), Decimal('483.33')))

    def test_vade_farki_orani_eslesmesi(self):
        """Çekilen tutar = tutar x (1 + oran/100) ± taksit sayısı kadar kuruş; oran 0 eşleşmez."""
        t = _tools()
        m = t.match_surcharge_rate
        self.assertEqual(m('9000', '10221.30', 7, [13.57]), Decimal('13.57'))
        self.assertEqual(m('9000', '10221.37', 7, [13.57]), Decimal('13.57'))
        self.assertIsNone(m('9000', '10221.38', 7, [13.57]))
        self.assertIsNone(m('9000', '10221.30', 1, [13.57]))           # tek çekim
        self.assertIsNone(m('9000', '9000.00', 7, [13.57]))            # fark yok
        self.assertIsNone(m('9000', '8999.00', 7, [13.57]))            # eksik
        self.assertIsNone(m('9000', '9000.05', 7, [0]))                # oran 0
        self.assertIsNone(m('9000', '10221.30', 7, []))                # oran bilinmiyor
        # Birden çok oran: en yakın toplam seçilir
        self.assertEqual(m('9000', '10350.00', 7, [13.57, 15.0]), Decimal('15.0'))
        self.assertEqual(t.format_rate(13.57), '%13,57')

    def test_ortak_program_tek_satir_unknown_gizli(self):
        t = _tools()
        options = [{'count': 2, 'networks': ['PARAF', 'UNKNOWN', 'KVY_NTW'], 'rate': 0},
                   {'count': 3, 'networks': ['KVY_NTW', 'PARAF'], 'rate': 1.5}]
        table = t.installment_table(1000, options)
        self.assertFalse(table['per_row'])
        self.assertEqual(table['common_networks'], ['Paraf', 'Kuveyt Türk (Sağlam Kart)'])
        self.assertNotIn('UNKNOWN', str(table))
        rows = table['rows']
        self.assertEqual([r['count'] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]['rate_text'], 'Vade farkı yok')
        self.assertEqual(rows[0]['total_text'], '1.000,00 TL')
        self.assertEqual(rows[1]['rate_text'], 'Vade farkı yok')
        self.assertEqual(rows[2]['rate_text'], '%1,50')
        self.assertEqual(rows[2]['total_text'], '1.015,00 TL')
        self.assertEqual(rows[2]['monthly_text'], '338,33 TL')
        self.assertNotIn('select_text', rows[2], 'A2-G3: select_text kaldırıldı')
        self.assertEqual(rows[2]['label'], '3 taksit')
        self.assertEqual(rows[2]['networks'], [])

    def test_farkli_programlar_satir_basinda(self):
        t = _tools()
        options = [{'count': 2, 'networks': ['AXESS', 'BONUS'], 'rate': 0},
                   {'count': 9, 'networks': ['BONUS'], 'rate': 4.5}]
        table = t.installment_table(1000, options)
        self.assertTrue(table['per_row'])
        self.assertEqual(table['rows'][1]['networks'], ['Axess', 'Bonus'])
        self.assertEqual(table['rows'][2]['networks'], ['Bonus'])
        self.assertNotIn('select_text', table['rows'][2], 'A2-G3: select_text kaldırıldı')
        self.assertEqual(table['rows'][2]['total_text'], '1.045,00 TL')

    def test_taksit_yoksa_yalniz_tek_cekim(self):
        table = _tools().installment_table(1450, [])
        self.assertEqual([r['count'] for r in table['rows']], [1])
        self.assertNotIn('select_text', table['rows'][0], 'A2-G3: select_text kaldırıldı')
        self.assertEqual(table['rows'][0]['total_text'], '1.450,00 TL')
        self.assertEqual(table['common_networks'], [])


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


@tagged('post_install', '-at_install', 'sanal_pos')
class TestStaticFileVersion(TransactionCase):

    def test_surum_icerikten_turer_ve_degisince_degisir(self):
        # Canlı hata: sabit CSS adresi tarayıcıda 1 hafta eski kalıyordu; içerik değişince sürüm değişmeli
        import os
        import tempfile
        t = _tools()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'a.css')
            with open(path, 'w') as f:
                f.write('a{color:red}')
            v1 = t.static_file_version(path)
            self.assertRegex(v1, r'^[0-9a-f]{12}$')
            self.assertEqual(t.static_file_version(path), v1)
            with open(path, 'w') as f:
                f.write('a{color:blue}')
            os.utime(path, (1, 1))      # mtime farklı olsun (önbellek anahtarı)
            v2 = t.static_file_version(path)
            self.assertNotEqual(v1, v2)

    def test_css_adresi_surumlu(self):
        t = _tools()
        self.assertRegex(t.mail_order_css_url(),
                         r'^/sanal_pos/static/src/css/mail_order\.css\?v=[0-9a-f]{12}$')


# ======================================================================================
# Mail Order kart sayfası Aşama 1: hash'li betik (tek kaynak) ve taksit kartı alanları
# ======================================================================================
_STAMPS = iter(range(1, 10 ** 6))


@tagged('post_install', '-at_install', 'sanal_pos')
class TestMailOrderScript(TransactionCase):
    """``tools.mail_order_script()`` -> ``(metin, sha256_base64)`` (02-tasarim §3.1, NFR-1.2)."""

    def _script(self, content):
        """Geçici dosya içeriğiyle ``mail_order_script()`` döndürür (content=None: dosya yok)."""
        import os
        import tempfile
        import time
        from unittest.mock import patch
        t = _tools()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'mail_order_card.js')
            if content is not None:
                with open(path, 'wb') as handle:
                    handle.write(content)
                stamp = time.time_ns() + next(_STAMPS) * 10 ** 9       # önbellek anahtarı benzersiz
                os.utime(path, ns=(stamp, stamp))
            with patch.object(t, 'MAIL_ORDER_JS_FILE', path):
                return t._read_mail_order_script()

    @staticmethod
    def _digest(text):
        import base64
        import hashlib
        return base64.b64encode(hashlib.sha256(text.encode('utf-8')).digest()).decode('ascii')

    def test_gercek_dosya_sabitleri_ve_donus_bicimi(self):
        t = _tools()
        self.assertEqual(t.MAIL_ORDER_JS_PATH, '/sanal_pos/static/src/js/mail_order_card.js')
        self.assertTrue(t.MAIL_ORDER_JS_FILE.replace('\\', '/').endswith(
            'sanal_pos/static/src/js/mail_order_card.js'))
        text, digest = t.mail_order_script()
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip())
        self.assertRegex(digest, r'^[A-Za-z0-9+/]{43}=$')
        self.assertEqual(digest, self._digest(text))
        self.assertNotIn('\r', text)
        self.assertFalse(text.startswith('﻿'))

    def test_onay_hashi_tutmayan_icerik_sunulmaz_d2(self):
        """D-2 (PCI 11.6.1): içerik geçerli ama onaylı hash'ten farklı -> MailOrderScriptHashMismatch."""
        import os
        import tempfile
        from unittest.mock import patch
        t = _tools()
        self.assertTrue(issubclass(t.MailOrderScriptHashMismatch, ValueError))   # controller yakalar
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'mail_order_card.js')
            with open(path, 'wb') as handle:
                handle.write(b'var onaysiz = 1;\n')
            os.utime(path, ns=(7 * 10 ** 18, 7 * 10 ** 18))
            with patch.object(t, 'MAIL_ORDER_JS_FILE', path):
                with self.assertRaises(t.MailOrderScriptHashMismatch):
                    t.mail_order_script()
                text, digest = t._read_mail_order_script()
                with patch.object(t, 'MAIL_ORDER_SCRIPT_SHA256', digest):
                    self.assertEqual(t.mail_order_script(), (text, digest))

    def test_lf_crlf_cr_ve_bom_ayni_metin_ayni_hash(self):
        source = 'var a = 1;\n// ç ğ ş ı İ\nvar b = 2;\n'
        variants = {
            'lf': source.encode('utf-8'),
            'crlf': source.replace('\n', '\r\n').encode('utf-8'),
            'cr': source.replace('\n', '\r').encode('utf-8'),
            'bom_lf': b'\xef\xbb\xbf' + source.encode('utf-8'),
            'bom_crlf': b'\xef\xbb\xbf' + source.replace('\n', '\r\n').encode('utf-8'),
        }
        for name, content in variants.items():
            with self.subTest(varyant=name):
                text, digest = self._script(content)
                self.assertEqual(text, source)
                self.assertEqual(digest, self._digest(source))

    def test_farkli_icerik_farkli_hash(self):
        _, first = self._script(b'var a = 1;\n')
        _, second = self._script(b'var a = 2;\n')
        self.assertNotEqual(first, second)

    def test_script_blogunu_bozan_icerik_reddedilir_value_error(self):
        for content in (b'var s = "</script>";', b'var s = "</SCRIPT>";', b'x = "</ScRiPt >";',
                        b'x = "</script", 1;', b'var c = "<!--";', b'/* <!-- */'):
            with self.subTest(icerik=content):
                with self.assertRaises(ValueError):
                    self._script(content)

    def test_zararsiz_kucuktur_isareti_reddedilmez(self):
        text, _ = self._script(b'if (a < b && c <= d) { x = "<b"; }\n')
        self.assertIn('a < b', text)

    def test_dosya_yoksa_os_error(self):
        with self.assertRaises(OSError):
            self._script(None)

    def test_icerik_degisince_onbellek_yenilenir(self):
        import os
        import tempfile
        from unittest.mock import patch
        t = _tools()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'mail_order_card.js')
            with open(path, 'w') as handle:
                handle.write('var one = 1;\n')
            os.utime(path, ns=(5 * 10 ** 18, 5 * 10 ** 18))
            with patch.object(t, 'MAIL_ORDER_JS_FILE', path):
                first = t._read_mail_order_script()
                self.assertEqual(t._read_mail_order_script(), first)   # aynı dosya, aynı sonuç
                with open(path, 'w') as handle:
                    handle.write('var two = 2;\n')
                os.utime(path, ns=(6 * 10 ** 18, 6 * 10 ** 18))
                second = t._read_mail_order_script()
        self.assertEqual(second[0], 'var two = 2;\n')
        self.assertNotEqual(first[1], second[1])


@tagged('post_install', '-at_install', 'sanal_pos')
class TestInstallmentTableStage1(TransactionCase):
    """Taksit kartı için ``label`` ve ``surcharge_text`` (KK-1.3/1.4); mevcut anahtarlar kalır."""

    def test_kk_1_4_ornek_1450_tl_oran_13_57_uc_taksit(self):
        t = _tools()
        self.assertEqual(t.installment_totals(1450, 13.57, 3), (Decimal('1646.77'), Decimal('548.92')))
        rows = t.installment_table(1450, [{'count': 3, 'networks': ['AXESS'], 'rate': 13.57}])['rows']
        self.assertEqual([r['count'] for r in rows], [1, 3])
        self.assertEqual(rows[1]['label'], '3 taksit')
        self.assertEqual(rows[1]['total_text'], '1.646,77 TL')
        self.assertEqual(rows[1]['monthly_text'], '548,92 TL')
        self.assertEqual(rows[1]['rate_text'], '%13,57')
        self.assertEqual(rows[1]['surcharge_text'], '196,77 TL')

    def test_tek_cekim_etiketi_ve_vade_farki_yok(self):
        rows = _tools().installment_table(1450, [])['rows']
        self.assertEqual(rows[0]['label'], 'Tek çekim')
        self.assertEqual(rows[0]['surcharge_text'], '')

    def test_oran_sifirsa_vade_farki_tutari_bos(self):
        rows = _tools().installment_table(1000, [{'count': 2, 'networks': [], 'rate': 0},
                                                 {'count': 3, 'networks': [], 'rate': 1.5}])['rows']
        self.assertEqual([r['label'] for r in rows], ['Tek çekim', '2 taksit', '3 taksit'])
        self.assertEqual([r['surcharge_text'] for r in rows], ['', '', '15,00 TL'])

    def test_vade_farki_toplam_eksi_tutar_kurus_yuvarlamasi(self):
        rows = _tools().installment_table('100.05', [{'count': 2, 'networks': [], 'rate': 1}])['rows']
        self.assertEqual(rows[1]['total_text'], '101,05 TL')
        self.assertEqual(rows[1]['surcharge_text'], '1,00 TL')

    def test_mevcut_anahtarlar_korunur(self):
        table = _tools().installment_table(1000, [{'count': 3, 'networks': ['PARAF'], 'rate': 1.5}])
        self.assertEqual(sorted(table), ['common_networks', 'per_row', 'rows'])
        for key in ('count', 'networks', 'rate_text', 'total_text', 'monthly_text',
                    'label', 'surcharge_text'):
            self.assertIn(key, table['rows'][1], key)
        # A2-G3: select_text KALDIRILDI (A1'de redeploy güvenliği için kalmıştı; EKIP-BORC kapandı)
        self.assertNotIn('select_text', table['rows'][1])


@tagged('post_install', '-at_install', 'sanal_pos')
class TestBankCardLabelStage2(TransactionCase):
    """A2 (S2.5/KK-2.2): ``tools.bank_label`` ve ``tools.card_label`` saf yardımcıları."""

    def test_bank_label_bilinen_kodlar(self):
        t = _tools()
        self.assertEqual(t.bank_label('AKBANK'), 'Akbank')
        self.assertEqual(t.bank_label('  AKBANK '), 'Akbank')
        self.assertEqual(t.bank_label('akbank'), 'Akbank', 'küçük harf kodu da eşlenir')

    def test_bank_label_bilinmeyen_kod_baslik_bicimi_kaybolmaz(self):
        t = _tools()
        self.assertEqual(t.bank_label('YENI_BANKA'), 'Yeni Banka')
        self.assertEqual(t.bank_label('XYZBANK'), 'Xyzbank')

    def test_bank_label_bos_yazilmaz(self):
        t = _tools()
        for empty in ('', None, False, '   '):
            self.assertEqual(t.bank_label(empty), '', repr(empty))

    def test_bank_label_ham_issuer_metni_kullanilmaz(self):
        """Banka adı kod eşlemesinden üretilir; serbest metin (``issuer``/``cardName``) ekrana gitmez."""
        t = _tools()
        self.assertNotIn('A.S.', t.bank_label('AKBANK'))
        self.assertTrue(isinstance(t.bank_label('AKBANK'), str))

    def test_bank_label_turkce_adlar_ve_kod_yazim_bicimleri(self):
        """B-5: kod sözlükte yoksa başlık biçimi Türkçe harfi kaybederdi (``Yapikredi``)."""
        t = _tools()
        for code, expected in (('YAPIKREDI', 'Yapı Kredi'), ('YAPI_KREDI', 'Yapı Kredi'), ('yapı kredi', 'Yapı Kredi'),
                               ('GARANTI', 'Garanti BBVA'), ('ISBANK', 'İş Bankası'), ('VAKIFBANK', 'VakıfBank'),
                               ('ZIRAAT', 'Ziraat Bankası'), ('HALKBANK', 'Halkbank'), ('AKBANK', 'Akbank')):
            with self.subTest(kod=code):
                self.assertEqual(t.bank_label(code), expected)

    def test_valid_bin_kisa_pan_aglari_reddedilir(self):
        """G2-4: 14-15 haneli ağlarda (Amex 34/37, Diners 300-305/36/38/39) 8 hane PAN'ın yarısını aşar."""
        t = _tools()
        for value in ('34000000', '37999999', '36000000', '38000000', '39000000', '30000000', '30599999'):
            with self.subTest(bin=value):
                self.assertFalse(t.valid_bin(value))
        for value in ('43550843', '30600000', '35000000', '33000000', '52828282', '97920000'):
            with self.subTest(bin=value):
                self.assertTrue(t.valid_bin(value))

    def test_card_label_kredi_kartlari(self):
        t = _tools()
        self.assertEqual(t.card_label('Akbank', 'Axess', 'credit'), 'Akbank · Axess · Kredi kartı')
        self.assertEqual(t.card_label('Garanti', 'Bonus', 'credit'), 'Garanti · Bonus · Kredi kartı')

    def test_card_label_banka_karti_program_yazilmaz(self):
        t = _tools()
        self.assertEqual(t.card_label('Akbank', 'Axess', 'debit'), 'Akbank · Banka kartı')
        self.assertEqual(t.card_label('Akbank', '', 'debit'), 'Akbank · Banka kartı')

    def test_card_label_on_odemeli(self):
        t = _tools()
        self.assertEqual(t.card_label('Akbank', 'Axess', 'prepaid'), 'Akbank · Ön ödemeli kart')

    def test_card_label_yurt_disi_sona_eklenir(self):
        t = _tools()
        self.assertEqual(t.card_label('Akbank', '', 'credit', foreign=True), 'Akbank · Kredi kartı · Yurt dışı')
        self.assertEqual(t.card_label('Akbank', 'Axess', 'debit', foreign=True), 'Akbank · Banka kartı · Yurt dışı')

    def test_card_label_olmayan_parca_yazilmaz(self):
        t = _tools()
        self.assertEqual(t.card_label('', 'Axess', 'credit'), 'Axess · Kredi kartı')
        self.assertEqual(t.card_label('Akbank', '', 'credit'), 'Akbank · Kredi kartı')
        self.assertEqual(t.card_label('', '', 'credit'), 'Kredi kartı')
        self.assertEqual(t.card_label('', '', 'debit', foreign=True), 'Banka kartı · Yurt dışı')
        for text in (t.card_label('', '', 'credit'), t.card_label(None, None, 'prepaid')):
            self.assertNotIn('None', text)
            self.assertFalse(text.startswith(' ·') or text.endswith('· '), text)
            self.assertNotIn('·  ·', text)

    def test_card_label_bilinmeyen_tur_sessiz_kalmaz(self):
        """Tanınmayan tür ``unknown`` olarak sunucuda 502 olur; yardımcıya gelirse de uydurma tür yazmaz."""
        t = _tools()
        text = t.card_label('Akbank', 'Axess', 'unknown')
        self.assertNotIn('Kredi kartı', text)
        self.assertNotIn('Banka kartı', text)

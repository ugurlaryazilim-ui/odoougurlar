# -*- coding: utf-8 -*-
"""KABUL: il/ilce esleme (KK-8, KK-8b, KK-8c) - cekirdek, SAHTE ilce verisiyle.

Gercek UPS verisiyle (1014 satir) ozdes-esleme testi cargo_ups/tests/test_kabul_ups_alan.py'dedir.
Yesile donecegi gorevler: G2 (cargo.area: normalize/esleme/diger adlar), G3 (gonderideki area_id / not / elle secim).

KURAL (02-tasarim 1.4): alt dize/bulanik/posta kodu/varsayilan YOK; il yalniz state_id; yasak girdiler: bos, il adi,
buyuksehirde MERKEZ ve <IL>MERKEZ; belirsizlikte aday listesi.
"""
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .kabul_taban import CargoKabulCase

METROPOLITAN = ['01', '06', '07', '09', '10', '16', '20', '21', '25', '26', '27', '31', '33', '34', '35', '38',
                '41', '42', '44', '45', '46', '47', '48', '52', '54', '55', '59', '61', '63', '65']
NON_METROPOLITAN = ['11', '71', '14', '19', '57']


class IlceBase(CargoKabulCase):
    REQUIRES_MODELS = ('cargo.area',)
    PROVIDER_TYPES = ('fixed', 'base_on_rule')

    @classmethod
    def _kur(cls):
        super()._kur()
        A = cls.make_area
        # il bazli sahte ilceler (gercek UPS adlarindan esinlenmis; veri sentetiktir)
        cls.a = {
            ('06', 'ALTINDAG'): A('06', 'ALTINDAG', alias='CENTER'),
            ('06', 'YENIMAHALLE'): A('06', 'YENIMAHALLE', alias='CENTER'),
            ('06', 'KAZAN'): A('06', 'KAZAN', alias='Kahramankazan'),
            ('06', 'MERKEZ'): A('06', 'MERKEZ'),
            ('21', 'KAYAPINAR'): A('21', 'KAYAPINAR'),
            ('21', 'MERKEZ'): A('21', 'MERKEZ'),
            ('11', 'MERKEZ'): A('11', 'MERKEZ'),
            ('16', 'OSMANGAZI'): A('16', 'OSMANGAZI', alias='Bursa Merkez Bolgesi'),
            ('16', 'YILDIRIM'): A('16', 'YILDIRIM'),
            ('20', 'KALE'): A('20', 'KALE'),
            ('20', 'PAMUKKALE'): A('20', 'PAMUKKALE'),
            ('20', 'MERKEZ'): A('20', 'MERKEZ'),
            ('20', 'MERKEZEFENDI'): A('20', 'MERKEZEFENDI'),
            ('53', 'HEMSIN'): A('53', 'HEMSIN'),
            ('53', 'CAMLIHEMSIN'): A('53', 'CAMLIHEMSIN'),
            ('07', 'KALE (DEMRE)'): A('07', 'KALE (DEMRE)'),
            ('07', 'DEMRE'): A('07', 'DEMRE'),
            ('35', 'MENDERES(CUMAOVASI)'): A('35', 'MENDERES(CUMAOVASI)'),
            ('35', 'BEYDAG'): A('35', 'BEYDAG'),
            ('35', 'BEYDAGI'): A('35', 'BEYDAGI'),
            ('65', 'SARAY'): A('65', 'SARAY'),
            ('65', 'BAHCESARAY'): A('65', 'BAHCESARAY'),
            ('65', 'EDREMIT (GUMUSDERE)'): A('65', 'EDREMIT (GUMUSDERE)'),
            ('10', 'EDREMIT'): A('10', 'EDREMIT'),
            ('34', 'EYUP'): A('34', 'EYUP', alias='Eyupsultan'),
            ('34', 'BUYUKCEKMECE'): A('34', 'BUYUKCEKMECE'),
            ('34', 'MIMARSINAN/BUYUKCEKMECE'): A('34', 'MIMARSINAN/BUYUKCEKMECE'),
            ('26', 'BEYLIKAHIR(B.OVA)'): A('26', 'BEYLIKAHIR(B.OVA)', alias='Beylikova'),
            ('01', 'CUKUROVA'): A('01', 'CUKUROVA'),
        }
        cls.area_alt = cls.a[('06', 'ALTINDAG')]
        cls.area_yeni = cls.a[('06', 'YENIMAHALLE')]
        cls.Area = cls.env['cargo.area']

    def cands(self, code, text, provider='fixed'):
        return self.Area._match_candidates(provider, self.st(code), text)

    def match(self, code, text, provider='fixed'):
        return self.Area._match(provider, self.st(code), text)

    def assertMatches(self, code, text, key, provider='fixed', msg=None):
        found = self.match(code, text, provider)
        self.assertEqual(found, self.a[(code, key)],
                         msg or 'il %s ilce %r -> %s beklenirdi, gelen: %s' % (code, text, key, found.mapped('name')))

    def assertNoMatch(self, code, text, provider='fixed', msg=None):
        self.assertFalse(self.match(code, text, provider),
                         msg or 'il %s ilce %r ESLESMEMELI, gelen: %s' % (code, text, self.match(code, text, provider).mapped('name')))
        return self.cands(code, text, provider)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulIlceNormalize(IlceBase):

    def test_normalize_tablosu(self):
        """02-tasarim 1.4: Turkce->ASCII, NFKD, buyuk harf, yalniz harf/rakam."""
        normalize = self.Area._normalize
        tablo = {
            'Çankaya': 'CANKAYA', 'çankaya ': 'CANKAYA', 'Iğdır': 'IGDIR', 'ığdır': 'IGDIR', 'İstanbul': 'ISTANBUL',
            'i̇stanbul': 'ISTANBUL', 'Şişli': 'SISLI', 'Üsküdar': 'USKUDAR', 'Ömerli': 'OMERLI',
            'Gölbaşı': 'GOLBASI', 'Çukurova': 'CUKUROVA', 'Merkez Efendi': 'MERKEZEFENDI',
            'Kale (Demre)': 'KALEDEMRE', 'B.Ova': 'BOVA', 'Mimar-Sinan': 'MIMARSINAN',
            'Kâğıthane': 'KAGITHANE', '  Beyoğlu  ': 'BEYOGLU', 'Altındığ': 'ALTINDIG',
            '': '', 'Çamlı-Hemşin 2': 'CAMLIHEMSIN2',
        }
        for girdi, beklenen in tablo.items():
            with self.subTest(girdi=girdi):
                self.assertEqual(normalize(girdi), beklenen)

    def test_kayit_anahtarlari(self):
        area = self.a[('07', 'KALE (DEMRE)')]
        self.assertEqual(area.name_key, 'KALEDEMRE', 'name_key: adin tam anahtari (stored)')

    def test_benzersizlik_saglayici_ve_kod(self):
        """(provider, area_code) benzersiz."""
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(Exception) as ctx:
                self.make_area('06', 'COPY', code=self.area_cankaya.area_code)
        self.assertTrue(type(ctx.exception).__name__ in ('IntegrityError', 'ValidationError', 'UniqueViolation'),
                        'ayni (provider, area_code) reddedilmeli: %r' % ctx.exception)
        # ayni kod baska saglayicida serbest
        other = self.make_area('06', 'CANKAYA', provider='base_on_rule', code=self.area_cankaya.area_code)
        self.assertEqual(other.provider, 'base_on_rule')

    def test_kullanici_yetkisi(self):
        area = self.a[('06', 'ALTINDAG')]
        self.assertEqual(area.with_user(self.user).read(['name'])[0]['name'], 'ALTINDAG')
        with self.assertRaises(AccessError):
            area.with_user(self.user).write({'alias_names': 'XYZ'})
        with self.assertRaises(AccessError):
            self.env['cargo.area'].with_user(self.user).create({
                'provider': 'fixed', 'state_id': self.st('06').id, 'name': 'YETKISIZ', 'area_code': 999001})
        # yonetici diger adlari yazar
        area.with_user(self.manager).write({'alias_names': 'Alt Dag Bolgesi'})
        self.assertEqual(area.alias_names, 'Alt Dag Bolgesi')


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulIlceEsleme(IlceBase):

    def test_ad_farklari_tek_eslesme(self):
        """KK-8: buyuk/kucuk harf, aksan, bosluk, il adi eki/oneki farki tek aday doner."""
        for text in ('Çankaya', 'CANKAYA', 'cankaya', ' Çankaya ', 'Ankara Çankaya', 'Çankaya Ankara',
                     'Ankara/Çankaya', 'Çankaya, Ankara', 'ANKARA - ÇANKAYA'):
            with self.subTest(text=text):
                self.assertEqual(self.match('06', text), self.area_cankaya)
        self.assertMatches('21', 'Kayapınar Diyarbakır', 'KAYAPINAR')
        self.assertMatches('21', 'Kayapinar', 'KAYAPINAR')
        self.assertMatches('01', 'Çukurova', 'CUKUROVA')
        self.assertMatches('01', 'Adana Çukurova', 'CUKUROVA')

    def test_yasak_girdiler(self):
        """KK-8c: bos, il adi, buyuksehirde Merkez / <IL> Merkez asla otomatik eslesmez."""
        for code in ('06', '21', '20'):
            il = self.st(code).name
            for text in ('', '   ', False, il, il.upper(), 'Merkez', 'MERKEZ', il + ' Merkez', il + 'Merkez',
                         'Merkez ' + il, il + '/Merkez'):
                with self.subTest(il=il, text=text):
                    self.assertFalse(self.match(code, text), 'yasak girdi eslesmemeli')
                    self.assertFalse(self.cands(code, text), 'yasak girdide aday da donmemeli')

    def test_buyuksehir_sabiti_davranissal(self):
        """30 buyuksehir: her birinde MERKEZ kaydi olsa bile Merkez/<IL> Merkez eslesmez; digerlerinde eslesir."""
        for code in METROPOLITAN:
            self.make_area(code, 'MERKEZ', alias='')
        for code in NON_METROPOLITAN:
            if ('%s' % code, 'MERKEZ') not in self.a:
                self.make_area(code, 'MERKEZ')
        for code in METROPOLITAN:
            il = self.st(code).name
            for text in ('Merkez', il + ' Merkez', il + ' MERKEZ'):
                with self.subTest(buyuksehir=code, text=text):
                    self.assertFalse(self.match(code, text),
                                     '%s buyuksehir: %r otomatik eslesmemeli' % (il, text))
        for code in NON_METROPOLITAN:
            il = self.st(code).name
            merkez = self.env['cargo.area'].search([('provider', '=', 'fixed'), ('state_id', '=', self.st(code).id),
                                                    ('name', '=', 'MERKEZ')], limit=1)
            for text in ('Merkez', il + ' Merkez', 'Merkez ' + il):
                with self.subTest(buyuksehir_degil=code, text=text):
                    self.assertEqual(self.match(code, text), merkez, '%s buyuksehir degil: Merkez eslesir' % il)

    def test_alt_dize_ve_bulanik_yok(self):
        """KK-8: yalniz tam anahtar; alt dize/bulanik YOK."""
        self.assertNoMatch('20', 'Pamuk')           # Denizli: PAMUKKALE'nin parcasi
        self.assertNoMatch('20', 'Kalee')
        self.assertNoMatch('53', 'Sin')             # Rize
        self.assertNoMatch('65', 'Sara')            # Van SARAY'a yakin
        self.assertNoMatch('65', 'Bahce')
        self.assertNoMatch('06', 'Cankayaa')
        self.assertNoMatch('06', 'Canka')
        self.assertNoMatch('35', 'Beyda')
        # bosluk ile bolunmez: "Merkez Efendi" MERKEZ olmaz, "Pamuk Kale" KALE olmaz
        self.assertMatches('20', 'Merkez Efendi', 'MERKEZEFENDI')
        self.assertNoMatch('20', 'Pamuk Kale')
        self.assertNoMatch('06', 'Eski Cankaya Mahallesi')

    def test_tam_ad_ile_alt_dize_ciftleri(self):
        """Ayni ilde birbirinin parcasi olan adlar karismaz (shopicargo hatasi)."""
        self.assertMatches('20', 'Kale', 'KALE')
        self.assertMatches('20', 'Pamukkale', 'PAMUKKALE')
        self.assertMatches('20', 'Merkezefendi', 'MERKEZEFENDI')
        self.assertMatches('53', 'Hemşin', 'HEMSIN')
        self.assertMatches('53', 'Çamlıhemşin', 'CAMLIHEMSIN')
        self.assertMatches('65', 'Saray', 'SARAY')
        self.assertMatches('65', 'Bahçesaray', 'BAHCESARAY')
        self.assertMatches('35', 'Beydağ', 'BEYDAG')
        self.assertMatches('35', 'Beydağı', 'BEYDAGI')

    def test_parantezli_metin_duzey2(self):
        """Duzey 2: ad '(' ')' '/' parcalari; duzey 1 (gercek ad) duzey 2'yi yener."""
        self.assertMatches('07', 'Demre', 'DEMRE')                       # gercek DEMRE kaydi kazanir
        self.assertMatches('07', 'Kale', 'KALE (DEMRE)')                 # yalniz duzey 2'de var
        self.assertMatches('07', 'Kale (Demre)', 'KALE (DEMRE)')
        self.assertMatches('35', 'Cumaovası', 'MENDERES(CUMAOVASI)')
        self.assertMatches('35', 'Menderes', 'MENDERES(CUMAOVASI)')
        self.assertMatches('65', 'Edremit', 'EDREMIT (GUMUSDERE)')
        self.assertMatches('10', 'Edremit', 'EDREMIT')                   # il ayrimi: Balikesir
        self.assertMatches('34', 'Büyükçekmece', 'BUYUKCEKMECE')         # duzey 1, MIMARSINAN/... duzey 2'ye karsi
        self.assertMatches('26', 'B.Ova', 'BEYLIKAHIR(B.OVA)')
        self.assertMatches('26', 'Beylikahır', 'BEYLIKAHIR(B.OVA)')

    def test_duzey2_gercek_kayit_yoksa(self):
        """Gercek BUYUKCEKMECE kaydi yokken ayni girdi MIMARSINAN/BUYUKCEKMECE'ye duzey 2'den eslesir."""
        self.a[('34', 'BUYUKCEKMECE')].unlink()
        self.assertMatches('34', 'Büyükçekmece', 'MIMARSINAN/BUYUKCEKMECE')

    def test_belirsiz_sonuc_aday_listesi(self):
        """Alias cakismasi -> belirsiz: _match bos, _match_candidates tum adaylari verir; sessiz secim yok."""
        cands = self.cands('06', 'Center')
        self.assertEqual(cands, self.area_alt | self.area_yeni)
        self.assertFalse(self.match('06', 'Center'))
        # baska kayitla ayni tam anahtarli alias
        self.a[('06', 'KAZAN')].write({'alias_names': 'Kahramankazan, Yenimahalle'})
        self.assertEqual(self.cands('06', 'Yenimahalle'), self.area_yeni | self.a[('06', 'KAZAN')])
        self.assertFalse(self.match('06', 'Yenimahalle'))

    def test_alias_yonetimi(self):
        """Diger adlar virgulle ayrilir; yazinca eslesme anahtarlari yeniden hesaplanir; kaldirinca eslesme biter."""
        self.assertMatches('34', 'Eyüpsultan', 'EYUP')
        self.assertMatches('06', 'Kahramankazan', 'KAZAN')
        self.assertMatches('26', 'Beylikova', 'BEYLIKAHIR(B.OVA)')
        self.assertNoMatch('34', 'Eyüp Sultan Bolgesi')
        eyup = self.a[('34', 'EYUP')]
        eyup.with_user(self.manager).write({'alias_names': 'Eyupsultan, Eyüp Sultan Bölgesi'})
        self.assertMatches('34', 'Eyüp Sultan Bölgesi', 'EYUP')
        self.assertMatches('34', 'Eyüpsultan', 'EYUP')
        eyup.with_user(self.manager).write({'alias_names': 'Eyupsultan'})
        self.assertNoMatch('34', 'Eyüp Sultan Bölgesi')
        eyup.with_user(self.manager).write({'alias_names': False})
        self.assertNoMatch('34', 'Eyüpsultan')
        self.assertMatches('34', 'Eyüp', 'EYUP')                           # kendi adi hala eslesir

    def test_il_yalniz_state_ile(self):
        """Il yalniz state_id: bos/yabanci il bos; yanlis ilin ilcesi baska ilde eslesmez; il gecmis kalan metin <3 ise at."""
        empty_state = self.env['res.country.state']
        self.assertFalse(self.Area._match('fixed', empty_state, 'Çankaya'))
        self.assertFalse(self.Area._match_candidates('fixed', empty_state, 'Çankaya'))
        us_state = self.env['res.country.state'].search([('country_id.code', '=', 'US')], limit=1)
        if us_state:
            self.assertFalse(self.Area._match('fixed', us_state, 'Çankaya'))
        self.assertNoMatch('34', 'Çankaya')         # Ankara ilcesi Istanbul'da yok
        self.assertNoMatch('06', 'Kadıköy')
        self.assertMatches('34', 'Eyüpsultan', 'EYUP')

    def test_saglayici_ayrimi(self):
        """Ayni il/ad iki saglayicida ayri kayit; her saglayici kendi kaydini gorur."""
        other = self.make_area('06', 'CANKAYA', provider='base_on_rule')
        self.assertEqual(self.match('06', 'Çankaya', 'fixed'), self.area_cankaya)
        self.assertEqual(self.match('06', 'Çankaya', 'base_on_rule'), other)
        self.assertNotEqual(other.area_code, self.area_cankaya.area_code)
        self.assertFalse(self.match('06', 'Altındağ', 'base_on_rule'))

    def test_81_il_icin_eslesme(self):
        """Her ilde bir sahte ilce eslesir (il kodu 01..81 sorunsuz)."""
        for no in range(1, 82):
            code = '%02d' % no
            area = self.make_area(code, 'KABULILCE%02d' % no)
            with self.subTest(il=code):
                self.assertEqual(self.match(code, 'Kabulilce%02d' % no), area)
                self.assertEqual(self.match(code, 'Kabulilce%02d %s' % (no, self.st(code).name)), area)


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulIlceGonderi(IlceBase):
    """Gonderi duzeyi: area_id otomatik, not, gonderimde red, elle secim (chatter), yeniden hesaplama."""
    REQUIRES_MODELS = ('cargo.area', 'cargo.shipment')

    def test_otomatik_eslesme(self):
        shipment = self.mk()
        self.assertEqual(shipment.area_id, self.area_cankaya)
        self.assertFalse(shipment.area_match_note)

    def test_eslesmeyen_ilce_not_ve_gonderim_reddi(self):
        shipment = self.mk(recipient_district='Bilinmeyenilce')
        self.assertFalse(shipment.area_id)
        self.assertIn('İlçe eşleşmedi', shipment.area_match_note)
        self.assertIn('Bilinmeyenilce', shipment.area_match_note)
        self.assertIn('Listeden ilçe seçin', shipment.area_match_note)
        self.assert_user_error(shipment.action_send, r'(?i)ilçe')
        self.no_provider_calls('ilce eslesmezse disariya cagri yapilmaz')
        self.assertEqual(shipment.state, 'draft')

    def test_yasak_girdi_il_adi_ve_merkez(self):
        """KK-8c: ilce yerine il adi / buyuksehirde Merkez girilen gonderi eslesmez, gonderilemez."""
        for text in ('Ankara', 'Merkez', 'Ankara Merkez'):
            with self.subTest(text=text):
                shipment = self.mk(recipient_district=text)
                self.assertFalse(shipment.area_id)
                self.assertTrue(shipment.area_match_note)
                self.assert_user_error(shipment.action_send, r'(?i)ilçe')
        self.no_provider_calls()

    def test_belirsiz_ilce_adaylar_listelenir(self):
        shipment = self.mk(recipient_district='Center')
        self.assertFalse(shipment.area_id)
        self.assertIn('İlçe belirsiz', shipment.area_match_note)
        self.assertIn('ALTINDAG', shipment.area_match_note)
        self.assertIn('YENIMAHALLE', shipment.area_match_note)
        self.assert_user_error(shipment.action_send, r'(?i)ilçe')
        self.no_provider_calls()

    def test_elle_secim_chatter_izi(self):
        shipment = self.mk(recipient_district='Center')
        shipment.write({'area_id': self.area_alt.id})
        shipment.action_send()
        self.assertEqual(shipment.state, 'created')
        self.assertEqual(self.provider.of('send')[0]['area_code'], self.area_alt.area_code)
        chat = self.chatter(shipment)
        self.assertIn('İlçe elle seçildi', chat)
        self.assertIn('ALTINDAG', chat)
        self.assertIn('Center', chat)

    def test_hesaplanandan_farkli_secim_not_dusurur(self):
        shipment = self.mk()      # Cankaya otomatik
        shipment.write({'area_id': self.area_yeni.id})
        shipment.action_send()
        self.assertEqual(self.provider.of('send')[0]['area_code'], self.area_yeni.area_code)
        self.assertIn('İlçe elle seçildi', self.chatter(shipment))

    def test_normal_eslesmede_elle_secim_notu_yok(self):
        shipment = self.sent()
        self.assertNotIn('İlçe elle seçildi', self.chatter(shipment))
        self.assertEqual(self.provider.of('send')[0]['area_code'], self.area_cankaya.area_code)

    def test_farkli_il_veya_saglayici_secilemez(self):
        shipment = self.mk()
        with self.assertRaises(ValidationError):
            shipment.write({'area_id': self.area_kadikoy.id})      # Istanbul ilcesi, il Ankara
        other_provider = self.make_area('06', 'ALTINDAG', provider='base_on_rule')
        with self.assertRaises(ValidationError):
            shipment.write({'area_id': other_provider.id})         # firma 'fixed', alan baska saglayici
        with self.assertRaises(ValidationError):
            self.mk(area_id=self.area_kadikoy.id)

    def test_il_ilce_firma_degisince_yeniden_hesap(self):
        shipment = self.mk()
        self.assertEqual(shipment.area_id, self.area_cankaya)
        shipment.write({'recipient_district': 'Yenimahalle'})
        self.assertEqual(shipment.area_id, self.area_yeni)
        shipment.write({'recipient_state_id': self.st('34').id, 'recipient_district': 'Kadıköy'})
        self.assertEqual(shipment.area_id, self.area_kadikoy)
        self.assertFalse(shipment.area_match_note)
        shipment.write({'recipient_district': 'Hicbiryer'})
        self.assertFalse(shipment.area_id)
        self.assertIn('İlçe eşleşmedi', shipment.area_match_note)
        # firma degisince: base_on_rule saglayicisi icin ayri alan
        other_carrier = self.make_carrier('Ikinci saglayici', ptype='base_on_rule')
        other_area = self.make_area('06', 'CANKAYA', provider='base_on_rule')
        shipment.write({'recipient_state_id': self.st('06').id, 'recipient_district': 'Çankaya'})
        self.assertEqual(shipment.area_id, self.area_cankaya)
        shipment.write({'carrier_id': other_carrier.id})
        self.assertEqual(shipment.area_id, other_area, 'firma degisince area_id yeniden hesaplanmali')

# -*- coding: utf-8 -*-
"""KABUL: GERCEK UPS il/ilce verisi (1014 satir) ile eslesme - KK-8, KK-8b, KK-8c, KK-32.

Cekirdegin SAHTE veriyle testleri addons/cargo/tests/test_kabul_ilce.py'dedir. Burada ayni kurallar gercek
``cargo_ups`` verisine uygulanir (02-tasarim 8: ozdes-esleme, istisna yalniz 22 buyuksehir MERKEZ kaydi).
Yesile donecegi gorev: G8 (1014 veri + takma adlar).
"""
import glob
import os

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .kabul_taban import UpsCase

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METROPOLITAN = {'01', '06', '07', '09', '10', '16', '20', '21', '25', '26', '27', '31', '33', '34', '35', '38',
                '41', '42', '44', '45', '46', '47', '48', '52', '54', '55', '59', '61', '63', '65'}

# (il plaka kodu, girdi, beklenen area_code) - gercek UPS koduyla (kaynak CSV'den dogrulanmis)
BEKLENEN = [
    ('07', 'Demre', 5889), ('07', 'DEMRE', 5889), ('07', 'İbradı', 90), ('35', 'Menderes', 492),
    ('65', 'Edremit', 885), ('10', 'Edremit', 147),
    ('34', 'Eyüpsultan', 444), ('34', 'Eyüp', 444), ('06', 'Kahramankazan', 69), ('06', 'Kazan', 69),
    ('26', 'Beylikova', 351), ('34', 'Büyükçekmece', 441), ('34', 'Mimarsinan', 5677),
    ('20', 'Pamukkale', 2390), ('20', 'Kale', 279), ('53', 'Çamlıhemşin', 729), ('53', 'Hemşin', 739),
    ('21', 'Kayapınar', 2456), ('21', 'Kayapınar / Diyarbakır', 2456), ('21', 'Kayapınar Diyarbakır', 2456),
    ('21', 'Diyarbakır / Kayapınar', 2456), ('01', 'Çukurova', 5820), ('01', 'ÇUKUROVA', 5820), ('01', 'cukurova', 5820),
]
ESLESMEMELI = [
    ('21', 'Diyarbakır'), ('21', 'Merkez'), ('21', 'Diyarbakır Merkez'), ('11', 'Bilecik'), ('07', 'Aksu'),
    ('31', 'Antakya'), ('21', 'Yenişehir'), ('34', 'İstanbul'), ('34', 'Merkez'), ('06', 'Ankara'), ('06', 'Merkez'),
    ('34', ''), ('34', '   '), ('06', 'Cank'), ('06', 'Çankayaaa'),
]


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul', 'cargo_ups_kabul')
class TestKabulUpsAlan(UpsCase):

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.Area = cls.env['cargo.area']
        cls.ups_areas = cls.Area.sudo().search([('provider', '=', 'ups_tr')])

    def match(self, code, text):
        return self.Area._match('ups_tr', self.st(code), text)

    def test_ozdes_esleme_1014(self):
        """Her UPS kaydinin kendi adi kendi kaydina doner; istisna yalniz buyuksehir MERKEZ / <IL> MERKEZ (22)."""
        normalize = self.Area._normalize
        exceptions, failures = [], []
        for area in self.ups_areas:
            key = normalize(area.name)
            forbidden = (area.state_id.code in METROPOLITAN
                         and key in ('MERKEZ', normalize(area.state_id.name) + 'MERKEZ', normalize(area.state_id.name.split()[0]) + 'MERKEZ'))
            if forbidden:
                exceptions.append(area.id)
                self.assertFalse(self.Area._match('ups_tr', area.state_id, area.name),
                                 'buyuksehirde %s/%s otomatik eslesmemeli' % (area.state_id.name, area.name))
                continue
            found = self.Area._match('ups_tr', area.state_id, area.name)
            if found != area:
                failures.append('%s / %s -> %s' % (area.state_id.name, area.name, found.mapped('name')))
        self.assertEqual(len(exceptions), 22, 'buyuksehir MERKEZ istisna sayisi')
        self.assertEqual(failures, [], 'ozdes-esleme basarisiz kayitlar')

    def test_81_ilin_her_biri_icin_esleme(self):
        by_state = {}
        for area in self.ups_areas:
            by_state.setdefault(area.state_id, self.Area.browse())
            by_state[area.state_id] |= area
        self.assertEqual(len(by_state), 81)
        for state, areas in by_state.items():
            with self.subTest(il=state.name):
                matched = [a for a in areas if self.Area._match('ups_tr', state, a.name) == a]
                self.assertTrue(matched, '%s icin hic ilce eslesmedi' % state.name)

    def test_gercek_veri_ornekleri(self):
        for code, text, area_code in BEKLENEN:
            with self.subTest(il=code, girdi=text):
                found = self.match(code, text)
                self.assertEqual(found.mapped('area_code'), [area_code],
                                 'il %s %r -> %s beklenirdi, gelen: %s' % (code, text, area_code, found.mapped('name')))
                self.assertEqual(found.state_id, self.st(code))

    def test_eslesmemesi_gerekenler(self):
        for code, text in ESLESMEMELI:
            with self.subTest(il=code, girdi=text):
                self.assertFalse(self.match(code, text), 'il %s %r eslesmemeli' % (code, text))

    def test_merkez_buyuksehir_disinda_eslesir(self):
        merkez = self.Area.sudo().search([('provider', '=', 'ups_tr'), ('state_id', '=', self.st('11').id), ('name', '=', 'MERKEZ')])
        self.assertEqual(len(merkez), 1)
        self.assertEqual(self.match('11', 'Merkez'), merkez)

    def test_belirsiz_aday_listesi(self):
        """Bursa 'Osmangazi / Yildirim' iki farkli kaydi isaret eder: sessiz secim yok, 2 aday."""
        state = self.st('16')
        self.assertFalse(self.Area._match('ups_tr', state, 'Osmangazi / Yıldırım'))
        candidates = self.Area._match_candidates('ups_tr', state, 'Osmangazi / Yıldırım')
        self.assertEqual(sorted(candidates.mapped('area_code')), [1908, 1925])

    def test_il_alias_ve_yasak_listeleri(self):
        """Antakya/Yenisehir/Aksu takma adi veride YOK (UPS'ten teyit edilince yonetici ekler)."""
        for needle in ('Antakya', 'Yenişehir', 'Aksu'):
            self.assertFalse(self.Area.sudo().search_count([('provider', '=', 'ups_tr'), ('alias_names', 'ilike', needle)]),
                             '%s takma adi veri dosyasinda olmamali' % needle)
        aliased = self.ups_areas.filtered('alias_names')
        self.assertEqual(sorted(aliased.mapped('area_code')), [69, 351, 444],
                         'yalniz 3 kesin ad degisikligi: EYUP, KAZAN, BEYLIKAHIR(B.OVA)')

    def test_alias_veri_dosyasi_noupdate(self):
        """Takma adlar noupdate=1 xml'de; CSV alias sutunu tasimaz (yonetici adlari -u ile ezilmez)."""
        files = [p for p in glob.glob(os.path.join(MODULE_DIR, 'data', '*.xml'))
                 if 'alias_names' in open(p, encoding='utf-8').read()]
        self.assertTrue(files, 'alias_names yazan bir data xml dosyasi olmali (cargo_area_alias_data.xml)')
        for path in files:
            with open(path, encoding='utf-8') as handle:
                self.assertIn('noupdate="1"', handle.read(), os.path.basename(path))

    def test_yonetici_takma_adi_eslemeyi_degistirir(self):
        area = self.match('06', 'Çankaya')
        self.assertEqual(area, self.ups_cankaya)
        self.assertFalse(self.match('06', 'Çankaya Merkez Bolgesi'))
        area.with_user(self.manager).write({'alias_names': 'Cankaya Merkez Bolgesi'})
        self.assertEqual(self.match('06', 'Çankaya Merkez Bölgesi'), area)

    def test_kullanici_okur_yazamaz(self):
        area = self.ups_cankaya.with_user(self.user)
        self.assertEqual(area.name, 'CANKAYA')
        with self.assertRaises(AccessError):
            area.write({'alias_names': 'x'})
        with self.assertRaises(AccessError):
            self.Area.with_user(self.user).create({'provider': 'ups_tr', 'state_id': self.st('06').id, 'name': 'YENI',
                                                   'city_code': 6, 'area_code': 987654})

    def test_gonderide_gercek_veri(self):
        """Gonderi duzeyi: otomatik area_id; belirsiz/eslesmeyen ilcede not + gonderim reddi + 0 HTTP."""
        ok = self.mk(**self.ups_vals(recipient_state_id=self.st('21').id, recipient_district='Kayapınar / Diyarbakır'))
        self.assertEqual(ok.area_id.area_code, 2456)
        self.assertFalse(ok.area_match_note)
        for state, district, expected in (('16', 'Osmangazi / Yıldırım', 'İlçe belirsiz'), ('21', 'Merkez', 'İlçe'),
                                          ('21', 'Diyarbakır', 'İlçe')):
            with self.subTest(il=state, ilce=district):
                shipment = self.mk(**self.ups_vals(recipient_state_id=self.st(state).id, recipient_district=district))
                self.assertFalse(shipment.area_id)
                self.assertIn(expected, shipment.area_match_note or '')
                self.assert_user_error(shipment.action_send)
        self.assertEqual(self.net.requests, [], 'eslesmeyen ilcede UPS\'e cagri gitmemeli')

    def test_tum_kayitlarda_alan_butunlugu(self):
        self.assertEqual(len(self.ups_areas), 1014)
        for area in self.ups_areas:
            self.assertTrue(area.name and area.area_code and area.city_code, area.name)
        self.assertTrue(all(self.ups_areas.mapped('match_keys')), 'match_keys her kayitta dolu')

# -*- coding: utf-8 -*-
"""G2 birim testleri: cargo.area anahtarları, aşamalı eşleme, ACL ve görünümler (sahte veri, provider='fixed')."""
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CargoTestCase


@tagged('post_install', '-at_install', 'cargo')
class TestCargoArea(CargoTestCase):
    REQUIRES_MODELS = ('cargo.area',)

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.Area = cls.env['cargo.area']
        cls.kale_demre = cls.make_area('07', 'KALE (DEMRE)')
        cls.demre = cls.make_area('07', 'DEMRE')
        cls.pamukkale = cls.make_area('20', 'PAMUKKALE')
        cls.kale = cls.make_area('20', 'KALE')

    def match(self, code, text):
        return self.Area._match('fixed', self.st(code), text)

    def test_match_keys_duzey_1_ve_2_ayri_saklanir(self):
        self.assertEqual(self.kale_demre.match_keys.split(), ['L1:KALEDEMRE', 'L2:DEMRE', 'L2:KALE'])
        self.assertEqual(self.demre.match_keys, 'L1:DEMRE')     # ayraç yok -> düzey 2 üretilmez
        area = self.make_area('06', 'ALTINDAG', alias='Center, Alt Dag')
        self.assertEqual(area.match_keys.split(), ['L1:ALTDAG', 'L1:ALTINDAG', 'L1:CENTER'])

    def test_kisa_parca_ve_bos_alias_atilir(self):
        area = self.make_area('06', 'AB/CDE', alias=' , ,')
        self.assertEqual(area.match_keys.split(), ['L1:ABCDE', 'L2:CDE'])

    def test_tam_ad_parantezli_dar_adaya_dusmez(self):
        """'Kale (Demre)': tam anahtar önce denenir, DEMRE kaydı ile sebepsiz belirsiz kalmaz."""
        self.assertEqual(self.match('07', 'Kale (Demre)'), self.kale_demre)
        self.assertEqual(self.match('07', 'Demre'), self.demre)
        self.assertEqual(self.match('07', 'Kale'), self.kale_demre)

    def test_alt_dize_yok_iki_yonlu(self):
        self.assertEqual(self.match('20', 'Kale'), self.kale)
        self.assertEqual(self.match('20', 'Pamukkale'), self.pamukkale)
        self.assertFalse(self.match('20', 'Pamuk'))
        self.assertFalse(self.match('20', 'Kalesi'))

    def test_il_atilmis_kalan_en_az_uc_karakter(self):
        self.make_area('20', 'KA')
        # 'KADenizli' -> kalan 'KA' (2 karakter) aday olmaz; tam anahtar KADENIZLI zaten kayıtta yok
        self.assertFalse(self.match('20', 'KA Denizli'))

    def test_yasak_girdide_sessiz_secim_yok(self):
        for code in ('34', '20'):
            self.make_area(code, 'MERKEZ')
        self.assertFalse(self.match('34', 'İstanbul'))
        self.assertFalse(self.match('34', 'Merkez'))
        self.assertFalse(self.match('20', 'Denizli / Merkez'))
        self.assertFalse(self.Area._match_candidates('fixed', self.st('20'), None))

    def test_yabanci_ulke_ve_bos_saglayici(self):
        self.assertFalse(self.Area._match_candidates('', self.st('20'), 'Kale'))
        usa = self.env['res.country.state'].search([('country_id.code', '=', 'US')], limit=1)
        if usa:
            self.assertFalse(self.Area._match_candidates('fixed', usa, 'Kale'))

    def test_alias_yazimi_anahtari_gunceller(self):
        self.kale.with_user(self.manager).write({'alias_names': 'Kalecik'})
        self.assertEqual(self.match('20', 'Kalecik'), self.kale)
        self.kale.with_user(self.manager).write({'alias_names': False})
        self.assertFalse(self.match('20', 'Kalecik'))
        self.assertEqual(self.kale.match_keys, 'L1:KALE')

    def test_yonetici_tam_yetki_kullanici_yalniz_okur(self):
        created = self.Area.with_user(self.manager).create({
            'provider': 'fixed', 'state_id': self.st('06').id, 'name': 'YENI', 'area_code': 999002})
        created.with_user(self.manager).unlink()
        with self.assertRaises(AccessError):
            self.kale.with_user(self.user).unlink()
        with self.assertRaises(AccessError):
            self.Area.with_user(self.plain).search([])

    def test_kullanici_eslemeyi_calistirabilir(self):
        found = self.Area.with_user(self.user)._match('fixed', self.st('20').with_user(self.user), 'Kale')
        self.assertEqual(found, self.kale)

    def test_gorunumler_ve_menu(self):
        for name in ('view_cargo_area_list', 'view_cargo_area_form', 'view_cargo_area_search'):
            self.assertTrue(self.env.ref('cargo.' + name))
        menu = self.env.ref('cargo.menu_cargo_area')
        self.assertEqual(menu.parent_id, self.env.ref('cargo.menu_cargo_config'))
        self.assertEqual(menu.action, self.env.ref('cargo.action_cargo_area'))
        self.assertIn(self.env.ref('cargo.group_cargo_manager'), menu.group_ids)

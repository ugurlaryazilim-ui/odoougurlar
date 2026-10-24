# -*- coding: utf-8 -*-
"""G1 birim testleri: delivery.carrier uzantısı (yönetilen firma, _cargo_call, rate kısıtı, ODP bayrak alanları)."""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CargoTestCase

COD_FIELDS = ('cargo_cod_enabled', 'cargo_cod_allow_cash', 'cargo_cod_allow_card', 'cargo_cod_allow_check')


@tagged('post_install', '-at_install', 'cargo')
class TestCarrierExtension(CargoTestCase):

    def test_odp_alanlari_gruplu_ve_sizdirmaz(self):
        """Alan listesiz read/search_read ve fields_get yetkisiz kullanıcıya ODP bayrağı vermez."""
        Carrier = self.env['delivery.carrier']
        # satış kullanıcısı delivery.zip.prefix gibi ilişkili modelleri de okuyabildiğinden alan listesiz okur
        row = self.carrier.with_user(self.plain_sales).read()[0]
        rows = Carrier.with_user(self.plain_sales).search_read([('id', '=', self.carrier.id)])
        for name in COD_FIELDS:
            self.assertNotIn(name, row, name)
            self.assertNotIn(name, rows[0], name)
        # kargo kullanıcısı yalnız firma kaydını okur (zip/kural tabloları yok): fields_get'ten türeyen liste
        described = self.carrier.with_user(self.user).fields_get()
        for name in COD_FIELDS:
            self.assertNotIn(name, described, name)
        plain_fields = [n for n, f in described.items() if f['type'] not in ('one2many', 'many2many')]
        row = self.carrier.with_user(self.user).read(plain_fields)[0]
        for name in COD_FIELDS:
            self.assertNotIn(name, row, name)

    def test_odp_alanlari_web_read_ve_arama(self):
        for user in (self.user, self.plain_sales):
            carrier = self.carrier.with_user(user)
            for name in COD_FIELDS:
                with self.assertRaises(AccessError, msg=name):
                    carrier.web_read({name: {}})
                with self.assertRaises(AccessError, msg=name):
                    self.env['delivery.carrier'].with_user(user).web_search_read(
                        [('id', '=', self.carrier.id)], {name: {}})
                with self.assertRaises(AccessError, msg=name):
                    # alana göre arama da değer sızdırır (varlık/yokluk)
                    self.env['delivery.carrier'].with_user(user).search([(name, '=', True)])

    def test_yonetici_odp_alanlarini_gorur(self):
        described = self.carrier.with_user(self.manager).fields_get()
        self.assertTrue(set(COD_FIELDS) <= set(described))
        row = self.carrier.with_user(self.manager).read(list(COD_FIELDS))[0]
        self.assertTrue(row['cargo_cod_enabled'])

    def test_kullanici_firma_yazamaz(self):
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.user).write({'name': 'Degisti'})
        with self.assertRaises(AccessError):
            self.env['delivery.carrier'].with_user(self.user).create({
                'name': 'Yeni', 'delivery_type': 'fixed', 'product_id': self._service_product().id})

    def test_yonetici_firma_olusturamaz_silemez(self):
        # NEDEN: kargo yöneticisi mevcut firmanın bayrak/kimlik alanlarını yazar; firma kaydı açıp silmek
        # satış yöneticisinin işidir (ACL 1,1,0,0).
        with self.assertRaises(AccessError):
            self.env['delivery.carrier'].with_user(self.manager).create({
                'name': 'Yeni', 'delivery_type': 'fixed', 'product_id': self._service_product().id})
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.manager).unlink()

    def test_yonetilen_firma_tipleri_ve_hesaplanan_alan(self):
        self.stub_provider('fixed', ops=('send',))
        self.assertIn('fixed', self.env['delivery.carrier']._cargo_managed_types())
        self.assertNotIn('base_on_rule', self.env['delivery.carrier']._cargo_managed_types())
        self.assertTrue(self.carrier.cargo_managed)
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        self.assertFalse(other.cargo_managed)

    def test_yonetilmeyen_tipte_cargo_call_user_error(self):
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        with self.assertRaises(UserError):
            other._cargo_call('send', 'x')

    def test_bilinmeyen_islem_reddedilir(self):
        # NEDEN: op dizgesi getattr'a gidiyor; yalnız bilinen sağlayıcı işlemleri çağrılabilir.
        self.stub_provider('fixed', ops=('send',))
        with self.assertRaises(UserError):
            self.carrier._cargo_call('unlink')
        with self.assertRaises(UserError):
            self.carrier._cargo_call('send_to_shipper')

    def test_cargo_call_argumanlari_iletir_prod_bayragi_engellemez(self):
        calls = self.stub_provider('fixed', ops=('send', 'cod_code'), result={'status': 'ok', 'tracking_ref': 'T'})
        self.assertFalse(self.carrier.prod_environment)
        self.assertEqual(self.carrier._cargo_call('send', 'kayit')['tracking_ref'], 'T')
        self.carrier.prod_environment = True
        self.carrier._cargo_call('cod_code', 'cash')
        self.assertEqual(calls, [('send', ('kayit',)), ('cod_code', ('cash',))])

    def test_rate_kisiti_yalniz_yonetilen_tipte(self):
        self.stub_provider('fixed', ops=('send',))
        with self.assertRaises(ValidationError):
            self.carrier.integration_level = 'rate_and_ship'
        # sağlayıcı yoksa (yönetilmeyen) rate_and_ship serbest kalır
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'integration_level': 'rate_and_ship',
            'product_id': self._service_product().id})
        self.assertEqual(other.integration_level, 'rate_and_ship')

    def test_onchange_yonetilen_tipte_rate_secer(self):
        self.stub_provider('fixed', ops=('send',))
        carrier = self.env['delivery.carrier'].new({'name': 'Yeni', 'integration_level': 'rate_and_ship'})
        carrier.delivery_type = 'fixed'
        carrier._onchange_delivery_type_cargo()
        self.assertEqual(carrier.integration_level, 'rate')

    def test_odp_varsayilanlari_yeni_firmada(self):
        fresh = self.env['delivery.carrier'].create({
            'name': 'Varsayilan', 'delivery_type': 'fixed', 'integration_level': 'rate',
            'product_id': self._service_product().id})
        self.assertEqual([fresh[name] for name in COD_FIELDS], [False, True, False, False])

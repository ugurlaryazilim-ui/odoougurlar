# -*- coding: utf-8 -*-
"""G1 birim testleri: şirket alanları ve kargo ayarları (sırsız ekran, set_values denetimi)."""
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import CargoTestCase

SETTING_FIELDS = ('cargo_default_carrier_id', 'cargo_default_weight', 'cargo_cod_max_amount', 'cargo_label_size')


@tagged('post_install', '-at_install', 'cargo')
class TestCargoSettings(CargoTestCase):

    def setUp(self):
        super().setUp()
        self.admin = self.env.ref('base.user_admin')
        self.Settings = self.env['res.config.settings']

    def test_default_get_normal_kullanici_kargo_odp_ve_kimlik_vermez(self):
        """Normal iç kullanıcı default_get'te yalnız sırsız ayar alanlarını görür; ODP bayrağı/kimlik anahtarı yok."""
        self.company.cargo_default_weight = 3.0
        for user in (self.plain, self.user, self.manager):
            res = self.Settings.with_user(user).default_get(list(self.Settings._fields))
            for key in res:
                self.assertFalse(key.startswith('cargo_cod_') and key != 'cargo_cod_max_amount',
                                 '%s default_get ODP bayrağı sızdırdı: %s' % (user.login, key))
                self.assertFalse('password' in key and key.startswith(('cargo', 'ups')), key)
            self.assertEqual(res.get('cargo_default_weight'), 3.0)

    def test_ayar_alanlari_related_degil(self):
        # NEDEN: related+readonly=False alan create sırasında şirkete yazar ve set_values denetimini atlatır.
        for name in SETTING_FIELDS:
            self.assertFalse(self.Settings._fields[name].related, name)

    def test_olusturma_sirkete_yazmaz(self):
        before = self.company.cargo_default_weight
        self.Settings.create({'cargo_default_weight': 9.0})
        self.assertEqual(self.company.cargo_default_weight, before)

    def test_bos_kume_set_values_yonetici_olmayana_kapali(self):
        """Boş kayıt kümesiyle set_values (RPC) yetkisiz kullanıcıda AccessError verir (denetim super'den önce)."""
        with self.assertRaises(AccessError):
            self.Settings.with_user(self.manager).browse().set_values()
        with self.assertRaises(AccessError):
            self.Settings.with_user(self.user).set_values()

    def test_set_values_yazar_ve_get_values_okur(self):
        self.Settings.with_user(self.admin).create({
            'cargo_default_carrier_id': self.carrier_y.id, 'cargo_default_weight': 2.5,
            'cargo_cod_max_amount': 1500.0, 'cargo_label_size': 'a4'}).set_values()
        self.assertEqual(self.company.cargo_default_carrier_id, self.carrier_y)
        self.assertEqual(self.company.cargo_default_weight, 2.5)
        self.assertEqual(self.company.cargo_cod_max_amount, 1500.0)
        values = self.Settings.get_values()
        self.assertEqual(values['cargo_default_carrier_id'], self.carrier_y.id)
        self.assertEqual(values['cargo_label_size'], 'a4')
        self.assertEqual(self.Settings.create({}).cargo_default_weight, 2.5)

    def test_varsayilan_firma_temizlenebilir(self):
        self.Settings.with_user(self.admin).create({'cargo_default_carrier_id': False}).set_values()
        self.assertFalse(self.company.cargo_default_carrier_id)

    def test_varsayilan_firma_domaini_yonetilenlerle_sinirli(self):
        self.stub_provider('fixed', ops=('send',))
        for model in ('res.company', 'res.config.settings'):
            domain = self.env[model].fields_get(['cargo_default_carrier_id'])['cargo_default_carrier_id']['domain']
            self.assertEqual(domain, [('delivery_type', 'in', ['fixed'])], model)

    def test_sirket_degerleri_dogrulanir(self):
        with self.assertRaises(ValidationError):
            self.company.cargo_default_weight = 0.0
        with self.assertRaises(ValidationError):
            self.company.cargo_cod_max_amount = -1.0
        self.company.cargo_cod_max_amount = 0.0   # 0 = sınırsız geçerli

    def test_ayar_ekraninda_sir_alani_yok(self):
        names = [f for f in self.Settings._fields if f.startswith('cargo')]
        self.assertEqual(sorted(names), sorted(SETTING_FIELDS + ('cargo_currency_id',)))

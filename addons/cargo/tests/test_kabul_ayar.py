# -*- coding: utf-8 -*-
"""KABUL: gruplar, ayarlar, kargo firmasi uzantisi (KK-2 cekirdek, KK-19b/19c bayraklari, KK-33 zemini).

Yesile donecegi gorev: G1 (cargo iskeleti, gruplar, ayarlar, carrier uzantisi).
"""
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .kabul_taban import CargoKabulCase

SIR_ANAHTAR = ('password', 'passwd', 'username', 'secret', 'token', 'session', 'customer_number', 'shipper_account')


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulGruplarAyarlar(CargoKabulCase):
    REQUIRES_MODELS = ()   # G1 testleri: yalniz gruplar + company alanlari

    def _implied(self, group):
        return group.all_implied_ids if 'all_implied_ids' in group._fields else group.implied_ids

    def test_grup_yapisi(self):
        """KK-2 zemini: yonetici kullaniciyi icerir, kullanici base.group_user'i icerir, group_system'e eklenmez."""
        user_g = self.env.ref('cargo.group_cargo_user')
        mgr_g = self.env.ref('cargo.group_cargo_manager')
        self.assertIn(self.env.ref('base.group_user'), self._implied(user_g))
        self.assertIn(user_g, self._implied(mgr_g))
        self.assertNotIn(mgr_g, self._implied(user_g))
        admin = self.env.ref('base.user_admin')
        self.assertFalse(admin.has_group('cargo.group_cargo_user'),
                         'base.group_system kargo gruplarina OTOMATIK eklenmemeli (yonetici elle atar)')
        self.assertTrue(self.user.has_group('cargo.group_cargo_user'))
        self.assertFalse(self.user.has_group('cargo.group_cargo_manager'))
        self.assertTrue(self.manager.has_group('cargo.group_cargo_user'))
        self.assertTrue(self.manager.has_group('cargo.group_cargo_manager'))

    def test_sirket_ayar_varsayilanlari(self):
        company = self.env['res.company'].create({'name': 'Yeni Kabul Firmasi'})
        self.assertFalse(company.cargo_default_carrier_id)
        self.assertEqual(company.cargo_default_weight, 1.0)
        self.assertEqual(company.cargo_cod_max_amount, 0.0)
        self.assertEqual(company.cargo_label_size, '10x15')
        values = [v for v, _l in self.env['res.company']._fields['cargo_label_size']._description_selection(self.env)]
        self.assertEqual(sorted(values), ['10x15', 'a4'])

    def test_ayar_ekraninda_sir_yok(self):
        """KK-2 (cekirdek): res.config.settings sir tasimaz; default_get/alan listesinde sir anahtari yok."""
        Settings = self.env['res.config.settings']
        cargo_fields = [f for f in Settings._fields if f.startswith('cargo')]
        self.assertTrue(cargo_fields, 'res.config.settings uzerinde cargo_* ayar alanlari bulunmali')
        for field in cargo_fields:
            for needle in SIR_ANAHTAR:
                self.assertNotIn(needle, field, 'ayar ekraninda sir alani olmamali: %s' % field)
        defaults = Settings.with_user(self.manager).default_get(list(Settings._fields))
        for key in defaults:
            if key.startswith('cargo'):
                for needle in SIR_ANAHTAR:
                    self.assertNotIn(needle, key)

    def test_ayar_yazimi_yalniz_sistem_yoneticisi(self):
        """set_values super()'den ONCE base.group_system denetler; kargo yoneticisi sirket ayarini degistiremez."""
        Settings = self.env['res.config.settings']
        before = self.company.cargo_default_weight
        settings = Settings.create({'cargo_default_weight': 7.5})
        with self.assertRaises(AccessError):
            settings.with_user(self.manager).set_values()
        self.assertEqual(self.company.cargo_default_weight, before, 'yetkisiz set_values sirket degerini degistirmemeli')
        admin = self.env.ref('base.user_admin')
        settings_admin = Settings.with_user(admin).create({'cargo_default_weight': 7.5})
        settings_admin.set_values()
        self.assertEqual(self.company.cargo_default_weight, 7.5)

    def test_ayar_geri_yazimi_degeri_silmez(self):
        """cargo_cod_max_amount=0 (sinirsiz) geri yazimi mevcut degeri silmez/bozmaz: 0 gecerli bir degerdir."""
        admin = self.env.ref('base.user_admin')
        Settings = self.env['res.config.settings'].with_user(admin)
        self.company.cargo_cod_max_amount = 300.0
        Settings.create({'cargo_cod_max_amount': 0.0}).set_values()
        self.assertEqual(self.company.cargo_cod_max_amount, 0.0)
        Settings.create({'cargo_cod_max_amount': 450.0}).set_values()
        self.assertEqual(self.company.cargo_cod_max_amount, 450.0)

    def test_ayar_varsayilan_firma_ve_etiket_boyutu(self):
        admin = self.env.ref('base.user_admin')
        Settings = self.env['res.config.settings'].with_user(admin)
        Settings.create({'cargo_default_carrier_id': self.carrier_y.id, 'cargo_label_size': 'a4'}).set_values()
        self.assertEqual(self.company.cargo_default_carrier_id, self.carrier_y)
        self.assertEqual(self.company.cargo_label_size, 'a4')


@tagged('post_install', '-at_install', 'cargo', 'cargo_kabul')
class TestKabulKargoFirmasi(CargoKabulCase):
    REQUIRES_MODELS = ()

    def test_odp_bayrak_varsayilanlari(self):
        """KK-19b/19c: cekirdek ODP etkin DEGIL; nakit True / kart False / cek False varsayilan."""
        fresh = self.env['delivery.carrier'].create({
            'name': 'Varsayilan', 'delivery_type': 'fixed', 'integration_level': 'rate',
            'product_id': self._service_product().id})
        self.assertFalse(fresh.cargo_cod_enabled)
        self.assertTrue(fresh.cargo_cod_allow_cash)
        self.assertFalse(fresh.cargo_cod_allow_card)
        self.assertFalse(fresh.cargo_cod_allow_check)

    def test_odp_bayraklari_yalniz_yonetici(self):
        """Bayrak alanlari groups=cargo.group_cargo_manager: kargo kullanicisi okuyamaz ve yazamaz."""
        for field in ('cargo_cod_enabled', 'cargo_cod_allow_cash', 'cargo_cod_allow_card', 'cargo_cod_allow_check'):
            with self.assertRaises(AccessError, msg='kullanici %s okuyamamali' % field):
                self.carrier.with_user(self.user).read([field])
            with self.assertRaises(AccessError, msg='duz kullanici %s okuyamamali' % field):
                self.carrier.with_user(self.plain_sales).read([field])
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.user).write({'cargo_cod_enabled': False})
        # yonetici okur ve yazar
        self.assertTrue(self.carrier.with_user(self.manager).read(['cargo_cod_enabled'])[0]['cargo_cod_enabled'])
        self.carrier.with_user(self.manager).write({'cargo_cod_allow_card': True})
        self.assertTrue(self.carrier.cargo_cod_allow_card)

    def test_kargo_kullanicisi_firmayi_okur(self):
        """Gonderi formunda firma secilebilmeli: cargo kullanicisi delivery.carrier adini okuyabilmeli (ACL cargo'dan)."""
        data = self.carrier.with_user(self.user).read(['name', 'delivery_type'])
        self.assertEqual(data[0]['name'], self.carrier.name)

    def test_yonetilen_firma_tespiti(self):
        Carrier = self.env['delivery.carrier']
        managed = self.carrier._cargo_is_managed()
        self.assertTrue(managed, 'fixed icin <tip>_cargo_send tanimli (sahte saglayici) -> yonetilen')
        other = Carrier.create({'name': 'Kural tabanli', 'delivery_type': 'base_on_rule',
                                'product_id': self._service_product().id})
        self.assertFalse(other._cargo_is_managed(), '<tip>_cargo_send tanimsiz firma yonetilen sayilmaz')

    def test_cargo_call_yonetilmeyen_firma(self):
        other = self.env['delivery.carrier'].create({
            'name': 'Kural tabanli', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        shipment = self.mk()
        with self.assertRaises(Exception) as ctx:
            other._cargo_call('send', shipment)
        self.assertNotIsInstance(ctx.exception, AssertionError)
        self.assertTrue(type(ctx.exception).__name__ in ('UserError', 'ValidationError', 'AccessError'),
                        'yonetilmeyen firmada _cargo_call UserError olmali, gelen: %r' % ctx.exception)

    def test_cargo_call_test_ortami_engellemez(self):
        """prod_environment kapaliyken _cargo_call ENGELLEMEZ (test ucu zaten ayri; K-26)."""
        self.assertFalse(self.carrier.prod_environment)
        shipment = self.mk()
        result = self.carrier._cargo_call('send', shipment)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.provider.count('send'), 1)

    def test_cargo_call_yonlendirme_saglayiciya(self):
        shipment = self.mk()
        self.carrier._cargo_call('find', shipment)
        self.carrier._cargo_call('cancel', shipment)
        self.assertEqual([c['op'] for c in self.provider.calls], ['find', 'cancel'])
        self.assertTrue(all(c['carrier_id'] == self.carrier.id for c in self.provider.calls))

    def test_yonetilen_firmada_rate_zorunlu(self):
        """Yonetilen firma integration_level='rate' olmali (create/write/delivery_type degisimi) -> KK-33 zemini."""
        Carrier = self.env['delivery.carrier']
        pid = self._service_product().id
        with self.assertRaises(ValidationError):
            Carrier.create({'name': 'Hatali', 'delivery_type': 'fixed', 'integration_level': 'rate_and_ship',
                            'product_id': pid})
        with self.assertRaises(ValidationError):
            self.carrier.write({'integration_level': 'rate_and_ship'})
        self.assertEqual(self.carrier.integration_level, 'rate')
        # yonetilmeyen tipte rate_and_ship serbest; sonra yonetilen tipe cevirme reddedilir
        other = Carrier.create({'name': 'Kural', 'delivery_type': 'base_on_rule', 'integration_level': 'rate_and_ship',
                                'product_id': pid})
        with self.assertRaises(ValidationError):
            other.write({'delivery_type': 'fixed'})

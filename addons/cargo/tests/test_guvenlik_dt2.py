# -*- coding: utf-8 -*-
"""05-guvenlik D-5 / 05-inceleme Y2: yönetilen firmanın şirketi teslimat ürünü yoluyla değiştirilemez.

``delivery.carrier.company_id`` = ``product_id.company_id`` (saklanan related). PoC: ürün yöneticisi ürünün şirketini
yazınca firma şirketi carrier.write'a uğramadan değişiyordu; aynı ürünü kullanan yönetilmeyen firmanın company_id
yazımı da (related inverse) ürünü, dolayısıyla yönetilen firmayı değiştiriyordu.
"""
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from .kabul_taban import CargoKabulCase

_DENIED = 'yalnız "Kargo / Yönetici"'


@tagged('post_install', '-at_install', 'cargo')
class TestGuvenlikDt2UrunSirketi(CargoKabulCase):

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.co2 = cls.env['res.company'].create({'name': 'DT2 Sirket 2'})
        companies = [(6, 0, [cls.company.id, cls.co2.id])]
        cls.product_manager = new_test_user(
            cls.env, login='dt2_urun', groups='base.group_user,product.group_product_manager,stock.group_stock_manager',
            company_id=cls.company.id, company_ids=companies)
        cls.cargo_product_manager = new_test_user(
            cls.env, login='dt2_kargo_urun', groups='base.group_user,product.group_product_manager,cargo.group_cargo_manager',
            company_id=cls.company.id, company_ids=companies)
        cls.delivery_product = cls.carrier.product_id
        # yönetilmeyen (Odoo kural tabanlı) firma, yönetilen firmayla aynı teslimat ürünü
        cls.unmanaged = cls.env['delivery.carrier'].create({
            'name': 'DT2 kural', 'delivery_type': 'base_on_rule', 'product_id': cls.delivery_product.id})

    def setUp(self):
        super().setUp()
        self.assertTrue(self.carrier._cargo_is_managed(), 'ön koşul')
        self.assertFalse(self.unmanaged._cargo_is_managed(), 'ön koşul')
        self.before = self.carrier.company_id

    def test_urun_sirketi_sablondan_degistirilemez(self):
        template = self.delivery_product.product_tmpl_id.with_user(self.product_manager)
        with self.assertRaisesRegex(AccessError, _DENIED):
            template.write({'company_id': self.co2.id})
        self.assertEqual(self.carrier.company_id, self.before)

    def test_urun_sirketi_varyanttan_degistirilemez(self):
        with self.assertRaisesRegex(AccessError, _DENIED):
            self.delivery_product.with_user(self.product_manager).write({'company_id': self.co2.id})
        self.assertEqual(self.carrier.company_id, self.before)

    def test_urun_sirketi_yonetilmeyen_firma_uzerinden_degistirilemez(self):
        unmanaged = self.unmanaged.with_user(self.product_manager)
        with self.assertRaisesRegex(AccessError, _DENIED):
            unmanaged.write({'company_id': self.co2.id})
        self.assertEqual(self.carrier.company_id, self.before)
        # yönetilmeyen firmanın diğer alanları serbest (kardeş yol bozulmaz)
        unmanaged.write({'name': 'DT2 kural 2'})

    def test_urun_sirketi_arsivli_firma_da_korunur(self):
        self.carrier.active = False
        with self.assertRaisesRegex(AccessError, _DENIED):
            self.delivery_product.with_user(self.product_manager).write({'company_id': self.co2.id})

    def test_urun_sirketi_kargo_yoneticisi_ve_su_degistirebilir(self):
        self.delivery_product.with_user(self.cargo_product_manager).write({'company_id': self.co2.id})
        self.assertEqual(self.carrier.company_id, self.co2)
        self.delivery_product.with_user(self.product_manager).sudo().write({'company_id': False})
        self.assertFalse(self.carrier.company_id)

    def test_ilgisiz_urun_ve_ayni_deger_etkilenmez(self):
        other = self.env['product.product'].create({'name': 'DT2 ilgisiz', 'type': 'service'})
        other.with_user(self.product_manager).write({'company_id': self.co2.id})
        self.assertEqual(other.company_id, self.co2)
        # değişmeyen değer yazımı (form/içe aktarma) engellenmez
        self.delivery_product.product_tmpl_id.with_user(self.product_manager).write(
            {'company_id': self.before.id, 'name': self.delivery_product.name})

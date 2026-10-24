# -*- coding: utf-8 -*-
"""05-guvenlik O-1 (çekirdek denetimi, cargo/models/delivery_carrier.py) UPS firmasıyla: stok/satış yöneticisi
UPS firmasının test/canlı bayrağını yazamaz, UPS firması açamaz/silemez/çoğaltamaz; Kargo / Yönetici yazar."""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'cargo_ups')
class TestUpsCarrierGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ups = cls.env.ref('cargo_ups.carrier_ups_tr')
        cls.stock_manager = new_test_user(
            cls.env, login='o1u_stok', groups='base.group_user,stock.group_stock_manager')
        cls.sale_manager = new_test_user(
            cls.env, login='o1u_satis', groups='base.group_user,sales_team.group_sale_manager')
        cls.stock_cargo_manager = new_test_user(
            cls.env, login='o1u_stok_kargo', groups='base.group_user,stock.group_stock_manager,cargo.group_cargo_manager')

    def test_stok_satis_yoneticisi_ups_firmasina_dokunamaz(self):
        vals = {'name': 'Ikinci UPS', 'delivery_type': 'ups_tr', 'integration_level': 'rate',
                'product_id': self.ups.product_id.id}
        for user in (self.stock_manager, self.sale_manager):
            with self.subTest(user=user.login):
                for field, value in (('prod_environment', True), ('active', False), ('delivery_type', 'fixed')):
                    with self.assertRaises(AccessError, msg=field):
                        self.ups.with_user(user).write({field: value})
                with self.assertRaises(AccessError):
                    self.env['delivery.carrier'].with_user(user).create(dict(vals))
                with self.assertRaises(AccessError):
                    self.ups.with_user(user).copy()
                with self.assertRaises(AccessError):
                    self.ups.with_user(user).unlink()
        self.assertFalse(self.ups.prod_environment)
        self.assertTrue(self.ups.active)

    def test_kargo_yoneticisi_ups_firmasini_yonetir(self):
        self.ups.with_user(self.stock_cargo_manager).write({'prod_environment': True})
        self.assertTrue(self.ups.prod_environment)
        copy = self.ups.with_user(self.stock_cargo_manager).copy()
        self.assertEqual(copy.delivery_type, 'ups_tr')
        # NEDEN: sırlar copy=False (kopyalanan firma hesap bilgisi taşımaz)
        self.assertFalse(copy.sudo().ups_tr_password)

    def test_stok_yoneticisi_yonetilmeyen_firmayi_cogaltir(self):
        """UPS hizmet alanları (groups) yüklüyken başka bir firmanın kopyası AccessError vermez."""
        free = self.env['delivery.carrier'].create({
            'name': 'Serbest', 'delivery_type': 'base_on_rule', 'product_id': self.ups.product_id.id})
        copy = free.with_user(self.stock_manager).copy()
        self.assertEqual(copy.delivery_type, 'base_on_rule')

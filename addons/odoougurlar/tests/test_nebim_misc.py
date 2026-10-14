# -*- coding: utf-8 -*-
"""Barkod eşleşmesi, ayarlar ve kuyruk/cron düzeltmeleri."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestNebimMisc(TransactionCase):

    def test_nebim_barcode_list_needs_exact_element(self):
        Product = self.env['product.product']
        target = Product.create({'name': 'Liste Ürünü', 'nebim_barcode': '8690000000011,8690000000028'})
        Product.create({'name': 'Başka Ürün', 'nebim_barcode': '8690000000035'})
        self.assertEqual(Product.find_by_marketplace_barcode('8690000000028'), target)
        # Kısmi kod başka ürünün barkodunun içinde geçse de eşleşmez
        self.assertFalse(Product.find_by_marketplace_barcode('86900000000'))

    def test_stock_interval_has_no_seconds_option(self):
        field = self.env['res.config.settings']._fields['nebim_stock_sync_interval']
        values = [v for v, _label in field.selection]
        self.assertNotIn('30', values)
        self.assertNotIn('45', values)

    def test_settings_keep_deprecated_product_cron_off(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('odoougurlar.nebim_auto_sync', 'True')
        ICP.set_param('odoougurlar.nebim_sync_mode', 'hourly')
        self.env['res.config.settings'].nebim_apply_configured_crons()
        auto = self.env.ref('odoougurlar.cron_auto_product_sync')
        daily = self.env.ref('odoougurlar.cron_product_sync')
        self.assertTrue(auto.active)
        self.assertEqual(auto.interval_type, 'hours')
        self.assertFalse(daily.active)

    def test_mapping_lookup_sees_new_rule_without_cache(self):
        Mapping = self.env['odoougurlar.marketplace.mapping']
        self.assertFalse(Mapping.find_mapping('ZzTestPazar'))
        rule = Mapping.create({'name': 'Test Kural', 'marketplace': 'ZzTestPazar'})
        self.assertEqual(Mapping.find_mapping('ZzTestPazar'), rule)

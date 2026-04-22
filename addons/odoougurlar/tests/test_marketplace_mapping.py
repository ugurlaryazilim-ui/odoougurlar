# -*- coding: utf-8 -*-
"""Marketplace Mapping — Temel testler."""
from odoo.tests.common import TransactionCase


class TestMarketplaceMapping(TransactionCase):
    """marketplace_mapping.py temel akış testleri."""

    def setUp(self):
        super().setUp()
        self.Mapping = self.env['odoougurlar.marketplace.mapping']

    # -----------------------------------------------------------------
    #  find_mapping
    # -----------------------------------------------------------------
    def test_find_mapping_basic(self):
        """Global (ülkesiz) mapping bulunabilmeli."""
        mapping = self.Mapping.create({
            'name': 'Test Mapping',
            'marketplace': 'Trendyol',
            'nebim_customer_code': 'TY001',
        })
        found = self.Mapping.find_mapping('Trendyol')
        self.assertEqual(found.id, mapping.id)

    def test_find_mapping_country_priority(self):
        """Ülke eşleşmesi global eşleşmeden öncelikli olmalı."""
        tr = self.env['res.country'].search([('code', '=', 'TR')], limit=1)
        az = self.env['res.country'].search([('code', '=', 'AZ')], limit=1)

        global_mapping = self.Mapping.create({
            'name': 'Trendyol Global',
            'marketplace': 'Trendyol',
            'nebim_customer_code': 'TY-GLOBAL',
        })
        az_mapping = self.Mapping.create({
            'name': 'Trendyol AZ',
            'marketplace': 'Trendyol',
            'country_id': az.id if az else False,
            'nebim_customer_code': 'TY-AZ',
        })

        # Ülke belirtilmezse global dönmeli
        found = self.Mapping.find_mapping('Trendyol')
        self.assertEqual(found.nebim_customer_code, 'TY-GLOBAL')

        # AZ ülkesi belirtilirse AZ mapping dönmeli
        if az:
            found = self.Mapping.find_mapping('Trendyol', az.id)
            self.assertEqual(found.nebim_customer_code, 'TY-AZ')

    def test_find_mapping_not_found(self):
        """Olmayan marketplace için False dönmeli."""
        found = self.Mapping.find_mapping('BilinmeyenPazar')
        self.assertFalse(found)

    # -----------------------------------------------------------------
    #  Cache
    # -----------------------------------------------------------------
    def test_cache_clear_on_write(self):
        """Mapping değiştiğinde cache temizlenmeli."""
        mapping = self.Mapping.create({
            'name': 'Cache Test',
            'marketplace': 'TestMP',
            'nebim_customer_code': 'OLD',
        })
        # İlk lookup — cache oluşur
        found = self.Mapping.find_mapping('TestMP')
        self.assertEqual(found.nebim_customer_code, 'OLD')

        # Güncelle — cache temizlenir
        mapping.write({'nebim_customer_code': 'NEW'})
        found = self.Mapping.find_mapping('TestMP')
        self.assertEqual(found.nebim_customer_code, 'NEW')

    # -----------------------------------------------------------------
    #  Default Değerler
    # -----------------------------------------------------------------
    def test_default_values(self):
        """Mapping oluşturulduğunda varsayılan değerler doğru olmalı."""
        mapping = self.Mapping.create({
            'name': 'Default Test',
            'marketplace': 'Trendyol',
        })
        self.assertEqual(mapping.delivery_company_code, 'YRT')
        self.assertEqual(mapping.store_code, '002')
        self.assertEqual(mapping.warehouse_code, '002')
        self.assertEqual(mapping.payment_agent, 'TrendyolMp')
        self.assertEqual(mapping.sales_url, 'www.trendyol.com')

# -*- coding: utf-8 -*-
"""base_api._find_product: nebim_barcode liste içi TAM eşleşme ifade indeksiyle (denetim H1)."""
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import product_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestFindProductNebimIndex(BarcodeCase):

    def setUp(self):
        super().setUp()
        self._patch_request(product_api)
        self.ctl = product_api.ProductApiController()
        self.only_nebim = self.env['product.product'].create(
            {'name': 'H1 Liste', 'nebim_barcode': 'H1-A1, H1-A2,H1-A3'})
        self.env['product.product'].create({'name': 'H1 Alt Dize', 'nebim_barcode': 'H1-A1999'})

    def test_exact_element_found_substring_not(self):
        for code in ('H1-A1', 'H1-A2', 'H1-A3'):
            self.assertEqual(self.ctl._find_product(code), self.only_nebim, code)
        self.assertFalse(self.ctl._find_product('H1-A19'))

    def test_barcode_wins_over_nebim_barcode(self):
        winner = self.env['product.product'].create({'name': 'H1 Barkod', 'barcode': 'H1-A2'})
        self.assertEqual(self.ctl._find_product('H1-A2'), winner)

    def test_default_code_fallback_and_single_exact_query(self):
        by_code = self.env['product.product'].create({'name': 'H1 Kod', 'default_code': 'H1-KOD'})
        self.assertEqual(self.ctl._find_product('H1-KOD'), by_code)
        # nebim_barcode araması TEK sorgudur (eskiden `=` + `ilike` + Python süzme)
        with self.assertQueryCount(__system__=6):
            self.ctl._find_product('H1-A3')

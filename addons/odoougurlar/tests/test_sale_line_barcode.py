# -*- coding: utf-8 -*-
"""Satış siparişi satırlarında Barkod sütunu: ürünün barkodu, formda ürünün sağında."""
from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSaleLineBarcode(TransactionCase):

    def test_line_shows_product_barcode(self):
        partner = self.env['res.partner'].create({'name': 'Barkod Müşteri'})
        product = self.env['product.product'].create({
            'name': 'Barkod Ürün', 'type': 'consu', 'barcode': '8690000000017'})
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})],
        })
        line = order.order_line
        self.assertEqual(line.product_barcode, '8690000000017')

        product.barcode = '8690000000024'
        self.assertEqual(line.product_barcode, '8690000000024', 'Saklanmaz, ürünle güncel kalır')

    def test_form_has_barcode_column_after_product(self):
        arch = self.env['sale.order'].get_view(
            self.env.ref('sale.view_order_form').id, 'form')['arch']
        cols = [f.get('name') for f in etree.fromstring(arch).xpath(
            "//field[@name='order_line']/list/field")]
        self.assertIn('product_barcode', cols)
        self.assertEqual(cols.index('product_barcode'), cols.index('product_template_id') + 1)

# -*- coding: utf-8 -*-
"""Satış listesindeki Fatura Tarihi: ilk onaylı müşteri faturasının Nebim gönderim anı."""
from datetime import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestInvoiceDatetime(TransactionCase):

    def test_invoice_datetime_follows_posted_invoice(self):
        partner = self.env['res.partner'].create({'name': 'Fatura Tarihi Müşteri'})
        product = self.env['product.product'].create({
            'name': 'Fatura Tarihi Ürün', 'type': 'service', 'invoice_policy': 'order', 'list_price': 100.0})
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})],
        })
        order.action_confirm()
        self.assertFalse(order.invoice_datetime)

        invoice = order._create_invoices()
        self.assertFalse(order.invoice_datetime, 'Taslak fatura sayılmaz')

        invoice.action_post()
        self.assertEqual(order.invoice_datetime, invoice.create_date)

        sent = datetime(2026, 10, 16, 9, 17, 0)
        invoice.nebim_sent_date = sent
        self.assertEqual(order.invoice_datetime, sent)

        invoice.button_draft()
        self.assertFalse(order.invoice_datetime)

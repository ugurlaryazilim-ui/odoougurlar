# -*- coding: utf-8 -*-
"""Yutulan yazma hatası transaction'ı bozmamalı (savepoint'siz `except: pass` kalıbı)."""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSavepointSwallow(TransactionCase):

    def test_failed_status_write_does_not_abort_transaction(self):
        order = self.env['sale.order'].create({
            'partner_id': self.env['res.partner'].create({'name': 'Savepoint Test'}).id,
        })

        def broken_write(*_args, **_kwargs):
            # Ham SQL hatası PostgreSQL transaction'ını aborted yapar (savepoint yoksa kalıcı)
            self.env.cr.execute("SELECT 1/0")

        with patch.object(type(order), 'write', broken_write):
            order._nebim_safe_write(order, {'nebim_order_response': 'x'})

        # Savepoint geri alındı: sonraki sorgu InFailedSqlTransaction vermemeli
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone()[0], 1)
        # Başarılı yol: yazma gerçekten yapılır
        order._nebim_safe_write(order, {'nebim_order_response': 'tamam'})
        order.invalidate_recordset(['nebim_order_response'])
        self.assertEqual(order.nebim_order_response, 'tamam')

# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ugurlar_barcode')
class TestOperationGc(TransactionCase):
    """J6 / TODO-31: operasyon kaydı temizliği 10 bin/gün sınırında kalmaz; parça parça + süre bütçesi."""

    def setUp(self):
        super().setUp()
        self.Op = self.env['ugurlar.barcode.operation']

    def _make(self, op_type, days_ago, n):
        ops = self.Op.create([{'operation_type': op_type} for _ in range(n)])
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ugurlar_barcode_operation SET create_date = now() at time zone 'utc' - %s * interval '1 day' "
            "WHERE id IN %s", [days_ago, tuple(ops.ids)])
        ops.invalidate_recordset()
        return ops

    def test_gc_drains_more_than_one_batch_in_a_single_run(self):
        old_search = self._make('search', 100, 5)
        recent = self._make('search', 1, 2)
        old_write = self._make('putaway', 200, 3)
        with patch.object(type(self.Op), 'GC_BATCH', 2):
            self.Op._gc_old_operations()
        self.assertFalse(old_search.exists(), 'eski okuma kayıtları tek turda (3 parça) silinmeli')
        self.assertFalse(old_write.exists())
        self.assertEqual(len(recent.exists()), 2)

    def test_gc_stops_at_time_budget(self):
        old_search = self._make('search', 100, 5)
        with patch.object(type(self.Op), 'GC_TIME_BUDGET', 0):
            self.Op._gc_old_operations()
        self.assertEqual(len(old_search.exists()), 5)

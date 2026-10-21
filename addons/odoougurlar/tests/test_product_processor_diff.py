# -*- coding: utf-8 -*-
"""Nebim ürün senkronu: karşılaştırmalı write, toplu nebim_last_sync, kısıtlı cache."""
import json
from unittest.mock import patch

from odoo import fields
from odoo.addons.odoougurlar.processors import product_processor as pp
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestProductProcessorDiff(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.processor = cls.env['odoougurlar.product.processor']
        cls.Template = cls.env['product.template']
        cls.Product = cls.env['product.product']
        cls.rows = [
            {
                'ItemCode': 'H2-TST1', 'ItemDescription': 'H2 Test Ürün', 'Price': 100,
                'VatRate': 10, 'ColorDescription': 'H2Kirmizi', 'ColorCode': '01',
                'ItemDim1Code': size, 'ItemSku': 'H2-SKU-' + size,
                'Barcode1': 'H2B000' + size, 'ProductAtt04Desc': 'H2 Kategori',
                'ProductAtt06Desc': 'H2Marka',
            }
            for size in ('S', 'M')
        ]

    def _sync(self, rows=None, defer=False):
        self.processor._init_cache()
        return self.processor._process_product_group(
            'H2-TST1', rows or self.rows, defer_last_sync=defer)

    def _writes(self, fn):
        """fn çalışırken template ve varyant write çağrılarının (model, vals) listesi."""
        calls = []
        orig_t, orig_p = type(self.Template).write, type(self.Product).write

        def spy(orig):
            def wrapper(rec, vals):
                calls.append((rec._name, dict(vals)))
                return orig(rec, vals)
            return wrapper

        with patch.object(type(self.Template), 'write', spy(orig_t)), \
                patch.object(type(self.Product), 'write', spy(orig_p)):
            fn()
        return calls

    def test_create_then_unchanged_no_write(self):
        self.assertEqual(self._sync(), 'created')
        tmpl = self.Template.search([('nebim_code', '=', 'H2-TST1')])
        self.assertEqual(len(tmpl.product_variant_ids), 2)
        self.assertEqual(
            sorted(tmpl.product_variant_ids.mapped('default_code')), ['H2-SKU-M', 'H2-SKU-S'])
        self.assertEqual(len(tmpl.taxes_id), 1)

        calls = self._writes(self._sync)
        # Değişen yok: ne template ne varyant write (M2M vergi kümeleri de aynı)
        self.assertEqual(calls, [])

    def test_changed_price_writes_only_that_field(self):
        self._sync()
        tmpl = self.Template.search([('nebim_code', '=', 'H2-TST1')])
        rows = [dict(r, Price=150) for r in self.rows]
        calls = self._writes(lambda: self._sync(rows))
        self.assertEqual(calls, [('product.template', {'list_price': 150.0})])
        self.assertEqual(tmpl.list_price, 150.0)

    def test_changed_variant_field_writes_only_that_field(self):
        self._sync()
        variant = self.Product.search([('default_code', '=', 'H2-SKU-S')])
        variant.write({'nebim_barcode': 'ESKI'})
        calls = self._writes(self._sync)
        self.assertEqual(calls, [('product.product', {'nebim_barcode': 'H2B000S'})])
        self.assertEqual(variant.nebim_barcode, 'H2B000S')

    def test_changed_tax_set_is_written(self):
        self._sync()
        tmpl = self.Template.search([('nebim_code', '=', 'H2-TST1')])
        tmpl.taxes_id = [(5, 0, 0)]
        calls = self._writes(self._sync)
        self.assertEqual([c[0] for c in calls], ['product.template'])
        self.assertEqual(list(calls[0][1]), ['taxes_id'])
        self.assertEqual(len(tmpl.taxes_id), 1)

    def test_last_sync_deferred_then_bulk_flushed(self):
        self._sync()
        tmpl = self.Template.search([('nebim_code', '=', 'H2-TST1')])
        old = fields.Datetime.from_string('2020-01-01 00:00:00')
        self.env.cr.execute(
            "UPDATE product_template SET nebim_last_sync = %s WHERE id = %s", [old, tmpl.id])
        tmpl.invalidate_recordset(['nebim_last_sync'])

        self._sync(defer=True)
        tmpl.invalidate_recordset(['nebim_last_sync'])
        self.assertEqual(tmpl.nebim_last_sync, old)  # parti sonunu bekler

        self.processor._flush_last_sync()
        self.assertGreater(tmpl.nebim_last_sync, old)

        # Ertelemesiz yol hemen yazar
        self.env.cr.execute(
            "UPDATE product_template SET nebim_last_sync = %s WHERE id = %s", [old, tmpl.id])
        tmpl.invalidate_recordset(['nebim_last_sync'])
        self._sync(defer=False)
        self.assertGreater(tmpl.nebim_last_sync, old)

    def test_restricted_cache_loads_only_batch_barcodes(self):
        self.Product.create({'name': 'H2 BC1', 'barcode': 'H2-ONLY-A'})
        self.Product.create({'name': 'H2 BC2', 'barcode': 'H2-ONLY-B'})
        self.processor._init_cache([{'Barcode1': 'H2-ONLY-A', 'Barcode2': ' H2-YOK '}])
        try:
            self.assertEqual(pp._CACHE['barcodes'], {'H2-ONLY-A'})
            self.assertTrue(pp._CACHE['restricted'])
        finally:
            self.processor._reset_cache()
        self.assertFalse(pp._CACHE['loaded'])

    def test_restricted_cache_existing_value_not_duplicated(self):
        self._sync()
        count = self.env['product.attribute.value'].search_count([('name', '=', 'H2Kirmizi')])
        self.processor._init_cache(self.rows)
        try:
            self.processor._process_product_group('H2-TST1', self.rows, defer_last_sync=True)
        finally:
            self.processor._reset_cache()
        self.assertEqual(
            self.env['product.attribute.value'].search_count([('name', '=', 'H2Kirmizi')]), count)
        self.assertEqual(
            self.env['product.category'].search_count([('name', '=', 'H2 Kategori')]), 1)


@tagged('post_install', '-at_install')
class TestQueueBadRecord(TransactionCase):

    def test_bad_record_errors_alone_rest_of_batch_processed(self):
        """Bozuk kayıt (dict, [None], str olmayan alan) yalnız kendisi error olur."""
        Queue = self.env['odoougurlar.product.queue'].sudo()
        Queue.search([]).unlink()
        good_row = {'ItemCode': 'H2-BAD-OK', 'ItemDescription': 'Iyi', 'Price': 10,
                    'ColorDescription': 'H2BadRenk', 'ItemDim1Code': 'S',
                    'Barcode1': 'H2BAD0001'}
        raw = {
            'H2-BAD-DICT': {'ItemCode': 'H2-BAD-DICT'},
            'H2-BAD-NULL': [None],
            'H2-BAD-INT': [{'ItemCode': 'H2-BAD-INT', 'ColorDescription': 5,
                            'Barcode1': 123}],
            'H2-BAD-OK': [good_row],
        }
        recs = {code: Queue.create({'item_code': code, 'raw_data': json.dumps(data)})
                for code, data in raw.items()}

        # TransactionCase'te cr.commit yasak; kuyruk kendi commit'ini yapar
        with patch.object(self.env.cr, 'commit', lambda: None):
            Queue.process_queue_batch()

        self.assertEqual(recs['H2-BAD-OK'].state, 'done')
        for code in ('H2-BAD-DICT', 'H2-BAD-NULL', 'H2-BAD-INT'):
            self.assertEqual(recs[code].state, 'error', code)
        self.assertTrue(
            self.env['product.template'].search_count([('nebim_code', '=', 'H2-BAD-OK')]))

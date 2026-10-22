# -*- coding: utf-8 -*-
"""A5 düzeltme #1: çift okutma kilidi hatası transaction'ı bozmaz (Ö-2), etiket barkodu geniş
istisnada boş döner (Ö-3), count_save bozuk kalem tiplerinde düşmez (H2)."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import base_api, counting_api, packing_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestA5ScanLockFailure(BarcodeCase):

    def setUp(self):
        super().setUp()
        self._patch_request()
        self.ctl = base_api.BarcodeApiBase()

    def test_lock_sql_error_keeps_transaction_usable(self):
        # gerçek SQL hatası: savepoint olmasaydı transaction abort olur, sonraki sorgu düşerdi
        with patch.object(base_api, '_SCAN_LOCK_SQL', 'SELECT bozuk_fonksiyon_yok(%s)'), \
                self.assertLogs('odoo.addons.ugurlar_barcode.controllers.base_api', level='WARNING') as cm:
            self.assertFalse(self.ctl._check_duplicate_request('a5_scan', 'A5-BC-1'),
                             'kilit alınamazsa istek geçer')
        self.assertTrue(any('kilidi alınamadı' in r.getMessage() for r in cm.records))
        self.env.cr.execute('SELECT 1')
        self.assertEqual(self.env.cr.fetchone()[0], 1)
        self.assertTrue(self.env['res.users'].search_count([]))


@tagged('post_install', '-at_install')
class TestA5LabelBarcodeAnyError(BarcodeCase):

    def test_type_error_returns_empty(self):
        self._patch_request(packing_api)
        ctl = packing_api.PackingApiController()
        with patch.object(type(self.env['ir.actions.report']), 'barcode', side_effect=TypeError('x')):
            self.assertEqual(ctl._barcode_data_uri('Code128', 'ABC'), '')


@tagged('post_install', '-at_install')
class TestA5CountSaveTypes(BarcodeCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('A5 Sayım Ürünü', 'A5-CN-1')
        cls.shelf = cls._new_shelf('A5-CN-RAF', 'A5-CN-RAF-1')

    def setUp(self):
        super().setUp()
        self._patch_request(counting_api)
        self.ctl = counting_api.CountingApiController()

    def test_bad_item_types_are_not_found_others_counted(self):
        res = self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=[
            'duz-metin', 12, None, {'barcode': ['x'], 'quantity': 1}, {'barcode': True, 'quantity': 1},
            {'barcode': self.prod.barcode, 'quantity': 4},
        ])
        self.assertTrue(res.get('success'), res)
        statuses = [r['status'] for r in res['results']]
        self.assertEqual(statuses[:5], ['not_found'] * 5)
        self.assertNotEqual(statuses[5], 'not_found')
        self.assertEqual(self._qty(self.prod, self.shelf), 4)

    def test_numeric_barcode_is_looked_up_as_text(self):
        prod = self._new_product('A5 Sayısal', '99887766554433')
        res = self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=[{'barcode': 99887766554433, 'quantity': 2}])
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(prod, self.shelf), 2)

    def test_missing_or_null_quantity_is_invalid_not_zero(self):
        # B4: eksik/null/boş miktar rafı sıfırlamaz; açık 0 hâlâ geçerli
        bc = self.prod.barcode
        self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=[{'barcode': bc, 'quantity': 5}])
        self.assertEqual(self._qty(self.prod, self.shelf), 5)
        for item in ({'barcode': bc}, {'barcode': bc, 'quantity': None}, {'barcode': bc, 'quantity': ''}):
            res = self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=[item])
            self.assertEqual(res['results'][0]['status'], 'error', item)
            self.assertEqual(res['results'][0]['message'], 'Geçersiz miktar', item)
            self.assertEqual(self._qty(self.prod, self.shelf), 5, item)
        res = self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=[{'barcode': bc, 'quantity': 0}])
        self.assertNotEqual(res['results'][0]['status'], 'error', res)
        self.assertEqual(self._qty(self.prod, self.shelf), 0)

    def test_items_not_a_list_is_error(self):
        for items in ({'barcode': 'x'}, 5, 'abc'):
            self.assertIn('error', self.ctl.count_save(shelf_barcode='A5-CN-RAF-1', items=items))

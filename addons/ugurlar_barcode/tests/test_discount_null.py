"""discount_api: Nebim satırında sayısal alan None gelirse 500 yerine 0 kabul edilir."""
from types import SimpleNamespace
from unittest.mock import patch

from odoo import http as odoo_http
from odoo.tests import tagged

from odoo.addons.ugurlar_barcode.controllers import discount_api
from odoo.addons.ugurlar_barcode.tests.common import BarcodeCase


@tagged('post_install', '-at_install')
class TestDiscountNullFields(BarcodeCase):

    def setUp(self):
        super().setUp()
        self._patch_request(discount_api)
        # NEDEN: `_error_text` çeviri dilini odoo.http.request.env'den alır (bkz. test_small_fixes KK-F4)
        p = patch.object(odoo_http, 'request', SimpleNamespace(env=self.env))
        p.start()
        self.addCleanup(p.stop)
        self.ctl = discount_api.DiscountApiController()

    def _calc(self, row):
        cls = type(self.env['odoougurlar.nebim.connector'])
        with patch.object(cls, 'run_proc', lambda conn, proc_name, params=None, **kw: [row]):
            return self.ctl.calculate_discounts(basket=[{'barcode': 'NULL-BC-1', 'quantity': 1}])

    def test_none_numeric_fields_become_zero(self):
        res = self._calc({
            'Barcode': 'NULL-BC-1', 'Quantity': None, 'RetailPrice': None, 'DiscountAmount': None,
            'FinalLineTotal': None, 'RetailInstallmentPrice': None,
            'InstallmentDiscountAmount': None, 'InstallmentFinalLineTotal': None,
        })
        self.assertTrue(res.get('success'), res)
        line = res['lines'][0]
        self.assertEqual(line['retail_price'], 0.0)
        self.assertEqual(line['final_price'], 0.0)
        self.assertEqual(line['installment_price'], 0.0)
        self.assertEqual(line['quantity'], 1)  # eksik adet 1 sayılır (eski varsayılan)
        self.assertTrue(line['not_found'])

    def test_normal_values_unchanged(self):
        res = self._calc({'Barcode': 'NULL-BC-1', 'Quantity': 2, 'RetailPrice': 100.0,
                          'DiscountAmount': 10.0, 'FinalLineTotal': 190.0})
        line = res['lines'][0]
        self.assertEqual((line['retail_price'], line['discount_amount'], line['final_price']),
                         (100.0, 10.0, 190.0))
        self.assertEqual(res['lines'][0]['quantity'], 2)

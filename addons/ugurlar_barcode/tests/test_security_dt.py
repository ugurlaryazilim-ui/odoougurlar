"""Dal D düzeltme turu (DT-D): güvenlik ve inceleme bulguları.

Her bölüm bir düzeltme maddesine aittir (R1..R6); bölümler commit sırasıyla eklenir.
"""
import re

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ugurlar_barcode.controllers import label_api
from odoo.addons.ugurlar_barcode.tests.test_security import SecurityCase


class DtLabelCase(SecurityCase):

    def setUp(self):
        super().setUp()
        self.default_tpl = self.Template.create({
            'name': 'DT Varsayılan', 'is_default': True, 'user_id': self.manager.id})

    def _as_stock(self, sudo):
        env_tpl = self.Template.with_user(self.stock_user)
        return env_tpl.sudo() if sudo else env_tpl

    def _ctl_as(self, user):
        self._patch_request_as(user, label_api)
        return label_api.LabelApiController()

    def _assert_default_untouched(self):
        self.default_tpl.invalidate_recordset()
        self.assertTrue(self.default_tpl.is_default)
        self.assertEqual(self.Template.search_count([('is_default', '=', True)]), 1)


# ==== R1 ====
@tagged('post_install', '-at_install')
class TestDtR1CreateDefaults(DtLabelCase):
    """Y-D1: kural, super().create içinde eklenen varsayılanlarla atlatılamaz."""

    def test_r1_context_default_name_kargo_denied(self):
        for sudo in (False, True):
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).with_context(default_name='Kargo X').create(
                    {'elements_json': '[]'})
        self.assertFalse(self.Template.search([('name', '=', 'Kargo X')]))

    def test_r1_context_default_is_default_denied(self):
        for sudo in (False, True):
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).with_context(default_is_default=True).create(
                    {'name': 'DT R1 Bağlam %s' % sudo})
        self._assert_default_untouched()

    def test_r1_name_create_kargo_denied(self):
        for sudo in (False, True):
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).name_create('Kargo X')
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).with_context(default_is_default=True).name_create(
                    'DT R1 Ad %s' % sudo)
        self.assertFalse(self.Template.search([('name', '=', 'Kargo X')]))
        self._assert_default_untouched()

    def test_r1_load_with_context_default_denied(self):
        """İçe aktarma (load) kayıtları _load_records üzerinden create ile yazar. load()'un
        kendisi test imlecinde savepoint.close desteklemediği için alt katman çağrılır."""
        for sudo in (False, True):
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).with_context(default_is_default=True)._load_records(
                    [{'values': {'name': 'DT R1 Yükle'}}])
        self.assertFalse(self.Template.search([('name', '=', 'DT R1 Yükle')]))
        self._assert_default_untouched()

    def test_r1_user_ir_default_denied(self):
        self.env['ir.default'].set('ugurlar.label.template', 'is_default', True,
                                   user_id=self.stock_user.id)
        with self.assertRaises(AccessError):
            self._as_stock(True).create({'name': 'DT R1 ir.default'})
        self._assert_default_untouched()

    def test_r1_protect_plain_create_and_name_create_still_work(self):
        for sudo in (False, True):
            tpl = self._as_stock(sudo).create({'name': 'DT R1 Sıradan %s' % sudo})
            self.assertFalse(tpl.is_default)
            rid, _name = self._as_stock(sudo).name_create('DT R1 Hızlı %s' % sudo)
            self.assertTrue(self.Template.browse(rid).exists())
        kargo = self.Template.with_user(self.manager).with_context(
            default_is_default=True).create({'name': 'Kargo Yönetici'})
        self.assertTrue(kargo.is_default)

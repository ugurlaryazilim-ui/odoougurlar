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


# ==== R2 ====
@tagged('post_install', '-at_install')
class TestDtR2Ownership(DtLabelCase):
    """O-D2: RPC yazımı da controller'daki sahiplik kuralına (_can_edit_template) uyar."""

    def setUp(self):
        super().setUp()
        self.other = self.Template.create({
            'name': 'DT R2 Başkası', 'user_id': self.stock_user2.id, 'elements_json': '[]'})

    def test_r2_cannot_write_others_template(self):
        with self.assertRaises(AccessError):
            self._as_stock(False).browse(self.other.id).write({'elements_json': '[9]'})
        self.other.invalidate_recordset()
        self.assertEqual(self.other.elements_json, '[]')

    def test_r2_cannot_take_ownership(self):
        with self.assertRaises(AccessError):
            self._as_stock(False).browse(self.other.id).write({'user_id': self.stock_user.id})
        self.other.invalidate_recordset()
        self.assertEqual(self.other.user_id, self.stock_user2)

    def test_r2_cannot_write_managers_default_template(self):
        with self.assertRaises(AccessError):
            self._as_stock(False).browse(self.default_tpl.id).write({'width_mm': 99})
        self.default_tpl.invalidate_recordset()
        self.assertNotEqual(self.default_tpl.width_mm, 99)

    def test_r2_protect_own_and_ownerless_writable_all_readable(self):
        own = self.Template.create({'name': 'DT R2 Kendi', 'user_id': self.stock_user.id})
        free = self.Template.create({'name': 'DT R2 Sahipsiz', 'user_id': False})
        self._as_stock(False).browse((own | free).ids).write({'elements_json': '[1]'})
        self.assertEqual((own | free).mapped('elements_json'), ['[1]', '[1]'])
        found = self._as_stock(False).search([('id', 'in', (self.other | self.default_tpl).ids)])
        self.assertEqual(len(found), 2, 'okuma herkese açık kalmalı')

    def test_r2_protect_manager_writes_any(self):
        self.Template.with_user(self.manager).browse(self.other.id).write(
            {'elements_json': '[7]', 'user_id': self.manager.id})
        self.assertEqual(self.other.user_id, self.manager)

    def test_r2_protect_controller_flow_unchanged(self):
        ctl = self._ctl_as(self.stock_user)
        res = ctl.label_template_save(template_id=self.other.id, name='DT R2 X', elements=[])
        self.assertTrue(res.get('error'), res)
        free = self.Template.create({'name': 'DT R2 Ortak', 'user_id': False})
        res = ctl.label_template_save(template_id=free.id, name='DT R2 Ortak2', elements=[])
        self.assertTrue(res.get('success'), res)
        res = ctl.label_template_delete(template_id=free.id)
        self.assertTrue(res.get('success'), res)


# ==== R3 ====
@tagged('post_install', '-at_install')
class TestDtR3StockGroup(DtLabelCase):
    """D-D5: stok grubunda olmayan iç kullanıcı sudo controller üzerinden şablon yazamaz."""

    def test_r3_plain_internal_user_cannot_save(self):
        res = self._ctl_as(self.plain_user).label_template_save(name='DT R3 Yeni', elements=[])
        self.assertTrue(res.get('error') and not res.get('success'), res)
        self.assertFalse(self.Template.search([('name', '=', 'DT R3 Yeni')]))

    def test_r3_plain_internal_user_cannot_update_or_delete(self):
        free = self.Template.create({'name': 'DT R3 Ortak', 'user_id': False})
        ctl = self._ctl_as(self.plain_user)
        res = ctl.label_template_save(template_id=free.id, name='DT R3 Değişti', elements=[])
        self.assertTrue(res.get('error') and not res.get('success'), res)
        res = ctl.label_template_delete(template_id=free.id)
        self.assertTrue(res.get('error') and not res.get('success'), res)
        self.assertEqual(free.name, 'DT R3 Ortak')
        self.assertTrue(free.exists())

    def test_r3_protect_plain_internal_user_can_list(self):
        res = self._ctl_as(self.plain_user).label_template_list()
        self.assertIn(self.default_tpl.id, [t['id'] for t in res['templates']])


# ==== R4 ====
@tagged('post_install', '-at_install')
class TestDtR4FiniteDims(DtLabelCase):
    """D-D4: ölçüler sonlu, pozitif sayı olmalı (nan/inf şablon listesinin JSON'unu bozar)."""

    BAD = ('nan', 'NaN', 'inf', '-inf', 'Infinity', 'abc', '-5', '0')

    def test_r4_create_rejects_non_finite(self):
        ctl = self._ctl_as(self.stock_user)
        for bad in self.BAD:
            for field in ('width_mm', 'height_mm'):
                res = ctl.label_template_save(name='DT R4 %s %s' % (bad, field), elements=[],
                                              **{field: bad})
                self.assertTrue(res.get('error') and not res.get('success'), (bad, field, res))
        self.assertFalse(self.Template.search([('name', '=like', 'DT R4 %')]))

    def test_r4_update_rejects_non_finite(self):
        own = self.Template.create({'name': 'DT R4 Kendi', 'user_id': self.stock_user.id,
                                    'width_mm': 50})
        res = self._ctl_as(self.stock_user).label_template_save(
            template_id=own.id, name='DT R4 Kendi', width_mm='nan', elements=[])
        self.assertTrue(res.get('error') and not res.get('success'), res)
        own.invalidate_recordset()
        self.assertEqual(own.width_mm, 50)

    def test_r4_protect_numeric_strings_accepted(self):
        res = self._ctl_as(self.stock_user).label_template_save(
            name='DT R4 Geçerli', width_mm='62.5', height_mm=30, elements=[])
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self.Template.browse(res['id']).width_mm, 62.5)

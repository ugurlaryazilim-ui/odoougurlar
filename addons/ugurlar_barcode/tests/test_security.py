"""Dal D / G11-G13: KK-D1, KK-D2.1, KK-D2.2, KK-D3, KK-D4.

- KK-D1 (labels.js safeNum): Python tarafında yalnız statik kaynak kontrolü yapılabilir;
  gerçek XSS doğrulaması Mod 2'de Playwright senaryosudur (aşağıda dosya sonunda).
- KK-D2: etiket şablonu yetki kuralı MODEL katmanında olmalı; testler hem `with_user`
  hem `with_user(...).sudo()` (controller kalıbı: sudo uid'yi değiştirmez) ile çalışır.
- KK-D3: count.session / barcode.operation stok kullanıcısı için salt-okunur, ama mobil
  controller akışları (sudo ile yazanlar) stok kullanıcısıyla çalışmaya devam eder (KORUMA).
- KK-D4: kök Mobil menüsü stok grubunda olmayan iç kullanıcıya görünmez.
"""
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ugurlar_barcode.controllers import (
    base_api, counting_api, label_api, batch_api, packing_api, shelf_api)
from odoo.addons.ugurlar_barcode.tests.common import PackingCase


class SecurityCase(PackingCase):
    """Üç kullanıcı: yalnız stok kullanıcısı, stok yöneticisi, stok grubu olmayan iç kullanıcı."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = cls._new_user('d_stok_kullanici', 'stock.group_stock_user')
        cls.stock_user2 = cls._new_user('d_stok_kullanici2', 'stock.group_stock_user')
        cls.manager = cls._new_user('d_stok_yonetici', 'stock.group_stock_manager')
        cls.plain_user = cls._new_user('d_ic_kullanici')
        cls.Template = cls.env['ugurlar.label.template']

    @classmethod
    def _new_user(cls, login, *group_xmlids):
        groups = [cls.env.ref(x).id for x in ('base.group_user',) + group_xmlids]
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'email': '%s@example.com' % login,
            'group_ids': [(6, 0, groups)]})

    def _patch_request_as(self, user, *modules):
        """`request.env` verilen kullanıcıyla (sudo'suz) çalışır; controller çağrıları o kullanıcıdır."""
        fake = SimpleNamespace(env=self.env(user=user))
        for mod in (base_api, *modules):
            p = patch.object(mod, 'request', fake)
            p.start()
            self.addCleanup(p.stop)


# ═══════════════════════════════════════════════════════════════
# KK-D1: labels.js (statik kontrol)
# ═══════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestLabelsJsSafeNum(SecurityCase):

    def _generate_barcode_img_body(self):
        with file_open('ugurlar_barcode/static/src/js/screens/labels.js') as f:
            src = f.read()
        match = re.search(r'\n    _generateBarcodeImg\([^)]*\)\s*\{\n(.*?)\n    \}\n', src, re.S)
        self.assertTrue(match, '_generateBarcodeImg bulunamadı')
        return match.group(1)

    def test_d1_barcode_img_width_height_pass_through_safenum(self):
        """width/height ham olarak HTML/style'a girmez: yalnız safeNum(...) içinde kullanılır."""
        body = self._generate_barcode_img_body()
        self.assertRegex(body, r'safeNum\(\s*widthMm', 'widthMm safeNum\'dan geçmeli')
        self.assertRegex(body, r'safeNum\(\s*heightMm', 'heightMm safeNum\'dan geçmeli')
        rest = re.sub(r'safeNum\(\s*(widthMm|heightMm)[^()]*\)', '', body)
        self.assertNotRegex(rest, r'\b(widthMm|heightMm)\b',
                            'widthMm/heightMm safeNum dışında kullanılıyor (HTML enjeksiyonu)')

    def test_d1_safenum_import_kept(self):
        """Koruma: labels.js safeNum'ı içe aktarmaya devam eder."""
        with file_open('ugurlar_barcode/static/src/js/screens/labels.js') as f:
            src = f.read()
        self.assertRegex(src, r'import \{[^}]*\bsafeNum\b[^}]*\} from "\.\./utils/html"')


# ═══════════════════════════════════════════════════════════════
# KK-D2: etiket şablonu yetkisi (model katmanı)
# ═══════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestLabelTemplatePermissions(SecurityCase):

    KARGO_NAMES = ['Kargo Etiketi', 'kargo', 'KARGO etiketi', 'Yeni kArGo 100x150']

    def setUp(self):
        super().setUp()
        # Yöneticinin bıraktığı varsayılan şablon
        self.default_tpl = self.Template.create({
            'name': 'D2 Varsayılan', 'is_default': True, 'user_id': self.manager.id})

    def _tpl(self, name, owner=None, is_default=False):
        return self.Template.create({
            'name': name, 'user_id': (owner or self.stock_user).id, 'is_default': is_default})

    def _as_stock(self, sudo):
        env_tpl = self.Template.with_user(self.stock_user)
        return env_tpl.sudo() if sudo else env_tpl

    def _denied_save(self, **kw):
        """Controller kaydı reddedilmeli: AccessError fırlatır ya da `error` döner."""
        self._patch_request_as(self.stock_user, label_api)
        ctl = label_api.LabelApiController()
        try:
            res = ctl.label_template_save(**kw)
        except AccessError:
            return
        self.assertTrue(res.get('error') and not res.get('success'), res)

    # ─── KK-D2.1 ───────────────────────────────────────
    def test_d21_nonmanager_cannot_create_default(self):
        for sudo in (False, True):
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                self._as_stock(sudo).create({'name': 'D2 Benim', 'is_default': True})
        self.assertFalse(self.Template.search([('name', '=', 'D2 Benim')]))

    def test_d21_nonmanager_cannot_write_default_flag(self):
        for sudo in (False, True):
            tpl = self._tpl('D2 Normal %s' % sudo)
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                tpl.with_user(self.stock_user).sudo(sudo).write({'is_default': True})
            self.assertFalse(tpl.is_default)
        self.assertTrue(self.default_tpl.is_default)

    def test_d21_controller_failed_default_attempt_keeps_existing_default(self):
        """label_template_save yetkiyi bayrağı temizlemeden ÖNCE denetler."""
        self._denied_save(name='D2 Yeni Varsayılan', is_default=True, elements=[])
        self.default_tpl.invalidate_recordset()
        self.assertTrue(self.default_tpl.is_default, 'mevcut varsayılan bozulmamalı')
        self.assertFalse(self.Template.search([('name', '=', 'D2 Yeni Varsayılan')]))

    def test_d21_controller_failed_default_on_own_template_keeps_existing_default(self):
        own = self._tpl('D2 Benim Şablon')
        self._denied_save(template_id=own.id, name='D2 Benim Şablon', is_default=True)
        self.default_tpl.invalidate_recordset()
        own.invalidate_recordset()
        self.assertTrue(self.default_tpl.is_default)
        self.assertFalse(own.is_default)

    # ─── KK-D2.2 ───────────────────────────────────────
    def test_d22_nonmanager_cannot_create_kargo_named_template(self):
        for sudo in (False, True):
            for name in self.KARGO_NAMES:
                with self.assertRaises(AccessError, msg='%r sudo=%s' % (name, sudo)):
                    self._as_stock(sudo).create({'name': name})
        # çoklu create içinde tek kargo adı bile tümünü reddeder
        with self.assertRaises(AccessError):
            self._as_stock(True).create([{'name': 'D2 Masum'}, {'name': 'D2 kargo gizli'}])
        self.assertFalse(self.Template.search([('name', 'in', self.KARGO_NAMES + ['D2 Masum'])]))

    def test_d22_nonmanager_cannot_rename_to_kargo(self):
        for sudo in (False, True):
            tpl = self._tpl('D2 Normal Ad %s' % sudo)
            with self.assertRaises(AccessError, msg='sudo=%s' % sudo):
                tpl.with_user(self.stock_user).sudo(sudo).write({'name': 'Kargo Etiketi'})
            self.assertEqual(tpl.name, 'D2 Normal Ad %s' % sudo)

    def test_d22_nonmanager_cannot_modify_or_delete_existing_kargo_template(self):
        """Şablonu stok kullanıcısı oluşturmuş (sahibi) olsa bile eski adı 'kargo' ise dokunamaz."""
        for sudo in (False, True):
            tpl = self._tpl('Kargo Etiketi D2 %s' % sudo, owner=self.stock_user)
            ro = tpl.with_user(self.stock_user).sudo(sudo)
            with self.assertRaises(AccessError):
                ro.write({'elements_json': '[{"type": "x"}]'})
            with self.assertRaises(AccessError):
                ro.write({'name': 'Başka Ad'})      # kargo'dan çıkarma da yasak
            with self.assertRaises(AccessError):
                ro.unlink()
            tpl.invalidate_recordset()
            self.assertTrue(tpl.exists())
            self.assertEqual(tpl.name, 'Kargo Etiketi D2 %s' % sudo)
            self.assertEqual(tpl.elements_json, '[]')

    def test_d22_controller_save_create_and_update_kargo_rejected(self):
        self._denied_save(name='Kargo Hızlı', elements=[])
        own = self._tpl('D2 Benim')
        self._denied_save(template_id=own.id, name='KARGO benim', elements=[])
        own.invalidate_recordset()
        self.assertEqual(own.name, 'D2 Benim')
        self.assertFalse(self.Template.search([('name', 'ilike', 'kargo')]))

    def test_d22_controller_delete_own_kargo_template_rejected(self):
        tpl = self._tpl('Kargo Etiketi Sahip', owner=self.stock_user)
        self._patch_request_as(self.stock_user, label_api)
        ctl = label_api.LabelApiController()
        try:
            res = ctl.label_template_delete(template_id=tpl.id)
        except AccessError:
            res = {'error': 'AccessError'}
        self.assertTrue(res.get('error') and not res.get('success'), res)
        self.assertTrue(tpl.exists(), 'kargo şablonu silinmemeli')

    def test_d22_cargo_template_selection_ignores_nonmanager_attempts(self):
        """cargo_label_pdf şablonu `name ilike Kargo` ile bulur: reddedilen denemeler
        arama sonucunu değiştirmemeli (yalnız yöneticinin bıraktığı şablon kalır)."""
        mgr_tpl = self.Template.with_user(self.manager).create({'name': 'Kargo Etiketi Yönetici'})
        self._denied_save(name='Kargo Sahte', is_default=True, elements=[])
        found = self.Template.search([('name', 'ilike', 'Kargo')])
        self.assertEqual(found, mgr_tpl)

    # ─── KORUMA (bugün de yeşil, değişiklikten sonra da yeşil) ──
    def test_protect_nonmanager_normal_template_crud_still_works(self):
        for sudo in (False, True):
            tpl = self._as_stock(sudo).create({'name': 'D2 Sıradan %s' % sudo})
            tpl.write({'name': 'D2 Sıradan Yeni %s' % sudo, 'width_mm': 50})
            self.assertEqual(tpl.width_mm, 50)
            self.assertFalse(tpl.is_default)
            if sudo:      # silme yetkisi ACL'de yalnız yönetici; controller sudo ile siler
                tpl.unlink()
                self.assertFalse(tpl.exists())

    def test_protect_nonmanager_controller_normal_save_and_delete_works(self):
        self._patch_request_as(self.stock_user, label_api)
        ctl = label_api.LabelApiController()
        res = ctl.label_template_save(name='D2 Controller Sıradan', width_mm=50, height_mm=30,
                                      elements=[{'type': 'barcode'}])
        self.assertTrue(res.get('success'), res)
        tpl = self.Template.browse(res['id'])
        self.assertEqual(json.loads(tpl.elements_json), [{'type': 'barcode'}])
        self.assertFalse(tpl.is_default)
        res = ctl.label_template_save(template_id=tpl.id, name='D2 Controller Güncel',
                                      width_mm=55, height_mm=30, elements=[])
        self.assertTrue(res.get('success'), res)
        tpl.invalidate_recordset()
        self.assertEqual((tpl.name, tpl.width_mm), ('D2 Controller Güncel', 55))
        self.assertTrue(self.default_tpl.is_default)
        res = ctl.label_template_delete(template_id=tpl.id)
        self.assertTrue(res.get('success'), res)
        self.assertFalse(tpl.exists())

    def test_protect_nonmanager_can_edit_default_template_content(self):
        """G12 rev: varsayılan ve kargo olmayan şablonun alanlarını stok kullanıcısı yazabilir."""
        for sudo in (False, True):
            self._as_stock(sudo).browse(self.default_tpl.id).write(
                {'width_mm': 70, 'elements_json': '[1]', 'name': 'D2 Varsayılan Yeni'})
            self.default_tpl.invalidate_recordset()
            self.assertEqual(self.default_tpl.width_mm, 70)
            self.assertTrue(self.default_tpl.is_default)
        # controller: arayüz is_default göndermez (False); bayrak ve içerik korunur
        own_default = self.Template.create({
            'name': 'D2 Sahibi Stok', 'user_id': self.stock_user.id, 'is_default': False})
        self.default_tpl.user_id = self.stock_user
        self._patch_request_as(self.stock_user, label_api)
        ctl = label_api.LabelApiController()
        res = ctl.label_template_save(template_id=self.default_tpl.id, name='D2 Varsayılan Yeni',
                                      width_mm=80, height_mm=30, elements=[{'type': 'x'}])
        self.assertTrue(res.get('success'), res)
        res = ctl.label_template_save(template_id=self.default_tpl.id, name='D2 Varsayılan Yeni',
                                      width_mm=85, height_mm=30, elements=[], is_default=True)
        self.assertTrue(res.get('success'), res)
        self.default_tpl.invalidate_recordset()
        own_default.invalidate_recordset()
        self.assertEqual(self.default_tpl.width_mm, 85)
        self.assertTrue(self.default_tpl.is_default)
        self.assertFalse(own_default.is_default)

    def test_protect_nonmanager_can_list_templates(self):
        self._patch_request_as(self.stock_user, label_api)
        res = label_api.LabelApiController().label_template_list()
        self.assertIn(self.default_tpl.id, [t['id'] for t in res['templates']])

    def test_protect_manager_can_create_kargo_and_default_and_delete(self):
        mgr = self.Template.with_user(self.manager)
        kargo = mgr.create({'name': 'Kargo Etiketi M', 'is_default': True})
        kargo.write({'elements_json': '[1]', 'name': 'KARGO M2'})
        self.assertTrue(kargo.is_default)
        kargo.write({'is_default': False})
        kargo.unlink()
        self.assertFalse(kargo.exists())

    def test_protect_manager_controller_set_default_clears_previous(self):
        self._patch_request_as(self.manager, label_api)
        ctl = label_api.LabelApiController()
        res = ctl.label_template_save(name='Kargo Etiketi Y', is_default=True, elements=[])
        self.assertTrue(res.get('success'), res)
        self.default_tpl.invalidate_recordset()
        self.assertFalse(self.default_tpl.is_default, 'önceki varsayılan temizlenmeli')
        self.assertTrue(self.Template.browse(res['id']).is_default)
        res = ctl.label_template_delete(template_id=res['id'])
        self.assertTrue(res.get('success'), res)

    def test_protect_superuser_is_exempt(self):
        """Kurulum / cron (uid 1) kargo adı ve varsayılan bayrağını yazabilir (AS-3)."""
        tpl = self.env['ugurlar.label.template'].create({'name': 'Kargo Kurulum', 'is_default': True})
        tpl.write({'name': 'Kargo Kurulum 2'})
        self.assertTrue(tpl.exists())


# ═══════════════════════════════════════════════════════════════
# KK-D3: ACL — salt-okunur (ORM) ama mobil akışlar çalışır
# ═══════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestAclReadOnly(SecurityCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shelf = cls._new_shelf('D3-RAF', 'D3-RAF-1')
        cls.session = cls.env['ugurlar.barcode.count.session'].create({
            'location_id': cls.shelf.id, 'user_id': cls.stock_user.id})
        cls.op = cls.env['ugurlar.barcode.operation'].create({
            'operation_type': 'counting', 'barcode': 'D3-X', 'count_session_id': cls.session.id})

    def test_d3_stock_user_can_read(self):
        Session = self.env['ugurlar.barcode.count.session'].with_user(self.stock_user)
        Op = self.env['ugurlar.barcode.operation'].with_user(self.stock_user)
        self.assertTrue(Session.search([('id', '=', self.session.id)]))
        self.assertEqual(Session.browse(self.session.id).location_id, self.shelf)
        self.assertEqual(Op.browse(self.op.id).barcode, 'D3-X')
        self.assertTrue(Op.search_count([('count_session_id', '=', self.session.id)]))

    def test_d3_stock_user_cannot_create_or_write_session(self):
        Session = self.env['ugurlar.barcode.count.session'].with_user(self.stock_user)
        with self.assertRaises(AccessError):
            Session.create({'location_id': self.shelf.id})
        with self.assertRaises(AccessError):
            Session.browse(self.session.id).write({'notes': 'sahte'})
        self.assertFalse(self.session.notes)

    def test_d3_stock_user_cannot_create_or_write_operation(self):
        Op = self.env['ugurlar.barcode.operation'].with_user(self.stock_user)
        with self.assertRaises(AccessError):
            Op.create({'operation_type': 'putaway', 'barcode': 'D3-SAHTE'})
        with self.assertRaises(AccessError):
            Op.browse(self.op.id).write({'quantity': 999})
        self.assertFalse(self.env['ugurlar.barcode.operation'].search([('barcode', '=', 'D3-SAHTE')]))
        self.assertEqual(self.op.quantity, 0)

    def test_d3_protect_stock_user_cannot_unlink(self):
        with self.assertRaises(AccessError):
            self.session.with_user(self.stock_user).unlink()
        with self.assertRaises(AccessError):
            self.op.with_user(self.stock_user).unlink()

    def test_d3_protect_manager_can_still_write(self):
        sess = self.session.with_user(self.manager)
        sess.write({'notes': 'yönetici notu'})
        self.assertEqual(self.session.notes, 'yönetici notu')
        new = self.env['ugurlar.barcode.operation'].with_user(self.manager).create(
            {'operation_type': 'putaway', 'barcode': 'D3-YON'})
        new.write({'quantity': 2})
        sess.action_validate()
        self.assertEqual(self.session.state, 'validated')
        sess.action_draft()
        self.assertEqual(self.session.state, 'draft')

    def test_d3_protect_stock_user_cannot_validate(self):
        with self.assertRaises(AccessError):
            self.session.with_user(self.stock_user).action_validate()


@tagged('post_install', '-at_install')
class TestMobileFlowsAsStockUser(SecurityCase):
    """KORUMA: ACL daraltıldıktan sonra da mobil akışlar yalnız stok kullanıcısıyla çalışır
    ve `barcode.operation` / `count.session` kayıtları yine oluşur."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = cls._new_product('D3 Ürün', 'D3-P1')
        cls.prod_b = cls._new_product('D3 Ürün B', 'D3-P2')
        cls.shelf_a = cls._new_shelf('D3-RAF-A', 'D3-RAF-A1')
        cls.shelf_b = cls._new_shelf('D3-RAF-B', 'D3-RAF-B1')
        cls.shelf_neg = cls._new_shelf('D3-RAF-NEG', 'D3-RAF-N1')

    def setUp(self):
        super().setUp()
        nebim = patch.object(packing_api.PackingApiController, '_trigger_nebim_sync')
        nebim.start()
        self.addCleanup(nebim.stop)
        self._patch_request_as(self.stock_user, counting_api, shelf_api, label_api,
                               batch_api, packing_api)

    def _ops(self, op_type, product=None):
        domain = [('operation_type', '=', op_type)]
        if product:
            domain.append(('product_id', '=', product.id))
        return self.env['ugurlar.barcode.operation'].search(domain)

    def test_d3_flow_count_save_creates_session_and_operations(self):
        self._add_stock(self.prod, self.shelf_neg, -3)     # düzeltme (session.notes sudo yazımı)
        res = counting_api.CountingApiController().count_save(
            shelf_barcode='D3-RAF-A1', items=[{'barcode': 'D3-P1', 'quantity': 4}])
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf_a), 4)
        sessions = self.env['ugurlar.barcode.count.session'].search(
            [('location_id', '=', self.shelf_a.id)])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions.user_id, self.stock_user)
        self.assertIn('Sayım Düzeltmeleri', sessions.notes or '')
        ops = self._ops('counting', self.prod)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops.count_session_id, sessions)
        self.assertEqual(ops.user_id, self.stock_user)
        self.assertTrue(self._ops('count_adjustment', self.prod))

    def test_d3_flow_putaway_remove_transfer_create_operations(self):
        ctl = shelf_api.ShelfApiController()
        res = ctl.putaway(product_barcode='D3-P1', shelf_barcode='D3-RAF-A1', quantity=5)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf_a), 5)
        self.assertEqual(len(self._ops('putaway', self.prod)), 1)

        res = ctl.shelf_transfer(product_barcode='D3-P1', source_shelf_barcode='D3-RAF-A1',
                                 target_shelf_barcode='D3-RAF-B1', quantity=2)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf_a), 3)
        self.assertEqual(self._qty(self.prod, self.shelf_b), 2)
        self.assertTrue(self._ops('shelf_transfer', self.prod))

        res = ctl.remove_from_shelf(product_barcode='D3-P1', shelf_barcode='D3-RAF-A1', quantity=1)
        self.assertTrue(res.get('success'), res)
        self.assertEqual(len(self._ops('remove', self.prod)), 1)

    def test_d3_flow_shelf_clear_and_move_all_work(self):
        self._add_stock(self.prod, self.shelf_a, 3)
        self._add_stock(self.prod_b, self.shelf_a, 2)
        ctl = shelf_api.ShelfApiController()
        res = ctl.shelf_move_all(source_barcode='D3-RAF-A1', target_barcode='D3-RAF-B1')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf_b), 3)
        res = ctl.shelf_clear_all(shelf_barcode='D3-RAF-B1')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(self._qty(self.prod, self.shelf_b), 0)

    def test_d3_flow_label_data_creates_operation(self):
        res = label_api.LabelApiController().label_data(barcodes=['D3-P1'])
        self.assertEqual(res.get('found'), 1, res)
        self.assertEqual(len(self._ops('label', self.prod)), 1)

    def test_d3_flow_route_collect_scan_creates_operation(self):
        self._add_stock(self.prod, self.shelf_a, 5)
        picking = self._picking(self.prod, 2)
        batch = self._route(picking)
        res = batch_api.BatchApiController().batch_collect_scan(batch_id=batch.id, barcode='D3-P1')
        self.assertFalse(res.get('error'), res)
        self.assertEqual(picking.move_ids.wave_collected_qty, 1)
        self.assertEqual(len(self._ops('picking', self.prod)), 1)

    def test_d3_flow_packing_scan_works(self):
        self._add_stock(self.prod, self.shelf_a, 5)
        picking = self._picking(self.prod, 1)
        picking.move_ids.write({'wave_collected_qty': 1})
        batch = self._route(picking)
        res = packing_api.PackingApiController().packing_scan(batch_id=batch.id, barcode='D3-P1')
        self.assertTrue(res.get('success'), res)
        picking.invalidate_recordset()
        picking.move_ids.invalidate_recordset()
        self.assertEqual(picking.move_ids.packing_scanned_qty, 1)


# ═══════════════════════════════════════════════════════════════
# KK-D4: kök Mobil menüsü
# ═══════════════════════════════════════════════════════════════
@tagged('post_install', '-at_install')
class TestMobileMenuGroup(SecurityCase):

    def _visible(self, user):
        Menu = self.env['ir.ui.menu'].with_user(user)
        return set(Menu._visible_menu_ids())

    def test_d4_root_menu_requires_stock_user_group(self):
        root = self.env.ref('ugurlar_barcode.menu_ugurlar_barcode_root')
        self.assertIn(self.env.ref('stock.group_stock_user'), root.group_ids)

    def test_d4_plain_internal_user_does_not_see_mobile_menu(self):
        root = self.env.ref('ugurlar_barcode.menu_ugurlar_barcode_root')
        visible = self._visible(self.plain_user)
        self.assertNotIn(root.id, visible)
        children = self.env['ir.ui.menu'].search([('id', 'child_of', root.id)])
        self.assertFalse(set(children.ids) & visible, 'alt menüler de görünmemeli')

    def test_d4_protect_stock_user_and_manager_still_see_mobile_menu(self):
        root = self.env.ref('ugurlar_barcode.menu_ugurlar_barcode_root')
        self.assertIn(root.id, self._visible(self.stock_user))
        self.assertIn(root.id, self._visible(self.manager))


# ═══════════════════════════════════════════════════════════════
# Mod 2 için Playwright senaryosu (otomatikleştirilemeyen kısım):
#   KK-D1: DB'de ugurlar.label.template kaydı: elements_json içinde
#   {"type":"barcode","x":1,"y":1,"width":"\"><img src=x onerror=window.__xss=1>",
#    "height":"\"><img src=x onerror=window.__xss=1>"}. Etiket ekranında şablonu seç,
#   önizlemeyi aç: window.__xss tanımsız kalmalı; DOM'da onerror öznitelikli img olmamalı;
#   barkod görseli varsayılan ölçüde görünmeli. (labels.js önizleme + yazdırma yolları.)
# ═══════════════════════════════════════════════════════════════

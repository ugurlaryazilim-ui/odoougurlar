"""Erişim grupları: Kullanıcı / Yönetici ayrımı ve yükseltmede bir kerelik otomatik atama."""
import importlib.util
import os

from odoo.exceptions import AccessDenied, AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .common import VcCase

MIGRATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'migrations', '19.0.1.3.0', 'post-migrate.py')


@tagged('post_install', '-at_install')
class TestVendorClaimAccess(VcCase):

    def setUp(self):
        super().setUp()
        # grubu olmayan sıradan iç kullanıcı
        self.plain = new_test_user(self.env, login='vc_t_plain', password='Vc-Test-Pw-12345', groups='base.group_user')

    def test_plain_internal_user_has_no_access(self):
        claim = self.make_claim()
        with self.assertRaises(AccessError):
            self.Claim.with_user(self.plain).search([])
        with self.assertRaises(AccessError):
            claim.with_user(self.plain).read(['name'])
        with self.assertRaises(AccessError):
            self.make_claim(user=self.plain)

    def test_plain_user_blocked_on_controller_and_partner_form_ok(self):
        with self.assertRaises(AccessDenied):
            self.controller('stats', user=self.plain)
        with self.assertRaises(AccessDenied):
            self.controller('search_invoice', user=self.plain, search_term='X')
        # iş ortağı formu (hesaplanan sayaç) grupsuz kullanıcıda hata vermemeli
        partner = self.env['res.partner'].create({'name': 'Tedarikçi X'})
        self.assertEqual(partner.with_user(self.plain).vendor_claim_count, 0)

    def test_user_creates_but_cannot_delete(self):
        claim = self.make_claim()
        self.assertTrue(claim.with_user(self.user).read(['name']))
        with self.assertRaises(AccessError):
            claim.with_user(self.user).unlink()

    def test_manager_deletes_and_implies_user(self):
        claim = self.make_claim()
        self.assertTrue(self.manager.has_group('vendor_claim.group_vendor_claim_user'))
        claim.with_user(self.manager).unlink()
        self.assertFalse(claim.exists())

    def test_admin_chain(self):
        self.assertTrue(self.env.ref('base.user_admin').has_group('vendor_claim.group_vendor_claim_manager'))

    def test_menu_follows_group(self):
        menu = self.env.ref('vendor_claim.menu_vendor_claim_root')
        Menu = self.env['ir.ui.menu']
        self.assertIn(menu.id, Menu.with_user(self.user)._visible_menu_ids())
        self.assertNotIn(menu.id, Menu.with_user(self.plain)._visible_menu_ids())

    def test_migration_grants_once_to_active_internal_users(self):
        spec = importlib.util.spec_from_file_location('vc_post_migrate_1_3_0', MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        portal = new_test_user(self.env, login='vc_t_portal2', groups='base.group_portal')
        inactive = new_test_user(self.env, login='vc_t_inactive', groups='base.group_user')
        inactive.active = False
        group = self.env.ref('vendor_claim.group_vendor_claim_user')
        granted = module.grant_internal_users(self.env)
        self.assertIn(self.plain, granted)
        self.assertTrue(self.plain.has_group('vendor_claim.group_vendor_claim_user'))
        self.assertNotIn(portal, group.user_ids)
        self.assertNotIn(inactive, group.user_ids)
        # ikinci çalıştırmada eklenecek kimse yok (idempotent)
        self.assertFalse(module.grant_internal_users(self.env))

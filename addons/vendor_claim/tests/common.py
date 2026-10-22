"""vendor_claim test tabanı: sms_system HTTP taklidi (yalnız karışım sınıfı; TestCase içe aktarılmaz)."""
import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, new_test_user

from odoo.addons.sms_system.tests.common import FakeNet, SmsFakes  # noqa: F401

PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
REQUEST = 'odoo.addons.vendor_claim.controllers.vendor_claim_controller.request'
PW = 'Vc-Test-Pw-12345'


class VcMixin(SmsFakes):
    """Ortak kurulum: ürün/tedarikçi, kullanıcılar, ağ taklidi; varsayılan test modu AÇIK."""

    @classmethod
    def vc_setup_class(cls):
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('vendor_claim.sms_reminder_days', '3')
        icp.set_param('vendor_claim.sms_reminder_max', '2')
        cls.user = new_test_user(cls.env, login='vc_t_user', password=PW, groups='base.group_user,vendor_claim.group_vendor_claim_user')
        cls.user2 = new_test_user(cls.env, login='vc_t_user2', password=PW, groups='base.group_user,vendor_claim.group_vendor_claim_user')
        cls.manager = new_test_user(cls.env, login='vc_t_mgr', password=PW,
                                    groups='base.group_user,vendor_claim.group_vendor_claim_manager')
        cls.sms_manager = new_test_user(cls.env, login='vc_t_smsmgr', password=PW,
                                        groups='base.group_user,vendor_claim.group_vendor_claim_user,sms_system.group_sms_manager')
        attr = cls.env['product.attribute'].create({'name': 'Tedarikçi', 'create_variant': 'no_variant'})
        value = cls.env['product.attribute.value'].create({'name': 'ABC Tekstil', 'attribute_id': attr.id})
        template = cls.env['product.template'].create({
            'name': 'Test Ceket', 'default_code': 'CKT-T1',
            'attribute_line_ids': [(0, 0, {'attribute_id': attr.id, 'value_ids': [(6, 0, value.ids)]})],
        })
        cls.product = template.product_variant_id
        cls.product.barcode = '8690000000311'

    def vc_setup(self, test_mode='True', auto_sms=False):
        self.setup_fakes()
        self.configure_sms(test_mode=test_mode)
        icp = self.icp
        for event in ('received', 'sent', 'returned', 'delivered'):
            icp.set_param('vendor_claim.sms_%s_enabled' % event, 'True' if auto_sms else 'False')
        icp.set_param('vendor_claim.sms_reminder_enabled', 'False')

    # ── yardımcılar ──
    @property
    def Claim(self):
        return self.env['vendor.claim']

    def make_claim(self, user=None, **vals):
        base = {'customer_name': 'Ali Veli', 'customer_mobile': '05321234567', 'defect_description': 'Fermuar bozuk',
                'product_barcode': '8690000000311', 'customer_code': False}
        base.update(vals)
        return self.Claim.with_user(user or self.user).create(base)

    def force_state(self, claim, state, **extra):
        vals = dict(extra, state=state)
        claim.sudo().with_context(vendor_claim_state_ok=True).write(vals)
        return claim

    def claim_sms(self, claim):
        return self.env['sms.system.message'].sudo().search(
            [('res_model', '=', 'vendor.claim'), ('res_id', '=', claim.id)])

    def ago(self, **kw):
        return fields.Datetime.now() - timedelta(**kw)

    def controller(self, method, user=None, **kw):
        from odoo.addons.vendor_claim.controllers.vendor_claim_controller import VendorClaimController
        fake = SimpleNamespace(env=self.env(user=user or self.user))
        with patch(REQUEST, fake), patch('odoo.http.request', fake):   # Controller.env odoo.http.request'ten okur
            return getattr(VendorClaimController(), method)(**kw)


class VcCase(VcMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vc_setup_class()

    def setUp(self):
        super().setUp()
        self.vc_setup()


class VcHttpCase(VcMixin, HttpCase):
    block_session = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vc_setup_class()

    def setUp(self):
        super().setUp()
        self.vc_setup()

    def rpc(self, route, **params):
        return self.make_jsonrpc_request(route, params)


def b64(raw=b'x'):
    return base64.b64encode(raw).decode()

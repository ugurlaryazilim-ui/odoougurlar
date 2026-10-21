import json
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.http import Request
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestProductExportAccess(HttpCase):
    """/ugurlar/product/export yalnız iç kullanıcıya açık; okuma sudo'suz yapılır."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.internal = Users.create({
            'name': 'Export İç', 'login': 'export_internal', 'password': 'export_internal',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.portal = Users.create({
            'name': 'Export Portal', 'login': 'export_portal', 'password': 'export_portal',
            'group_ids': [(6, 0, [cls.env.ref('base.group_portal').id])],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Export Ürün', 'default_code': 'EXP-1', 'standard_price': 42.0,
        })

    def _export(self, login, fields=None):
        self.authenticate(login, login)
        payload = {
            'res_model': 'product.product',
            'ids': [self.product.id],
            'fields': fields or [{'name': 'default_code', 'label': 'Kod', 'type': 'char'}],
        }
        return self.url_open('/ugurlar/product/export', data={
            'data': json.dumps(payload), 'csrf_token': Request.csrf_token(self),
        })

    def test_internal_user_gets_xlsx(self):
        res = self._export('export_internal')
        self.assertEqual(res.status_code, 200)
        self.assertIn('spreadsheetml', res.headers['Content-Type'])
        self.assertTrue(res.content.startswith(b'PK'))  # xlsx = zip

    def test_portal_user_is_forbidden(self):
        # alan listesi istemciden geldiği için maliyet fiyatı da istenebilir
        res = self._export('export_portal', [{'name': 'standard_price', 'type': 'monetary'}])
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.content.startswith(b'PK'))

    def test_access_error_on_read_returns_403_not_500(self):
        # NEDEN: sudo kalkınca kullanıcı hakkı olmayan alan AccessError verir; 500 değil 403 beklenir
        Model = type(self.env['product.product'])
        with patch.object(Model, 'read', side_effect=AccessError('yetkisiz alan')):
            res = self._export('export_internal')
        self.assertEqual(res.status_code, 403)

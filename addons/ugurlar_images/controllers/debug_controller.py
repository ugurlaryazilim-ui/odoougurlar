import json
from odoo import http
from odoo.http import request


class DebugImagesController(http.Controller):
    """Debug controller — yalnızca sistem yöneticisi erişebilir."""

    def _check_admin(self):
        if not request.env.user.has_group('base.group_system'):
            return request.make_response(
                json.dumps({'status': 'error', 'message': 'Yetkisiz erişim. Sadece yönetici kullanabilir.'}),
                status=403,
                headers=[('Content-Type', 'application/json')],
            )
        return None

    @http.route('/debug/images', type='http', auth='user', csrf=False, methods=['GET'])
    def debug_images(self, **kwargs):
        err = self._check_admin()
        if err: return err
        try:
            images = request.env['product.image'].sudo().search([], limit=100)
            data = [{
                'id': img.id,
                'name': img.name,
                'product_tmpl_id': img.product_tmpl_id.id if img.product_tmpl_id else False,
                'product_variant_id': img.product_variant_id.id if img.product_variant_id else False,
                'has_image_1920': bool(img.image_1920),
            } for img in images]
            return request.make_response(
                json.dumps({'status': 'success', 'images': data}, indent=4, default=str),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')],
            )

    @http.route('/debug/inspect_product', type='http', auth='user', csrf=False, methods=['GET'])
    def inspect_product(self, tmpl_id=None, **kwargs):
        err = self._check_admin()
        if err: return err
        try:
            if not tmpl_id:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'tmpl_id parametresi gerekli'}),
                    headers=[('Content-Type', 'application/json')],
                )
            tmpl_id = int(tmpl_id)
            images = request.env['product.image'].sudo().search([
                '|',
                ('product_tmpl_id', '=', tmpl_id),
                ('product_variant_id.product_tmpl_id', '=', tmpl_id)
            ])
            data = [{
                'id': img.id,
                'name': img.name,
                'product_tmpl_id': img.product_tmpl_id.id if img.product_tmpl_id else False,
                'product_variant_id': img.product_variant_id.id if img.product_variant_id else False,
                'has_image_1920': bool(img.image_1920),
            } for img in images]
            return request.make_response(
                json.dumps({'status': 'success', 'tmpl_id': tmpl_id, 'images': data}, indent=4, default=str),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')],
            )

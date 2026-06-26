import json
from odoo import http
from odoo.http import request

class DebugImagesController(http.Controller):

    @http.route('/debug/images', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_images(self, **kwargs):
        try:
            # Use Odoo ORM to query product.image records
            images = request.env['product.image'].sudo().search([], limit=100)
            
            data = []
            for img in images:
                data.append({
                    'id': img.id,
                    'name': img.name,
                    'product_tmpl_id': img.product_tmpl_id.id if img.product_tmpl_id else False,
                    'product_tmpl_name': img.product_tmpl_id.name if img.product_tmpl_id else False,
                    'product_variant_id': img.product_variant_id.id if img.product_variant_id else False,
                    'product_variant_barcode': img.product_variant_id.barcode if img.product_variant_id else False,
                    'has_image_1920': bool(img.image_1920),
                    'can_image_1024_be_zoomed': img.can_image_1024_be_zoomed,
                })
            
            result = {
                'status': 'success',
                'images': data
            }
            return request.make_response(
                json.dumps(result, indent=4, default=str),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/debug/fix_images', type='http', auth='public', csrf=False, methods=['GET'])
    def fix_images(self, **kwargs):
        try:
            # Find product.image records where product_tmpl_id is False but product_variant_id is set
            images = request.env['product.image'].sudo().search([
                ('product_tmpl_id', '=', False),
                ('product_variant_id', '!=', False)
            ])
            
            fixed_count = 0
            for img in images:
                if img.product_variant_id and img.product_variant_id.product_tmpl_id:
                    img.write({
                        'product_tmpl_id': img.product_variant_id.product_tmpl_id.id
                    })
                    fixed_count += 1
                    
            result = {
                'status': 'success',
                'message': f'Successfully updated {fixed_count} product.image records with their product_tmpl_id.'
            }
            return request.make_response(
                json.dumps(result, indent=4, default=str),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/debug/read_core_file', type='http', auth='public', csrf=False, methods=['GET'])
    def read_core_file(self, path=None, **kwargs):
        try:
            if not path:
                path = '/usr/lib/python3/dist-packages/odoo/addons/website_sale/models/product_template.py'
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return request.make_response(
                content,
                headers=[('Content-Type', 'text/plain; charset=utf-8')]
            )
        except Exception as e:
            return request.make_response(
                str(e),
                headers=[('Content-Type', 'text/plain; charset=utf-8')]
            )

    @http.route('/debug/acl', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_acl(self, **kwargs):
        try:
            accesses = request.env['ir.model.access'].sudo().search([
                ('model_id.model', '=', 'product.image')
            ])
            
            data = []
            for a in accesses:
                data.append({
                    'id': a.id,
                    'name': a.name,
                    'group': a.group_id.name if a.group_id else 'Public/All',
                    'group_external_id': a.group_id.get_external_id()[a.group_id.id] if a.group_id else False,
                    'perm_read': a.perm_read,
                    'perm_write': a.perm_write,
                    'perm_create': a.perm_create,
                    'perm_unlink': a.perm_unlink,
                })
            
            result = {
                'status': 'success',
                'acl': data
            }
            return request.make_response(
                json.dumps(result, indent=4, default=str),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/debug/rules', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_rules(self, **kwargs):
        try:
            rules = request.env['ir.rule'].sudo().search([
                ('model_id.model', '=', 'product.image')
            ])
            
            data = []
            for r in rules:
                data.append({
                    'id': r.id,
                    'name': r.name,
                    'active': r.active,
                    'domain_force': r.domain_force,
                    'perm_read': r.perm_read,
                    'perm_write': r.perm_write,
                    'perm_create': r.perm_create,
                    'perm_unlink': r.perm_unlink,
                    'groups': [g.name for g in r.groups],
                })
            
            result = {
                'status': 'success',
                'rules': data
            }
            return request.make_response(
                json.dumps(result, indent=4, default=str),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/debug/inspect_image_field', type='http', auth='public', csrf=False, methods=['GET'])
    def inspect_image_field(self, **kwargs):
        try:
            import os
            odoo_path = "/usr/lib/python3/dist-packages/odoo"
            
            found = []
            for root, dirs, files in os.walk(odoo_path):
                for f in files:
                    if f.endswith('.py'):
                        path = os.path.join(root, f)
                        try:
                            with open(path, 'r', encoding='utf-8') as file:
                                content = file.read()
                                if 'class ImageMixin' in content or ('models.AbstractModel' in content and 'image_128 = ' in content):
                                    found.append(path)
                        except Exception:
                            pass
            
            content = "No files found."
            if found:
                with open(found[0], 'r', encoding='utf-8') as file:
                    content = f"=== File: {found[0]} ===\n" + file.read()
                    
            return request.make_response(
                content,
                headers=[('Content-Type', 'text/plain; charset=utf-8')]
            )
        except Exception as e:
            return request.make_response(
                str(e),
                headers=[('Content-Type', 'text/plain; charset=utf-8')]
            )

    @http.route('/debug/inspect_product', type='http', auth='public', csrf=False, methods=['GET'])
    def inspect_product(self, tmpl_id=32449, **kwargs):
        try:
            tmpl_id = int(tmpl_id)
            # Find all product.image records for the template
            images = request.env['product.image'].sudo().search([
                '|',
                ('product_tmpl_id', '=', tmpl_id),
                ('product_variant_id.product_tmpl_id', '=', tmpl_id)
            ])
            
            data = []
            for img in images:
                data.append({
                    'id': img.id,
                    'name': img.name,
                    'product_tmpl_id': img.product_tmpl_id.id if img.product_tmpl_id else False,
                    'product_variant_id': img.product_variant_id.id if img.product_variant_id else False,
                    'product_variant_name': img.product_variant_id.display_name if img.product_variant_id else False,
                    'has_image_1920': bool(img.image_1920),
                    'image_1920_len': len(img.image_1920) if img.image_1920 else 0,
                    'image_128_len': len(img.image_128) if img.image_128 else 0,
                    'can_image_1024_be_zoomed': img.can_image_1024_be_zoomed,
                })
                
            # Let's also inspect the variants of this template
            variants = request.env['product.product'].sudo().search([
                ('product_tmpl_id', '=', tmpl_id)
            ])
            var_data = []
            for v in variants:
                var_data.append({
                    'id': v.id,
                    'display_name': v.display_name,
                    'barcode': v.barcode,
                    'has_image_variant_1920': bool(v.image_variant_1920),
                    'has_image_1920': bool(v.image_1920),
                    'extra_image_count': len(v.product_variant_image_ids),
                })
            
            result = {
                'status': 'success',
                'tmpl_id': tmpl_id,
                'images': data,
                'variants': var_data,
            }
            return request.make_response(
                json.dumps(result, indent=4, default=str),
                headers=[('Content-Type', 'application/json')]
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')]
            )

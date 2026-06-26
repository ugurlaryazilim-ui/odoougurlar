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

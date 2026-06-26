import json
from odoo import http
from odoo.http import request

class DebugImagesController(http.Controller):

    @http.route('/debug/images', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_images(self, **kwargs):
        try:
            # Query product_image table
            request.env.cr.execute("""
                SELECT pi.id, pi.name, pi.product_tmpl_id, pi.product_variant_id, 
                       length(pi.image_1920) as size,
                       pt.name as template_name,
                       pp.barcode as variant_barcode
                FROM product_image pi
                LEFT JOIN product_template pt ON pi.product_tmpl_id = pt.id
                LEFT JOIN product_product pp ON pi.product_variant_id = pp.id
                ORDER BY pi.id DESC
                LIMIT 200
            """)
            rows = request.env.cr.fetchall()
            
            data = []
            for r in rows:
                data.append({
                    'id': r[0],
                    'name': r[1],
                    'product_tmpl_id': r[2],
                    'product_variant_id': r[3],
                    'size': r[4],
                    'template_name': r[5],
                    'variant_barcode': r[6]
                })
            
            # Also get some templates with their image count
            request.env.cr.execute("""
                SELECT pt.id, pt.name, count(pi.id)
                FROM product_template pt
                JOIN product_image pi ON pi.product_tmpl_id = pt.id
                GROUP BY pt.id, pt.name
                LIMIT 50
            """)
            template_rows = request.env.cr.fetchall()
            templates = [{'id': r[0], 'name': r[1], 'image_count': r[2]} for r in template_rows]
            
            result = {
                'status': 'success',
                'images': data,
                'templates_with_images': templates
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

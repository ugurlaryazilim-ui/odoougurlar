import json
from odoo import http
from odoo.http import request

class DebugImagesController(http.Controller):

    @http.route('/debug/images', type='http', auth='public', csrf=False, methods=['GET'])
    def debug_images(self, **kwargs):
        try:
            # Query columns of product_image
            request.env.cr.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'product_image'
            """)
            columns = [{'column_name': r[0], 'data_type': r[1]} for r in request.env.cr.fetchall()]

            # Also query some records from product_image (excluding binary data fields for now)
            request.env.cr.execute("""
                SELECT id, name, product_tmpl_id, product_variant_id
                FROM product_image
                ORDER BY id DESC
                LIMIT 50
            """)
            rows = request.env.cr.fetchall()
            
            data = []
            for r in rows:
                data.append({
                    'id': r[0],
                    'name': r[1],
                    'product_tmpl_id': r[2],
                    'product_variant_id': r[3]
                })
            
            result = {
                'status': 'success',
                'columns': columns,
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

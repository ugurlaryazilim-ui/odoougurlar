from odoo import http
from odoo.http import request


class EkOzelliklerController(http.Controller):

    @http.route(
        '/ek_ozellikler/product_settings',
        type='json', auth='public', website=True,
    )
    def get_product_settings(self):
        """SKU/Barkod gösterim ayarlarını frontend JS'e döner."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'show_sku': ICP.get_param('ek_ozellikler.show_sku') == 'True',
            'show_barcode': ICP.get_param('ek_ozellikler.show_barcode') == 'True',
        }

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductTemplateSkuBarcode(models.Model):
    """
    product.template'e _get_combination_info override ekler.
    Variant değiştiğinde SKU ve barkod bilgisini JS'e gönderir.
    """
    _inherit = 'product.template'

    def _get_combination_info(self, *args, **kwargs):
        """Extend combination info with SKU and barcode for dynamic updates."""
        res = super()._get_combination_info(*args, **kwargs)
        only_template = kwargs.get('only_template', False)
        # Belirli bir variant varsa SKU ve barkod bilgisini ekle
        if not only_template and res.get('product_id'):
            variant = self.env['product.product'].sudo().browse(
                res['product_id']
            )
            if variant.exists():
                res['default_code'] = variant.default_code or ''
                res['barcode'] = variant.barcode or ''

        # JS'in her zaman bu anahtarları bulmasını garantile
        res.setdefault('default_code', '')
        res.setdefault('barcode', '')
        return res

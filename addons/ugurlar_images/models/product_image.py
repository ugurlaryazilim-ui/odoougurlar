import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ProductImage(models.Model):
    """Ürünlere birden fazla alternatif görsel ekleme desteği."""
    _name = 'product.image'
    _description = 'Ürün Görseli'
    _order = 'sequence, id'

    name = fields.Char(string='Açıklama', required=True)
    sequence = fields.Integer(string='Sıra', default=10)
    image_1920 = fields.Image(string='Görsel', max_width=1920, max_height=1920, required=True)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Ürün Şablonu',
        index=True,
        ondelete='cascade',
    )
    product_variant_id = fields.Many2one(
        'product.product',
        string='Ürün Varyantı',
        index=True,
        ondelete='cascade',
    )


class ProductTemplateImageExtend(models.Model):
    """product.template üzerinde ek görseller (şablon bazlı)."""
    _inherit = 'product.template'

    product_template_image_ids = fields.One2many(
        'product.image',
        'product_tmpl_id',
        string='Şablon Görselleri',
    )


class ProductProductImageExtend(models.Model):
    """product.product (varyant/barkod) bazlı ek görseller."""
    _inherit = 'product.product'

    # Eski view'larla uyumluluk — şablon görselleri
    product_template_image_ids = fields.One2many(
        related='product_tmpl_id.product_template_image_ids',
        string='Şablon Görselleri',
        readonly=False,
    )

    # Barkod bazlı görseller — ASIL kullanılan alan
    product_variant_image_ids = fields.One2many(
        'product.image',
        'product_variant_id',
        string='Alternatif Görseller',
    )

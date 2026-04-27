import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ProductImage(models.Model):
    """Ürünlere birden fazla alternatif görsel ekleme desteği."""
    _name = 'product.image'
    _description = 'Ürün Görseli'
    _order = 'sequence, id'
    _rec_name = 'name'

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

    # Odoo 19: models.Constraint (eski _sql_constraints kaldırıldı)
    _unique_variant_name = models.Constraint(
        'UNIQUE(product_variant_id, name)',
        'Bu varyant için bu isimde sadece bir görsel olabilir!',
    )


class ProductProductImageExtend(models.Model):
    """product.product (varyant/barkod) bazlı ek görseller."""
    _inherit = 'product.product'

    # Barkod bazlı görseller — her varyantın kendi görselleri
    product_variant_image_ids = fields.One2many(
        'product.image',
        'product_variant_id',
        string='Alternatif Görseller',
    )

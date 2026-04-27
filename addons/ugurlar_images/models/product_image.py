import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ProductImage(models.Model):
    """Ürünlere birden fazla alternatif görsel ekleme desteği.

    Bu model Odoo'nun standart 'product.image' modelini sağlar.
    Eğer başka bir modül (ör: website_sale) zaten tanımlıyorsa,
    Odoo otomatik olarak birleştirir.
    """
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
    """product.template'e ek görsel alanı ekler."""
    _inherit = 'product.template'

    product_template_image_ids = fields.One2many(
        'product.image',
        'product_tmpl_id',
        string='Alternatif Görseller',
    )

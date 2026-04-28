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
    """
    product.product (varyant/barkod) bazlı ek görseller.

    Odoo'nun varsayılan davranışı:
      image_1920 = image_variant_1920 OR product_tmpl_id.image_1920

    Bu override ile çoklu varyantlı ürünlerde template fallback kapatılır.
    Böylece farklı renkteki varyantlar, template görselini göstermez.

    Tek varyantlı ürünlerde Odoo'nun normal davranışı korunur.
    """
    _inherit = 'product.product'

    # Barkod bazlı görseller — her varyantın kendi görselleri
    product_variant_image_ids = fields.One2many(
        'product.image',
        'product_variant_id',
        string='Alternatif Görseller',
    )

    @api.depends('image_variant_1920', 'product_tmpl_id.image_1920')
    def _compute_image_1920(self):
        """
        Çoklu varyantlı ürünlerde template image fallback'i kapat.

        - Tek varyant   → normal davranış (template fallback çalışır)
        - Çoklu varyant → SADECE kendi image_variant_1920'sini göster
        """
        for product in self:
            if product.image_variant_1920:
                # Varyantın kendi resmi var → onu göster
                product.image_1920 = product.image_variant_1920
            elif product.product_tmpl_id.product_variant_count <= 1:
                # Tek varyantlı ürün → template fallback (Odoo varsayılan)
                product.image_1920 = product.product_tmpl_id.image_1920
            else:
                # Çoklu varyant, kendi resmi yok → BOŞ göster
                # (template resminin farklı renklere sızmasını engelle)
                product.image_1920 = False

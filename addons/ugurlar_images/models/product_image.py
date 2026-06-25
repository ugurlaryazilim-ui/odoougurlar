import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductImage(models.Model):
    """Ürünlere birden fazla alternatif görsel ekleme desteği."""
    _inherit = 'product.image'

    @api.constrains('product_variant_id', 'name')
    def _check_unique_variant_name(self):
        for image in self:
            if image.product_variant_id and image.name:
                duplicates = self.search_count([
                    ('product_variant_id', '=', image.product_variant_id.id),
                    ('name', '=', image.name),
                    ('id', '!=', image.id),
                ])
                if duplicates > 0:
                    raise ValidationError(_('Bu varyant için bu isimde sadece bir görsel olabilir!'))

    def _compute_can_image_1024_be_zoomed(self):
        """
        Görsel boyut kontrolü.
        MemoryError hatasını önlemek için prefetch kapatılarak teker teker işlenir.
        """
        from odoo.tools.image import is_image_size_above
        for image in self.with_context(prefetch_fields=False):
            try:
                image.can_image_1024_be_zoomed = image.image_1920 and is_image_size_above(image.image_1920, image.image_1024)
            except Exception as e:
                _logger.warning('Zoom recompute error for image %s: %s', image.id, e)
                image.can_image_1024_be_zoomed = False


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

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

    _logged_debug = False

    def _compute_can_image_1024_be_zoomed(self):
        """
        Görsel boyut kontrolü.
        MemoryError hatasını önlemek için doğrudan True set edilir.
        Görsel sorunlarını teşhis etmek için veri tabanındaki kayıtları loglar.
        """
        if not ProductImage._logged_debug:
            ProductImage._logged_debug = True
            try:
                self.env.cr.execute("SELECT id, name, product_tmpl_id, product_variant_id, length(image_1920) FROM product_image")
                results = self.env.cr.fetchall()
                _logger.info("📸 DATABASE IMAGE COUNT: %d", len(results))
                for row in results[:150]:
                    _logger.info("📸 DB IMAGE: id=%s, name=%s, tmpl_id=%s, variant_id=%s, size=%s",
                                 row[0], row[1], row[2], row[3], row[4])
            except Exception as e:
                _logger.error("Error running database image query: %s", e)
        for image in self:
            image.can_image_1024_be_zoomed = True


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

    def _get_images(self):
        """
        Varyant bazlı resim çekme.
        Sadece bu varyantın rengine ait olan resimleri gösterir ve beden bazlı tekrarları eler.
        """
        self.ensure_one()
        
        # Rengi bul (Türkçe ve İngilizce özellikleri destekler)
        color_attribute = self.env['product.attribute'].sudo().search([
            '|', ('name', 'ilike', 'Renk'), ('name', 'ilike', 'Color')
        ], limit=1)
        
        selected_color_value = False
        if color_attribute:
            color_val = self.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id.id == color_attribute.id
            )
            if color_val:
                selected_color_value = color_val.product_attribute_value_id.name
                
        # Tüm template extra resimlerini al
        all_extra_images = self.product_tmpl_id.product_template_image_ids
        
        filtered_images = []
        seen_names = set()
        
        for img in all_extra_images:
            is_valid = False
            if not img.product_variant_id:
                # Genel resim (her varyanta uygun)
                is_valid = True
            elif selected_color_value:
                # Varyantın rengini kontrol et
                img_color_val = img.product_variant_id.product_template_attribute_value_ids.filtered(
                    lambda v: v.attribute_id.id == color_attribute.id
                )
                if img_color_val and img_color_val.product_attribute_value_id.name == selected_color_value:
                    is_valid = True
            else:
                # Renksiz bir ürün ise, sadece kendi varyantı ise göster
                if img.product_variant_id.id == self.id:
                    is_valid = True
                    
            if is_valid:
                # Resim adına göre tekilleştirme (Beden bazlı tekrarları önlemek için)
                img_name = img.name or ''
                if img_name not in seen_names:
                    seen_names.add(img_name)
                    filtered_images.append(img)
                    
        return [self] + filtered_images


class ProductTemplateImageExtend(models.Model):
    _inherit = 'product.template'

    def _get_images(self):
        """Şablon bazlı resim çekme. Resim adına göre tekilleştirme uygular."""
        self.ensure_one()
        all_extra_images = self.product_template_image_ids
        filtered_images = []
        seen_names = set()
        for img in all_extra_images:
            img_name = img.name or ''
            if img_name not in seen_names:
                seen_names.add(img_name)
                filtered_images.append(img)
        return [self] + filtered_images

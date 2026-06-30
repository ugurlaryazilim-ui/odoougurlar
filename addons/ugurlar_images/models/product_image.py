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
            # HATALI KOD (İşlemi kilitler):
            # Odoo'da image_1920 veritabanı kolonu olmayabilir (attachment'ta tutulur). 
            # Raw SQL exception fırlattığında ve savepoint olmadığında tüm transaction iptal olur!
            # Bu yüzden bu log satırını kapattık.
            _logger.info("📸 DATABASE IMAGE COUNT CHECK DISABLED TO PREVENT TRANSACTION ABORT")
                
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
        Varyant bazlı resim çekme — beden tekrarını kesin olarak önler.

        Strateji:
          1. Genel resimler (product_variant_id boş) → her zaman göster
          2. Aynı renkteki varyantlardan sadece BİRİNİN resimlerini göster
             (öncelik: mevcut varyant > ilk bulunan varyant)
          3. Renksiz ürünlerde sadece kendi varyant resimlerini göster

        Bu sayede 3 resim × 4 beden = 12 resim yerine sadece 3 resim gösterilir.
        """
        self.ensure_one()

        # ── Renk özelliğini bul ──
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

        # ── Tüm template extra resimlerini al ──
        all_extra_images = self.product_tmpl_id.product_template_image_ids

        # Genel resimler (hiçbir varyanta bağlı olmayan)
        generic_images = list(all_extra_images.filtered(
            lambda img: not img.product_variant_id
        ))

        if not selected_color_value:
            # Renksiz ürün → sadece kendi varyant resimlerini göster
            my_images = list(all_extra_images.filtered(
                lambda img: img.product_variant_id.id == self.id
            ))
            return [self] + generic_images + my_images

        # ── Aynı renkteki varyant ID'lerini bul ──
        same_color_variant_ids = set()
        for variant in self.product_tmpl_id.product_variant_ids:
            for ptav in variant.product_template_attribute_value_ids:
                if (ptav.attribute_id.id == color_attribute.id
                        and ptav.product_attribute_value_id.name == selected_color_value):
                    same_color_variant_ids.add(variant.id)
                    break

        # ── Bu renkteki varyant resimlerini al ──
        color_images = all_extra_images.filtered(
            lambda img: img.product_variant_id.id in same_color_variant_ids
        )

        # ── Sadece BİR varyantın resimlerini seç (beden tekrarını önle) ──
        # Öncelik: mevcut varyant → yoksa ilk bulunan varyant
        representative_id = None
        if color_images:
            my_images = color_images.filtered(
                lambda img: img.product_variant_id.id == self.id
            )
            if my_images:
                representative_id = self.id
            else:
                representative_id = color_images[0].product_variant_id.id

        if representative_id:
            selected_images = list(color_images.filtered(
                lambda img: img.product_variant_id.id == representative_id
            ))
        else:
            selected_images = []

        return [self] + generic_images + selected_images


class ProductTemplateImageExtend(models.Model):
    _inherit = 'product.template'

    def _get_images(self):
        """
        Şablon bazlı resim çekme — renk başına tek varyant resimleri gösterir.

        Beden tekrarını önlemek için her renk grubu için sadece
        ilk bulunan varyantın resimlerini gösterir.
        """
        self.ensure_one()
        all_extra_images = self.product_template_image_ids

        # Genel resimler (varyanta bağlı olmayan)
        generic_images = list(all_extra_images.filtered(
            lambda img: not img.product_variant_id
        ))

        # Renk özelliğini bul
        color_attribute = self.env['product.attribute'].sudo().search([
            '|', ('name', 'ilike', 'Renk'), ('name', 'ilike', 'Color')
        ], limit=1)

        variant_images = all_extra_images.filtered(
            lambda img: img.product_variant_id
        )

        if not color_attribute or not variant_images:
            # Renk özelliği yok veya varyant resimleri yok
            # Her varyant ID'si için sadece ilkini al
            seen_variant_ids = set()
            deduped = []
            for img in variant_images:
                vid = img.product_variant_id.id
                if vid not in seen_variant_ids:
                    seen_variant_ids.add(vid)
                    # Bu varyantın tüm resimlerini al
                    deduped.extend(list(variant_images.filtered(
                        lambda i, v=vid: i.product_variant_id.id == v
                    )))
                    break  # Sadece ilk varyant yeterli
            return [self] + generic_images + deduped

        # ── Renk bazlı gruplama: her renk için sadece 1 varyantın resimlerini al ──
        seen_colors = set()
        color_deduped = []

        for img in variant_images:
            # Bu resmin varyantının rengini bul
            img_color_val = img.product_variant_id.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id.id == color_attribute.id
            )
            color_name = (img_color_val.product_attribute_value_id.name
                          if img_color_val else '__no_color__')

            if color_name not in seen_colors:
                seen_colors.add(color_name)
                # Bu renk + varyant ID'si için tüm resimleri al
                this_variant_id = img.product_variant_id.id
                color_deduped.extend(list(variant_images.filtered(
                    lambda i, v=this_variant_id: i.product_variant_id.id == v
                )))

        return [self] + generic_images + color_deduped


import logging

from odoo import models, api

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ------------------------------------------------------------------
    #  e-Ticarete Bağla — Server Action Metodu
    # ------------------------------------------------------------------
    def action_publish_ecommerce(self):
        """
        Seçili ürünleri e-ticarete yayınla ve dahili kategorilerini
        otomatik olarak e-ticaret kategorilerine eşle.

        Aksiyonlar dropdown'undan çağrılır (binding_model_id).

        Kurallar:
          • Görseli olmayan ürünler atlanır
          • Zaten yayınlı olanlar tekrar yazılmaz (sadece kategori kontrol)
          • Dahili kategori → e-ticaret kategorisi eşlenir (mükerrer oluşturmaz)
        """
        published = 0
        skipped_no_image = 0
        already_published = 0
        categories_created = 0
        category_cache = {}  # {categ_id: (public_categ, created)}

        for tmpl in self:
            # ── Görseli yoksa atla ──
            if not tmpl.image_1920:
                skipped_no_image += 1
                continue

            # ── Yayınla ──
            if not tmpl.is_published:
                tmpl.is_published = True
                published += 1
            else:
                already_published += 1

            # ── Dahili kategori → e-Ticaret kategorisi eşle ──
            if tmpl.categ_id and tmpl.categ_id.id:
                categ = tmpl.categ_id
                if categ.id not in category_cache:
                    public_categ, created = self._get_or_create_public_category(categ)
                    category_cache[categ.id] = (public_categ, created)
                    if created:
                        categories_created += 1
                else:
                    public_categ, _ = category_cache[categ.id]

                if public_categ and public_categ not in tmpl.public_categ_ids:
                    tmpl.public_categ_ids = [(4, public_categ.id)]

        _logger.info(
            "e-Ticaret yayınlama: %d yayınlandı, %d zaten yayında, "
            "%d görselsiz atlandı, %d yeni kategori oluşturuldu",
            published, already_published, skipped_no_image, categories_created,
        )

        # ── Sonuç bildirimi ──
        message_parts = []
        if published:
            message_parts.append(f'✅ {published} ürün yayınlandı')
        if already_published:
            message_parts.append(f'ℹ️ {already_published} zaten yayında')
        if skipped_no_image:
            message_parts.append(f'⚠️ {skipped_no_image} görselsiz atlandı')
        if categories_created:
            message_parts.append(f'📁 {categories_created} yeni kategori oluşturuldu')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'e-Ticaret Yayınlama',
                'message': '\n'.join(message_parts) or 'İşlenecek ürün bulunamadı.',
                'type': 'success' if published else 'warning',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    #  Kategori Eşleme Yardımcısı
    # ------------------------------------------------------------------
    @api.model
    def _get_or_create_public_category(self, internal_categ):
        """
        Dahili kategoriyi (product.category) e-ticaret kategorisine
        (product.public.category) eşle. Yoksa oluştur.

        Hiyerarşi desteği:
          • Dahili kategoride parent_id varsa, önce parent eşlenir
          • Aynı isim + aynı parent = mükerrer oluşturmaz

        Args:
            internal_categ: product.category recordset

        Returns:
            tuple: (product.public.category recordset, bool created)
        """
        PublicCategory = self.env['product.public.category'].sudo()

        # ── Kategori zincirini oluştur (kökten yaprağa) ──
        chain = []
        current = internal_categ
        while current:
            chain.append(current)
            current = current.parent_id
        chain.reverse()  # Kökten yaprağa sırala

        parent_public_id = False
        public_categ = None
        created = False

        for categ in chain:
            # Aynı isim + aynı parent ile ara
            existing = PublicCategory.search([
                ('name', '=', categ.name),
                ('parent_id', '=', parent_public_id),
            ], limit=1)

            if existing:
                public_categ = existing
            else:
                public_categ = PublicCategory.create({
                    'name': categ.name,
                    'parent_id': parent_public_id,
                })
                created = True
                _logger.info(
                    "e-Ticaret kategorisi oluşturuldu: '%s' (parent_id=%s)",
                    categ.name, parent_public_id,
                )

            parent_public_id = public_categ.id

        return public_categ, created

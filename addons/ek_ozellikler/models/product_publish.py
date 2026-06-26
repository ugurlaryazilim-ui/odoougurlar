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
          • Görseli olmayan ürünler atlanır (SQL ile kontrol — bellek güvenli)
          • Zaten yayınlı olanlar tekrar yazılmaz
          • Dahili kategori → e-ticaret kategorisi eşlenir (mükerrer oluşturmaz)
          • Toplu write ile performanslı çalışır
        """
        if not self:
            return

        # ── Görseli olan ürün ID'lerini SQL ile bul (MemoryError önleme) ──
        # image_1920 attachment olarak saklanıyor, binary yüklemeden kontrol
        cr = self.env.cr
        cr.execute("""
            SELECT DISTINCT res_id
            FROM ir_attachment
            WHERE res_model = 'product.template'
              AND res_field = 'image_1920'
              AND res_id IN %s
        """, (tuple(self.ids),))
        ids_with_image = {row[0] for row in cr.fetchall()}

        # Attachment'ta bulunamadıysa, tabloda direkt saklananları da kontrol et
        if len(ids_with_image) < len(self):
            remaining_ids = tuple(set(self.ids) - ids_with_image)
            if remaining_ids:
                cr.execute("""
                    SELECT id FROM product_template
                    WHERE id IN %s
                      AND image_1920 IS NOT NULL
                """, (remaining_ids,))
                ids_with_image.update(row[0] for row in cr.fetchall())

        # ── Filtreleme ──
        templates_with_image = self.browse(
            [t_id for t_id in self.ids if t_id in ids_with_image]
        )
        skipped_no_image = len(self) - len(templates_with_image)

        if not templates_with_image:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'e-Ticaret Yayınlama',
                    'message': f'⚠️ Seçili {len(self)} üründe görsel bulunamadı.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # ── Toplu yayınlama ──
        to_publish = templates_with_image.filtered(lambda t: not t.is_published)
        already_published = len(templates_with_image) - len(to_publish)
        if to_publish:
            to_publish.write({'is_published': True})
        published = len(to_publish)

        # ── Kategori eşleme ──
        categories_created = 0
        category_cache = {}  # {internal_categ_id: public_categ}

        # Kategorilere göre grupla (toplu işlem)
        categ_to_tmpls = {}
        for tmpl in templates_with_image:
            if tmpl.categ_id and tmpl.categ_id.id:
                categ_to_tmpls.setdefault(tmpl.categ_id, self.env['product.template'])
                categ_to_tmpls[tmpl.categ_id] |= tmpl

        for internal_categ, tmpls in categ_to_tmpls.items():
            if internal_categ.id not in category_cache:
                public_categ, created = self._get_or_create_public_category(
                    internal_categ
                )
                category_cache[internal_categ.id] = public_categ
                if created:
                    categories_created += 1
            else:
                public_categ = category_cache[internal_categ.id]

            if public_categ:
                # Henüz bu kategoriye bağlı olmayanları filtrele
                to_assign = tmpls.filtered(
                    lambda t, pc=public_categ: pc not in t.public_categ_ids
                )
                if to_assign:
                    to_assign.write({
                        'public_categ_ids': [(4, public_categ.id)],
                    })

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
                'type': 'success' if published else 'info',
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

        # Kök "All" veya "Tümü" kategorisini atla (varsa)
        if len(chain) > 1 and not chain[0].parent_id and chain[0].name in (
            'All', 'Tümü', 'Tüm Ürünler',
        ):
            chain = chain[1:]

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

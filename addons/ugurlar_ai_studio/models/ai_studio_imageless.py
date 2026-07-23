# -*- coding: utf-8 -*-
"""
AI Studio — Görselsiz Ürünler Modeli

Görseli olmayan ürün varyantlarını tespit eder.
Her (template + renk) grubu için yalnızca bir beden seçer.
Marka/Sezon/Cinsiyet bilgilerini Nitelikler'den (product.attribute) çeker.
"""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiStudioImagelessLine(models.Model):
    _name = 'ai.studio.imageless.line'
    _description = 'Görselsiz Ürün Satırı'
    _order = 'product_name'

    # --- Ana İlişki ---
    product_id = fields.Many2one(
        'product.product', string='Ürün Varyantı',
        required=True, ondelete='cascade', index=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Ürün Şablonu',
        related='product_id.product_tmpl_id', store=True, index=True,
    )

    # --- Ürün Bilgileri ---
    default_code = fields.Char(
        string='Stok Kodu',
        related='product_id.default_code', store=True,
    )
    product_name = fields.Char(string='Ürün Adı', store=True)
    barcode = fields.Char(
        string='Barkod',
        related='product_id.barcode', store=True,
    )

    # --- Attribute Bilgileri ---
    color_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_imageless_color_rel', string='Renk',
        domain="[('attribute_id.name', 'ilike', 'renk')]"
    )
    size_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_imageless_size_rel', string='Beden',
        domain="['|', ('attribute_id.name', 'ilike', 'beden'), ('attribute_id.name', 'ilike', 'numara')]"
    )
    brand_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_imageless_brand_rel', string='Marka',
        domain="[('attribute_id.name', 'ilike', 'marka')]"
    )
    season_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_imageless_season_rel', string='Sezon',
        domain="[('attribute_id.name', 'ilike', 'sezon')]"
    )
    gender_value_ids = fields.Many2many(
        'product.attribute.value', 'ai_imageless_gender_rel', string='Cinsiyet',
        domain="[('attribute_id.name', 'ilike', 'cinsiyet')]"
    )
    category_name = fields.Char(string='Kategori', store=True)

    # --- Stok & Durum ---
    qty_available = fields.Float(string='Stok Miktarı', store=True, digits=(12, 0))
    has_session = fields.Boolean(
        string='AI Oturumu Var', store=True, default=False,
        help='Bu ürün için zaten bir AI Studio oturumu oluşturulmuş mu?',
    )

    # -------------------------------------------------------------------------
    # Listeyi Yenile
    # -------------------------------------------------------------------------
    @api.model
    def action_refresh(self):
        """Görselsiz + stokta olan ürünleri tespit et ve tabloyu güncelle."""
        _logger.info('Görselsiz ürün listesi yenileniyor...')

        # 1) Mevcut listeyi temizle (TRUNCATE SQL hizli silme)
        self.env.cr.execute("TRUNCATE TABLE ai_studio_imageless_line CASCADE")

        # 2) Stokta olan ürünlerin listesini al (ÇOK HIZLI SQL)
        # Sadece iç lokasyonlarda (usage = 'internal') stoku olanları buluruz
        self.env.cr.execute("""
            SELECT product_id 
            FROM stock_quant 
            WHERE quantity > 0 
              AND location_id IN (SELECT id FROM stock_location WHERE usage = 'internal')
            GROUP BY product_id
            HAVING sum(quantity) > 0
        """)
        in_stock_product_ids = [row[0] for row in self.env.cr.fetchall()]

        if not in_stock_product_ids:
            _logger.info('Stokta hiçbir ürün bulunamadı.')
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # 3) Sadece stokta olanlar içinden görselsizleri bul
        Product = self.env['product.product'].sudo()
        variants_with_stock = Product.search([
            ('id', 'in', in_stock_product_ids),
            ('product_tmpl_id.image_1920', '=', False),
            ('image_variant_1920', '=', False),
            ('active', '=', True),
            ('product_tmpl_id.active', '=', True),
        ])

        _logger.info('Stokta olan görselsiz varyant sayısı: %d', len(variants_with_stock))

        if not variants_with_stock:
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # Prefetch: N+1 sorgu engellemek için attribute verilerini toplu yükle
        variants_with_stock.mapped('product_template_attribute_value_ids.attribute_id')
        variants_with_stock.mapped('product_tmpl_id.attribute_line_ids.attribute_id')
        variants_with_stock.mapped('product_tmpl_id.attribute_line_ids.value_ids')
        variants_with_stock.mapped('product_tmpl_id.categ_id')

        # 4) Her (template + renk) grubu için bir beden seç
        seen = set()  # (template_id, color_value) çiftleri
        lines_data = []
        tmpl_cache = {}  # Performans için template verilerini önbelleğe al

        # Attribute adlarını doğrudan eşleştir (Nebim'den gelen kesin isimler)
        color_attrs = {'renk', 'color', 'colour'}
        size_attrs = {'beden', 'size', 'numara'}
        brand_attrs = {'marka', 'brand'}
        season_attrs = {'sezon', 'sezon/yıl', 'season'}
        gender_attrs = {'cinsiyet', 'gender'}

        # Tüm sistem genelinde iptal edilmemiş aktif AI oturumlarını bul
        active_sessions = self.env['ai.studio.session'].sudo().search([
            ('state', 'not in', ['cancelled']),
        ])

        # Oturumu olan (template_id, color_key) gruplarını tespit et
        existing_session_group_keys = set()
        for sess in active_sessions:
            if not sess.product_id:
                continue
            sess_prod = sess.product_id
            sess_tmpl_id = sess_prod.product_tmpl_id.id
            sess_color_id = None
            sess_color_name = ''
            for ptav in sess_prod.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name.lower().strip()
                if any(c in attr_name for c in color_attrs):
                    sess_color_id = ptav.product_attribute_value_id.id
                    sess_color_name = ptav.name or ''
                    break
            sess_key = (sess_tmpl_id, sess_color_id or sess_color_name or 'no_color')
            existing_session_group_keys.add(sess_key)

        for variant in variants_with_stock:
            tmpl = variant.product_tmpl_id

            # Cache kontrolü: Bu template daha önce işlendi mi?
            if tmpl.id not in tmpl_cache:
                b_ids, s_ids, g_ids = [], [], []
                # create_variant='no_variant' olan attribute'lar (Marka, Sezon, Cinsiyet)
                for ptal in tmpl.attribute_line_ids:
                    attr_name = ptal.attribute_id.name.lower().strip()
                    if ptal.attribute_id.create_variant == 'no_variant':
                        if any(a in attr_name for a in brand_attrs):
                            b_ids.extend(ptal.value_ids.ids)
                        elif any(a in attr_name for a in season_attrs):
                            s_ids.extend(ptal.value_ids.ids)
                        elif any(a in attr_name for a in gender_attrs):
                            g_ids.extend(ptal.value_ids.ids)
                
                tmpl_cache[tmpl.id] = {
                    'brand_ids': [(6, 0, b_ids)],
                    'season_ids': [(6, 0, s_ids)],
                    'gender_ids': [(6, 0, g_ids)],
                    'category': tmpl.categ_id.name if tmpl.categ_id else '-'
                }

            # Varyant attribute değerlerini parse et
            color_ids = []
            size_ids = []
            color_val = ''
            color_ptav_id = None

            # create_variant='always' olan attribute'lar (Renk, Beden)
            for ptav in variant.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name.lower().strip()
                if any(c in attr_name for c in color_attrs):
                    color_ptav_id = ptav.product_attribute_value_id.id
                    color_ids.append(ptav.product_attribute_value_id.id)
                    color_val = ptav.name or ''
                elif any(a in attr_name for a in size_attrs):
                    size_ids.append(ptav.product_attribute_value_id.id)

            # "Her renkten bir beden" gruplama key'i
            variant_group_key = (tmpl.id, color_ptav_id or color_val or 'no_color')
            if variant_group_key in seen:
                continue
            seen.add(variant_group_key)

            t_data = tmpl_cache[tmpl.id]

            # Bu renk grubundaki (herhangi bir bedeninde) aktif oturum var mı?
            group_has_session = variant_group_key in existing_session_group_keys

            lines_data.append({
                'product_id': variant.id,
                'product_name': variant.display_name or variant.name,
                'color_value_ids': [(6, 0, color_ids)],
                'size_value_ids': [(6, 0, size_ids)],
                'brand_value_ids': t_data['brand_ids'],
                'season_value_ids': t_data['season_ids'],
                'gender_value_ids': t_data['gender_ids'],
                'category_name': t_data['category'] or '-',
                'qty_available': variant.qty_available,
                'has_session': group_has_session,
            })

        # 5) Toplu oluştur
        if lines_data:
            self.create(lines_data)
            _logger.info('Görselsiz ürün listesi oluşturuldu: %d satır', len(lines_data))
        else:
            _logger.info('Görselsiz ürün bulunamadı.')

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # -------------------------------------------------------------------------
    # Resim Çek — Capture Ekranına Yönlendir
    # -------------------------------------------------------------------------
    def action_start_session(self):
        """Bu ürün için AI Studio capture ekranına yönlendir."""
        self.ensure_one()

        return {
            'type': 'ir.actions.client',
            'tag': 'ugurlar_ai_studio.main',
            'params': {
                'auto_product_id': self.product_id.id,
            },
        }

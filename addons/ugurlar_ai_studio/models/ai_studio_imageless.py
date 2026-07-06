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
    _order = 'brand_name, product_name, color_name'

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
    color_name = fields.Char(string='Renk', store=True, index=True)
    size_name = fields.Char(string='Beden', store=True)
    brand_name = fields.Char(string='Marka', store=True, index=True)
    season_name = fields.Char(string='Sezon', store=True, index=True)
    gender_name = fields.Char(string='Cinsiyet', store=True, index=True)
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

        # 1) Mevcut listeyi temizle
        self.search([]).unlink()

        # 2) Görselsiz varyantları bul
        #    - Template'in kendi görseli yok
        #    - Varyantın kendi görseli yok
        Product = self.env['product.product'].sudo()
        all_variants = Product.search([
            ('product_tmpl_id.image_1920', '=', False),
            ('image_variant_1920', '=', False),
            ('active', '=', True),
            ('product_tmpl_id.active', '=', True),
        ])

        _logger.info('Görselsiz varyant sayısı (filtresiz): %d', len(all_variants))

        # 3) Stokta olanları filtrele
        variants_with_stock = all_variants.filtered(lambda p: p.qty_available > 0)
        _logger.info('Stokta olan görselsiz varyant sayısı: %d', len(variants_with_stock))

        # Prefetch: N+1 sorgu engellemek için attribute verilerini toplu yükle
        variants_with_stock.mapped('product_template_attribute_value_ids.attribute_id')
        variants_with_stock.mapped('product_tmpl_id.attribute_line_ids.attribute_id')
        variants_with_stock.mapped('product_tmpl_id.attribute_line_ids.value_ids')
        variants_with_stock.mapped('product_tmpl_id.categ_id')

        # 4) Her (template + renk) grubu için bir beden seç
        seen = set()  # (template_id, color_value) çiftleri
        lines_data = []

        # Attribute adlarını doğrudan eşleştir (Nebim'den gelen kesin isimler)
        color_attrs = {'renk', 'color'}
        size_attrs = {'beden', 'size', 'numara'}
        brand_attrs = {'marka', 'brand'}
        season_attrs = {'sezon', 'sezon/yıl', 'season'}
        gender_attrs = {'cinsiyet', 'gender'}

        # Mevcut AI session'ları bul
        existing_sessions = set(
            self.env['ai.studio.session'].sudo().search([
                ('product_id', 'in', variants_with_stock.ids),
                ('state', 'not in', ['cancelled']),
            ]).mapped('product_id.id')
        )

        for variant in variants_with_stock:
            tmpl = variant.product_tmpl_id

            # Varyant attribute değerlerini parse et
            color_val = ''
            size_val = ''
            brand_val = ''
            season_val = ''
            gender_val = ''

            # create_variant='always' olan attribute'lar (Renk, Beden)
            for ptav in variant.product_template_attribute_value_ids:
                attr_name = ptav.attribute_id.name.lower().strip()
                value = ptav.name or ''

                if any(a in attr_name for a in color_attrs):
                    color_val = value
                elif any(a in attr_name for a in size_attrs):
                    size_val = value

            # create_variant='no_variant' olan attribute'lar (Marka, Sezon, Cinsiyet)
            # Bu attribute'lar template seviyesinde, product_template_attribute_value_ids
            # ile çekilir ama variant oluşturmaz
            for ptal in tmpl.attribute_line_ids:
                attr_name = ptal.attribute_id.name.lower().strip()
                if ptal.attribute_id.create_variant == 'no_variant':
                    values = ptal.value_ids
                    if values:
                        value = ', '.join(values.mapped('name'))
                        if any(a in attr_name for a in brand_attrs):
                            brand_val = value
                        elif any(a in attr_name for a in season_attrs):
                            season_val = value
                        elif any(a in attr_name for a in gender_attrs):
                            gender_val = value

            # "Her renkten bir beden" mantığı
            group_key = (tmpl.id, color_val)
            if group_key in seen:
                continue
            seen.add(group_key)

            lines_data.append({
                'product_id': variant.id,
                'product_name': variant.display_name or variant.name,
                'color_name': color_val or '-',
                'size_name': size_val or '-',
                'brand_name': brand_val or '-',
                'season_name': season_val or '-',
                'gender_name': gender_val or '-',
                'category_name': tmpl.categ_id.name if tmpl.categ_id else '-',
                'qty_available': variant.qty_available,
                'has_session': variant.id in existing_sessions,
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

# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ai_trendyol_title = fields.Char("Trendyol Başlığı", size=100, tracking=True)
    ai_ecommerce_title = fields.Char("E-Ticaret Başlığı", tracking=True)
    ai_short_description = fields.Text("AI Kısa Açıklama")
    ai_html_description = fields.Html("AI Zengin Açıklama", sanitize=True)
    ai_meta_title = fields.Char("SEO Meta Başlık", size=60)
    ai_meta_description = fields.Text("SEO Meta Açıklama")
    ai_seo_keywords = fields.Char("SEO Anahtar Kelimeler")
    ai_content_generated = fields.Boolean("AI İçerik Üretildi", default=False)
    ai_last_generated = fields.Datetime("Son AI Üretimi", readonly=True)
    ai_generation_count = fields.Integer("AI Üretim Sayısı", default=0)
    # AI ürün adını değiştirir; tekrar üretimde model kendi önceki başlığını değil
    # orijinal (Nebim) adı görsün diye ilk değişiklikten önceki ad saklanır
    ai_original_name = fields.Char("Orijinal Ürün Adı", copy=False,
                                   help="AI ürün adını ilk kez değiştirmeden önceki ad. Üretimde bu ad kullanılır.")

    def action_open_ai_title_wizard(self):
        self.ensure_one()
        if not self.image_1920:
            raise UserError(_("Ürün görseli (image_1920) bulunamadı. Lütfen önce görsel yükleyin."))
        
        return {
            'name': _('AI İçerik Üret'),
            'type': 'ir.actions.act_window',
            'res_model': 'ai.content.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': self.id,
                'default_mode': 'both',
            }
        }

    @api.model
    def _ai_sale_text(self, html, fallback=''):
        """description_sale düz metin alanı: HTML açıklamanın metin hâli (yoksa kısa özet)."""
        if html:
            text = html2plaintext(html).strip()
            if text:
                return text
        return fallback or ''

    def _ai_name_vals(self, new_name):
        """Ürün adını AI başlığıyla değiştirirken orijinal adı (bir kez) sakla."""
        self.ensure_one()
        vals = {'name': new_name}
        if not self.ai_original_name and self.name and self.name != new_name:
            vals['ai_original_name'] = self.name
        return vals

    @api.model
    def _ai_create_tags_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'ai_title_description.create_tags', 'True') == 'True'

    def action_view_ai_logs(self):
        """Bu ürünün AI üretim geçmişi (yalnız bu ürün)."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('ai_title_description.action_ai_content_log')
        action['domain'] = [('product_tmpl_id', '=', self.id)]
        action['context'] = {'default_product_tmpl_id': self.id}
        return action

    def _add_to_ai_queue(self, mode):
        """Toplu kuyruğa ekleme — Binary görselleri RAM'e çekmeden, batch insert ile güvenli ekler."""
        if not self:
            return 0

        # Zaten kuyrukta bekleyen veya işlenen kayıtları tekrar eklemeyelim
        existing_queued_pids = set(self.env['ai.content.queue'].search([
            ('product_tmpl_id', 'in', self.ids),
            ('state', 'in', ('pending', 'processing'))
        ]).mapped('product_tmpl_id.id'))

        to_create = [
            {'product_tmpl_id': pid, 'mode': mode}
            for pid in self.ids
            if pid not in existing_queued_pids
        ]

        if to_create:
            # 500'lük gruplarla batch insert yaparak veritabanını ve belleği koru
            batch_size = 500
            for i in range(0, len(to_create), batch_size):
                self.env['ai.content.queue'].create(to_create[i:i + batch_size])

        return len(to_create)

    def action_bulk_ai_generate_title(self):
        count = self._add_to_ai_queue('title')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün başlık üretim kuyruğuna eklendi.', count),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_bulk_ai_generate_description(self):
        count = self._add_to_ai_queue('description')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün açıklama üretim kuyruğuna eklendi.', count),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_bulk_ai_generate_both(self):
        count = self._add_to_ai_queue('both')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün başlık ve açıklama üretim kuyruğuna eklendi.', count),
                'sticky': False,
                'type': 'success',
            }
        }

    def _extract_ai_payload(self):
        """Ürün verilerini AI promptu için hazırla.
        
        ÖNEMLİ: Renk bilgisi GÖNDERME — Trendyol kurallarına göre varyantlı
        ürünlerde başlık ve açıklamada renk belirtilmemeli.
        """
        self.ensure_one()
        attributes = {}
        brand = ""
        
        # Renk niteliğini filtrele — Trendyol kuralı: başlıkta/açıklamada renk belirtme
        EXCLUDED_ATTRIBUTES = ['renk', 'color', 'colour']
        
        for line in self.attribute_line_ids:
            attr_name = line.attribute_id.name
            attr_name_lower = attr_name.lower().strip()
            
            # Marka bilgisini al
            if attr_name_lower in ['marka', 'brand']:
                brand = ", ".join(line.value_ids.mapped('name'))
                continue
            
            # Renk bilgisini atla
            if attr_name_lower in EXCLUDED_ATTRIBUTES:
                continue
            
            # Beden bilgisini atla (varyant bilgisi)
            if attr_name_lower in ['beden', 'size', 'numara']:
                continue
                
            values = ", ".join(line.value_ids.mapped('name'))
            attributes[attr_name] = values
                
        return {
            'raw_name': self.ai_original_name or self.name,
            'brand': brand,
            'category': self.categ_id.complete_name if self.categ_id else '',
            'attributes': attributes,
            'list_price': self.list_price,
            'default_code': self.default_code,
        }

# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

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

    def action_bulk_ai_generate_title(self):
        products = self.filtered(lambda p: p.image_1920)
        for product in products:
            self.env['ai.content.queue'].create({
                'product_tmpl_id': product.id,
                'mode': 'title'
            })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün için başlık üretim kuyruğa eklendi.', len(products)),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_bulk_ai_generate_description(self):
        products = self.filtered(lambda p: p.image_1920)
        for product in products:
            self.env['ai.content.queue'].create({
                'product_tmpl_id': product.id,
                'mode': 'description'
            })
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün için açıklama üretim kuyruğa eklendi.', len(products)),
                'sticky': False,
                'type': 'success',
            }
        }

    def action_bulk_ai_generate_both(self):
        products = self.filtered(lambda p: p.image_1920)
        for product in products:
            self.env['ai.content.queue'].create({
                'product_tmpl_id': product.id,
                'mode': 'both'
            })
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': _('%s ürün için başlık ve açıklama üretim kuyruğa eklendi.', len(products)),
                'sticky': False,
                'type': 'success',
            }
        }

    def _extract_ai_payload(self):
        self.ensure_one()
        attributes = {}
        brand = ""
        
        for line in self.attribute_line_ids:
            attr_name = line.attribute_id.name
            values = ", ".join(line.value_ids.mapped('name'))
            attributes[attr_name] = values
            
            if attr_name.lower() in ['marka', 'brand']:
                brand = values
                
        return {
            'raw_name': self.name,
            'brand': brand,
            'category': self.categ_id.complete_name if self.categ_id else '',
            'attributes': attributes,
            'list_price': self.list_price,
            'default_code': self.default_code,
        }

# -*- coding: utf-8 -*-
from odoo import models, fields

class AIContentLog(models.Model):
    _name = 'ai.content.log'
    _description = 'AI İçerik Üretim Geçmişi'
    _order = 'create_date desc'

    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade', index=True)
    mode = fields.Selection([
        ('title', 'Başlık'),
        ('description', 'Açıklama'),
        ('both', 'Başlık + Açıklama')
    ], string="Mod")
    generated_title = fields.Char("Üretilen Başlık")
    generated_description = fields.Html("Üretilen Açıklama")
    applied = fields.Boolean("Uygulandı", default=False)
    title_score = fields.Integer("Başlık Skoru")
    used_vision = fields.Boolean("Görsel Analiz")
    seo_keywords_used = fields.Char("Kullanılan SEO Kelimeleri")
    token_count = fields.Integer("Token Sayısı")
    cost_estimate = fields.Float("Tahmini Maliyet ($)", digits=(10, 6))
    prompt_used = fields.Text("Kullanılan Prompt")
    raw_response = fields.Text("Ham AI Yanıtı")

# -*- coding: utf-8 -*-
from odoo import models, fields

class AIContentLog(models.Model):
    _name = 'ai.content.log'
    _description = 'AI İçerik Üretim Geçmişi'
    _order = 'create_date desc'

    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade', index=True, string="Ürün")
    provider = fields.Selection([
        ('gemini', 'Google Gemini'),
        ('openai', 'OpenAI')
    ], string="AI Sağlayıcı")
    model_name = fields.Char("Model Adı")
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
    prompt_tokens = fields.Integer("Girdi Token (Prompt)")
    completion_tokens = fields.Integer("Çıktı Token (Completion)")
    token_count = fields.Integer("Toplam Token")
    cost_estimate = fields.Float("Maliyet ($)", digits=(10, 6))
    prompt_used = fields.Text("Kullanılan Prompt")
    raw_response = fields.Text("Ham AI Yanıtı")

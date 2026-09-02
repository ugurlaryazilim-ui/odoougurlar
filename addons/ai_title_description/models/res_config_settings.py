# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_td_gemini_api_key = fields.Char("Gemini API Key", config_parameter='ai_title_description.gemini_api_key')
    ai_td_default_platform = fields.Selection([
        ('trendyol', 'Trendyol'), 
        ('hepsiburada', 'Hepsiburada'), 
        ('genel', 'Genel E-Ticaret')
    ], default='trendyol', string="Varsayılan Platform", config_parameter='ai_title_description.default_platform')
    ai_td_use_vision = fields.Boolean("Görsel Analiz Aktif", default=True, config_parameter='ai_title_description.use_vision')
    ai_td_image_size = fields.Selection([
        ('image_512', '512px (Hızlı)'), 
        ('image_1024', '1024px (Önerilen)'), 
        ('image_1920', '1920px (Detaylı)')
    ], default='image_1024', string="Görsel Boyutu", config_parameter='ai_title_description.image_size')
    ai_td_default_tone = fields.Selection([
        ('professional', 'Profesyonel'), 
        ('casual', 'Samimi'), 
        ('seo_marketing', 'SEO Odaklı')
    ], default='seo_marketing', string="Varsayılan Ton", config_parameter='ai_title_description.default_tone')
    ai_td_use_google_suggest = fields.Boolean("Google Suggest Aktif", default=True, config_parameter='ai_title_description.use_google_suggest')
    ai_td_use_trendyol_suggest = fields.Boolean("Trendyol Suggest Aktif", default=True, config_parameter='ai_title_description.use_trendyol_suggest')
    ai_td_use_search_grounding = fields.Boolean("Gemini Search Grounding", default=True, config_parameter='ai_title_description.use_search_grounding')

# -*- coding: utf-8 -*-
from odoo import api, models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_td_provider = fields.Selection([
        ('gemini', 'Google Gemini'),
        ('openai', 'OpenAI')
    ], default='gemini', string="Başlık AI Sağlayıcı", config_parameter='ai_title_description.provider')

    ai_td_gemini_api_key = fields.Char("Başlık AI Gemini Key", config_parameter='ai_title_description.gemini_api_key')
    ai_td_gemini_model = fields.Selection([
        ('gemini-2.5-flash', 'Gemini 2.5 Flash (Hızlı & Ekonomik - Önerilen)'),
        ('gemini-2.5-pro', 'Gemini 2.5 Pro (Gelişmiş & Derin Analiz)'),
        ('gemini-2.0-flash', 'Gemini 2.0 Flash')
    ], default='gemini-2.5-flash', string="Gemini Modeli", config_parameter='ai_title_description.gemini_model')

    ai_td_openai_api_key = fields.Char("Başlık AI OpenAI Key", config_parameter='ai_title_description.openai_api_key')
    ai_td_openai_model = fields.Selection([
        ('gpt-4o-mini', 'GPT-4o Mini (Hızlı & Ekonomik)'),
        ('gpt-4o', 'GPT-4o (En Yüksek Kalite)')
    ], default='gpt-4o-mini', string="OpenAI Modeli", config_parameter='ai_title_description.openai_model')

    # Varsayılanı AÇIK kutular config_parameter ile tanımlanmaz: Odoo kutu kaldırılınca
    # parametreyi siler, kod da varsayılan 'True' okuyup özelliği kapatılamaz yapıyordu.
    # Açıkça 'True'/'False' olarak get_values/set_values ile saklanır.
    ai_td_use_vision = fields.Boolean("Görsel Analiz Aktif")
    ai_td_image_size = fields.Selection([
        ('image_512', '512px (Hızlı)'), 
        ('image_1024', '1024px (Önerilen)'), 
        ('image_1920', '1920px (Detaylı)')
    ], default='image_1024', string="Görsel Boyutu", config_parameter='ai_title_description.image_size')
    ai_td_use_google_suggest = fields.Boolean("Google Suggest Aktif")
    ai_td_use_trendyol_suggest = fields.Boolean("Trendyol Suggest Aktif")
    ai_td_use_search_grounding = fields.Boolean("Gemini Search Grounding")
    ai_td_create_tags = fields.Boolean("SEO Kelimelerinden Ürün Etiketi Oluştur")
    ai_td_monthly_budget = fields.Float("Aylık Bütçe Uyarısı ($)", config_parameter='ai_title_description.monthly_budget',
                                        help="Bu ayki tahmini maliyet bu tutarı geçince yöneticilere bir kez bildirim gider. "
                                             "Üretim durmaz. 0 = kapalı.")
    ai_td_month_spend = fields.Float("Bu Ayki Harcama ($)", compute='_compute_ai_td_month_spend')

    def _compute_ai_td_month_spend(self):
        spend = self.env['ai.content.log']._month_spend()
        for rec in self:
            rec.ai_td_month_spend = spend

    _AI_TD_DEFAULT_ON_TOGGLES = {
        'ai_td_use_vision': 'ai_title_description.use_vision',
        'ai_td_use_google_suggest': 'ai_title_description.use_google_suggest',
        'ai_td_use_trendyol_suggest': 'ai_title_description.use_trendyol_suggest',
        'ai_td_use_search_grounding': 'ai_title_description.use_search_grounding',
        'ai_td_create_tags': 'ai_title_description.create_tags',
    }

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        for field_name, key in self._AI_TD_DEFAULT_ON_TOGGLES.items():
            res[field_name] = icp.get_param(key, 'True') == 'True'
        return res

    def set_values(self):
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()
        for field_name, key in self._AI_TD_DEFAULT_ON_TOGGLES.items():
            icp.set_param(key, 'True' if self[field_name] else 'False')

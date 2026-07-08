# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    social_ai_provider = fields.Selection([
        ('openai', 'OpenAI (ChatGPT)'),
        ('gemini', 'Google Gemini'),
        ('ollama', 'Ollama (Local/Open Source)'),
    ], string="AI Provider", default='openai', config_parameter='social_media_ai.provider')

    social_openai_api_key = fields.Char(string="OpenAI API Key", config_parameter='social_media_ai.openai_key')
    social_gemini_api_key = fields.Char(string="Gemini API Key", config_parameter='social_media_ai.gemini_key')
    social_ollama_endpoint = fields.Char(string="Ollama Endpoint URL", default="http://localhost:11434/api/generate", config_parameter='social_media_ai.ollama_endpoint')
    social_ollama_model = fields.Char(string="Ollama Model Name", default="llama3", config_parameter='social_media_ai.ollama_model')

    social_system_prompt = fields.Char(
        string="System Prompt", 
        default="Sen profesyonel bir müşteri temsilcisisin. Sorulara kısa ve nazik cevaplar ver. Eğer soruyu cevaplayamıyorsan veya müşteri bir insanla görüşmek istiyorsa cevabının sonuna [DEVRET] yaz.",
        config_parameter='social_media_ai.system_prompt'
    )
    
    social_comment_auto_reply = fields.Char(
        string="Yorum Otomatik Yanıt (Herkese Açık)",
        default="Merhaba, konu ile ilgili detaylı bilgi DM (Mesaj) üzerinden iletilmiştir. Teşekkür ederiz.",
        config_parameter='social_media_ai.comment_auto_reply',
        help="Bir gönderiye yorum yapıldığında, AI herkese açık olarak bu metni yazar. Gerçek cevabı DM'den gönderir."
    )

    # Meta Integration Settings
    social_meta_app_id = fields.Char(string="Meta App ID", config_parameter='social_media_ai.meta_app_id')
    social_meta_app_secret = fields.Char(string="Meta App Secret", config_parameter='social_media_ai.meta_app_secret')

    social_post_cron_interval = fields.Integer(string="Gönderi Yayınlama Gecikmesi (Dakika)", default=3)

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        cron = self.env.ref('social_media_ai_manager.ir_cron_publish_social_posts', raise_if_not_found=False)
        if cron:
            res.update(social_post_cron_interval=cron.interval_number)
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        cron = self.env.ref('social_media_ai_manager.ir_cron_publish_social_posts', raise_if_not_found=False)
        if cron and self.social_post_cron_interval > 0:
            cron.sudo().write({'interval_number': self.social_post_cron_interval})

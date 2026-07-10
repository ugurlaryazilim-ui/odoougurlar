# -*- coding: utf-8 -*-
from odoo import models, fields, api

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

    # YouTube Integration Settings
    social_youtube_client_id = fields.Char(string="Google Client ID (YouTube)", config_parameter='social_media_ai.youtube_client_id')
    social_youtube_client_secret = fields.Char(string="Google Client Secret", config_parameter='social_media_ai.youtube_client_secret')

    # WhatsApp Redirection
    social_whatsapp_number = fields.Char(
        string="WhatsApp Yönlendirme Numarası", 
        config_parameter='social_media_ai.whatsapp_number',
        help="YouTube vb. kanallardan gelen müşterileri WhatsApp'a yönlendirirken kullanılacak numara (Örn: 905XXXXXXXXX)"
    )

    social_post_cron_interval = fields.Integer(string="Gönderi Yayınlama Gecikmesi (Dakika)", default=3)
    
    # Feature Toggles
    social_enable_comments = fields.Boolean(string="Yorumlara Cevap Ver", config_parameter='social_media_ai.enable_comments')
    social_enable_dms = fields.Boolean(string="DM'lere Cevap Ver", config_parameter='social_media_ai.enable_dms')
    social_enable_posting = fields.Boolean(string="Paylaşımları Yap", default=True, config_parameter='social_media_ai.enable_posting')
    
    social_handoff_user_ids = fields.Many2many(
        'res.users', 'res_config_social_handoff_rel', 'config_id', 'user_id',
        string="Devredilecek Personeller (Handoff Users)",
        help="Yapay zeka başa çıkamadığında veya manuel olarak devret dendiğinde atanacak personeller."
    )

    social_ecommerce_url = fields.Char(
        string="E-Ticaret Mağaza Linki (URL)",
        default="https://www.ugurlar.com",
        config_parameter='social_media_ai.ecommerce_url',
        help="Yapay zeka sipariş linki verirken bu alan adını kullanır. Örn: https://www.ugurlar.com/search?q=[ÜRÜNKODU]"
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        cron = self.env.ref('social_media_ai_manager.ir_cron_publish_social_posts', raise_if_not_found=False)
        if cron:
            res.update(social_post_cron_interval=cron.interval_number)
            
        handoff_users = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.handoff_user_ids')
        if handoff_users:
            import json
            try:
                user_ids = json.loads(handoff_users)
                res.update(social_handoff_user_ids=[(6, 0, user_ids)])
            except Exception:
                pass
                
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        cron = self.env.ref('social_media_ai_manager.ir_cron_publish_social_posts', raise_if_not_found=False)
        if cron and self.social_post_cron_interval > 0:
            cron.sudo().write({'interval_number': self.social_post_cron_interval})
            
        import json
        self.env['ir.config_parameter'].sudo().set_param(
            'social_media_ai.handoff_user_ids', 
            json.dumps(self.social_handoff_user_ids.ids)
        )

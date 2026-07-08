# -*- coding: utf-8 -*-
from odoo import models, fields, exceptions

class SocialMediaAccount(models.Model):
    _name = 'social.media.account'
    _description = 'Social Media Account'

    name = fields.Char(string="Account Name", required=True)
    platform = fields.Selection([
        ('whatsapp', 'WhatsApp (WAHA/Evolution)'),
        ('facebook', 'Facebook Page'),
        ('instagram', 'Instagram Account'),
        ('youtube', 'YouTube Channel'),
        ('tiktok', 'TikTok Account'),
    ], string="Platform", required=True)
    
    active = fields.Boolean(default=True)
    
    # API Credentials / Webhook tokens
    api_token = fields.Char(string="API Token / Access Token")
    webhook_secret = fields.Char(string="Webhook Secret (Verify Token)")
    phone_number = fields.Char(string="Phone Number (WhatsApp)")
    
    # Meta Specific IDs
    meta_page_id = fields.Char(string="Meta Page ID")
    meta_ig_id = fields.Char(string="Instagram Account ID")
    
    # Connection status
    state = fields.Selection([
        ('draft', 'Not Connected'),
        ('connected', 'Connected'),
        ('error', 'Error / Disconnected')
    ], string="Status", default='draft')
    
    def action_subscribe_webhooks(self):
        """ Manually subscribe the Page to the App's Webhooks and show result """
        self.ensure_one()
        if self.platform not in ['facebook', 'instagram'] or not self.api_token or not self.meta_page_id:
            raise exceptions.UserError("Bu işlem için Facebook/Instagram seçili olmalı, Meta Page ID ve API Token dolu olmalıdır.")
            
        import requests
        
        subscribe_url = f"https://graph.facebook.com/v19.0/{self.meta_page_id}/subscribed_apps"
        sub_data = {
            'subscribed_fields': 'messages,messaging_postbacks,feed',
            'access_token': self.api_token
        }
        
        try:
            resp = requests.post(subscribe_url, data=sub_data).json()
            if resp.get('success'):
                raise exceptions.UserError("BAŞARILI! Facebook sayfanız Odoo tetikleyicisine başarıyla bağlandı. Artık mesajlar Odoo'ya düşecek.")
            else:
                raise exceptions.UserError(f"HATA! Facebook tetikleyiciyi reddetti: {resp}")
        except Exception as e:
            if "BAŞARILI" in str(e) or "HATA" in str(e):
                raise e
            raise exceptions.UserError(f"Bağlantı hatası: {e}")

    def action_login_facebook(self):
        """ Redirect to Facebook Login """
        return {
            'type': 'ir.actions.act_url',
            'url': '/social_media_ai/facebook/login',
            'target': 'self',
        }

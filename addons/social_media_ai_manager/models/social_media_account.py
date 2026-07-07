# -*- coding: utf-8 -*-
from odoo import models, fields

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
    
    def action_test_connection(self):
        """ Test the API connection based on platform """
        self.ensure_one()
        # TODO: Implement connection tests for each platform
        self.state = 'connected'

    def action_login_facebook(self):
        """ Redirect to Facebook Login """
        return {
            'type': 'ir.actions.act_url',
            'url': '/social_media_ai/facebook/login',
            'target': 'self',
        }

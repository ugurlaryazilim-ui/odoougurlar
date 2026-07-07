# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SocialMediaAIRule(models.Model):
    _name = 'social.media.ai.rule'
    _description = 'Social Media AI Automation Rule'

    name = fields.Char(string="Rule Name", required=True)
    active = fields.Boolean(string="Active", default=True)
    trigger_type = fields.Selection([
        ('all', 'All Incoming Messages'),
        ('keyword', 'Contains Specific Keywords'),
    ], string="Trigger Type", default='all', required=True)
    
    trigger_keywords = fields.Char(string="Keywords (comma separated)", help="Keywords to trigger this rule.")
    
    action_type = fields.Selection([
        ('reply', 'Generate AI Reply'),
        ('handoff', 'Hand-off to Human (Pause AI)'),
    ], string="Action", default='reply', required=True)
    
    context_type = fields.Selection([
        ('general', 'General Chat'),
        ('product', 'Product & Pricing Search'),
        ('appointment', 'Appointment Booking (Calendar)'),
    ], string="AI Context / Skill", default='general', required=True)

    additional_prompt = fields.Text(string="Additional Prompt Instructions", help="Specific instructions for this rule.")

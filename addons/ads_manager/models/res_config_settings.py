# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ads_default_ai_provider = fields.Selection([
        ('gemini', 'Gemini'),
        ('openai', 'OpenAI'),
        ('claude', 'Claude'),
        ('ollama', 'Ollama')
    ], default='gemini', config_parameter='ads_manager.default_ai_provider')
    ads_gemini_api_key = fields.Char(config_parameter='ads_manager.gemini_api_key')
    ads_openai_api_key = fields.Char(config_parameter='ads_manager.openai_api_key')
    ads_claude_api_key = fields.Char(config_parameter='ads_manager.claude_api_key')
    ads_default_platform = fields.Selection([
        ('meta', 'Meta Ads'),
        ('google', 'Google Ads'),
        ('all', 'All Platforms')
    ], default='all', config_parameter='ads_manager.default_platform')
    ads_auto_sync = fields.Boolean(default=True, config_parameter='ads_manager.auto_sync')
    ads_sync_hour = fields.Integer(default=2, help='Hour of day for metric sync (0-23)', config_parameter='ads_manager.sync_hour')
    ads_rule_evaluation_interval = fields.Integer(default=6, help='Hours between rule evaluations', config_parameter='ads_manager.rule_eval_interval')
    ads_archive_after_months = fields.Integer(default=24, help='Archive daily metrics older than N months', config_parameter='ads_manager.archive_after_months')

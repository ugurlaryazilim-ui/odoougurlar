# -*- coding: utf-8 -*-
from odoo import models, fields, api


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
    ads_ai_analysis_frequency = fields.Selection([
        ('1', 'Günlük'),
        ('3', 'Her 3 Günde Bir'),
        ('7', 'Haftalık'),
    ], default='7', config_parameter='ads_manager.ai_analysis_frequency',
       help='AI analiz cron sıklığı (gün)')
    ads_default_platform = fields.Selection([
        ('meta', 'Meta Ads'),
        ('google', 'Google Ads'),
        ('all', 'All Platforms')
    ], default='all', config_parameter='ads_manager.default_platform')
    ads_auto_sync = fields.Boolean(default=True, config_parameter='ads_manager.auto_sync')
    ads_sync_hour = fields.Integer(default=2, help='Hour of day for metric sync (0-23)', config_parameter='ads_manager.sync_hour')
    ads_rule_evaluation_interval = fields.Integer(default=6, help='Hours between rule evaluations', config_parameter='ads_manager.rule_eval_interval')
    ads_archive_after_months = fields.Integer(default=24, help='Archive daily metrics older than N months', config_parameter='ads_manager.archive_after_months')

    def set_values(self):
        res = super().set_values()
        # Update AI analysis cron interval when frequency changes
        freq = self.ads_ai_analysis_frequency
        if freq:
            ai_cron = self.env.ref('ads_manager.ir_cron_ads_ai_analysis', raise_if_not_found=False)
            if ai_cron:
                ai_cron.sudo().write({
                    'interval_number': int(freq),
                    'interval_type': 'days',
                })
        return res

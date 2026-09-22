# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AdsAiProvider(models.Model):
    _name = 'ads.ai.provider'
    _description = 'AI Provider'

    name = fields.Char(required=True)
    provider_type = fields.Selection([
        ('gemini', 'Gemini'),
        ('openai', 'OpenAI'),
        ('claude', 'Claude'),
        ('ollama', 'Ollama')
    ], required=True, default='gemini')
    api_key = fields.Char(groups='base.group_system', copy=False)
    endpoint_url = fields.Char()
    model_name = fields.Char(default='gemini-2.0-flash')
    active = fields.Boolean(default=True)
    max_tokens = fields.Integer(default=4096)
    temperature = fields.Float(default=0.3, digits=(3, 2))

    def generate_response(self, prompt, context=None):
        self.ensure_one()
        if self.provider_type == 'gemini':
            return self._call_gemini(prompt, context)
        else:
            raise NotImplementedError(_("Provider %s is not implemented yet.", self.provider_type))

    @api.private
    def _call_gemini(self, prompt, context):
        api_key = self.api_key or self.env['ir.config_parameter'].sudo().get_param('ads_manager.gemini_api_key')
        if not api_key:
            raise UserError(_("Gemini API key is not configured."))
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            if 'candidates' in data and data['candidates']:
                return data['candidates'][0]['content']['parts'][0]['text']
            return ""
        except requests.exceptions.RequestException as e:
            _logger.error("Error calling Gemini API: %s", str(e))
            raise UserError(_("Failed to communicate with Gemini API: %s") % str(e))

    def _prepare_ads_analysis_prompt(self, campaign_data):
        self.ensure_one()
        prompt = f"Analyze the following campaign data and provide insights:\n\n{json.dumps(campaign_data, indent=2)}\n\n"
        prompt += "Please evaluate performance metrics and suggest optimizations."
        return prompt

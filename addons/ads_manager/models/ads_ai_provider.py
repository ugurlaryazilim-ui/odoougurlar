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
    
    usage_count = fields.Integer('API Calls', readonly=True, default=0)
    total_tokens_used = fields.Integer('Total Tokens', readonly=True, default=0)
    last_used = fields.Datetime('Last Used', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.model
    def _cron_ai_analysis(self):
        """Cron: Run weekly AI deep analysis on all campaigns."""
        from ..services.ai_engine import AdsAIEngine
        try:
            engine = AdsAIEngine(self.env)
            result = engine.run_deep_analysis()
            _logger.info(
                'AI deep analysis complete: %d analyzed, %d high risk, %d recommendations created',
                result.get('analyzed', 0),
                result.get('high_risk', 0),
                result.get('recommendations_created', 0),
            )
        except Exception as e:
            _logger.error('AI deep analysis cron failed: %s', e)

    def action_test_provider(self):
        """Test AI provider connection."""
        self.ensure_one()
        try:
            response = self.generate_response(
                'Say "Hello, I am working correctly!" in one sentence.',
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AI Provider Test'),
                    'message': _('Success! Response: %s') % response[:100],
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_('Provider test failed: %s') % str(e))

    def generate_response(self, prompt, context=None):
        self.ensure_one()
        response = None
        if self.provider_type == 'gemini':
            response = self._call_gemini(prompt, context)
        elif self.provider_type == 'openai':
            response = self._call_openai(prompt, context)
        elif self.provider_type == 'claude':
            response = self._call_claude(prompt, context)
        elif self.provider_type == 'ollama':
            response = self._call_ollama(prompt, context)
        else:
            raise UserError(_('Provider type %s is not supported.') % self.provider_type)
            
        if response:
            self.write({
                'usage_count': self.usage_count + 1,
                'last_used': fields.Datetime.now()
            })
        return response

    @api.private
    def _call_gemini(self, prompt, context):
        api_key = self.api_key or self.env['ir.config_parameter'].sudo().get_param('ads_manager.gemini_api_key')
        if not api_key:
            raise UserError(_("Gemini API key is not configured."))
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "system_instruction": {
                "parts": [{"text": "Sen bir dijital reklam analiz uzmanısın. Türkçe yanıt ver. Somut, veri odaklı öneriler sun."}]
            },
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

    @api.private
    def _call_openai(self, prompt, context):
        """Call OpenAI-compatible API (works with OpenAI, Azure OpenAI, local APIs)."""
        api_key = self.api_key
        if not api_key:
            raise UserError(_('OpenAI API key is not configured.'))
        
        endpoint = self.endpoint_url or 'https://api.openai.com/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        payload = {
            'model': self.model_name or 'gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': 'Sen bir dijital reklam analiz uzmanısın. Türkçe yanıt ver.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
        }
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            _logger.error('OpenAI API error: %s', e)
            raise UserError(_('Failed to communicate with OpenAI API: %s') % str(e))

    @api.private
    def _call_claude(self, prompt, context):
        """Call Anthropic Claude Messages API natively."""
        api_key = self.api_key or self.env['ir.config_parameter'].sudo().get_param('ads_manager.claude_api_key')
        if not api_key:
            raise UserError(_('Claude API key is not configured.'))
            
        endpoint = self.endpoint_url or 'https://api.anthropic.com/v1/messages'
        headers = {
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }
        payload = {
            'model': self.model_name or 'claude-3-5-sonnet-20241022',
            'max_tokens': self.max_tokens or 1024,
            'temperature': self.temperature,
            'system': 'Sen bir dijital reklam analiz uzmanısın. Türkçe yanıt ver. Somut, veri odaklı öneriler sun.',
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            if 'content' in data and data['content']:
                return data['content'][0].get('text', '')
            return ''
        except requests.exceptions.RequestException as e:
            _logger.error('Claude API error: %s', e)
            raise UserError(_('Failed to communicate with Claude API: %s') % str(e))

    @api.private
    def _call_ollama(self, prompt, context):
        """Call local Ollama API."""
        endpoint = self.endpoint_url or 'http://localhost:11434/api/generate'
        payload = {
            'model': self.model_name or 'llama3',
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': self.temperature,
                'num_predict': self.max_tokens,
            }
        }
        try:
            response = requests.post(endpoint, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data.get('response', '')
        except requests.exceptions.RequestException as e:
            _logger.error('Ollama API error: %s', e)
            raise UserError(_('Failed to communicate with Ollama: %s') % str(e))

    def _prepare_ads_analysis_prompt(self, campaign_data):
        self.ensure_one()
        prompt = f"Analyze the following campaign data and provide insights:\n\n{json.dumps(campaign_data, indent=2)}\n\n"
        prompt += "Please evaluate performance metrics and suggest optimizations."
        return prompt

# -*- coding: utf-8 -*-
import json
import requests
import logging
from odoo import models, api

_logger = logging.getLogger(__name__)

class SocialAIProvider(models.AbstractModel):
    _name = 'social.media.ai.provider'
    _description = 'AI Provider Abstraction Layer'

    @api.model
    def generate_response(self, message_text, context_prompt=""):
        """ Main entry point to generate AI response based on selected provider """
        provider = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.provider', 'openai')
        system_prompt = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.system_prompt', '')
        
        full_system_prompt = f"{system_prompt}\n{context_prompt}"

        if provider == 'openai':
            return self._call_openai(message_text, full_system_prompt)
        elif provider == 'gemini':
            return self._call_gemini(message_text, full_system_prompt)
        elif provider == 'ollama':
            return self._call_ollama(message_text, full_system_prompt)
        
        return "I am unable to process your request at the moment."

    def _call_openai(self, message_text, system_prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.openai_key')
        if not api_key:
            return "OpenAI API Key is not configured."
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        data = {
            'model': 'gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': message_text}
            ]
        }
        try:
            response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            return res_data['choices'][0]['message']['content']
        except Exception as e:
            _logger.error(f"OpenAI API Error: {e}")
            return "[ERROR] An error occurred with the OpenAI service."

    def _call_gemini(self, message_text, system_prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.gemini_key')
        if not api_key:
            return "Gemini API Key is not configured."
        
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': api_key.strip()
        }
        data = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [{
                "parts": [{"text": message_text}]
            }]
        }
        try:
            response = requests.post(url, headers=headers, json=data, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            return res_data['candidates'][0]['content']['parts'][0]['text']
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 500
            _logger.error(f"Gemini API HTTP Error {status_code}: {e}")
            return f"[ERROR] [{status_code}] Gemini API Error: {e}"
        except Exception as e:
            _logger.error(f"Gemini API Error: {e}")
            return f"[ERROR] {e}"

    def _call_ollama(self, message_text, system_prompt):
        endpoint = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.ollama_endpoint', 'http://localhost:11434/api/generate')
        model = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.ollama_model', 'llama3')
        
        prompt = f"System: {system_prompt}\nUser: {message_text}\nAssistant:"
        
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        try:
            response = requests.post(endpoint, json=data, timeout=30)
            response.raise_for_status()
            res_data = response.json()
            return res_data.get('response', '')
        except Exception as e:
            _logger.error(f"Ollama API Error: {e}")
            return "[ERROR] An error occurred with the local Ollama service."

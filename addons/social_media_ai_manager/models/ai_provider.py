# -*- coding: utf-8 -*-
import json
import time
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
        
        # [ERROR] öneki: kuyruk bunu müşteriye yanıt diye göndermez
        return "[ERROR] Unknown AI provider: %s" % provider

    def _call_openai(self, message_text, system_prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.openai_key')
        if not api_key:
            return "[ERROR] OpenAI API Key is not configured."
        
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
        started = time.monotonic()
        try:
            response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data, timeout=30)
            usage = {}
            try:
                usage = (response.json() or {}).get('usage') or {}
            except Exception:
                pass
            self.env['social.media.ai.usage']._record(
                'openai', 'gpt-4o-mini', int(usage.get('prompt_tokens') or 0),
                int(usage.get('completion_tokens') or 0), time.monotonic() - started,
                'ok' if response.ok else 'error')
            response.raise_for_status()
            res_data = response.json()
            return res_data['choices'][0]['message']['content']
        except requests.exceptions.Timeout as e:
            self.env['social.media.ai.usage']._record('openai', 'gpt-4o-mini', duration=time.monotonic() - started,
                                                      status='timeout')
            _logger.error(f"OpenAI API Timeout: {e}")
            return "[ERROR] OpenAI timeout."
        except Exception as e:
            _logger.error(f"OpenAI API Error: {e}")
            return "[ERROR] An error occurred with the OpenAI service."

    def _call_gemini(self, message_text, system_prompt):
        api_key = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.gemini_key')
        if not api_key:
            return "[ERROR] Gemini API Key is not configured."
        
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
            }],
            # Kısa müşteri yanıtı için "thinking" gereksiz: çıkış fiyatından faturalanıyor ve
            # 15 sn'lik sınırı aşıp zaman aşımına (ve her dakika yeniden denemeye) yol açıyordu
            "generationConfig": {
                "thinkingConfig": {"thinkingBudget": 0},
                "maxOutputTokens": 2048,
            },
        }
        started = time.monotonic()
        try:
            try:
                response = requests.post(url, headers=headers, json=data, timeout=30)
            except requests.exceptions.Timeout:
                self.env['social.media.ai.usage']._record('gemini', 'gemini-2.5-flash',
                                                          duration=time.monotonic() - started, status='timeout')
                raise
            usage = {}
            try:
                usage = (response.json() or {}).get('usageMetadata') or {}
            except Exception:
                pass
            self.env['social.media.ai.usage']._record(
                'gemini', 'gemini-2.5-flash', int(usage.get('promptTokenCount') or 0),
                int(usage.get('candidatesTokenCount') or 0) + int(usage.get('thoughtsTokenCount') or 0),
                time.monotonic() - started, 'ok' if response.ok else 'error')
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

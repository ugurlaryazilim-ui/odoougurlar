# -*- coding: utf-8 -*-
from odoo import models, fields

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
        default="You are a helpful customer support assistant. Answer user queries concisely.",
        config_parameter='social_media_ai.system_prompt'
    )

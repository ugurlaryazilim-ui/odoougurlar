# -*- coding: utf-8 -*-
from . import gemini_provider
from . import openai_provider
from . import prompt_engine
from . import title_validator
from . import keyword_discovery
from . import vision_analyzer

def get_ai_provider(provider, gemini_key, openai_key, model_name=None):
    """Provider tipine göre uygun AI servis örneğini döndürür."""
    if provider == 'openai':
        return openai_provider.OpenAIContentProvider(openai_key, model_name=model_name or 'gpt-4o-mini')
    else:
        return gemini_provider.GeminiContentProvider(gemini_key, model_name=model_name or 'gemini-2.5-flash')

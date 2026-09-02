# -*- coding: utf-8 -*-
"""AI Model Cost Calculator.

Google Gemini ve OpenAI modelleri için token bazlı kesin maliyet hesaplayıcı.
Fiyatlandırma: 1,000,000 token üzerinden standart tarifeler.
"""

def calculate_ai_cost(provider, model_name, prompt_tokens=0, completion_tokens=0):
    """Girdi ve çıktı token sayılarına ve seçilen modele göre USD cinsinden kesin maliyet hesaplar."""
    PRICING = {
        # Gemini Models (Input / Output per 1,000,000 tokens)
        'gemini-2.5-flash': (0.075 / 1_000_000, 0.30 / 1_000_000),
        'gemini-2.5-pro': (1.25 / 1_000_000, 5.00 / 1_000_000),
        'gemini-2.0-flash': (0.10 / 1_000_000, 0.40 / 1_000_000),
        
        # OpenAI Models (Input / Output per 1,000,000 tokens)
        'gpt-4o-mini': (0.15 / 1_000_000, 0.60 / 1_000_000),
        'gpt-4o': (2.50 / 1_000_000, 10.00 / 1_000_000),
    }

    rates = PRICING.get(model_name)
    if not rates:
        if provider == 'openai':
            rates = (0.15 / 1_000_000, 0.60 / 1_000_000)
        else:
            rates = (0.075 / 1_000_000, 0.30 / 1_000_000)

    input_rate, output_rate = rates
    cost = (prompt_tokens * input_rate) + (completion_tokens * output_rate)
    return round(cost, 6)

# -*- coding: utf-8 -*-
"""Gemini 2.5 Flash ile yapılandırılmış ürün içeriği üretimi."""
import json
import logging
import requests

_logger = logging.getLogger(__name__)


class GeminiContentProvider:
    """Gemini 2.5 Flash API ile structured JSON output ürün içeriği üretir.
    
    Özellikler:
    - Structured JSON output (responseSchema)
    - Google Search Grounding (opsiyonel)
    - Multimodal Vision (görsel analiz)
    - ~0.0001$/ürün maliyet
    """

    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    RESPONSE_SCHEMA = {
        "type": "OBJECT",
        "properties": {
            "trendyol_title": {"type": "STRING", "description": "Trendyol kurallarına uygun max 100 karakter başlık"},
            "ecommerce_title": {"type": "STRING", "description": "SEO odaklı e-ticaret başlığı"},
            "short_summary": {"type": "STRING", "description": "1-2 cümle özet açıklama"},
            "key_features": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "3-5 madde fayda odaklı"},
            "html_description": {"type": "STRING", "description": "Semantik HTML (h3, p, ul, li, strong)"},
            "meta_title": {"type": "STRING", "description": "Max 60 karakter SEO meta başlık"},
            "meta_description": {"type": "STRING", "description": "Max 155 karakter SEO meta açıklama"},
            "seo_keywords": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "5-8 anahtar kelime"}
        },
        "required": ["trendyol_title", "ecommerce_title", "short_summary", "key_features",
                     "html_description", "meta_title", "meta_description", "seo_keywords"]
    }

    def __init__(self, api_key):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("Gemini API key yapılandırılmamış.")

    def generate(self, system_prompt, user_prompt, image_base64=None, use_search_grounding=True):
        """Gemini 2.5 Flash API çağrısı — structured JSON çıktı ile.
        
        Args:
            system_prompt: Sistem talimatı
            user_prompt: Kullanıcı promptu (ürün verileri)
            image_base64: Opsiyonel ürün görseli (base64)
            use_search_grounding: Google Search Grounding aktif mi
            
        Returns:
            dict: Structured JSON çıktı (trendyol_title, ecommerce_title, etc.)
        """
        url = f"{self.API_URL}?key={self.api_key}"

        # Build contents based on whether image is provided
        parts = []
        if image_base64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_base64
                }
            })
        parts.append({"text": user_prompt})

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": self.RESPONSE_SCHEMA,
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            }
        }

        if use_search_grounding:
            payload["tools"] = [{"google_search": {}}]

        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            # Extract text from response
            candidates = result.get('candidates', [])
            if not candidates:
                raise ValueError("Gemini API boş yanıt döndürdü.")

            text = candidates[0]['content']['parts'][0]['text']
            parsed = json.loads(text)

            # Extract token usage for cost tracking
            usage = result.get('usageMetadata', {})
            parsed['_token_count'] = usage.get('totalTokenCount', 0)
            parsed['_prompt_tokens'] = usage.get('promptTokenCount', 0)
            parsed['_completion_tokens'] = usage.get('candidatesTokenCount', 0)

            return parsed

        except requests.exceptions.Timeout:
            _logger.error("Gemini API timeout (60s)")
            raise ValueError("Gemini API zaman aşımına uğradı. Lütfen tekrar deneyin.")
        except requests.exceptions.HTTPError as e:
            _logger.error("Gemini API HTTP error: %s - %s", e.response.status_code, e.response.text[:500])
            raise ValueError(f"Gemini API hatası: {e.response.status_code}")
        except json.JSONDecodeError:
            _logger.error("Gemini API yanıtı JSON olarak ayrıştırılamadı: %s", text[:500])
            raise ValueError("Gemini API geçersiz JSON yanıtı döndürdü.")
        except Exception as e:
            _logger.error("Gemini API beklenmeyen hata: %s", str(e))
            raise

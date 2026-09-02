# -*- coding: utf-8 -*-
"""Gemini 2.5 Flash ile yapılandırılmış ürün içeriği üretimi."""
import json
import logging
import time
import requests

_logger = logging.getLogger(__name__)


class GeminiContentProvider:
    """Gemini 2.5 Flash API ile structured JSON output ürün içeriği üretir.
    
    Özellikler:
    - Structured JSON output (responseSchema)
    - Google Search Grounding (opsiyonel)
    - Multimodal Vision (görsel analiz)
    - ~0.0001$/ürün maliyet
    - 429 Rate Limit retry (exponential backoff)
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

    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 30]  # Exponential backoff seconds

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
        mime_type = "image/jpeg"
        if image_base64:
            # Detect mime type from base64 header (PNG vs JPEG)
            try:
                import base64 as b64
                raw = b64.b64decode(image_base64[:32])
                if raw[:8] == b'\x89PNG\r\n\x1a\n':
                    mime_type = "image/png"
                elif raw[:2] == b'\xff\xd8':
                    mime_type = "image/jpeg"
                elif raw[:4] == b'RIFF':
                    mime_type = "image/webp"
            except Exception:
                pass  # Default to jpeg

            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
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

        # Note: google_search tool can conflict with responseSchema in some cases
        # Only enable if no image is being sent (reduces complexity)
        if use_search_grounding and not image_base64:
            payload["tools"] = [{"google_search": {}}]

        _logger.info("Gemini API çağrısı: image=%s, grounding=%s, mime=%s",
                    bool(image_base64), use_search_grounding and not image_base64,
                    mime_type if image_base64 else 'N/A')

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = requests.post(url, json=payload, timeout=60)

                # Handle 429 Rate Limit with retry
                if response.status_code == 429:
                    if attempt < self.MAX_RETRIES:
                        delay = self.RETRY_DELAYS[attempt]
                        _logger.warning(
                            "Gemini API 429 Rate Limit (deneme %d/%d). %d saniye bekleniyor...",
                            attempt + 1, self.MAX_RETRIES, delay
                        )
                        time.sleep(delay)
                        continue
                    else:
                        raise ValueError(
                            "Gemini API istek limiti aşıldı (429). "
                            "Lütfen birkaç dakika bekleyip tekrar deneyin. "
                            "Ücretsiz API anahtarı kullanıyorsanız dakikada 15 istek sınırı vardır."
                        )

                response.raise_for_status()
                result = response.json()

                # Extract text from response
                candidates = result.get('candidates', [])
                if not candidates:
                    _logger.error("Gemini API boş yanıt: %s", json.dumps(result)[:500])
                    raise ValueError("Gemini API boş yanıt döndürdü.")

                text = candidates[0]['content']['parts'][0]['text']
                parsed = json.loads(text)

                # Extract token usage for cost tracking
                usage = result.get('usageMetadata', {})
                parsed['_token_count'] = usage.get('totalTokenCount', 0)
                parsed['_prompt_tokens'] = usage.get('promptTokenCount', 0)
                parsed['_completion_tokens'] = usage.get('candidatesTokenCount', 0)

                _logger.info("Gemini API başarılı: %d token kullanıldı (deneme %d)",
                           parsed.get('_token_count', 0), attempt + 1)
                return parsed

            except requests.exceptions.Timeout:
                _logger.error("Gemini API timeout (60s) - deneme %d", attempt + 1)
                last_error = "Gemini API zaman aşımına uğradı. Lütfen tekrar deneyin."
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                raise ValueError(last_error)
            except requests.exceptions.HTTPError as e:
                error_body = ''
                status_code = 0
                if e.response is not None:
                    status_code = e.response.status_code
                    try:
                        error_body = e.response.text[:500]
                    except Exception:
                        error_body = 'Yanıt okunamadı'
                _logger.error("Gemini API HTTP error: %s - %s", status_code, error_body)
                raise ValueError(f"Gemini API hatası: {status_code}")
            except json.JSONDecodeError:
                _logger.error("Gemini API yanıtı JSON olarak ayrıştırılamadı: %s", text[:500])
                raise ValueError("Gemini API geçersiz JSON yanıtı döndürdü.")
            except ValueError:
                raise  # Re-raise ValueError (our own errors)
            except Exception as e:
                _logger.error("Gemini API beklenmeyen hata: %s", str(e))
                raise

        raise ValueError(last_error or "Gemini API bilinmeyen hata")

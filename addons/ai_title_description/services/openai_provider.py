# -*- coding: utf-8 -*-
"""OpenAI GPT-4o / GPT-4o-mini ile ürün içeriği üretimi."""
import json
import logging
import time
import requests

_logger = logging.getLogger(__name__)


class OpenAIContentProvider:
    """OpenAI API (GPT-4o, GPT-4o-mini) ile ürün içeriği üretir.
    
    Özellikler:
    - Structured JSON output (response_format)
    - Multimodal Vision (görsel analiz)
    - 429 Rate Limit retry (exponential backoff)
    """

    API_URL = "https://api.openai.com/v1/chat/completions"

    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 30]

    def __init__(self, api_key, model_name='gpt-4o-mini'):
        self.api_key = api_key
        self.model_name = model_name or 'gpt-4o-mini'
        if not self.api_key:
            raise ValueError("OpenAI API key yapılandırılmamış. Lütfen Ayarlar > AI Başlık & Açıklama bölümünden OpenAI API anahtarını girin.")

    def generate(self, system_prompt, user_prompt, image_base64=None, use_search_grounding=False):
        """OpenAI Chat Completions API çağrısı — JSON format ile.
        
        Args:
            system_prompt: Sistem talimatı
            user_prompt: Kullanıcı promptu (ürün verileri)
            image_base64: Opsiyonel ürün görseli (base64)
            use_search_grounding: (OpenAI'da desteklenmez, yoksayılır)
            
        Returns:
            dict: Structured JSON çıktı
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        system_instruction = system_prompt + "\n\nÇIKTI FORMATI: Yanıtı YALNIZCA aşağıdaki JSON formatında ver, başka metin ekleme:\n" + json.dumps({
            "trendyol_title": "Trendyol kurallarına uygun max 100 karakter başlık",
            "ecommerce_title": "SEO odaklı e-ticaret başlığı",
            "short_summary": "1-2 cümle özet açıklama",
            "key_features": ["fayda 1", "fayda 2", "fayda 3"],
            "html_description": "Semantik HTML (h3, p, ul, li, strong)",
            "meta_title": "Max 60 karakter SEO meta başlık",
            "meta_description": "Max 155 karakter SEO meta açıklama",
            "seo_keywords": ["kelime 1", "kelime 2", "kelime 3"]
        }, ensure_ascii=False)

        # Vision handling for OpenAI
        if image_base64:
            # Detect mime type from base64
            mime_type = "image/jpeg"
            if image_base64.startswith("iVBORw0KGgo"):
                mime_type = "image/png"
            elif image_base64.startswith("UklGR"):
                mime_type = "image/webp"

            user_content = [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}",
                        "detail": "high"
                    }
                }
            ]
        else:
            user_content = user_prompt

        payload = {
            "model": self.model_name,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ]
        }

        _logger.info("OpenAI API çağrısı: model=%s, image=%s", self.model_name, bool(image_base64))

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = requests.post(self.API_URL, headers=headers, json=payload, timeout=90)

                # Handle 429 Rate Limit
                if response.status_code == 429:
                    if attempt < self.MAX_RETRIES:
                        delay = self.RETRY_DELAYS[attempt]
                        _logger.warning("OpenAI API 429 Rate Limit (deneme %d/%d). %d saniye bekleniyor...", attempt + 1, self.MAX_RETRIES, delay)
                        time.sleep(delay)
                        continue
                    else:
                        raise ValueError("OpenAI API istek limiti aşıldı (429). Lütfen bakiye ve kota durumunuzu kontrol edin.")

                response.raise_for_status()
                result = response.json()

                choices = result.get('choices', [])
                if not choices:
                    raise ValueError("OpenAI API boş yanıt döndürdü.")

                text = choices[0]['message']['content']
                parsed = self._parse_json_response(text)

                # Token usage tracking
                usage = result.get('usage', {})
                parsed['_token_count'] = usage.get('total_tokens', 0)
                parsed['_prompt_tokens'] = usage.get('prompt_tokens', 0)
                parsed['_completion_tokens'] = usage.get('completion_tokens', 0)
                parsed['_provider'] = 'openai'
                parsed['_model'] = self.model_name

                _logger.info("OpenAI API başarılı: %s token kullanıldı (model: %s)", parsed['_token_count'], self.model_name)
                return parsed

            except requests.exceptions.Timeout:
                _logger.error("OpenAI API timeout (90s)")
                last_error = ValueError("OpenAI API zaman aşımına uğradı. Lütfen tekrar deneyin.")
            except requests.exceptions.HTTPError as e:
                err_text = response.text[:500] if 'response' in locals() else str(e)
                _logger.error("OpenAI API HTTP hatası: %s", err_text)
                last_error = ValueError(f"OpenAI API hatası: {response.status_code} - {err_text}")
            except Exception as e:
                _logger.error("OpenAI API beklenmeyen hata: %s", e)
                last_error = e

        raise last_error

    @staticmethod
    def _parse_json_response(text):
        """OpenAI yanıtından JSON çıkar."""
        if not text:
            raise json.JSONDecodeError("Boş yanıt", text or "", 0)

        # 1. Direkt parse dene
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2. Markdown fence temizle
        import re
        fence_pattern = re.compile(r'```(?:json)?\s*\n?(.*?)\n?\s*```', re.DOTALL)
        match = fence_pattern.search(text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3. İlk { ile son } arası
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(text[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("OpenAI yanıtı geçerli JSON içermiyor", text[:200], 0)

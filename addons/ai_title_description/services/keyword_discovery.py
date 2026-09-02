# -*- coding: utf-8 -*-
"""Keyword discovery tool using Google Suggest and Trendyol Autocomplete."""
import json
import logging
import requests
import time

_logger = logging.getLogger(__name__)

class KeywordDiscovery:
    TURKISH_CHARS = list("abcçdefgğhıijklmnoöprsştuüvyz")
    INTENT_MODIFIERS = [
        'fiyatları', 'modelleri', 'kombinleri', 'en iyi', 
        'tavsiye', 'trendyol', 'kadın', 'erkek', 'çeşitleri', 'yorumları'
    ]

    def discover_keywords(self, seed_keyword, use_google=True, use_trendyol=True, max_keywords=10):
        keywords = set()

        if use_google:
            google_kws = self._google_suggest_expand(seed_keyword)
            keywords.update(google_kws)

        if use_trendyol:
            trendyol_kws = self._trendyol_autocomplete(seed_keyword)
            keywords.update(trendyol_kws)

        # Ensure seed keyword is present
        keywords.add(seed_keyword.lower())
        
        # Simple scoring based on length (prefer reasonable length)
        valid_keywords = [kw for kw in keywords if len(kw.split()) >= 2 and len(kw) <= 50]
        valid_keywords.sort(key=lambda x: len(x))
        
        return list(valid_keywords)[:max_keywords]

    def _google_suggest_expand(self, seed):
        results = set()
        
        # Base query
        base_res = self._fetch_google_suggest(seed)
        results.update(base_res)
        
        # First 15 chars + 5 intent modifiers
        queries = []
        for char in self.TURKISH_CHARS[:15]:
            queries.append(f"{seed} {char}")
            
        for modifier in self.INTENT_MODIFIERS[:5]:
            queries.append(f"{seed} {modifier}")
            
        for q in queries:
            time.sleep(0.05)
            res = self._fetch_google_suggest(q)
            results.update(res)
            
        return list(results)

    def _fetch_google_suggest(self, query):
        url = "http://suggestqueries.google.com/complete/search"
        params = {
            "client": "firefox",
            "hl": "tr",
            "gl": "tr",
            "q": query
        }
        try:
            response = requests.get(url, params=params, timeout=3)
            response.raise_for_status()
            data = response.json()
            if len(data) > 1 and isinstance(data[1], list):
                return data[1]
        except Exception as e:
            _logger.warning("Google Suggest error for query '%s': %s", query, str(e))
        return []

    def _trendyol_autocomplete(self, query):
        url = "https://public.trendyol.com/discovery-web-searchgw-service/v2/api/autocomplete"
        params = {"text": query}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.trendyol.com",
            "Referer": "https://www.trendyol.com/"
        }
        try:
            response = requests.get(url, params=params, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            suggestions = data.get("result", {}).get("suggestions", [])
            return [s.get("text") for s in suggestions if s.get("text")]
        except Exception as e:
            _logger.warning("Trendyol Autocomplete error for query '%s': %s", query, str(e))
        return []

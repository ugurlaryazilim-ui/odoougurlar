# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AIKeywordCache(models.Model):
    """SEO anahtar kelime keşfi önbelleği.

    Tohum (kategori) başına sonuç tüm işçilerce paylaşılır: aynı kategorideki her ürün
    için Google/Trendyol'a ~21 istek atılmaz (yavaşlık + engellenme riski).
    """
    _name = 'ai.keyword.cache'
    _description = 'AI Anahtar Kelime Önbelleği'

    CACHE_DAYS = 7

    key = fields.Char(required=True, index=True)
    keywords = fields.Text(default='[]')

    _key_uniq = models.Constraint('UNIQUE(key)', 'Anahtar kelime önbellek anahtarı tekil olmalıdır.')

    @api.model
    def _get_keywords(self, seed, use_google=True, use_trendyol=True):
        """Önbellekten (en fazla CACHE_DAYS gün) ya da keşfederek anahtar kelimeleri döndürür."""
        if not seed or not (use_google or use_trendyol):
            return []
        key = '%s|g%d|t%d' % (seed.strip().lower(), int(bool(use_google)), int(bool(use_trendyol)))
        cache = self.sudo().search([('key', '=', key)], limit=1)
        fresh_after = fields.Datetime.now() - timedelta(days=self.CACHE_DAYS)
        if cache and cache.write_date >= fresh_after:
            try:
                return json.loads(cache.keywords or '[]')
            except ValueError:
                pass

        from ..services.keyword_discovery import KeywordDiscovery
        keywords = KeywordDiscovery().discover_keywords(seed, use_google=use_google, use_trendyol=use_trendyol)
        if not keywords:
            # Geçici ağ hatasında boş sonucu 7 gün saklama; varsa eski sonucu kullan
            if cache:
                try:
                    return json.loads(cache.keywords or '[]')
                except ValueError:
                    return []
            return []
        payload = json.dumps(keywords, ensure_ascii=False)
        try:
            with self.env.cr.savepoint():
                if cache:
                    cache.write({'keywords': payload})
                else:
                    self.sudo().create({'key': key, 'keywords': payload})
        except Exception as e:  # başka bir işçi aynı anda yazdıysa önbellek olmadan devam
            _logger.info("Anahtar kelime önbelleği yazılamadı (%s): %s", key, e)
        return keywords

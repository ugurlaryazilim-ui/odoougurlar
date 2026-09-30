# -*- coding: utf-8 -*-
"""19.0.1.0.2: AI'ın değiştirdiği ürünlerde orijinal adı ilk üretimin prompt'undan geri kazan."""
import logging
import re

_logger = logging.getLogger(__name__)

NAME_LINE = re.compile(r'^- Ürün Adı: (.+)$', re.MULTILINE)


def migrate(cr, version):
    # Her ürünün İLK üretim kaydı: o anki ad henüz AI tarafından değiştirilmemişti
    cr.execute("""
        SELECT DISTINCT ON (l.product_tmpl_id) l.product_tmpl_id, l.prompt_used
        FROM ai_content_log l
        JOIN product_template t ON t.id = l.product_tmpl_id
        WHERE t.ai_content_generated IS TRUE
          AND t.ai_original_name IS NULL
          AND l.prompt_used IS NOT NULL
        ORDER BY l.product_tmpl_id, l.create_date ASC, l.id ASC
    """)
    restored = 0
    for tmpl_id, prompt in cr.fetchall():
        match = NAME_LINE.search(prompt or '')
        if not match:
            continue
        original = match.group(1).strip()
        if original:
            cr.execute("UPDATE product_template SET ai_original_name = %s WHERE id = %s", (original, tmpl_id))
            restored += 1
    _logger.info('ai_title_description: %d ürünün orijinal adı geri kazanıldı', restored)

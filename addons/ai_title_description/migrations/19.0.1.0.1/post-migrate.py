# -*- coding: utf-8 -*-
"""19.0.1.0.1: yetkiler modül gruplarına bağlandı; description_sale düz metne çevrildi."""
import json
import logging

from odoo import api, SUPERUSER_ID
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) Erişim artık modül gruplarında: modülü kullanmış olanlar ve yöneticiler erişimsiz kalmasın
    user_group = env.ref('ai_title_description.group_ai_content_user', raise_if_not_found=False)
    manager_group = env.ref('ai_title_description.group_ai_content_manager', raise_if_not_found=False)
    if user_group:
        cr.execute("""
            SELECT DISTINCT create_uid FROM ai_content_log WHERE create_uid IS NOT NULL
            UNION
            SELECT DISTINCT create_uid FROM ai_content_queue WHERE create_uid IS NOT NULL
        """)
        uids = [r[0] for r in cr.fetchall()]
        users = env['res.users'].browse(uids).exists().filtered(lambda u: u.active and not u.share)
        if users:
            users.write({'group_ids': [(4, user_group.id)]})
            _logger.info('ai_title_description: %d kullanıcıya AI İçerik Kullanıcı grubu atandı', len(users))
    admin_group = env.ref('base.group_system', raise_if_not_found=False)
    if manager_group and admin_group:
        admins = env['res.users'].search([('all_group_ids', 'in', admin_group.id), ('share', '=', False)])
        if admins:
            admins.write({'group_ids': [(4, manager_group.id)]})

    # 2) description_sale düz metin alanı: AI'ın yazdığı HTML'i (tüm dillerde) metne çevir
    cr.execute("""
        SELECT id, description_sale FROM product_template
        WHERE ai_content_generated IS TRUE AND description_sale::text LIKE '%%<%%'
    """)
    fixed = 0
    for tmpl_id, value in cr.fetchall():
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            continue
        new_value = {lang: (html2plaintext(text).strip() if text and '<' in text else text)
                     for lang, text in value.items()}
        if new_value != value:
            cr.execute("UPDATE product_template SET description_sale = %s WHERE id = %s",
                       (json.dumps(new_value), tmpl_id))
            fixed += 1
    _logger.info('ai_title_description: %d ürünün satış açıklaması düz metne çevrildi', fixed)

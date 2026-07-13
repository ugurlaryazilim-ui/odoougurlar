import odoo
from odoo import api, SUPERUSER_ID
import logging

odoo.tools.config.parse_config(['-c', 'C:\\Program Files\\Odoo 19.0.20260706\\server\\odoo.conf'])
registry = odoo.registry('ugurlar')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Get last outgoing message
    msg = env['social.media.message'].search([('message_type','=','outgoing'), ('author_id','!=',False)], order='id desc', limit=1)
    if msg:
        print(f"Testing resent for msg {msg.id} in conversation {msg.conversation_id.id}")
        # Manually invoke the create hook by creating a dummy message
        env['social.media.message'].with_context(from_ai_cron=False).create({
            'conversation_id': msg.conversation_id.id,
            'message_type': 'outgoing',
            'content': 'Test direct message from human',
            'author_id': 1
        })
        print("Done. Check logs for Meta API error.")

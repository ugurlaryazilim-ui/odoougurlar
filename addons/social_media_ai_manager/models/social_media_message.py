# -*- coding: utf-8 -*-
from odoo import models, fields

class SocialMediaMessage(models.Model):
    _name = 'social.media.message'
    _description = 'Social Media Message / Comment'
    _order = 'date asc'

    conversation_id = fields.Many2one('social.media.conversation', string="Conversation", required=True, ondelete='cascade')
    platform_message_id = fields.Char(string="Platform Message ID", help="Unique ID from WhatsApp/Meta")
    post_link = fields.Char(string="Post URL", help="Direct link to the post if this is a comment")
    
    message_type = fields.Selection([
        ('incoming', 'Incoming (Customer)'),
        ('outgoing', 'Outgoing (Agent/AI)'),
        ('system', 'System Note')
    ], string="Direction", required=True)
    
    content = fields.Text(string="Message Content", required=True)
    date = fields.Datetime(string="Date", default=fields.Datetime.now)
    
    is_read = fields.Boolean(string="Read", default=False)
    author_id = fields.Many2one('res.users', string="Sent By (Agent)", help="If empty and outgoing, sent by AI")

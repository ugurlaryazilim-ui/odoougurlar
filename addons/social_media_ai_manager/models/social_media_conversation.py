# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class SocialMediaConversation(models.Model):
    _name = 'social.media.conversation'
    _description = 'Omnichannel Conversation'
    _order = 'last_message_date desc'

    name = fields.Char(string="Conversation Reference", compute="_compute_name", store=True)
    account_id = fields.Many2one('social.media.account', string="Social Account", required=True, ondelete='cascade')
    platform = fields.Selection(related='account_id.platform', store=True)
    
    partner_id = fields.Many2one('res.partner', string="Customer")
    social_user_id = fields.Char(string="Platform User ID / Phone Number", required=True, help="WhatsApp Number or Instagram/FB User ID")
    
    user_id = fields.Many2one('res.users', string="Assigned Agent")
    
    message_ids = fields.One2many('social.media.message', 'conversation_id', string="Messages")
    
    last_message_date = fields.Datetime(string="Last Message Date", compute="_compute_last_message", store=True)
    unread_count = fields.Integer(string="Unread Messages", compute="_compute_unread_count", store=True)
    
    state = fields.Selection([
        ('open', 'Open'),
        ('bot', 'Handled by AI'),
        ('closed', 'Closed')
    ], string="Status", default='open')

    @api.depends('partner_id', 'social_user_id', 'platform')
    def _compute_name(self):
        for rec in self:
            partner_name = rec.partner_id.name if rec.partner_id else rec.social_user_id
            platform_str = dict(self.env['social.media.account'].fields_get(allfields=['platform'])['platform']['selection']).get(rec.platform, '')
            rec.name = f"{partner_name} ({platform_str})"

    @api.depends('message_ids.is_read')
    def _compute_last_message(self):
        for rec in self:
            last_msg = self.env['social.media.message'].search([('conversation_id', '=', rec.id)], order='date desc', limit=1)
            rec.last_message_date = last_msg.date if last_msg else False

    @api.depends('message_ids.is_read', 'message_ids.message_type')
    def _compute_unread_count(self):
        for rec in self:
            rec.unread_count = len(rec.message_ids.filtered(lambda m: not m.is_read and m.message_type == 'incoming'))

    def mark_as_read(self):
        for rec in self:
            unread_messages = rec.message_ids.filtered(lambda m: not m.is_read and m.message_type == 'incoming')
            if unread_messages:
                unread_messages.write({'is_read': True})
        return True

    def action_handoff_to_human(self):
        handoff_user_ids = self.env['ir.config_parameter'].sudo().get_param('social_media_ai.handoff_user_ids')
        for rec in self:
            rec.state = 'open'
            if not rec.user_id and handoff_user_ids:
                import json
                try:
                    user_ids = json.loads(handoff_user_ids)
                    if user_ids and isinstance(user_ids, list):
                        # Simple logic: Assign to the first user in the list for now
                        # Ideally, could do round-robin or check workload
                        rec.user_id = user_ids[0]
                except Exception:
                    pass
        return True

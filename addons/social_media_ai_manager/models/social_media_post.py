# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime

class SocialMediaPost(models.Model):
    _name = 'social.media.post'
    _description = 'Social Media Post'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Post Title", required=True)
    message = fields.Text(string="Post Message", required=True)
    
    # Scheduling
    scheduled_date = fields.Datetime(string="Scheduled Date", default=fields.Datetime.now, required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('posting', 'Posting...'),
        ('posted', 'Posted'),
        ('error', 'Error')
    ], string="Status", default='draft', tracking=True)

    # Platforms
    account_ids = fields.Many2many('social.media.account', string="Publish to Accounts", required=True)
    
    # Media
    image_ids = fields.Many2many('ir.attachment', string="Images/Videos")

    post_line_ids = fields.One2many('social.media.post.line', 'post_id', string="Platform Statuses")

    def action_schedule(self):
        for rec in self:
            rec.state = 'scheduled'
            # Create lines
            for account in rec.account_ids:
                self.env['social.media.post.line'].create({
                    'post_id': rec.id,
                    'account_id': account.id,
                    'state': 'pending'
                })

    def action_draft(self):
        self.write({'state': 'draft'})
        self.post_line_ids.unlink()

    @api.model
    def _cron_publish_scheduled_posts(self):
        """ Cron job to publish posts whose time has come """
        posts = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_date', '<=', fields.Datetime.now())
        ])
        for post in posts:
            post.state = 'posting'
            all_success = True
            
            for line in post.post_line_ids.filtered(lambda l: l.state == 'pending'):
                # Call specific API logic per platform
                success = line._publish_to_platform()
                if not success:
                    all_success = False

            post.state = 'posted' if all_success else 'error'


class SocialMediaPostLine(models.Model):
    _name = 'social.media.post.line'
    _description = 'Post Line Status'

    post_id = fields.Many2one('social.media.post', required=True, ondelete='cascade')
    account_id = fields.Many2one('social.media.account', required=True)
    platform = fields.Selection(related='account_id.platform')
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('error', 'Error')
    ], default='pending')
    
    error_message = fields.Text(string="Error Details")
    platform_post_id = fields.Char(string="Platform Post ID")

    def _publish_to_platform(self):
        """ Abstract API logic """
        self.ensure_one()
        # TODO: Integrate standard API calls (Facebook Graph, TikTok API etc.)
        # Dummy success for now
        self.state = 'success'
        self.platform_post_id = "DUMMY_ID_123"
        return True

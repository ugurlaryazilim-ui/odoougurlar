# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AdsRecommendation(models.Model):
    _name = 'ads.recommendation'
    _description = 'Optimization Recommendation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'severity_order desc, create_date desc'

    name = fields.Char(required=True, tracking=True)
    campaign_id = fields.Many2one('ads.campaign', required=True, tracking=True, index=True)
    account_id = fields.Many2one(related='campaign_id.account_id', store=True)
    rule_id = fields.Many2one('ads.rule')
    company_id = fields.Many2one(related='campaign_id.company_id', store=True)
    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical')
    ], default='info', tracking=True)
    severity_order = fields.Integer(compute='_compute_severity_order', store=True)
    category = fields.Selection([
        ('budget', 'Budget'),
        ('performance', 'Performance'),
        ('creative', 'Creative'),
        ('audience', 'Audience')
    ], tracking=True)
    status = fields.Selection([
        ('new', 'New'),
        ('in_review', 'In Review'),
        ('applied', 'Applied'),
        ('dismissed', 'Dismissed')
    ], default='new', tracking=True)
    description = fields.Text()
    ai_explanation = fields.Text(string='AI Analizi')
    proposed_action = fields.Text()
    metric_data = fields.Json()
    estimated_impact = fields.Char()
    applied_date = fields.Datetime(readonly=True)
    applied_by = fields.Many2one('res.users', readonly=True)
    dismiss_reason = fields.Text()

    @api.depends('severity')
    def _compute_severity_order(self):
        order_map = {'info': 0, 'warning': 1, 'critical': 2}
        for rec in self:
            rec.severity_order = order_map.get(rec.severity, 0)

    def action_apply(self):
        for rec in self:
            rec.status = 'applied'
            rec.applied_date = fields.Datetime.now()
            rec.applied_by = self.env.user
            rec.message_post(body='Recommendation applied.')

    def action_dismiss(self):
        for rec in self:
            rec.status = 'dismissed'
            rec.message_post(body='Recommendation dismissed.')

    def action_review(self):
        for rec in self:
            rec.status = 'in_review'

    def _notify_critical(self):
        for rec in self:
            if rec.severity == 'critical':
                rec.message_post(body='CRITICAL Recommendation Requires Attention', message_type='comment')
                user_id = getattr(rec.campaign_id, 'user_id', False)
                if user_id:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user_id.id,
                        note='Please review critical recommendation'
                    )

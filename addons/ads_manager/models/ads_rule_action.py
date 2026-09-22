# -*- coding: utf-8 -*-
from odoo import models, fields

class AdsRuleAction(models.Model):
    _name = 'ads.rule.action'
    _description = 'Rule Action'

    rule_id = fields.Many2one('ads.rule', required=True, ondelete='cascade')
    action_type = fields.Selection([
        ('create_recommendation', 'Create Recommendation'),
        ('notify_chatter', 'Notify Chatter'),
        ('notify_activity', 'Notify Activity'),
        ('notify_email', 'Notify Email'),
        ('pause_entity', 'Pause Entity'),
        ('adjust_budget_pct', 'Adjust Budget (%)')
    ], required=True)
    adjustment_value = fields.Float(help='For budget adjustments: percentage')
    max_single_adjustment = fields.Float(help='Maximum single adjustment amount')
    require_approval = fields.Boolean(default=True)

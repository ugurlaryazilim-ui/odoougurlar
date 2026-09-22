# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AdsRule(models.Model):
    _name = 'ads.rule'
    _description = 'Automated Optimization Rule'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    platform_filter = fields.Selection([
        ('all', 'All Platforms'),
        ('meta', 'Meta Ads'),
        ('google', 'Google Ads')
    ], default='all')
    campaign_ids = fields.Many2many('ads.campaign', help='Leave empty for all campaigns')
    condition_ids = fields.One2many('ads.rule.condition', 'rule_id')
    condition_logic = fields.Selection([
        ('all', 'ALL (AND)'),
        ('any', 'ANY (OR)')
    ], default='all', help='ALL=AND, ANY=OR')
    action_ids = fields.One2many('ads.rule.action', 'rule_id')
    min_impressions = fields.Integer(default=100)
    cooldown_hours = fields.Integer(default=24)
    last_triggered = fields.Datetime(readonly=True)
    severity = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical')
    ], default='warning')
    category = fields.Selection([
        ('budget', 'Budget'),
        ('performance', 'Performance'),
        ('creative', 'Creative'),
        ('audience', 'Audience')
    ])
    trigger_count = fields.Integer(readonly=True, default=0)

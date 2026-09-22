# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AdsRuleCondition(models.Model):
    _name = 'ads.rule.condition'
    _description = 'Rule Condition'
    _order = 'sequence'

    rule_id = fields.Many2one('ads.rule', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    metric = fields.Selection([
        ('ctr', 'CTR'),
        ('cpc', 'CPC'),
        ('cpa', 'CPA'),
        ('roas', 'ROAS'),
        ('spend', 'Spend'),
        ('impressions', 'Impressions'),
        ('conversion_rate', 'Conversion Rate'),
        ('frequency', 'Frequency'),
        ('budget_pace', 'Budget Pace')
    ], required=True)
    operator = fields.Selection([
        ('gt', '>'),
        ('lt', '<'),
        ('gte', '>='),
        ('lte', '<='),
        ('change_pct_up', '% Change Up'),
        ('change_pct_down', '% Change Down')
    ], required=True)
    threshold = fields.Float(required=True)
    lookback_days = fields.Integer(default=7)
    consecutive_days = fields.Integer(default=1, help='How many consecutive days the condition must be met')

    @api.depends('metric', 'operator', 'threshold', 'lookback_days')
    def _compute_display_name(self):
        for rec in self:
            metric_label = dict(self._fields['metric'].selection).get(rec.metric, rec.metric) if rec.metric else ''
            operator_label = dict(self._fields['operator'].selection).get(rec.operator, rec.operator) if rec.operator else ''
            rec.display_name = f"{metric_label} {operator_label} {rec.threshold} (last {rec.lookback_days} days)"

    def _get_display_name(self):
        # Fallback method in case the explicit method name is needed elsewhere
        return self.display_name

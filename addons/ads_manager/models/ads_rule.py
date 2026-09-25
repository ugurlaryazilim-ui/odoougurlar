# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

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
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
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
    is_in_cooldown = fields.Boolean(compute='_compute_is_in_cooldown')

    @api.depends('last_triggered', 'cooldown_hours')
    def _compute_is_in_cooldown(self):
        now = fields.Datetime.now()
        for rule in self:
            if rule.last_triggered and rule.cooldown_hours:
                cooldown_end = rule.last_triggered + timedelta(hours=rule.cooldown_hours)
                rule.is_in_cooldown = now < cooldown_end
            else:
                rule.is_in_cooldown = False

    @api.model
    def _cron_evaluate_rules(self):
        """Cron job entry point: evaluate all active rules."""
        from ..services.rule_engine import RuleEngine
        engine = RuleEngine(self.env)
        result = engine.evaluate_all_rules()
        _logger.info(
            'Rule evaluation complete: %d evaluated, %d triggered, %d skipped, %d errors',
            result.get('evaluated', 0),
            result.get('triggered', 0),
            result.get('skipped', 0),
            result.get('errors', 0),
        )

    def action_evaluate_now(self):
        """Manually evaluate this rule immediately against all matching campaigns."""
        self.ensure_one()
        from ..services.rule_engine import RuleEngine
        engine = RuleEngine(self.env)
        
        # Get matching campaigns
        campaign_domain = [('status', '=', 'active')]
        if self.platform_filter != 'all':
            campaign_domain.append(('account_id.platform', '=', self.platform_filter))
        if self.campaign_ids:
            campaign_domain.append(('id', 'in', self.campaign_ids.ids))
        campaigns = self.env['ads.campaign'].search(campaign_domain)
        
        triggered = 0
        for campaign in campaigns:
            met, metric_data = engine._evaluate_rule_conditions(self, campaign)
            if met:
                engine._execute_rule_actions(self, campaign, metric_data)
                triggered += 1
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rule Evaluation Complete'),
                'message': _('%d campaigns evaluated, %d triggered.') % (len(campaigns), triggered),
                'type': 'info' if triggered == 0 else 'warning',
                'sticky': False,
            }
        }

    def action_reset_cooldown(self):
        """Reset the cooldown timer."""
        self.ensure_one()
        self.write({'last_triggered': False})

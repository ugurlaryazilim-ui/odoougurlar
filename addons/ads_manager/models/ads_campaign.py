# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class AdsCampaign(models.Model):
    _name = 'ads.campaign'
    _description = 'Advertising Campaign'
    _inherit = ['mail.thread']
    _order = 'total_spend desc'

    _unique_platform_campaign = models.Constraint(
        'UNIQUE(account_id, platform_campaign_id)',
        'The campaign ID must be unique per account!',
    )

    name = fields.Char(string='Campaign Name', required=True, tracking=True)
    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade', index=True)
    platform = fields.Selection(related='account_id.platform', store=True)
    platform_campaign_id = fields.Char(string='Platform Campaign ID', index=True)
    
    objective = fields.Selection([
        ('awareness', 'Awareness'),
        ('traffic', 'Traffic'),
        ('engagement', 'Engagement'),
        ('leads', 'Leads'),
        ('sales', 'Sales'),
        ('app_installs', 'App Installs')
    ], string='Objective', tracking=True)
    
    status = fields.Selection([
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
        ('removed', 'Removed')
    ], string='Status', default='active', tracking=True)
    
    currency_id = fields.Many2one('res.currency', related='account_id.currency_id', store=True)
    daily_budget = fields.Monetary(string='Daily Budget', currency_field='currency_id', tracking=True)
    lifetime_budget = fields.Monetary(string='Lifetime Budget', currency_field='currency_id')
    
    total_spend = fields.Monetary(string='Total Spend', currency_field='currency_id', compute='_compute_totals', store=True)
    total_clicks = fields.Integer(string='Total Clicks', compute='_compute_totals', store=True)
    total_impressions = fields.Integer(string='Total Impressions', compute='_compute_totals', store=True)
    total_conversions = fields.Float(string='Total Conversions', compute='_compute_totals', store=True, digits=(16,2))
    total_conversion_value = fields.Monetary(string='Total Conversion Value', currency_field='currency_id', compute='_compute_totals', store=True)
    avg_roas = fields.Float(string='Avg ROAS', compute='_compute_totals', store=True, digits=(16,2))
    avg_cpa = fields.Monetary(string='Avg CPA', currency_field='currency_id', compute='_compute_totals', store=True)
    
    budget_pace_status = fields.Selection([
        ('under', 'Under Pacing'),
        ('on_track', 'On Track'),
        ('over', 'Over Pacing')
    ], string='Budget Pace Status', compute='_compute_budget_pacing', store=True)
    budget_pace_pct = fields.Float(string='Budget Pace %', compute='_compute_budget_pacing', store=True)
    projected_monthly_spend = fields.Monetary(string='Projected Monthly Spend', currency_field='currency_id', compute='_compute_budget_pacing', store=True)
    
    adset_ids = fields.One2many('ads.adset', 'campaign_id', string='Ad Sets')
    metric_ids = fields.One2many('ads.metric.daily', 'campaign_id', string='Metrics')
    recommendation_ids = fields.One2many('ads.recommendation', 'campaign_id', string='Recommendations')
    
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', related='account_id.company_id', store=True)
    
    metric_count = fields.Integer(string='Metric Count', compute='_compute_stat_counts')
    recommendation_count = fields.Integer(string='Recommendation Count', compute='_compute_stat_counts')

    @api.depends('metric_ids.spend', 'metric_ids.clicks', 'metric_ids.impressions', 'metric_ids.conversions', 'metric_ids.conversion_value')
    def _compute_totals(self):
        for record in self:
            record.total_spend = sum(record.metric_ids.mapped('spend'))
            record.total_clicks = sum(record.metric_ids.mapped('clicks'))
            record.total_impressions = sum(record.metric_ids.mapped('impressions'))
            record.total_conversions = sum(record.metric_ids.mapped('conversions'))
            record.total_conversion_value = sum(record.metric_ids.mapped('conversion_value'))
            record.avg_roas = record.total_conversion_value / record.total_spend if record.total_spend else 0.0
            record.avg_cpa = record.total_spend / record.total_conversions if record.total_conversions else 0.0
            
    @api.depends('daily_budget', 'total_spend', 'metric_ids.spend')
    def _compute_budget_pacing(self):
        for record in self:
            if not record.daily_budget:
                record.budget_pace_status = False
                record.budget_pace_pct = 0.0
                record.projected_monthly_spend = 0.0
                continue
                
            # Simplified pacing logic for the skeleton
            record.projected_monthly_spend = record.daily_budget * 30
            record.budget_pace_pct = 100.0
            record.budget_pace_status = 'on_track'

    def _compute_stat_counts(self):
        for record in self:
            record.metric_count = len(record.metric_ids)
            record.recommendation_count = len(record.recommendation_ids)

    def action_view_metrics(self):
        self.ensure_one()
        return {
            'name': 'Metrics',
            'type': 'ir.actions.act_window',
            'res_model': 'ads.metric.daily',
            'view_mode': 'list,graph,pivot',
            'domain': [('campaign_id', '=', self.id)],
        }

    def action_view_recommendations(self):
        self.ensure_one()
        return {
            'name': 'Recommendations',
            'type': 'ir.actions.act_window',
            'res_model': 'ads.recommendation',
            'view_mode': 'list,kanban,form',
            'domain': [('campaign_id', '=', self.id)],
        }


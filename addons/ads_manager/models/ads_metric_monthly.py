# -*- coding: utf-8 -*-
from odoo import models, fields

class AdsMetricMonthly(models.Model):
    _name = 'ads.metric.monthly'
    _description = 'Monthly Aggregated Metrics'
    _order = 'year_month desc'

    _unique_campaign_month = models.Constraint(
        'UNIQUE(campaign_id, year_month)',
        'Monthly metrics must be unique per campaign and month!',
    )

    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade')
    campaign_id = fields.Many2one('ads.campaign', string='Campaign', required=True, ondelete='cascade')
    year_month = fields.Char(string='Year Month (YYYY-MM)', required=True, index=True)
    
    currency_id = fields.Many2one('res.currency', related='account_id.currency_id', store=True)
    
    total_impressions = fields.Integer(string='Total Impressions', default=0)
    total_clicks = fields.Integer(string='Total Clicks', default=0)
    total_spend = fields.Monetary(string='Total Spend', currency_field='currency_id', default=0.0)
    
    total_conversions = fields.Float(string='Total Conversions', digits=(16,2), default=0.0)
    total_conversion_value = fields.Monetary(string='Total Conversion Value', currency_field='currency_id', default=0.0)
    total_purchases = fields.Integer(string='Total Purchases', default=0)
    
    avg_ctr = fields.Float(string='Avg CTR', digits=(16,4), default=0.0)
    avg_cpc = fields.Monetary(string='Avg CPC', currency_field='currency_id', default=0.0)
    avg_cpa = fields.Monetary(string='Avg CPA', currency_field='currency_id', default=0.0)
    avg_roas = fields.Float(string='Avg ROAS', digits=(16,2), default=0.0)
    avg_frequency = fields.Float(string='Avg Frequency', digits=(16,2), default=0.0)
    
    days_active = fields.Integer(string='Days Active', default=0)
    company_id = fields.Many2one('res.company', related='account_id.company_id', store=True)

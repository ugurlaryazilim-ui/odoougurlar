# -*- coding: utf-8 -*-
from odoo import models, fields

class AdsAdset(models.Model):
    _name = 'ads.adset'
    _description = 'Ad Set / Ad Group'
    _order = 'name ASC'

    _unique_platform_adset = models.Constraint(
        'UNIQUE(campaign_id, platform_adset_id)',
        'The Ad Set ID must be unique per Campaign!',
    )

    name = fields.Char(string='Name', required=True)
    campaign_id = fields.Many2one('ads.campaign', string='Campaign', required=True, ondelete='cascade')
    account_id = fields.Many2one('ads.account', related='campaign_id.account_id', store=True)
    platform_adset_id = fields.Char(string='Platform Adset ID', required=True)
    
    status = fields.Selection([
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
        ('removed', 'Removed')
    ], string='Status', default='active')
    
    currency_id = fields.Many2one('res.currency', related='campaign_id.currency_id', store=True)
    daily_budget = fields.Monetary(string='Daily Budget', currency_field='currency_id')
    lifetime_budget = fields.Monetary(string='Lifetime Budget', currency_field='currency_id')
    
    targeting_summary = fields.Text(string='Targeting Summary')
    ad_ids = fields.One2many('ads.ad', 'adset_id', string='Ads')
    company_id = fields.Many2one('res.company', related='campaign_id.company_id', store=True)

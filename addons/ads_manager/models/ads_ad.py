# -*- coding: utf-8 -*-
from odoo import models, fields

class AdsAd(models.Model):
    _name = 'ads.ad'
    _description = 'Individual Ad / Creative'

    _unique_platform_ad = models.Constraint(
        'UNIQUE(adset_id, platform_ad_id)',
        'The Ad ID must be unique per Ad Set!',
    )

    name = fields.Char(string='Name', required=True)
    adset_id = fields.Many2one('ads.adset', string='Ad Set', required=True, ondelete='cascade')
    campaign_id = fields.Many2one('ads.campaign', related='adset_id.campaign_id', store=True)
    account_id = fields.Many2one('ads.account', related='adset_id.account_id', store=True)
    platform_ad_id = fields.Char(string='Platform Ad ID', required=True)
    
    status = fields.Selection([
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
        ('removed', 'Removed')
    ], string='Status', default='active')
    
    ad_type = fields.Selection([
        ('image', 'Image'),
        ('video', 'Video'),
        ('carousel', 'Carousel'),
        ('text', 'Text'),
        ('dynamic', 'Dynamic')
    ], string='Ad Type')
    
    preview_url = fields.Char(string='Preview URL')
    company_id = fields.Many2one('res.company', related='adset_id.company_id', store=True)

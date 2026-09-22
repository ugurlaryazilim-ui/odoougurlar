# -*- coding: utf-8 -*-
from odoo import models, fields

class AdsSyncLog(models.Model):
    _name = 'ads.sync.log'
    _description = 'Sync History Log'
    _order = 'sync_date desc'

    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Sync Date', default=fields.Datetime.now)
    
    sync_type = fields.Selection([
        ('campaigns', 'Campaigns'),
        ('metrics', 'Metrics'),
        ('full', 'Full Sync')
    ], string='Sync Type', required=True)
    
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('partial', 'Partial')
    ], string='Status', required=True)
    
    message = fields.Text(string='Message')
    records_created = fields.Integer(string='Records Created', default=0)
    records_updated = fields.Integer(string='Records Updated', default=0)
    duration_seconds = fields.Float(string='Duration (seconds)', default=0.0)
    
    company_id = fields.Many2one('res.company', related='account_id.company_id', store=True)

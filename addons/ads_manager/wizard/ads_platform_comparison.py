# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AdsPlatformComparison(models.TransientModel):
    _name = 'ads.platform.comparison'
    _description = 'Ads Platform Comparison'

    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    
    meta_spend = fields.Monetary(string='Meta Spend', currency_field='currency_id')
    google_spend = fields.Monetary(string='Google Spend', currency_field='currency_id')
    
    meta_roas = fields.Float(string='Meta ROAS')
    google_roas = fields.Float(string='Google ROAS')
    
    meta_cpa = fields.Monetary(string='Meta CPA', currency_field='currency_id')
    google_cpa = fields.Monetary(string='Google CPA', currency_field='currency_id')
    
    meta_conversions = fields.Float(string='Meta Conversions')
    google_conversions = fields.Float(string='Google Conversions')
    
    recommendation = fields.Text(string='Recommendation')

    def action_compute(self):
        self.ensure_one()
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        
        # Read group by platform (via campaign relation)
        groups = self.env['ads.metric.daily']._read_group(
            domain=domain,
            groupby=['campaign_id.account_id.platform'],
            aggregates=['spend:sum', 'conversions:sum', 'conversion_value:sum']
        )
        
        for platform, spend, conversions, conversion_value in groups:
            roas = (conversion_value / spend) if spend else 0.0
            cpa = (spend / conversions) if conversions else 0.0
            
            if platform == 'meta':
                self.meta_spend = spend
                self.meta_conversions = conversions
                self.meta_roas = roas
                self.meta_cpa = cpa
            elif platform == 'google':
                self.google_spend = spend
                self.google_conversions = conversions
                self.google_roas = roas
                self.google_cpa = cpa
        
        # Simple recommendation logic
        if self.meta_roas > self.google_roas:
            self.recommendation = "Meta Ads is currently yielding a higher ROAS. Consider reallocating budget to Meta."
        elif self.google_roas > self.meta_roas:
            self.recommendation = "Google Ads is currently yielding a higher ROAS. Consider reallocating budget to Google."
        else:
            self.recommendation = "Both platforms are performing similarly."

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ads.platform.comparison',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

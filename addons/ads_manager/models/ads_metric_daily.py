# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AdsMetricDaily(models.Model):
    _name = 'ads.metric.daily'
    _description = 'Daily Performance Metrics'
    _order = 'date desc, campaign_id'

    _unique_metric = models.Constraint(
        'UNIQUE(campaign_id, adset_id, ad_id, date)',
        'Metrics must be unique per campaign/adset/ad and date!',
    )

    _check_non_negative = models.Constraint(
        'CHECK(impressions >= 0 AND clicks >= 0 AND spend >= 0)',
        'Metrics cannot be negative!',
    )

    _campaign_date_idx = models.Index('(campaign_id, date DESC)')
    _account_date_idx = models.Index('(account_id, date DESC)')

    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade')
    campaign_id = fields.Many2one('ads.campaign', string='Campaign', required=True, ondelete='cascade')
    adset_id = fields.Many2one('ads.adset', string='Ad Set', ondelete='cascade')
    ad_id = fields.Many2one('ads.ad', string='Ad', ondelete='cascade')
    
    date = fields.Date(string='Date', required=True, index=True)
    impressions = fields.Integer(string='Impressions', default=0)
    clicks = fields.Integer(string='Clicks', default=0)
    
    currency_id = fields.Many2one('res.currency', related='account_id.currency_id', store=True)
    spend = fields.Monetary(string='Spend', currency_field='currency_id', default=0.0)
    conversion_value = fields.Monetary(string='Conversion Value', currency_field='currency_id', default=0.0)
    conversions = fields.Float(string='Conversions', digits=(16,2), default=0.0)
    
    link_clicks = fields.Integer(string='Link Clicks', default=0)
    landing_page_views = fields.Integer(string='Landing Page Views', default=0)
    add_to_cart = fields.Integer(string='Add to Cart', default=0)
    initiate_checkout = fields.Integer(string='Initiate Checkout', default=0)
    purchases = fields.Integer(string='Purchases', default=0)
    
    frequency = fields.Float(string='Frequency', digits=(16,2), default=0.0)
    reach = fields.Integer(string='Reach', default=0)
    
    attribution_model = fields.Selection([
        ('last_click', 'Last Click'),
        ('7d_click_1d_view', '7d Click 1d View'),
        ('data_driven', 'Data Driven')
    ], string='Attribution Model')
    
    ctr = fields.Float(string='CTR', compute='_compute_kpis', store=True, digits=(16,4))
    cpc = fields.Monetary(string='CPC', currency_field='currency_id', compute='_compute_kpis', store=True)
    cpa = fields.Monetary(string='CPA', currency_field='currency_id', compute='_compute_kpis', store=True)
    roas = fields.Float(string='ROAS', compute='_compute_kpis', store=True, digits=(16,2))
    cpm = fields.Monetary(string='CPM', currency_field='currency_id', compute='_compute_kpis', store=True)
    conversion_rate = fields.Float(string='Conversion Rate', compute='_compute_kpis', store=True, digits=(16,4))
    
    company_id = fields.Many2one('res.company', related='account_id.company_id', store=True)
    is_archived = fields.Boolean(string='Archived', default=False, index=True)

    @api.depends('impressions', 'clicks', 'spend', 'conversions', 'conversion_value')
    def _compute_kpis(self):
        for record in self:
            record.ctr = (record.clicks / record.impressions) * 100 if record.impressions else 0.0
            record.cpc = record.spend / record.clicks if record.clicks else 0.0
            record.cpa = record.spend / record.conversions if record.conversions else 0.0
            record.roas = record.conversion_value / record.spend if record.spend else 0.0
            record.cpm = (record.spend / record.impressions) * 1000 if record.impressions else 0.0
            record.conversion_rate = (record.conversions / record.clicks) * 100 if record.clicks else 0.0

    @api.model
    def _cron_archive_old_metrics(self, days_retention=90):
        """
        Cron: Aggregate daily metrics older than retention period into monthly summaries,
        and mark daily records as archived.
        """
        import logging
        from datetime import date, timedelta
        _logger = logging.getLogger(__name__)

        cutoff_date = date.today() - timedelta(days=days_retention)
        old_metrics = self.search([
            ('date', '<', cutoff_date),
            ('is_archived', '=', False)
        ])

        if not old_metrics:
            _logger.info("No old metrics to archive.")
            return

        _logger.info("Archiving %d daily metrics older than %s", len(old_metrics), cutoff_date)

        # Group by campaign and year_month
        campaign_months = {}
        for m in old_metrics:
            ym = m.date.strftime('%Y-%m')
            key = (m.campaign_id.id, m.account_id.id, ym)
            if key not in campaign_months:
                campaign_months[key] = []
            campaign_months[key].append(m)

        MonthlyModel = self.env['ads.metric.monthly']
        for (campaign_id, account_id, ym), metrics_list in campaign_months.items():
            tot_spend = sum(m.spend for m in metrics_list)
            tot_imp = sum(m.impressions for m in metrics_list)
            tot_clicks = sum(m.clicks for m in metrics_list)
            tot_conv = sum(m.conversions for m in metrics_list)
            tot_val = sum(m.conversion_value for m in metrics_list)
            tot_purchases = sum(m.purchases for m in metrics_list)
            days_count = len(set(m.date for m in metrics_list))

            existing = MonthlyModel.search([
                ('campaign_id', '=', campaign_id),
                ('year_month', '=', ym)
            ], limit=1)

            vals = {
                'account_id': account_id,
                'campaign_id': campaign_id,
                'year_month': ym,
                'total_spend': tot_spend,
                'total_impressions': tot_imp,
                'total_clicks': tot_clicks,
                'total_conversions': tot_conv,
                'total_conversion_value': tot_val,
                'total_purchases': tot_purchases,
                'avg_ctr': (tot_clicks / tot_imp * 100) if tot_imp else 0.0,
                'avg_cpc': (tot_spend / tot_clicks) if tot_clicks else 0.0,
                'avg_cpa': (tot_spend / tot_conv) if tot_conv else 0.0,
                'avg_roas': (tot_val / tot_spend) if tot_spend else 0.0,
                'days_active': days_count,
            }

            if existing:
                existing.write(vals)
            else:
                MonthlyModel.create(vals)

        # Mark all processed daily records as archived
        old_metrics.write({'is_archived': True})
        _logger.info("Archiving complete: %d records marked as archived.", len(old_metrics))

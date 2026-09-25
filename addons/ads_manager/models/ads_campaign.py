# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AdsCampaign(models.Model):
    _name = 'ads.campaign'
    _description = 'Advertising Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'total_spend desc'

    _unique_platform_campaign = models.Constraint(
        'UNIQUE(account_id, platform_campaign_id)',
        'The campaign ID must be unique per account!',
    )

    name = fields.Char(string='Campaign Name', required=True, tracking=True)
    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade', index=True)
    platform = fields.Selection(related='account_id.platform', store=True)
    platform_campaign_id = fields.Char(string='Platform Campaign ID', index=True)
    start_date = fields.Date(string='Start Date', tracking=True)
    end_date = fields.Date(string='End Date', tracking=True)
    
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
    
    # Approval workflow - for campaigns created/modified in Odoo
    approval_status = fields.Selection([
        ('draft', 'Taslak'),
        ('pending', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('published', 'Yayında'),
    ], string='Approval Status', default='draft', tracking=True)
    
    is_local = fields.Boolean(
        string='Locally Created', default=False,
        help='True if this campaign was created in Odoo (not synced from platform)'
    )
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approval Date', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason')
    publish_date = fields.Datetime(string='Publish Date', readonly=True)
    
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
        ('critical_overspend', 'Critical Overspend'),
        ('overspending', 'Overspending'),
        ('on_track', 'On Track'),
        ('underspending', 'Underspending'),
        ('under', 'Under Pacing'),
        ('over', 'Over Pacing'),
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

    @api.depends('metric_ids', 'recommendation_ids')
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

    def action_submit_for_approval(self):
        """Submit campaign for manager approval."""
        self.ensure_one()
        if self.approval_status != 'draft':
            raise UserError(_('Only draft campaigns can be submitted for approval.'))
        self.write({'approval_status': 'pending'})
        # Notify managers
        managers = self.env.ref('ads_manager.group_ads_manager').users
        for manager in managers:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.id,
                summary=_('Campaign approval required: %s') % self.name,
                note=_('Please review and approve/reject this campaign.'),
            )
        self.message_post(body=_('Campaign submitted for approval.'))

    def action_approve(self):
        """Manager approves the campaign."""
        self.ensure_one()
        if self.approval_status != 'pending':
            raise UserError(_('Only pending campaigns can be approved.'))
        self.write({
            'approval_status': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
        })
        self.activity_feedback(['mail.mail_activity_data_todo'])
        self.message_post(body=_('Campaign approved by %s.') % self.env.user.name)

    def action_reject(self):
        """Manager rejects the campaign. Opens a wizard for reason."""
        self.ensure_one()
        if self.approval_status != 'pending':
            raise UserError(_('Only pending campaigns can be rejected.'))
        return {
            'name': _('Reject Campaign'),
            'type': 'ir.actions.act_window',
            'res_model': 'ads.campaign.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_campaign_id': self.id},
        }

    def action_publish(self):
        """Publish approved campaign to the platform."""
        self.ensure_one()
        if self.approval_status != 'approved':
            raise UserError(_('Only approved campaigns can be published.'))
        try:
            if self.platform == 'meta':
                self._publish_to_meta()
            elif self.platform == 'google':
                self._publish_to_google()
            self.write({
                'approval_status': 'published',
                'publish_date': fields.Datetime.now(),
            })
            self.message_post(body=_('Campaign published to %s.') % self.platform)
        except Exception as e:
            self.message_post(body=_('Failed to publish: %s') % str(e))
            raise UserError(_('Publishing failed: %s') % str(e))

    def action_reset_to_draft(self):
        """Reset campaign back to draft."""
        self.ensure_one()
        if self.approval_status in ('published',):
            raise UserError(_('Published campaigns cannot be reset to draft.'))
        self.write({
            'approval_status': 'draft',
            'approved_by': False,
            'approved_date': False,
            'rejection_reason': False,
        })
        self.message_post(body=_('Campaign reset to draft.'))

    @api.private
    def _publish_to_meta(self):
        """Create or update campaign on Meta Ads platform."""
        from ..services.meta_client import MetaAdsClient, MetaApiError
        account = self.account_id.sudo()
        client = MetaAdsClient(
            access_token=account.access_token,
            api_version=account.meta_api_version,
            account_id=f'act_{account.platform_account_id}',
            business_id=account.meta_business_id,
        )
        # Map objective back to Meta format
        objective_map = {
            'awareness': 'OUTCOME_AWARENESS',
            'traffic': 'OUTCOME_TRAFFIC',
            'engagement': 'OUTCOME_ENGAGEMENT',
            'leads': 'OUTCOME_LEADS',
            'sales': 'OUTCOME_SALES',
            'app_installs': 'OUTCOME_APP_PROMOTION',
        }
        data = {
            'name': self.name,
            'objective': objective_map.get(self.objective, 'OUTCOME_TRAFFIC'),
            'status': 'PAUSED',  # Always create as paused
            'special_ad_categories': [],
        }
        if self.daily_budget:
            data['daily_budget'] = int(self.daily_budget * 100)  # Convert to cents
        if self.lifetime_budget:
            data['lifetime_budget'] = int(self.lifetime_budget * 100)
        
        if self.platform_campaign_id:
            # Update existing
            client._make_request('POST', self.platform_campaign_id, data=data)
        else:
            # Create new
            result = client._make_request('POST', f'act_{account.platform_account_id}/campaigns', data=data)
            self.write({'platform_campaign_id': result.get('id')})

    @api.private
    def _publish_to_google(self):
        """Create or update campaign on Google Ads platform."""
        from ..services.google_client import GoogleAdsClient, GoogleAdsError
        account = self.account_id.sudo()
        client = GoogleAdsClient(
            access_token=account.access_token,
            developer_token=account.google_developer_token,
            customer_id=account.platform_account_id,
            manager_id=account.google_manager_id,
        )
        # Google campaign creation via mutate
        channel_map = {
            'awareness': 'DISPLAY',
            'traffic': 'SEARCH',
            'engagement': 'DISPLAY',
            'leads': 'SEARCH',
            'sales': 'PERFORMANCE_MAX',
            'app_installs': 'MULTI_CHANNEL',
        }
        customer_id = account.platform_account_id.replace('-', '')
        
        # Build campaign operation
        campaign_operation = {
            'create': {
                'name': self.name,
                'advertisingChannelType': channel_map.get(self.objective, 'SEARCH'),
                'status': 'PAUSED',
            }
        }
        
        # Create budget first
        budget_amount = int((self.daily_budget or 0) * 1_000_000)  # Convert to micros
        budget_operation = {
            'create': {
                'name': f'{self.name}_budget',
                'amountMicros': str(budget_amount),
                'deliveryMethod': 'STANDARD',
            }
        }
        
        # For new campaign - create budget then campaign
        if not self.platform_campaign_id:
            # Create budget
            budget_result = client._make_request(
                'POST',
                f'customers/{customer_id}/campaignBudgets:mutate',
                data={'operations': [budget_operation]}
            )
            budget_resource = budget_result.get('results', [{}])[0].get('resourceName', '')
            
            # Create campaign with budget reference
            campaign_operation['create']['campaignBudget'] = budget_resource
            result = client._make_request(
                'POST',
                f'customers/{customer_id}/campaigns:mutate',
                data={'operations': [campaign_operation]}
            )
            resource_name = result.get('results', [{}])[0].get('resourceName', '')
            campaign_id = resource_name.split('/')[-1] if resource_name else ''
            self.write({'platform_campaign_id': campaign_id})
        else:
            # Update existing
            campaign_operation = {
                'update': {
                    'resourceName': f'customers/{customer_id}/campaigns/{self.platform_campaign_id}',
                    'name': self.name,
                    'status': 'PAUSED',
                },
                'updateMask': 'name,status'
            }
            client._make_request(
                'POST',
                f'customers/{customer_id}/campaigns:mutate',
                data={'operations': [campaign_operation]}
            )

    def action_adjust_budget(self, new_daily_budget):
        """Adjust daily budget on the platform."""
        self.ensure_one()
        old_budget = self.daily_budget
        self.daily_budget = new_daily_budget
        
        try:
            if self.platform_campaign_id:
                if self.platform == 'meta':
                    self._update_meta_budget(new_daily_budget)
                elif self.platform == 'google':
                    self._update_google_budget(new_daily_budget)
            self.message_post(
                body=_('Budget adjusted: %.2f → %.2f') % (old_budget, new_daily_budget)
            )
        except Exception as e:
            self.daily_budget = old_budget  # Rollback
            raise UserError(_('Budget adjustment failed: %s') % str(e))

    @api.private
    def _update_meta_budget(self, new_budget):
        from ..services.meta_client import MetaAdsClient
        account = self.account_id.sudo()
        client = MetaAdsClient(
            access_token=account.access_token,
            api_version=account.meta_api_version,
            account_id=f'act_{account.platform_account_id}',
        )
        client._make_request('POST', self.platform_campaign_id, data={
            'daily_budget': int(new_budget * 100),
        })

    @api.private
    def _update_google_budget(self, new_budget):
        from ..services.google_client import GoogleAdsClient
        account = self.account_id.sudo()
        client = GoogleAdsClient(
            access_token=account.access_token,
            developer_token=account.google_developer_token,
            customer_id=account.platform_account_id,
            manager_id=account.google_manager_id,
        )
        customer_id = account.platform_account_id.replace('-', '')
        # Update the budget resource
        # First get the budget resource name
        query = f"SELECT campaign_budget.resource_name FROM campaign WHERE campaign.id = {self.platform_campaign_id}"
        results = client.search_stream(query)
        if results:
            budget_resource = results[0].get('campaignBudget', {}).get('resourceName', '')
            if budget_resource:
                operation = {
                    'update': {
                        'resourceName': budget_resource,
                        'amountMicros': str(int(new_budget * 1_000_000)),
                    },
                    'updateMask': 'amountMicros'
                }
                client._make_request(
                    'POST',
                    f'customers/{customer_id}/campaignBudgets:mutate',
                    data={'operations': [operation]}
                )

    def action_ai_analyze(self):
        """Trigger AI analysis for this campaign."""
        self.ensure_one()
        from ..services.ai_engine import AdsAIEngine
        engine = AdsAIEngine(self.env)
        insights = engine.analyze_campaign(self)
        if insights:
            summary = insights.get('summary', 'Analiz tamamlandı.')
            self.message_post(body=f'<b>AI Analiz Sonucu:</b><br/>{summary}')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AI Analysis Complete'),
                    'message': summary[:200],
                    'type': 'info',
                    'sticky': False,
                }
            }
        raise UserError(_('AI analysis returned no results.'))

    @api.model
    def _cron_send_weekly_reports(self):
        """Cron: Generate and send weekly performance reports for active campaigns."""
        active_campaigns = self.search([('status', '=', 'active')])
        template = self.env.ref('ads_manager.email_template_ads_weekly_report', raise_if_not_found=False)
        _logger.info("Starting weekly reports cron for %d active campaigns", len(active_campaigns))

        sent_count = 0
        for campaign in active_campaigns:
            try:
                # If responsible user has an email, send email or post to chatter
                if template and campaign.user_id and campaign.user_id.email:
                    template.send_mail(campaign.id, force_send=True)
                    sent_count += 1
                else:
                    # Fallback to chatter post
                    campaign.message_post(
                        body=_("Haftalık performans raporu hazırlandı. Toplam harcama: %s, ROAS: %s") % (
                            campaign.total_spend, campaign.avg_roas
                        ),
                        subtype_xmlid='mail.mt_note'
                    )
            except Exception as e:
                _logger.error("Failed to send weekly report for campaign %s: %s", campaign.name, str(e))

        _logger.info("Weekly reports cron finished. %d reports sent.", sent_count)

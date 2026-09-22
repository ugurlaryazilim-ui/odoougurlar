# -*- coding: utf-8 -*-
import logging
import time
import requests as req
from datetime import date, timedelta, datetime

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AdsAccount(models.Model):
    _name = 'ads.account'
    _description = 'Advertising Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name ASC'

    _unique_platform_account = models.Constraint(
        'UNIQUE(platform, platform_account_id, company_id)',
        'The platform account ID must be unique per platform and company!',
    )

    name = fields.Char(string='Account Name', required=True, tracking=True)
    platform = fields.Selection([
        ('meta', 'Meta Ads'),
        ('google', 'Google Ads')
    ], string='Platform', required=True, tracking=True)
    platform_account_id = fields.Char(string='Platform Account ID', required=True)
    
    access_token = fields.Char(string='Access Token', groups='base.group_system', copy=False)
    refresh_token = fields.Char(string='Refresh Token', groups='base.group_system', copy=False)
    token_expiry = fields.Datetime(string='Token Expiry', groups='base.group_system')
    
    meta_app_id = fields.Char(string='Meta App ID')
    meta_app_secret = fields.Char(string='Meta App Secret', groups='base.group_system', copy=False)
    meta_api_version = fields.Char(string='Meta API Version', default='v26.0')
    meta_business_id = fields.Char(string='Meta Business ID')
    
    google_client_id = fields.Char(string='Google Client ID')
    google_client_secret = fields.Char(string='Google Client Secret', groups='base.group_system', copy=False)
    google_developer_token = fields.Char(string='Google Developer Token', groups='base.group_system', copy=False)
    google_manager_id = fields.Char(string='Google Manager ID', help='MCC Manager ID')
    google_api_version = fields.Char(string='Google API Version', default='v25')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('connected', 'Connected'),
        ('error', 'Error')
    ], string='State', default='draft', tracking=True)
    
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.company.currency_id)
    timezone = fields.Char(string='Timezone')
    
    campaign_ids = fields.One2many('ads.campaign', 'account_id', string='Campaigns')
    sync_log_ids = fields.One2many('ads.sync.log', 'account_id', string='Sync Logs')
    last_sync_date = fields.Datetime(string='Last Sync Date', readonly=True)
    
    campaign_count = fields.Integer(string='Campaign Count', compute='_compute_counts')
    active_campaign_count = fields.Integer(string='Active Campaign Count', compute='_compute_counts')


    @api.depends('campaign_ids', 'campaign_ids.status')
    def _compute_counts(self):
        for record in self:
            record.campaign_count = len(record.campaign_ids)
            record.active_campaign_count = len(record.campaign_ids.filtered(lambda c: c.status == 'active'))

    def action_connect(self):
        self.ensure_one()
        if self.platform == 'meta':
            if not self.meta_app_id or not self.meta_app_secret:
                raise UserError(_('Please configure Meta App ID and App Secret first.'))
            return {
                'type': 'ir.actions.act_url',
                'url': f'/ads_manager/meta/login?account_id={self.id}',
                'target': 'self',
            }
        elif self.platform == 'google':
            raise UserError(_('Google Ads connection will be available in a future update.'))

    def action_test_connection(self):
        self.ensure_one()
        if self.platform == 'meta':
            if not self.access_token:
                raise UserError(_('No access token available. Please connect first.'))
            url = f'https://graph.facebook.com/{self.meta_api_version}/me'
            params = {'access_token': self.access_token}
            try:
                resp = req.get(url, params=params)
                data = resp.json()
                if 'id' in data:
                    self.message_post(body=_('Connection test successful!'))
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Success'),
                            'message': _('Connection successful.'),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    self.state = 'error'
                    error_msg = data.get('error', {}).get('message', 'Unknown error')
                    self.message_post(body=_('Connection test failed: %s') % data)
                    raise UserError(_('Connection test failed: %s') % error_msg)
            except Exception as e:
                self.state = 'error'
                self.message_post(body=_('Connection test failed: %s') % str(e))
                raise UserError(_('Connection test failed: %s') % str(e))
        elif self.platform == 'google':
            raise UserError(_('Google Ads connection will be available in a future update.'))

    def action_sync_campaigns(self):
        self.ensure_one()
        if self.platform == 'meta':
            self._sync_meta_full()
        elif self.platform == 'google':
            raise UserError(_('Google sync not implemented yet.'))

    @api.private
    def _sync_meta_full(self):
        start_time = time.time()
        from ..services.meta_client import MetaAdsClient, MetaApiError
        
        client = MetaAdsClient(
            access_token=self.access_token,
            api_version=self.meta_api_version,
            account_id=f'act_{self.platform_account_id}',
            business_id=self.meta_business_id,
        )
        
        created = updated = 0
        try:
            # Sync campaigns
            c, u = self._sync_meta_campaigns(client)
            created += c; updated += u
            
            # Sync adsets
            c, u = self._sync_meta_adsets(client)
            created += c; updated += u
            
            # Sync ads
            c, u = self._sync_meta_ads(client)
            created += c; updated += u
            
            duration = time.time() - start_time
            self._create_sync_log('campaigns', 'success', 
                f'Synced {created} new, {updated} updated records', created, updated, duration)
            self.last_sync_date = fields.Datetime.now()
            self.message_post(body=f'Meta kampanyaları senkronize edildi: {created} yeni, {updated} güncellendi.')
            
        except MetaApiError as e:
            duration = time.time() - start_time
            self._create_sync_log('campaigns', 'error', str(e), created, updated, duration)
            self.state = 'error'
            self.message_post(body=f'Meta senkronizasyon hatası: {str(e)}')
            raise UserError(str(e))

    @api.private
    def _sync_meta_campaigns(self, client):
        """Sync campaigns from Meta. Returns (created_count, updated_count)"""
        raw_campaigns = client.get_campaigns()
        created = updated = 0
        Campaign = self.env['ads.campaign']
        
        for raw in raw_campaigns:
            normalized = client.normalize_campaign(raw)
            existing = Campaign.search([
                ('account_id', '=', self.id),
                ('platform_campaign_id', '=', normalized['platform_campaign_id']),
            ], limit=1)
            
            vals = {
                'name': normalized['name'],
                'status': normalized['status'],
                'objective': normalized['objective'],
                'daily_budget': normalized.get('daily_budget', 0),
                'lifetime_budget': normalized.get('lifetime_budget', 0),
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals.update({
                    'account_id': self.id,
                    'platform_campaign_id': normalized['platform_campaign_id'],
                })
                Campaign.create(vals)
                created += 1
        
        return created, updated

    @api.private
    def _sync_meta_adsets(self, client):
        raw_adsets = client.get_adsets()
        created = updated = 0
        Adset = self.env['ads.adset']
        Campaign = self.env['ads.campaign']
        
        for raw in raw_adsets:
            normalized = client.normalize_adset(raw)
            campaign = Campaign.search([
                ('account_id', '=', self.id),
                ('platform_campaign_id', '=', raw.get('campaign_id')),
            ], limit=1)
            if not campaign:
                continue
            
            existing = Adset.search([
                ('campaign_id', '=', campaign.id),
                ('platform_adset_id', '=', normalized['platform_adset_id']),
            ], limit=1)
            
            vals = {
                'name': normalized['name'],
                'status': normalized['status'],
                'daily_budget': normalized.get('daily_budget', 0),
                'lifetime_budget': normalized.get('lifetime_budget', 0),
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals.update({
                    'campaign_id': campaign.id,
                    'platform_adset_id': normalized['platform_adset_id'],
                })
                Adset.create(vals)
                created += 1
        
        return created, updated

    @api.private
    def _sync_meta_ads(self, client):
        raw_ads = client.get_ads()
        created = updated = 0
        Ad = self.env['ads.ad']
        Adset = self.env['ads.adset']
        
        for raw in raw_ads:
            normalized = client.normalize_ad(raw)
            adset = Adset.search([
                ('platform_adset_id', '=', raw.get('adset_id')),
            ], limit=1)
            if not adset:
                continue
            
            existing = Ad.search([
                ('adset_id', '=', adset.id),
                ('platform_ad_id', '=', normalized['platform_ad_id']),
            ], limit=1)
            
            vals = {
                'name': normalized['name'],
                'status': normalized['status'],
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals.update({
                    'adset_id': adset.id,
                    'platform_ad_id': normalized['platform_ad_id'],
                })
                Ad.create(vals)
                created += 1
        
        return created, updated

    @api.private
    def _sync_meta_metrics(self, client, date_from=None, date_to=None):
        if not date_from:
            date_from = (date.today() - timedelta(days=7)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()
        
        raw_insights = client.get_insights(
            date_from=date_from, date_to=date_to,
            level='campaign', time_increment=1
        )
        
        Metric = self.env['ads.metric.daily']
        created = updated = 0
        
        for raw in raw_insights:
            normalized = client.normalize_insights(raw)
            campaign = self.env['ads.campaign'].search([
                ('account_id', '=', self.id),
                ('platform_campaign_id', '=', raw.get('campaign_id')),
            ], limit=1)
            
            if not campaign:
                continue
            
            existing = Metric.search([
                ('campaign_id', '=', campaign.id),
                ('date', '=', normalized['date']),
                ('adset_id', '=', False),
                ('ad_id', '=', False),
            ], limit=1)
            
            vals = {
                'impressions': normalized['impressions'],
                'clicks': normalized['clicks'],
                'spend': normalized['spend'],
                'conversions': normalized['conversions'],
                'conversion_value': normalized['conversion_value'],
                'link_clicks': normalized.get('link_clicks', 0),
                'landing_page_views': normalized.get('landing_page_views', 0),
                'add_to_cart': normalized.get('add_to_cart', 0),
                'initiate_checkout': normalized.get('initiate_checkout', 0),
                'purchases': normalized.get('purchases', 0),
                'reach': normalized.get('reach', 0),
                'frequency': normalized.get('frequency', 0.0),
            }
            
            if existing:
                existing.write(vals)
                updated += 1
            else:
                vals.update({
                    'account_id': self.id,
                    'campaign_id': campaign.id,
                    'date': normalized['date'],
                })
                Metric.create(vals)
                created += 1
        
        return created, updated

    @api.private
    def _refresh_access_token(self):
        self.ensure_one()
        if self.platform == 'meta':
            self._refresh_meta_token()
        elif self.platform == 'google':
            pass

    @api.private
    def _refresh_meta_token(self):
        url = f'https://graph.facebook.com/{self.meta_api_version}/oauth/access_token'
        params = {
            'grant_type': 'fb_exchange_token',
            'client_id': self.meta_app_id,
            'client_secret': self.meta_app_secret,
            'fb_exchange_token': self.access_token,
        }
        try:
            resp = req.get(url, params=params)
            data = resp.json()
            if 'access_token' in data:
                self.sudo().write({
                    'access_token': data['access_token'],
                    'token_expiry': fields.Datetime.now() + timedelta(days=60),
                })
            else:
                self.state = 'error'
                self.message_post(body=_('Meta token yenileme hatası: %s') % data)
        except Exception as e:
            self.state = 'error'
            self.message_post(body=_('Meta token yenileme hatası: %s') % str(e))

    @api.private
    def _create_sync_log(self, sync_type, status, message, created=0, updated=0, duration=0):
        self.env['ads.sync.log'].create({
            'account_id': self.id,
            'sync_type': sync_type,
            'status': status,
            'message': message,
            'records_created': created,
            'records_updated': updated,
            'duration_seconds': duration,
        })

    @api.model
    def _cron_sync_all_accounts(self):
        accounts = self.search([('state', '=', 'connected')])
        total = len(accounts)
        for idx, account in enumerate(accounts):
            with self.env.cr.savepoint():
                try:
                    if account.platform == 'meta':
                        account._sync_meta_full()
                    elif account.platform == 'google':
                        pass  # M2
                except Exception as e:
                    _logger.error('Cron sync failed for %s: %s', account.name, e)
            self.env['ir.cron']._commit_progress(done=idx+1, remaining=total-idx-1)

    @api.model
    def _cron_sync_metrics(self):
        accounts = self.search([('state', '=', 'connected')])
        for account in accounts:
            with self.env.cr.savepoint():
                try:
                    if account.platform == 'meta':
                        from ..services.meta_client import MetaAdsClient
                        client = MetaAdsClient(
                            access_token=account.access_token,
                            api_version=account.meta_api_version,
                            account_id=f'act_{account.platform_account_id}',
                            business_id=account.meta_business_id,
                        )
                        account._sync_meta_metrics(client)
                except Exception as e:
                    _logger.error('Metric sync failed for %s: %s', account.name, e)

    @api.model
    def _cron_refresh_tokens(self):
        accounts = self.search([('state', '=', 'connected')])
        for account in accounts:
            try:
                account._refresh_access_token()
            except Exception as e:
                _logger.error(f"Failed to refresh token for account {account.name}: {str(e)}")

    def get_dashboard_data(self, period='7d', platform='all', account_id=None, compare=False):
        domain = []
        if platform != 'all':
            domain.append(('account_id.platform', '=', platform))
        if account_id:
            domain.append(('account_id', '=', account_id))
            
        today = date.today()
        if period == '7d':
            start_date = today - timedelta(days=7)
        elif period == '30d':
            start_date = today - timedelta(days=30)
        elif period == '90d':
            start_date = today - timedelta(days=90)
        elif period == 'mtd':
            start_date = today.replace(day=1)
        elif period == 'ytd':
            start_date = today.replace(month=1, day=1)
        else:
            start_date = today - timedelta(days=7)
            
        date_domain = domain + [('date', '>=', start_date), ('date', '<=', today)]
        
        metrics = self.env['ads.metric.daily'].search(date_domain)
        
        total_spend = sum(metrics.mapped('spend'))
        total_impressions = sum(metrics.mapped('impressions'))
        total_clicks = sum(metrics.mapped('clicks'))
        total_conversions = sum(metrics.mapped('conversions'))
        
        chart_data = []
        if metrics:
            groups = self.env['ads.metric.daily']._read_group(
                domain=date_domain,
                groupby=['date'],
                aggregates=['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum']
            )
            for group in groups:
                chart_data.append({
                    'date': str(group[0]),
                    'spend': group[1],
                    'impressions': group[2],
                    'clicks': group[3],
                    'conversions': group[4]
                })

        return {
            'period': period,
            'platform': platform,
            'account_id': account_id,
            'compare': compare,
            'kpis': {
                'spend': total_spend,
                'impressions': total_impressions,
                'clicks': total_clicks,
                'conversions': total_conversions,
            },
            'charts': chart_data,
            'top_campaigns': [],
            'recommendations': []
        }

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

    def action_view_campaigns(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Campaigns'),
            'res_model': 'ads.campaign',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }

    def action_reset_to_draft(self):
        self.ensure_one()
        self.write({'state': 'draft'})

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
            if not self.google_client_id or not self.google_client_secret:
                raise UserError(_('Please configure Google Client ID and Client Secret first.'))
            return {
                'type': 'ir.actions.act_url',
                'url': f'/ads_manager/google/login?account_id={self.id}',
                'target': 'self',
            }

    def action_test_connection(self):
        self.ensure_one()
        acc = self.sudo()
        if self.platform == 'meta':
            if not acc.access_token:
                raise UserError(_('No access token available. Please connect first.'))
            url = f'https://graph.facebook.com/{self.meta_api_version}/me'
            params = {'access_token': acc.access_token}
            try:
                resp = req.get(url, params=params)
                data = resp.json()
                if 'id' in data:
                    self.write({'state': 'connected'})
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
            self._ensure_google_token_valid()
            acc = self.sudo()
            from ..services.google_client import GoogleAdsClient, GoogleAdsError
            client = GoogleAdsClient(
                access_token=acc.access_token,
                developer_token=acc.google_developer_token,
                customer_id=acc.platform_account_id,
                manager_id=acc.google_manager_id,
                refresh_token=acc.refresh_token,
                client_id=acc.google_client_id,
                client_secret=acc.google_client_secret,
                api_version=acc.google_api_version or 'v25',
                on_token_refreshed=self._save_google_refreshed_token,
            )
            try:
                customers = client.list_accessible_customers()
                self.write({'state': 'connected'})
                self.message_post(body=_('Google Ads connection test successful! Accessible customers: %s') % len(customers))
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
            except GoogleAdsError as e:
                self.state = 'error'
                self.message_post(body=_('Google Ads test failed: %s') % str(e))
                raise UserError(str(e))

    def _save_google_refreshed_token(self, new_token, expires_in):
        self.sudo().write({
            'access_token': new_token,
            'token_expiry': fields.Datetime.now() + timedelta(seconds=expires_in),
        })

    def _ensure_google_token_valid(self):
        """Ensure Google access token is valid, refreshing it if expired or expiring soon."""
        self.ensure_one()
        acc = self.sudo()
        now = fields.Datetime.now()
        is_expired = False
        if not acc.access_token:
            is_expired = True
        elif acc.token_expiry and acc.token_expiry <= now + timedelta(minutes=5):
            is_expired = True
            
        if is_expired and acc.refresh_token and acc.google_client_id and acc.google_client_secret:
            from ..services.google_client import GoogleAdsClient, GoogleAdsError
            client = GoogleAdsClient(
                access_token=acc.access_token,
                developer_token=acc.google_developer_token,
                customer_id=acc.platform_account_id,
                manager_id=acc.google_manager_id,
                refresh_token=acc.refresh_token,
                client_id=acc.google_client_id,
                client_secret=acc.google_client_secret,
                api_version=acc.google_api_version or 'v25',
                on_token_refreshed=self._save_google_refreshed_token,
            )
            try:
                new_token, expires_in = client.refresh_access_token()
                self._save_google_refreshed_token(new_token, expires_in)
                _logger.info("Successfully refreshed Google Ads access token for account %s", self.id)
            except Exception as e:
                _logger.warning("Could not auto-refresh Google access token: %s", str(e))

    def action_sync_campaigns(self):
        self.ensure_one()
        if self.platform == 'meta':
            self._sync_meta_full()
        elif self.platform == 'google':
            self._sync_google_full()

    @api.private
    def _sync_meta_full(self):
        start_time = time.time()
        from ..services.meta_client import MetaAdsClient, MetaApiError
        
        acc = self.sudo()
        client = MetaAdsClient(
            access_token=acc.access_token,
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
            self.message_post(body=f'Meta senkronizasyon hatası: {str(e)}')
            raise UserError(str(e))

    @api.private
    def _sync_google_full(self):
        start_time = time.time()
        self._ensure_google_token_valid()
        from ..services.google_client import GoogleAdsClient, GoogleAdsError
        acc = self.sudo()
        client = GoogleAdsClient(
            access_token=acc.access_token,
            developer_token=acc.google_developer_token,
            customer_id=acc.platform_account_id,
            manager_id=acc.google_manager_id,
            refresh_token=acc.refresh_token,
            client_id=acc.google_client_id,
            client_secret=acc.google_client_secret,
            api_version=acc.google_api_version or 'v25',
            on_token_refreshed=self._save_google_refreshed_token,
        )
        created = updated = 0
        try:
            c, u = self._sync_google_campaigns(client)
            created += c; updated += u
            c, u = self._sync_google_ad_groups(client)
            created += c; updated += u
            c, u = self._sync_google_ads(client)
            created += c; updated += u
            
            duration = time.time() - start_time
            self._create_sync_log('campaigns', 'success', 
                f'Google sync: {created} new, {updated} updated', created, updated, duration)
            self.last_sync_date = fields.Datetime.now()
            self.message_post(body=f'Google Ads senkronize edildi: {created} yeni, {updated} güncellendi.')
        except (GoogleAdsError, Exception) as e:
            duration = time.time() - start_time
            self._create_sync_log('campaigns', 'error', str(e), created, updated, duration)
            self.message_post(body=f'Google Ads senkronizasyon hatası: {str(e)}')
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
    def _sync_google_campaigns(self, client):
        raw_campaigns = client.get_campaigns()
        created = updated = 0
        Campaign = self.env['ads.campaign']
        
        for raw in raw_campaigns:
            normalized = raw  # Google returns already-normalized data
            existing = Campaign.search([
                ('account_id', '=', self.id),
                ('platform_campaign_id', '=', normalized['platform_campaign_id']),
            ], limit=1)
            
            vals = {
                'name': normalized['name'],
                'status': normalized['status'],
                'objective': normalized.get('objective'),
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
    def _sync_google_ad_groups(self, client):
        raw_adsets = client.get_ad_groups()
        created = updated = 0
        Adset = self.env['ads.adset']
        Campaign = self.env['ads.campaign']
        
        for raw in raw_adsets:
            normalized = raw  # already normalized
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
    def _sync_google_ads(self, client):
        raw_ads = client.get_ads()
        created = updated = 0
        Ad = self.env['ads.ad']
        Adset = self.env['ads.adset']
        
        for raw in raw_ads:
            normalized = raw  # already normalized
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
    def _sync_google_metrics(self, client, date_from=None, date_to=None):
        if not date_from:
            date_from = (date.today() - timedelta(days=7)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()
        
        raw_insights = client.get_campaign_metrics(date_from=date_from, date_to=date_to)
        
        Metric = self.env['ads.metric.daily']
        created = updated = 0
        
        for raw in raw_insights:
            normalized = raw  # already normalized
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
                'impressions': normalized.get('impressions', 0),
                'clicks': normalized.get('clicks', 0),
                'spend': normalized.get('spend', 0.0),
                'conversions': normalized.get('conversions', 0.0),
                'conversion_value': normalized.get('conversion_value', 0.0),
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
            self._refresh_google_token()

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
    def _refresh_google_token(self):
        import requests as req_lib
        url = 'https://oauth2.googleapis.com/token'
        data = {
            'client_id': self.google_client_id,
            'client_secret': self.google_client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        resp = req_lib.post(url, data=data)
        token_data = resp.json()
        if 'access_token' in token_data:
            self.sudo().write({
                'access_token': token_data['access_token'],
                'token_expiry': fields.Datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600)),
            })
        else:
            self.state = 'error'
            self.message_post(body=_('Google token refresh failed: %s') % token_data)

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
                        account._sync_google_full()
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
                    elif account.platform == 'google':
                        from ..services.google_client import GoogleAdsClient
                        client = GoogleAdsClient(
                            access_token=account.access_token,
                            developer_token=account.google_developer_token,
                            customer_id=account.platform_account_id,
                            manager_id=account.google_manager_id,
                        )
                        account._sync_google_metrics(client)
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

    @api.model
    def get_dashboard_data(self, period='7d', platform='all', account_id=None, compare=False):
        """
        Comprehensive dashboard analytics aggregation for OWL frontend.
        """
        today = date.today()
        if period == '7d':
            delta_days = 7
            start_date = today - timedelta(days=7)
        elif period == '30d':
            delta_days = 30
            start_date = today - timedelta(days=30)
        elif period == '90d':
            delta_days = 90
            start_date = today - timedelta(days=90)
        elif period == 'mtd':
            start_date = today.replace(day=1)
            delta_days = (today - start_date).days + 1
        elif period == 'ytd':
            start_date = today.replace(month=1, day=1)
            delta_days = (today - start_date).days + 1
        else:
            delta_days = 7
            start_date = today - timedelta(days=7)

        prev_end_date = start_date - timedelta(days=1)
        prev_start_date = prev_end_date - timedelta(days=delta_days)

        base_domain = []
        if platform != 'all':
            base_domain.append(('campaign_id.account_id.platform', '=', platform))
        if account_id:
            base_domain.append(('campaign_id.account_id', '=', int(account_id)))

        curr_domain = base_domain + [('date', '>=', start_date), ('date', '<=', today)]
        prev_domain = base_domain + [('date', '>=', prev_start_date), ('date', '<=', prev_end_date)]

        MetricModel = self.env['ads.metric.daily']

        # 1. Current Period Aggregates
        curr_res = MetricModel._read_group(
            domain=curr_domain,
            groupby=[],
            aggregates=['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum']
        )
        if curr_res and curr_res[0]:
            spend, impressions, clicks, conversions, conv_value = curr_res[0]
            spend = spend or 0.0
            impressions = impressions or 0
            clicks = clicks or 0
            conversions = conversions or 0.0
            conv_value = conv_value or 0.0
        else:
            spend = impressions = clicks = conversions = conv_value = 0.0

        # 2. Previous Period Aggregates for Deltas
        prev_res = MetricModel._read_group(
            domain=prev_domain,
            groupby=[],
            aggregates=['spend:sum', 'impressions:sum', 'clicks:sum', 'conversions:sum', 'conversion_value:sum']
        )
        if prev_res and prev_res[0]:
            p_spend, p_impressions, p_clicks, p_conversions, p_conv_value = prev_res[0]
            p_spend = p_spend or 0.0
            p_clicks = p_clicks or 0
            p_conversions = p_conversions or 0.0
            p_conv_value = p_conv_value or 0.0
        else:
            p_spend = p_clicks = p_conversions = p_conv_value = 0.0

        # Helper for % delta
        def calc_delta(curr, prev):
            if not prev:
                return 100.0 if curr > 0 else 0.0
            return ((curr - prev) / prev) * 100.0

        ctr = (clicks / impressions * 100.0) if impressions else 0.0
        cpc = (spend / clicks) if clicks else 0.0
        cpa = (spend / conversions) if conversions else 0.0
        roas = (conv_value / spend) if spend else 0.0

        p_roas = (p_conv_value / p_spend) if p_spend else 0.0

        # 3. Daily time-series chart data
        chart_groups = MetricModel._read_group(
            domain=curr_domain,
            groupby=['date:day'],
            aggregates=['spend:sum', 'conversion_value:sum', 'clicks:sum', 'conversions:sum'],
            order='date:day asc'
        )
        chart_data = []
        for g in chart_groups:
            chart_data.append({
                'date': str(g[0]),
                'spend': round(g[1] or 0.0, 2),
                'revenue': round(g[2] or 0.0, 2),
                'clicks': g[3] or 0,
                'conversions': round(g[4] or 0.0, 2),
            })

        # 4. Platform Breakdown
        platform_groups = MetricModel._read_group(
            domain=curr_domain,
            groupby=['account_id'],
            aggregates=['spend:sum', 'conversion_value:sum', 'conversions:sum', 'clicks:sum']
        )
        platform_data = {}
        for p_grp in platform_groups:
            acc_rec = p_grp[0]
            p_name = acc_rec.platform if acc_rec else 'unknown'
            p_sp = p_grp[1] or 0.0
            p_rev = p_grp[2] or 0.0
            p_cv = p_grp[3] or 0.0
            p_cl = p_grp[4] or 0
            if p_name not in platform_data:
                platform_data[p_name] = {'spend': 0.0, 'revenue': 0.0, 'conversions': 0.0, 'clicks': 0}
            platform_data[p_name]['spend'] += round(p_sp, 2)
            platform_data[p_name]['revenue'] += round(p_rev, 2)
            platform_data[p_name]['conversions'] += round(p_cv, 2)
            platform_data[p_name]['clicks'] += p_cl
            platform_data[p_name]['roas'] = round(platform_data[p_name]['revenue'] / platform_data[p_name]['spend'], 2) if platform_data[p_name]['spend'] else 0.0

        # 5. Top Campaigns
        camp_domain = []
        if platform != 'all':
            camp_domain.append(('account_id.platform', '=', platform))
        if account_id:
            camp_domain.append(('account_id', '=', int(account_id)))
        
        top_camps = self.env['ads.campaign'].search(camp_domain, order='total_spend desc', limit=8)
        top_campaigns_list = []
        for c in top_camps:
            top_campaigns_list.append({
                'id': c.id,
                'name': c.name,
                'platform': c.platform,
                'status': c.status,
                'approval_status': getattr(c, 'approval_status', 'draft'),
                'daily_budget': c.daily_budget,
                'total_spend': round(c.total_spend, 2),
                'conversions': round(c.total_conversions, 1),
                'avg_roas': round(c.avg_roas, 2),
                'currency': c.currency_id.symbol or '₺',
            })

        # 6. Active Recommendations
        rec_domain = [('status', 'in', ['new', 'in_review'])]
        if platform != 'all':
            rec_domain.append(('campaign_id.account_id.platform', '=', platform))
        if account_id:
            rec_domain.append(('campaign_id.account_id', '=', int(account_id)))

        recs = self.env['ads.recommendation'].search(rec_domain, order='severity_order desc, create_date desc', limit=6)
        recommendations_list = []
        for r in recs:
            recommendations_list.append({
                'id': r.id,
                'name': r.name,
                'campaign_id': r.campaign_id.id,
                'campaign_name': r.campaign_id.name,
                'severity': r.severity,
                'category': r.category,
                'status': r.status,
                'description': r.description or '',
                'proposed_action': r.proposed_action or '',
            })

        # 7. Connected accounts summary
        accounts = self.search([])
        account_summary = {
            'total': len(accounts),
            'connected': len(accounts.filtered(lambda a: a.state == 'connected')),
            'error': len(accounts.filtered(lambda a: a.state == 'error')),
        }

        # 8. Pacing Summary
        active_campaigns = self.env['ads.campaign'].search([('status', '=', 'active')])
        pacing_summary = {
            'total_active': len(active_campaigns),
            'on_track': len(active_campaigns.filtered(lambda c: c.budget_pace_status == 'on_track')),
            'over': len(active_campaigns.filtered(lambda c: c.budget_pace_status == 'over')),
            'under': len(active_campaigns.filtered(lambda c: c.budget_pace_status == 'under')),
        }

        company_currency = self.env.company.currency_id.symbol or '₺'

        return {
            'period': period,
            'platform': platform,
            'account_id': account_id,
            'currency_symbol': company_currency,
            'kpis': {
                'spend': round(spend, 2),
                'spend_delta': round(calc_delta(spend, p_spend), 1),
                'conversion_value': round(conv_value, 2),
                'revenue_delta': round(calc_delta(conv_value, p_conv_value), 1),
                'clicks': clicks,
                'clicks_delta': round(calc_delta(clicks, p_clicks), 1),
                'impressions': impressions,
                'conversions': round(conversions, 1),
                'conversions_delta': round(calc_delta(conversions, p_conversions), 1),
                'ctr': round(ctr, 2),
                'cpc': round(cpc, 2),
                'cpa': round(cpa, 2),
                'roas': round(roas, 2),
                'roas_delta': round(roas - p_roas, 2),
            },
            'charts': chart_data,
            'platform_breakdown': platform_data,
            'top_campaigns': top_campaigns_list,
            'recommendations': recommendations_list,
            'accounts': account_summary,
            'pacing': pacing_summary,
        }

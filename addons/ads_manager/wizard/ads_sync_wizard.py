# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import datetime

class AdsSyncWizard(models.TransientModel):
    _name = 'ads.sync.wizard'
    _description = 'Ads Sync Wizard'

    account_id = fields.Many2one('ads.account', string='Ads Account', required=True,
        domain="[('state', '=', 'connected')]")
    date_from = fields.Date(string='Date From', required=True,
        default=lambda self: fields.Date.today() - datetime.timedelta(days=30))
    date_to = fields.Date(string='Date To', required=True,
        default=fields.Date.today)
    sync_type = fields.Selection([
        ('campaigns', 'Campaigns Only'),
        ('metrics', 'Metrics Only'),
        ('full', 'Full Sync (Campaigns + Metrics)')
    ], string='Sync Type', default='full', required=True)

    def action_sync(self):
        self.ensure_one()
        account = self.account_id.sudo()
        
        try:
            if self.sync_type in ('campaigns', 'full'):
                account.action_sync_campaigns()
            
            if self.sync_type in ('metrics', 'full'):
                if account.platform == 'meta':
                    from ..services.meta_client import MetaAdsClient
                    client = MetaAdsClient(
                        access_token=account.access_token,
                        api_version=account.meta_api_version,
                        account_id=f'act_{account.platform_account_id}',
                        business_id=account.meta_business_id,
                    )
                    account._sync_meta_metrics(
                        client,
                        date_from=self.date_from.isoformat(),
                        date_to=self.date_to.isoformat(),
                    )
                elif account.platform == 'google':
                    from ..services.google_client import GoogleAdsClient
                    client = GoogleAdsClient(
                        access_token=account.access_token,
                        developer_token=account.google_developer_token,
                        customer_id=account.platform_account_id,
                        manager_id=account.google_manager_id,
                    )
                    account._sync_google_metrics(
                        client,
                        date_from=self.date_from.isoformat(),
                        date_to=self.date_to.isoformat(),
                    )
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Successful'),
                    'message': _('Account synchronization completed successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_('Sync failed: %s') % str(e))

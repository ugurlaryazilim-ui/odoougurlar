# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import datetime

class AdsSyncWizard(models.TransientModel):
    _name = 'ads.sync.wizard'
    _description = 'Ads Sync Wizard'

    account_id = fields.Many2one('ads.account', string='Ads Account', required=True)
    date_from = fields.Date(string='Date From', required=True, default=lambda self: fields.Date.today() - datetime.timedelta(days=30))
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.today)
    sync_type = fields.Selection([
        ('campaigns', 'Campaigns Only'),
        ('metrics', 'Metrics Only'),
        ('full', 'Full Sync')
    ], string='Sync Type', default='full', required=True)

    def action_sync(self):
        self.ensure_one()
        try:
            # Assuming account_id has this method
            self.account_id._sync_campaigns_and_metrics(self.date_from, self.date_to, self.sync_type)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Successful'),
                    'message': _('Account synchronization completed.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_('Sync failed: %s') % str(e))

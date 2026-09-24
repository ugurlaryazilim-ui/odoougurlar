# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AdsCampaignRejectWizard(models.TransientModel):
    _name = 'ads.campaign.reject.wizard'
    _description = 'Campaign Rejection Wizard'

    campaign_id = fields.Many2one('ads.campaign', string='Campaign', required=True)
    rejection_reason = fields.Text(string='Rejection Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        if not self.rejection_reason:
            raise UserError(_('Please provide a rejection reason.'))
        self.campaign_id.write({
            'approval_status': 'rejected',
            'rejection_reason': self.rejection_reason,
        })
        self.campaign_id.activity_feedback(['mail.mail_activity_data_todo'])
        self.campaign_id.message_post(
            body=_('Campaign rejected by %s.\nReason: %s') % (
                self.env.user.name, self.rejection_reason
            )
        )
        return {'type': 'ir.actions.act_window_close'}

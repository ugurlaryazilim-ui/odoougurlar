# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AdsBudgetWizard(models.TransientModel):
    _name = 'ads.budget.wizard'
    _description = 'Budget Adjustment Wizard'

    campaign_id = fields.Many2one('ads.campaign', string='Campaign', required=True)
    recommendation_id = fields.Many2one('ads.recommendation', string='Recommendation')
    current_budget = fields.Monetary(string='Current Daily Budget', readonly=True, currency_field='currency_id')
    new_budget = fields.Monetary(string='New Daily Budget', required=True, currency_field='currency_id')
    change_pct = fields.Float(string='Change %', compute='_compute_change_pct')
    currency_id = fields.Many2one('res.currency', related='campaign_id.currency_id')
    reason = fields.Text(string='Reason')
    apply_to_platform = fields.Boolean(string='Apply to Platform', default=True,
        help='If checked, the budget change will be pushed to Meta/Google.')

    @api.depends('current_budget', 'new_budget')
    def _compute_change_pct(self):
        for wiz in self:
            if wiz.current_budget:
                wiz.change_pct = ((wiz.new_budget - wiz.current_budget) / wiz.current_budget) * 100
            else:
                wiz.change_pct = 0.0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'ads.campaign':
            campaign = self.env['ads.campaign'].browse(self.env.context.get('active_id'))
            res['campaign_id'] = campaign.id
            res['current_budget'] = campaign.daily_budget
            res['new_budget'] = campaign.daily_budget
        return res

    def action_apply(self):
        self.ensure_one()
        if self.new_budget < 0:
            raise UserError(_('Budget cannot be negative.'))
        
        old_budget = self.current_budget
        campaign = self.campaign_id
        
        if self.apply_to_platform and campaign.platform_campaign_id:
            campaign.action_adjust_budget(self.new_budget)
        else:
            campaign.write({'daily_budget': self.new_budget})
        
        # If linked to a recommendation, mark as applied
        if self.recommendation_id:
            self.recommendation_id.write({
                'status': 'applied',
                'applied_date': fields.Datetime.now(),
                'applied_by': self.env.user.id,
            })
            self.recommendation_id.message_post(
                body=_('Budget adjustment applied: %.2f → %.2f (%+.1f%%)') % (
                    old_budget, self.new_budget, self.change_pct
                )
            )
        
        campaign.message_post(
            body=_('Bütçe değişikliği: %.2f → %.2f (%+.1f%%)\nSebep: %s') % (
                old_budget, self.new_budget, self.change_pct, self.reason or '-'
            )
        )
        
        return {'type': 'ir.actions.act_window_close'}

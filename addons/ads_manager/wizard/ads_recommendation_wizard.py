# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AdsRecommendationApplyWizard(models.TransientModel):
    _name = 'ads.recommendation.apply.wizard'
    _description = 'Apply Recommendation Wizard'

    recommendation_id = fields.Many2one('ads.recommendation', string='Recommendation', required=True)
    confirm_text = fields.Text(string='Confirmation Details', readonly=True, compute='_compute_confirm_text')
    notes = fields.Text(string='Application Notes')

    @api.depends('recommendation_id')
    def _compute_confirm_text(self):
        for wiz in self:
            if wiz.recommendation_id:
                wiz.confirm_text = f"You are about to apply recommendation for {wiz.recommendation_id.campaign_id.name if wiz.recommendation_id.campaign_id else 'campaign'}:\n{wiz.recommendation_id.description}"
            else:
                wiz.confirm_text = ""

    def action_confirm_apply(self):
        self.ensure_one()
        if self.recommendation_id:
            # Assuming ads.recommendation has a state field or action_apply method
            self.recommendation_id.write({'state': 'applied', 'apply_notes': self.notes})
            self.recommendation_id.action_apply()
        return {'type': 'ir.actions.act_window_close'}

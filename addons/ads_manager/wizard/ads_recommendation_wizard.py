# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AdsRecommendationApplyWizard(models.TransientModel):
    _name = 'ads.recommendation.apply.wizard'
    _description = 'Apply Recommendation Wizard'

    recommendation_id = fields.Many2one('ads.recommendation', string='Recommendation', required=True)
    confirm_text = fields.Text(string='Confirmation', readonly=True, compute='_compute_confirm_text')
    notes = fields.Text(string='Notes')
    auto_apply = fields.Boolean(string='Apply to Platform', default=False,
        help='If checked, will push changes directly to Meta/Google')

    @api.depends('recommendation_id')
    def _compute_confirm_text(self):
        for wiz in self:
            rec = wiz.recommendation_id
            if rec:
                text = f"Öneri: {rec.name}\n"
                text += f"Kampanya: {rec.campaign_id.name}\n"
                text += f"Açıklama: {rec.description or '-'}\n"
                if rec.proposed_action:
                    text += f"\nÖnerilen Aksiyon:\n{rec.proposed_action}"
                wiz.confirm_text = text
            else:
                wiz.confirm_text = ""

    def action_confirm_apply(self):
        self.ensure_one()
        rec = self.recommendation_id
        if not rec:
            raise UserError(_('No recommendation selected.'))
        
        rec.write({
            'status': 'applied',
            'applied_date': fields.Datetime.now(),
            'applied_by': self.env.user.id,
        })
        rec.message_post(
            body=_('Öneri uygulandı.\nNotlar: %s') % (self.notes or '-')
        )
        return {'type': 'ir.actions.act_window_close'}

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IdefixClaimDeclineWizard(models.TransientModel):
    """İade red talebi (claim-decline-request) — Idefix red sebebini inceler."""
    _name = 'idefix.claim.decline.wizard'
    _description = 'Idefix İade Red Talebi'

    refund_ids = fields.Many2many('idefix.refund', string='İade Kalemleri', required=True)
    reason_id = fields.Many2one('idefix.reason', string='Red Sebebi', required=True,
                                domain="[('reason_type', '=', 'claim_decline')]")
    description = fields.Text(string='Açıklama', required=True)
    image_urls = fields.Text(string='Görsel Linkleri', help='Her satıra bir https görsel linki (isteğe bağlı)')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        refund_ids = res.get('refund_ids') or []
        ids = refund_ids[0][2] if refund_ids and isinstance(refund_ids[0], (list, tuple)) else refund_ids
        refunds = self.env['idefix.refund'].browse(ids)
        if refunds:
            self.env['idefix.reason']._ensure(refunds[0].store_id, 'claim_decline')
        return res

    def action_refresh_reasons(self):
        self.ensure_one()
        self.env['idefix.reason']._refresh(self.refund_ids[:1].store_id, 'claim_decline')
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_confirm(self):
        self.ensure_one()
        self.refund_ids._check_actionable()
        images = [u.strip() for u in (self.image_urls or '').splitlines() if u.strip()]
        errors = []
        for (store, claim_id), lines in self.refund_ids._group_by_claim().items():
            claim_lines = [{
                'id': int(line.claim_line_id),
                'claimDeclineReasonId': self.reason_id.idefix_id,
                'description': self.description,
                'images': images,
            } for line in lines]
            res = store.get_api().decline_claim(claim_id, claim_lines)
            if not res.get('success'):
                errors.append(f"{claim_id}: {res.get('error')}")
        self.refund_ids._refetch()
        if errors:
            raise UserError(_("Bazı red talepleri gönderilemedi:\n%s", '\n'.join(errors)))
        return self.env['idefix.order']._notify('İade', f"{len(self.refund_ids)} iade kalemi için red talebi gönderildi.",
                                                'success')

from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_claim_count = fields.Integer(string='İnceleme Kayıtları', compute='_compute_vendor_claim_count')

    def _compute_vendor_claim_count(self):
        counts = dict(self.env['vendor.claim']._read_group(
            [('vendor_id', 'in', self.ids)], ['vendor_id'], ['__count']))
        for partner in self:
            partner.vendor_claim_count = counts.get(partner, 0)

    def action_view_vendor_claims(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Tedarikçi İnceleme Kayıtları'),
            'res_model': 'vendor.claim', 'view_mode': 'list,form,pivot',
            'domain': [('vendor_id', '=', self.id)], 'context': {'default_vendor_id': self.id},
        }

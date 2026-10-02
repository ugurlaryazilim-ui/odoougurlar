import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REASON_TYPES = [
    ('noship', 'Tedarik Edilemedi'),
    ('claim_decline', 'İade Reddi'),
]


class IdefixReason(models.Model):
    """Idefix sebep listeleri (reasons/noship, claim-decline-reasons) — wizard seçimleri için önbellek."""
    _name = 'idefix.reason'
    _description = 'Idefix Sebep'
    _order = 'reason_type, name'

    reason_type = fields.Selection(REASON_TYPES, string='Tür', required=True)
    idefix_id = fields.Integer(string='Idefix ID', required=True)
    name = fields.Char(string='Sebep', required=True)
    description = fields.Char(string='Açıklama')
    active = fields.Boolean(default=True)

    _type_id_uniq = models.Constraint('UNIQUE(reason_type, idefix_id)', 'Bu sebep zaten kayıtlı.')

    @api.model
    def _refresh(self, store, reason_type):
        """Sebep listesini Idefix'ten çekip günceller; listede olmayanlar pasife alınır."""
        api_client = store.get_api()
        if reason_type == 'noship':
            res = api_client.get_noship_reasons()
        else:
            res = api_client.get_claim_decline_reasons()
        if not res.get('success'):
            raise UserError(_("Idefix sebep listesi alınamadı: %s", res.get('error')))
        data = res.get('data')
        if isinstance(data, dict):
            data = data.get('items') or data.get('data') or []
        existing = {r.idefix_id: r for r in self.with_context(active_test=False).search(
            [('reason_type', '=', reason_type)])}
        seen = set()
        for item in data or []:
            if not isinstance(item, dict) or not item.get('id') or item.get('deletedAt'):
                continue
            rid = int(item['id'])
            seen.add(rid)
            vals = {'name': item.get('name') or str(rid), 'description': item.get('description') or False,
                    'active': True}
            if rid in existing:
                existing[rid].write(vals)
            else:
                self.create(dict(vals, reason_type=reason_type, idefix_id=rid))
        stale = [r.id for rid, r in existing.items() if rid not in seen and r.active]
        if stale:
            self.browse(stale).write({'active': False})
        return len(seen)

    @api.model
    def _ensure(self, store, reason_type):
        if not self.search_count([('reason_type', '=', reason_type)]):
            self._refresh(store, reason_type)

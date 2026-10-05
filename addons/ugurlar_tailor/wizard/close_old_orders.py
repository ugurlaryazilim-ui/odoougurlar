from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class TailorCloseOldOrders(models.TransientModel):
    """Durumu güncellenmeden kalmış eski siparişleri toplu kapat (yalnız terzi yöneticisi)."""
    _name = 'ugurlar.tailor.close.old.wizard'
    _description = 'Terzi: Eski Siparişleri Kapat'

    days = fields.Integer(string='Kaç günden eski', default=30, required=True)
    from_states = fields.Selection([
        ('pending', 'Bekliyor'),
        ('pending_progress', 'Bekliyor + Terzide'),
        ('all_open', 'Bekliyor + Terzide + Hazır'),
    ], string='Hangi durumdakiler', default='pending', required=True)
    target_state = fields.Selection([
        ('delivered', 'Teslim Edildi'),
        ('cancelled', 'İptal Edildi'),
    ], string='Yeni durum', default='delivered', required=True)
    order_count = fields.Integer(string='Etkilenecek sipariş', compute='_compute_order_count')

    def _states(self):
        return {
            'pending': ('pending',),
            'pending_progress': ('pending', 'in_progress'),
            'all_open': ('pending', 'in_progress', 'completed'),
        }[self.from_states]

    def _domain(self):
        limit = fields.Datetime.now() - timedelta(days=max(self.days, 1))
        return [('state', 'in', self._states()), ('create_date', '<', limit)]

    @api.depends('days', 'from_states')
    def _compute_order_count(self):
        for wiz in self:
            wiz.order_count = self.env['ugurlar.tailor.order'].search_count(wiz._domain()) if wiz.days else 0

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('ugurlar_tailor.group_tailor_manager'):
            raise UserError(_('Bu işlemi yalnız terzi yöneticisi yapabilir.'))
        if self.days < 7:
            raise UserError(_('En az 7 günden eski siparişler kapatılabilir.'))
        orders = self.env['ugurlar.tailor.order'].search(self._domain())
        now = fields.Datetime.now()
        vals = {'state': self.target_state}
        vals['delivered_at' if self.target_state == 'delivered' else 'cancelled_at'] = now
        # Geçiş kontrolü yönetici için zaten serbest; toplu yazımda tek tek iz bırak
        orders.with_context(tailor_state_ok=True, tracking_disable=True).write(vals)
        label = dict(self._fields['target_state'].selection)[self.target_state]
        for order in orders:
            order.message_post(body=_('Eski sipariş toplu kapatıldı → %s (%s)') % (label, self.env.user.name))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Tamamlandı'), 'type': 'success',
                       'message': _('%s sipariş "%s" yapıldı.') % (len(orders), label),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }

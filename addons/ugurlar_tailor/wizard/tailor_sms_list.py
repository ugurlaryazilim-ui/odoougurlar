from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class TailorSmsListWizard(models.TransientModel):
    """Terzi müşterilerinin cep numaralarını SMS rehberine / listesine aktar.

    Sipariş listesinden seçilerek açılırsa seçili siparişler, menüden açılırsa tarih aralığı kullanılır.
    """
    _name = 'ugurlar.tailor.sms.list.wizard'
    _description = 'Terzi Müşterilerini SMS Listesine Aktar'

    date_from = fields.Date(string='Başlangıç')
    date_to = fields.Date(string='Bitiş')
    include_cancelled = fields.Boolean(string='İptal edilenler dahil')
    list_id = fields.Many2one('sms.system.list', string='Liste')
    new_list_name = fields.Char(string='ya da Yeni Liste', default=lambda self: _('Terzi Müşterileri'))
    from_selection = fields.Boolean(compute='_compute_counts')
    order_count = fields.Integer(string='Sipariş', compute='_compute_counts')
    number_count = fields.Integer(string='Cep numarası olan sipariş', compute='_compute_counts')

    def _orders(self):
        self.ensure_one()
        Order = self.env['ugurlar.tailor.order']
        ctx = self.env.context
        if ctx.get('active_model') == Order._name and ctx.get('active_ids'):
            return Order.browse(ctx['active_ids'])
        domain = []
        if self.date_from:
            domain.append(('create_date', '>=', fields.Datetime.to_datetime(self.date_from)))
        if self.date_to:
            domain.append(('create_date', '<', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)))
        if not self.include_cancelled:
            domain.append(('state', '!=', 'cancelled'))
        return Order.search(domain)

    @api.depends('date_from', 'date_to', 'include_cancelled')
    @api.depends_context('active_ids')
    def _compute_counts(self):
        for wiz in self:
            orders = wiz._orders()
            ctx = self.env.context
            wiz.from_selection = ctx.get('active_model') == 'ugurlar.tailor.order' and bool(ctx.get('active_ids'))
            wiz.order_count = len(orders)
            wiz.number_count = len(orders.filtered('customer_mobile'))

    def action_export(self):
        self.ensure_one()
        if not self.list_id and not (self.new_list_name or '').strip():
            raise UserError(_('Bir liste seçin ya da yeni liste adı yazın.'))
        orders = self._orders().filtered('customer_mobile').sorted('id', reverse=True)
        if not orders:
            raise UserError(_('Seçilen siparişlerde cep telefonu yok.'))
        lst = self.list_id or self.env['sms.system.list'].create({'name': self.new_list_name.strip()})
        # En yeni sipariş önce: aynı numaranın adı/kodu son siparişten gelir
        rows = [{'mobile': o.customer_mobile, 'name': o.customer_name, 'customer_code': o.customer_phone}
                for o in orders]
        res = self.env['sms.system.contact'].upsert_numbers(rows, 'tailor', lists=lst)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': lst.name, 'type': 'success', 'sticky': bool(res['invalid']),
                'message': _('%(c)s yeni, %(u)s mevcut numara listeye eklendi (%(d)s tekrar, %(i)s geçersiz numara).',
                             c=res['created'], u=res['updated'], d=res['duplicate'], i=len(res['invalid'])),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

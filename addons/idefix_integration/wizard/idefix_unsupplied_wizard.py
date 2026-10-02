from odoo import _, api, fields, models
from odoo.exceptions import UserError


class IdefixUnsuppliedWizard(models.TransientModel):
    """Tedarik Edilemedi bildirimi (unsupplied). Seçilen kalemler iptal olur; sevkiyatta kalan ürünler
    Idefix'te aynı sipariş numarasıyla yeni bir sevkiyat olarak oluşur."""
    _name = 'idefix.unsupplied.wizard'
    _description = 'Idefix Tedarik Edilemedi Bildirimi'

    idefix_order_id = fields.Many2one('idefix.order', string='Sevkiyat', required=True, readonly=True)
    line_ids = fields.Many2many('idefix.order.line', string='Tedarik Edilemeyen Kalemler',
                                domain="[('order_id', '=', idefix_order_id)]")
    reason_id = fields.Many2one('idefix.reason', string='Sebep', required=True,
                                domain="[('reason_type', '=', 'noship')]")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['idefix.order'].browse(res.get('idefix_order_id'))
        if order:
            self.env['idefix.reason']._ensure(order.store_id, 'noship')
            if 'line_ids' in fields_list:
                res['line_ids'] = [(6, 0, order._active_lines().ids)]
        return res

    def action_refresh_reasons(self):
        self.ensure_one()
        self.env['idefix.reason']._refresh(self.idefix_order_id.store_id, 'noship')
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_confirm(self):
        self.ensure_one()
        order = self.idefix_order_id
        if not self.line_ids:
            raise UserError(_('En az bir kalem seçin.'))
        store = order.store_id
        api_client = store.get_api()
        items = [{'id': int(line.item_id), 'reasonId': self.reason_id.idefix_id} for line in self.line_ids]
        res = api_client.mark_unsupplied(order.order_id, items)
        if not res.get('success'):
            raise UserError(_("Idefix tedarik edilemedi bildirimi başarısız:\n%s", res.get('error')))
        record = order.sale_order_id or order
        record.message_post(body=(
            f"Idefix'e tedarik edilemedi bildirildi ({self.reason_id.name}): "
            + ', '.join(self.line_ids.mapped(lambda l: l.product_code or l.item_id))))
        # Güncel sevkiyatları çek: eski sevkiyat kapanır (Odoo siparişi iptal), kalanlar yeni sevkiyat olur
        Order = self.env['idefix.order']
        orders, error = Order._fetch_orders(api_client, order_number=order.order_number)
        for order_json in orders:
            if str(order_json.get('orderNumber') or '') == order.order_number:
                Order._sync_order_json(store, order_json, api_client)
        msg = "Tedarik edilemedi bildirildi."
        if error:
            msg += f" Güncel sevkiyatlar çekilemedi ({error}); sonraki senkronda güncellenecek."
        return Order._notify('Tedarik Edilemedi', msg, 'warning' if error else 'success')

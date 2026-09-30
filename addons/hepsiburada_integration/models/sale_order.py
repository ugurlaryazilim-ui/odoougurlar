from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    hb_order_id = fields.Many2one('hepsiburada.order', string='Hepsiburada Siparişi', copy=False, help="İlişkili Hepsiburada Siparişi")
    hb_store_id = fields.Char(string='Hepsiburada Mağaza ID', copy=False, help="Hangi mağaza hesabına bağlı olduğu bilgisi")

    def action_confirm(self):
        res = super().action_confirm()
        # Eksik ürün / onay hatası uyarısı: sipariş elle onaylanınca kalkar
        hb_orders = self.filtered(lambda o: o.hb_order_id and o.state == 'sale').mapped('hb_order_id')
        hb_orders = hb_orders.filtered(lambda h: h.warning_message and h.sale_order_id.state == 'sale')
        if hb_orders:
            hb_orders.sudo().write({'warning_message': False})
        return res

import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class UgurlarTailorOrderLine(models.Model):
    """Terzi sipariş satırı — sipariş başına seçilen hizmetler."""
    _name = 'ugurlar.tailor.order.line'
    _description = 'Terzi Sipariş Satırı'

    order_id = fields.Many2one(
        'ugurlar.tailor.order', string='Sipariş',
        required=True, ondelete='cascade', index=True,
    )
    service_id = fields.Many2one(
        'ugurlar.tailor.service', string='Hizmet',
        required=True, ondelete='restrict',
    )
    service_name = fields.Char(
        string='Hizmet Adı',
        related='service_id.name', store=True,
    )
    price = fields.Float(string='Terzi Fiyatı', digits=(10, 2), required=True)
    measure = fields.Char(string='Ölçü / Not', help='Ör. 3 cm kısalt')

    @api.model
    def _get_service_price(self, tailor, service):
        """Terziye özel fiyat, yoksa hizmetin varsayılan fiyatı."""
        if tailor:
            special = self.env['ugurlar.tailor.price'].search(
                [('tailor_id', '=', tailor.id), ('service_id', '=', service.id)], limit=1)
            if special:
                return special.price
        return service.price

    def _can_set_price(self):
        return self.env.su or self.env.user.has_group('ugurlar_tailor.group_tailor_manager')

    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.price = self._get_service_price(self.order_id.tailor_id, self.service_id)

    @api.model_create_multi
    def create(self, vals_list):
        # Fiyatı yalnız terzi yöneticisi elle belirleyebilir; diğerlerinde tanımlı fiyat yazılır
        if not self._can_set_price():
            for vals in vals_list:
                order = self.env['ugurlar.tailor.order'].browse(vals.get('order_id'))
                service = self.env['ugurlar.tailor.service'].browse(vals.get('service_id'))
                if service:
                    vals['price'] = self._get_service_price(order.tailor_id, service)
        return super().create(vals_list)

    def write(self, vals):
        if not self._can_set_price() and ('price' in vals or 'service_id' in vals):
            vals = dict(vals)
            vals.pop('price', None)
            res = super().write(vals)
            for line in self:
                line_price = self._get_service_price(line.order_id.tailor_id, line.service_id)
                if line.price != line_price:
                    super(UgurlarTailorOrderLine, line).write({'price': line_price})
            return res
        return super().write(vals)

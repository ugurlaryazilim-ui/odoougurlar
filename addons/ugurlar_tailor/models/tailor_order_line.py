import logging

from odoo import models, fields

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
    price = fields.Float(string='Fiyat', digits=(10, 2), required=True)

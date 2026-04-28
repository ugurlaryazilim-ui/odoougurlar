import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class UgurlarTailor(models.Model):
    """Terzi tanımları — dış atölye veya kişi."""
    _name = 'ugurlar.tailor'
    _description = 'Terzi'
    _order = 'name'

    name = fields.Char(string='Terzi Adı', required=True, tracking=True)
    phone = fields.Char(string='Telefon')
    active = fields.Boolean(string='Aktif', default=True, tracking=True)
    note = fields.Text(string='Not')

    price_ids = fields.One2many(
        'ugurlar.tailor.price', 'tailor_id',
        string='Özel Fiyatlar',
    )
    order_ids = fields.One2many(
        'ugurlar.tailor.order', 'tailor_id',
        string='Siparişler',
    )
    order_count = fields.Integer(
        string='Sipariş Sayısı',
        compute='_compute_order_count',
    )

    @api.depends('order_ids')
    def _compute_order_count(self):
        for rec in self:
            rec.order_count = len(rec.order_ids)

    _unique_name = models.Constraint(
        'UNIQUE(name)',
        'Bu isimde bir terzi zaten mevcut!',
    )

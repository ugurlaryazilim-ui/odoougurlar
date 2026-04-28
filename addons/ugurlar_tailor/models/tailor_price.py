import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class UgurlarTailorPrice(models.Model):
    """Terziye özel fiyat matrisi — terzi×hizmet = özel fiyat."""
    _name = 'ugurlar.tailor.price'
    _description = 'Terziye Özel Fiyat'

    tailor_id = fields.Many2one(
        'ugurlar.tailor', string='Terzi',
        required=True, ondelete='cascade', index=True,
    )
    service_id = fields.Many2one(
        'ugurlar.tailor.service', string='Hizmet',
        required=True, ondelete='cascade', index=True,
    )
    price = fields.Float(string='Özel Fiyat', digits=(10, 2), required=True)

    _unique_tailor_service = models.Constraint(
        'UNIQUE(tailor_id, service_id)',
        'Bu terzi-hizmet kombinasyonu zaten mevcut!',
    )

import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class UgurlarTailorService(models.Model):
    """Terzi hizmet tanımları — Paça Kısaltma, Bel Daraltma vb."""
    _name = 'ugurlar.tailor.service'
    _description = 'Terzi Hizmeti'
    _order = 'sequence, name'

    name = fields.Char(string='Hizmet Adı', required=True)
    price = fields.Float(string='Terzi Fiyatı', digits=(10, 2), required=True, default=0.0,
                         help='Terziye ödenen varsayılan tutar (terziye özel fiyat yoksa)')
    customer_price = fields.Float(string='Müşteri Ücreti', digits=(10, 2), default=0.0,
                                  help='Müşteriden alınan varsayılan ücret; 0 = ücretsiz')
    active = fields.Boolean(string='Aktif', default=True)
    sequence = fields.Integer(string='Sıra', default=10)

    _unique_name = models.Constraint(
        'UNIQUE(name)',
        'Bu isimde bir hizmet zaten mevcut!',
    )

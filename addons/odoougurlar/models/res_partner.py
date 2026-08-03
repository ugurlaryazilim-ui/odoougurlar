import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    nebim_customer_code = fields.Char(
        string='Nebim Cari Kodu',
        index=True,
        copy=False,
        help='Nebim V3 sistemindeki Cari Kodu (CurrAccCode)',
    )
    nebim_customer_sent = fields.Boolean(
        string='Nebim Cari Açıldı',
        default=False,
        copy=False,
        help='Bu cari Nebim ile senkronize edildi mi?',
    )
    nebim_address_id = fields.Char(
        string='Nebim Adres ID',
        copy=False,
        help='Nebim PostalAddress ID',
    )

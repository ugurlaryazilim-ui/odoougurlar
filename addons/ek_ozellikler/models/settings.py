import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    #  Ek Özellikler — Ayarlar
    # ------------------------------------------------------------------
    module_ek_ozellikler = fields.Boolean(
        string='Ek Özellikler',
        default=True,
    )

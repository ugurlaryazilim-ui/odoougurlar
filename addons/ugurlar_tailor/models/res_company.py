import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)

class ResCompany(models.Model):
    _inherit = 'res.company'

    reyon_manager_ids = fields.Many2many(
        'res.users',
        'company_reyon_manager_rel',
        'company_id',
        'user_id',
        string='Reyon Yöneticileri'
    )

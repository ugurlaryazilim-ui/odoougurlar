from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    pq_notification_user_ids = fields.Many2many(
        'res.users',
        'company_pq_notification_user_rel',
        'company_id',
        'user_id',
        string='Müşteri Temsilcileri',
        help='Yeni pazaryeri sorusu geldiğinde bildirim alacak kullanıcılar',
    )

# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _cargo_carrier_domain(records):
    """Varsayılan firma yalnız yönetilen (kargo çekirdeğinin sürdüğü) firmalardan seçilir."""
    types = records.env['delivery.carrier']._cargo_managed_types()
    return [('delivery_type', 'in', types)]


class ResCompany(models.Model):
    _inherit = 'res.company'

    # NEDEN: ayarlar ir.config_parameter'da değil şirket alanlarında tutulur: şirket başına
    # değer doğal olur ve 0/False değerini parametre silme tuzağı (K-8) oluşmaz.
    cargo_default_carrier_id = fields.Many2one(
        'delivery.carrier', string='Varsayılan kargo firması', domain=_cargo_carrier_domain,
        help='Gönderide firma seçilmezse kullanılır.')
    cargo_default_weight = fields.Float(
        string='Varsayılan paket ağırlığı (kg)', default=1.0,
        help='Gönderide ağırlık verilmezse paket başına kullanılır.')
    cargo_cod_max_amount = fields.Monetary(
        string='Kapıda ödeme üst sınırı', currency_field='currency_id', default=0.0,
        help='0 = sınırsız.')
    cargo_label_size = fields.Selection(
        [('10x15', '10x15 cm termal'), ('a4', 'A4')], string='Etiket sayfası', default='10x15', required=True)

    @api.constrains('cargo_default_weight', 'cargo_cod_max_amount')
    def _check_cargo_company_values(self):
        for company in self:
            if company.cargo_default_weight <= 0:
                raise ValidationError(_('Varsayılan paket ağırlığı sıfırdan büyük olmalıdır.'))
            if company.cargo_cod_max_amount < 0:
                raise ValidationError(_('Kapıda ödeme üst sınırı negatif olamaz (0 = sınırsız).'))

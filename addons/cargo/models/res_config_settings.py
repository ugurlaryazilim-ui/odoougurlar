# -*- coding: utf-8 -*-
"""Kargo ayarları. Bu ekranda HİÇ sır yoktur (sağlayıcı kimlikleri firma kaydındadır).

NEDEN: alanlar ``related=company_id.*`` DEĞİL, açık ``get_values``/``set_values`` ile
okunur/yazılır. ``res.config.settings`` üzerindeki ``related`` + ``readonly=False`` alanlar
kayıt OLUŞTURULURKEN şirkete yazılır; bu, ``set_values``'taki sistem yöneticisi denetimini
(aşağıda) atlatırdı (DERSLER: set_values RPC'ye açıktır).
"""
from odoo import api, fields, models
from odoo.exceptions import AccessError

from .res_company import _cargo_carrier_domain

# Ayar alanı adı = şirket alanı adı
_CARGO_FIELDS = ('cargo_default_carrier_id', 'cargo_default_weight', 'cargo_cod_max_amount', 'cargo_label_size')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cargo_default_carrier_id = fields.Many2one(
        'delivery.carrier', string='Varsayılan kargo firması', domain=_cargo_carrier_domain)
    cargo_default_weight = fields.Float(string='Varsayılan paket ağırlığı (kg)', default=1.0)
    cargo_cod_max_amount = fields.Monetary(
        string='Kapıda ödeme üst sınırı', currency_field='cargo_currency_id',
        help='0 = sınırsız.')
    cargo_label_size = fields.Selection(
        [('10x15', '10x15 cm termal'), ('a4', 'A4')], string='Etiket sayfası', default='10x15')
    cargo_currency_id = fields.Many2one(
        'res.currency', compute='_compute_cargo_currency_id', string='Kargo para birimi')

    def _compute_cargo_currency_id(self):
        for settings in self:
            settings.cargo_currency_id = self.env.company.currency_id

    @api.model
    def get_values(self):
        res = super().get_values()
        company = self.env.company
        res.update(
            cargo_default_carrier_id=company.cargo_default_carrier_id.id,
            cargo_default_weight=company.cargo_default_weight,
            cargo_cod_max_amount=company.cargo_cod_max_amount,
            cargo_label_size=company.cargo_label_size,
        )
        return res

    def set_values(self):
        # DIKKAT: çekirdek set_values yönetici denetimini yalnız execute()'ta yapar ve RPC'ye
        # açıktır; denetim super()'den ve HER yazmadan ÖNCE yapılmalı (DERSLER, sanal_pos G-2).
        if not self.env.is_superuser() and not self.env.user.has_group('base.group_system'):
            raise AccessError('Ayarları yalnız sistem yöneticisi değiştirebilir.')
        super().set_values()
        company = self.env.company
        for settings in self:
            company.write({name: settings[name] for name in _CARGO_FIELDS})

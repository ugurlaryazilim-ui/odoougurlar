# -*- coding: utf-8 -*-
"""Bağlantı testi sonuç penceresi (yalnız gösterim; ayar ekranındaki düğme oluşturur)."""
from odoo import fields, models


class SanalPosConnectionTestWizard(models.TransientModel):
    _name = 'sanal.pos.connection.test.wizard'
    _description = 'Sanal POS Bağlantı Testi Sonucu'

    level = fields.Selection(
        [('success', 'Başarılı'), ('warning', 'Uyarılı'), ('danger', 'Başarısız')],
        string='Sonuç', readonly=True)
    summary = fields.Char(string='Özet', readonly=True)
    details = fields.Html(string='Ayrıntılar', readonly=True, sanitize=True)

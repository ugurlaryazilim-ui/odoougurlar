# -*- coding: utf-8 -*-
"""Belirsiz gönderiyi "kargo firmasında yok" olarak kapatma sihirbazı (KARARLAR K-28)."""
from odoo import fields, models


class CargoShipmentMissingWizard(models.TransientModel):
    _name = 'cargo.shipment.missing.wizard'
    _description = 'Kargo gönderisi: kargo firmasında yok'

    shipment_id = fields.Many2one('cargo.shipment', string='Gönderi', required=True, readonly=True, ondelete='cascade')
    carrier_id = fields.Many2one(related='shipment_id.carrier_id', string='Kargo firması')
    reason = fields.Text(string='Gerekçe', required=True,
                         help='Kargo firmasının panelinde nasıl kontrol ettiğinizi yazın (tarih, aranan referans).')

    def action_confirm(self):
        self.ensure_one()
        # NEDEN: yetki, kilit, durum ve gerekçe denetimi modeldedir; sihirbaz yalnız arayüzdür.
        self.shipment_id._cargo_mark_missing(self.reason)
        return {'type': 'ir.actions.act_window_close'}

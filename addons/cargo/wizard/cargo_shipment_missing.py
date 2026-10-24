# -*- coding: utf-8 -*-
"""Belirsiz gönderiyi elle kapatma sihirbazı: "kargo firmasında yok" (K-28) ve "kargo firmasında iptal edildi" (K-29)."""
from odoo import fields, models


class CargoShipmentMissingWizard(models.TransientModel):
    _name = 'cargo.shipment.missing.wizard'
    _description = 'Kargo gönderisi: elle kapatma'

    shipment_id = fields.Many2one('cargo.shipment', string='Gönderi', required=True, readonly=True, ondelete='cascade')
    carrier_id = fields.Many2one(related='shipment_id.carrier_id', string='Kargo firması')
    # NEDEN: iki eylem aynı ön koşulu (yönetici, gerekçe, kilit, 15 dk) paylaşır; mod yalnız hangi model metodunun
    # çağrılacağını seçer, yetki/durum denetimi metottadır (sahte mod yetki vermez).
    mode = fields.Selection([('missing', 'Kargo firmasında yok'), ('cancelled', 'Kargo firmasında iptal edildi')],
                            string='İşlem', required=True, default='missing', readonly=True)
    reason = fields.Text(string='Gerekçe', required=True,
                         help='Kargo firmasının panelinde nasıl kontrol ettiğinizi yazın (tarih, aranan referans).')

    def action_confirm(self):
        self.ensure_one()
        # NEDEN: yetki, kilit, durum, yaş ve gerekçe denetimi modeldedir; sihirbaz yalnız arayüzdür.
        if self.mode == 'cancelled':
            self.shipment_id._cargo_mark_cancelled(self.reason)
        else:
            self.shipment_id._cargo_mark_missing(self.reason)
        return {'type': 'ir.actions.act_window_close'}

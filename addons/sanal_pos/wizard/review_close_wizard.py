# -*- coding: utf-8 -*-
"""İncelemeyi kapat sihirbazı (G8, Risk 3): yönetici kapatma notunu zorunlu girer.

Not chatter'a yazılır; kayıt 'Hata' olur ve fatura yeni linke açılır. Yetki ve durum
kontrolleri ``sanal.pos.payment._review_close`` içinde yeniden yapılır.
"""
from odoo import fields, models


class SanalPosPaymentReviewCloseWizard(models.TransientModel):
    _name = 'sanal.pos.payment.review.close.wizard'
    _description = 'Sanal POS İncelemeyi Kapat'

    payment_id = fields.Many2one('sanal.pos.payment', string='Ödeme Talebi', required=True,
                                 readonly=True, ondelete='cascade')
    reason = fields.Text(string='Kapatma Notu', required=True,
                         help='Neden kapatıldığı (ör. Paratika panelinde tahsilat yok). '
                              'Chatter\'a yazılır.')

    def action_confirm(self):
        self.ensure_one()
        return self.payment_id._review_close(self.reason)

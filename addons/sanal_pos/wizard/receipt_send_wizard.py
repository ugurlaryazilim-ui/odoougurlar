# -*- coding: utf-8 -*-
"""Dekontu elle (yeniden) gönder sihirbazı (Aşama 4, KK-4.4).

Sihirbaz yalnız adresi toplar. Yetki, ``paid`` + mail order denetimi, e-posta doğrulaması, kilit ve
gönderim ``sanal.pos.payment._send_receipt_manual`` içindedir. E-posta adresi PII'dir: sihirbaz
kaydı yalnız oluşturanın okuyabildiği ``create_uid`` kuralıyla korunur (security/sanal_pos_security.xml).
"""
from odoo import api, fields, models


class SanalPosReceiptSendWizard(models.TransientModel):
    _name = 'sanal.pos.receipt.send.wizard'
    _description = 'Sanal POS Dekontu Gönder'

    payment_id = fields.Many2one('sanal.pos.payment', string='Ödeme Talebi', required=True,
                                 readonly=True, ondelete='cascade')
    # NEDEN: DB düzeyinde required DEĞİL (görünümde zorunlu): boş adres sunucuda anlamlı UserError verir
    email = fields.Char(string='Gönderilecek e-posta')
    record_email = fields.Char(related='payment_id.customer_email', string='Kayıttaki e-posta',
                               readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Adres varsayılanı kayıttaki müşteri e-postasıdır (boşsa boş kalır)."""
        values = super().default_get(fields_list)
        payment = self.env['sanal.pos.payment'].browse(values.get('payment_id') or 0).exists()
        if payment and 'email' in fields_list:
            values.setdefault('email', payment.customer_email or False)
        return values

    def action_send(self):
        self.ensure_one()
        return self.payment_id._send_receipt_manual(self.email)

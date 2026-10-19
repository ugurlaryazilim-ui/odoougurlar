# -*- coding: utf-8 -*-
"""Linki yeniden gönder sihirbazı (G10, KK-31): kanal seçimi.

Yetki, durum, kilit ve Paratika çağrısı ``sanal.pos.payment.action_resend`` içinde yapılır;
sihirbaz yalnız kanalları toplar.
"""
from odoo import api, fields, models


class SanalPosPaymentResendWizard(models.TransientModel):
    _name = 'sanal.pos.payment.resend.wizard'
    _description = 'Sanal POS Linki Yeniden Gönder'

    payment_id = fields.Many2one('sanal.pos.payment', string='Ödeme Talebi', required=True,
                                 readonly=True, ondelete='cascade')
    channel_sms = fields.Boolean(string='SMS ile gönder')
    channel_email = fields.Boolean(string='E-posta ile gönder')
    is_test = fields.Boolean(string='Test ortamı', compute='_compute_is_test')
    customer_phone = fields.Char(related='payment_id.customer_phone', string='Telefon',
                                 readonly=True)
    customer_email = fields.Char(related='payment_id.customer_email', string='Müşteri e-postası',
                                 readonly=True)

    @api.depends('payment_id.environment')
    def _compute_is_test(self):
        for wiz in self:
            wiz.is_test = wiz.payment_id.environment == 'test'

    @api.model
    def default_get(self, fields_list):
        """Kanal seçimleri kaydın ilk gönderim tercihinden gelir."""
        values = super().default_get(fields_list)
        payment = self.env['sanal.pos.payment'].browse(values.get('payment_id') or 0).exists()
        if payment:
            values.setdefault('channel_sms', payment.channel_sms)
            values.setdefault('channel_email', payment.channel_email)
        return values

    def action_confirm(self):
        self.ensure_one()
        channels = [name for name, selected in (
            ('sms', self.channel_sms), ('email', self.channel_email)) if selected]
        return self.payment_id.action_resend(channels)

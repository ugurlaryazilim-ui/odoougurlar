# -*- coding: utf-8 -*-
"""İptal / iade onay sihirbazı (G11, KK-50, KK-52). Yalnız Sanal POS Yöneticisi (ACL).

Sihirbaz kendi kuralını yazmaz: doğrulamanın tek kaynağı ``sanal.pos.payment``
(``action_void`` / ``action_refund``). Oluşturmak Paratika'ya istek göndermez.
``amount`` bilerek Float (digits'siz): Monetary alan para birimine yuvarlar ve 10,005
gibi girişleri sessizce 10,01 yapardı; 2'den fazla ondalık modelde reddedilir.
"""
from odoo import api, fields, models

from ..tools import format_try


class SanalPosPaymentRefundWizard(models.TransientModel):
    _name = 'sanal.pos.payment.refund.wizard'
    _description = 'Sanal POS İptal/İade Onayı'

    payment_id = fields.Many2one('sanal.pos.payment', string='Ödeme Talebi', required=True,
                                 readonly=True, ondelete='cascade')
    kind = fields.Selection([('refund', 'İade'), ('void', 'Ödeme İptali')], string='İşlem',
                            required=True, default='refund')
    currency_id = fields.Many2one(related='payment_id.currency_id')
    paid_amount = fields.Monetary(related='payment_id.paid_amount', string='Ödenen Tutar',
                                  currency_field='currency_id')
    refundable_amount = fields.Monetary(related='payment_id.refundable_amount',
                                        string='İade Edilebilir', currency_field='currency_id')
    amount = fields.Float(string='Tutar', compute='_compute_amount', store=True, readonly=False,
                          help='İptalde ödenen tutarın tamamı; iadede en çok iade edilebilir tutar.')
    # Zorunluluk modelde (en az 5 karakter); DB'de NOT NULL değil ki varsayılanla açılabilsin
    reason = fields.Char(string='Neden')
    summary = fields.Char(string='Özet', compute='_compute_summary')
    is_test = fields.Boolean(related='payment_id.is_test', string='Test ortamı')

    @api.depends('payment_id', 'kind')
    def _compute_amount(self):
        for wiz in self:
            payment = wiz.payment_id
            if wiz.kind == 'void':
                wiz.amount = payment.paid_amount or 0.0
            else:
                wiz.amount = max(payment.refundable_amount or 0.0, 0.0)

    @api.depends('payment_id', 'kind', 'amount')
    def _compute_summary(self):
        for wiz in self:
            payment = wiz.payment_id
            if wiz.kind == 'void':
                head, amount = 'Ödeme iptali', payment.paid_amount
            else:
                head, amount = 'İade', wiz.amount
            wiz.summary = ' · '.join([head, payment.invoice_no or '', payment.customer_name or '',
                                      format_try(amount or 0)])

    def action_confirm(self):
        self.ensure_one()
        if self.kind == 'void':
            return self.payment_id.action_void(self.reason)
        return self.payment_id.action_refund(self.amount, self.reason)

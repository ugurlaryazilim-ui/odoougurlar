# -*- coding: utf-8 -*-
"""Dekont e-postasının kuyruk sonucunu ödeme kaydına yansıtır (Aşama 4 düzeltme, B-C / Ö-3).

Elle gönderim e-postayı kuyruğa alıp ``Gönderildi`` yazar; SMTP sonradan reddederse kayıt bunu
ancak buradan öğrenir.
"""
from odoo import models

from .sanal_pos_payment import RECEIPT_MAIL_DOMAIN


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _postprocess_sent_message(self, success_pids, success_emails, failure_reason=False, failure_type=None):
        # DIKKAT: super() auto_delete kaydı (başarıda ve geçersiz adreste) SİLER; sonuç ondan ÖNCE okunur.
        receipts = self.filtered_domain(RECEIPT_MAIL_DOMAIN)
        if receipts:
            self.env['sanal.pos.payment']._receipt_mails_processed(receipts)
        return super()._postprocess_sent_message(
            success_pids, success_emails, failure_reason=failure_reason, failure_type=failure_type)

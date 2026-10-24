# -*- coding: utf-8 -*-
"""Dekont e-postasının kuyruk sonucunu ödeme kaydına yansıtır (Aşama 4 düzeltme, B-C / Ö-3).

Elle gönderim e-postayı kuyruğa alıp ``Gönderildi`` yazar; SMTP sonradan reddederse kayıt bunu
ancak buradan öğrenir. Hangi e-postanın dekont olduğu ``sanal.pos.payment.receipt_mail_id`` ile
belirlenir (G4-7); model/res_id tek başına yetmez.
"""
from odoo import models


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _postprocess_sent_message(self, success_pids, success_emails, failure_reason=False, failure_type=None):
        # DIKKAT: super() auto_delete kaydı (başarıda ve geçersiz adreste) SİLER; sonuç ondan ÖNCE okunur.
        # Çağrı raise etmez (Y-3): hata çekirdekte gönderilmiş e-postayı exception yapar/yeniden göndertir.
        self.env['sanal.pos.payment']._receipt_mails_processed(self)
        return super()._postprocess_sent_message(
            success_pids, success_emails, failure_reason=failure_reason, failure_type=failure_type)

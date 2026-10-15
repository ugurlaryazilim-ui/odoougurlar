from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vendor_claim_overdue_days = fields.Integer(
        string='Gecikme Süresi (gün)', config_parameter='vendor_claim.overdue_days', default=15)
    vendor_claim_sms_received = fields.Boolean(
        string='Teslim Alınınca SMS', config_parameter='vendor_claim.sms_received_enabled')
    vendor_claim_sms_sent = fields.Boolean(
        string='Tedarikçiye Gönderilince SMS', config_parameter='vendor_claim.sms_sent_enabled')
    vendor_claim_sms_returned = fields.Boolean(
        string='İncelemeden Gelince SMS', config_parameter='vendor_claim.sms_returned_enabled')
    vendor_claim_sms_delivered = fields.Boolean(
        string='Müşteriye Teslim Edilince SMS', config_parameter='vendor_claim.sms_delivered_enabled')
    vendor_claim_sms_reminder = fields.Boolean(
        string='İnceleme: Teslim Alınmayana Hatırlatma', config_parameter='vendor_claim.sms_reminder_enabled')
    vendor_claim_sms_reminder_days = fields.Integer(
        string='İnceleme hatırlatma günü', config_parameter='vendor_claim.sms_reminder_days', default=3)
    vendor_claim_sms_reminder_max = fields.Integer(
        string='İnceleme en fazla hatırlatma', config_parameter='vendor_claim.sms_reminder_max', default=2)

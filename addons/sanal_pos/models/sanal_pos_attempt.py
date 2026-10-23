# -*- coding: utf-8 -*-
"""Mail order kart denemesi (Paratika satış işlemi başına bir satır; tasarım §5.1).

NEDEN: sonuç sayfası ve kayıt formu işlem düzeyinde geçmiş, "aynı pgTranId'ye tek not" ve fatura
başına 24 saatte 3 başarısız sınırı ister; ``failed_attempt_count`` yalnız MPID başına sayıdır,
zamanı yoktur (bkz. KARARLAR K-17). Satırlar yalnız ``sanal.pos.payment._record_attempts`` ile
``sudo`` altında yazılır; ACL kullanıcıya ve yöneticiye yalnız okuma verir.
DIKKAT: kart verisi/BIN alanı eklenmez; yalnız Paratika'nın verdiği son 4 hane (PCI testi kapsar).
"""
from odoo import fields, models

ATTEMPT_STATUSES = [
    ('approved', 'Onaylandı'), ('failed', 'Reddedildi'), ('cancelled', 'İptal'),
    ('pending', 'Bekliyor'), ('review', 'İncelemede'),
]


class SanalPosPaymentAttempt(models.Model):
    _name = 'sanal.pos.payment.attempt'
    _description = 'Sanal POS Mail Order Denemesi'
    _order = 'tran_time desc, id desc'
    _rec_name = 'tran_ref'

    # NEDEN: aynı işlem her senkronda yeniden gelir; satır ve not tekrarlanmasın (KK-3.6)
    _payment_tran_ref_uniq = models.Constraint(
        'UNIQUE(payment_id, tran_ref)', 'Bu işlem zaten kayıtlı.')

    payment_id = fields.Many2one(
        'sanal.pos.payment', string='Ödeme Talebi', required=True, ondelete='cascade', index=True)
    tran_ref = fields.Char(string='İşlem No (pgTranId)', required=True)
    tran_time = fields.Datetime(string='Zaman', required=True)
    status = fields.Selection(ATTEMPT_STATUSES, string='Sonuç', required=True)
    error_code = fields.Char(string='Kod')
    reason = fields.Char(string='Neden', size=250)
    installment_count = fields.Integer(string='Taksit')
    card_last4 = fields.Char(string='Kart Son 4')
    approval_code = fields.Char(string='Onay Kodu')
    user_id = fields.Many2one('res.users', string='Başlatan')
    # NEDEN (Ö-1): K-15 aynı kaydı yeniden açar; satırın hangi oturumda (o anki ``sent_at``) görüldüğü
    # sonuç sayfasında eski oturumun reddini yeni oturumdan ayırır. create_date kullanılamaz: işlem
    # başlangıcıdır (cr.now) ve tran_time bankanın zamanıdır, oturumla ilişkisi yoktur. Boş = damgasız.
    session_sent_at = fields.Datetime(string='Oturum Başlangıcı', readonly=True)

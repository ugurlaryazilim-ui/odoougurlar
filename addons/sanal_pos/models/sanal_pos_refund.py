# -*- coding: utf-8 -*-
"""Sanal POS iptal/iade satırı (tasarım §3.2). Finansal iz: değiştirilemez, silinemez (KK-48).

ACL kullanıcıya ve yöneticiye yalnız okuma verir; satırlar ödeme metotlarından
``sudo()`` ile oluşturulur ve güncellenir. ``write``/``unlink`` yalnız ``sudo``
ortamında çalışır (``env.su``), böylece ACL'e ek olarak model düzeyinde de kilitlidir.
"""
from odoo import fields, models
from odoo.exceptions import UserError


class SanalPosRefund(models.Model):
    _name = 'sanal.pos.refund'
    _description = 'Sanal POS İptal/İade Satırı'
    _order = 'id desc'

    # Aynı ödemede tek devam eden işlem (KK-45, veritabanı düzeyi)
    # NEDEN: Paratika finans onayı bekleyen iade de "devam eden" sayılır; aynı ödemede
    # ikinci bekleyen/devam eden satır DB düzeyinde de engellenir (bkz. KARARLAR K-12).
    # DIKKAT: öznitelik adı değişmemeli; Odoo tanım farkını görüp -u'da indeksi yeniden kurar.
    _payment_in_progress_uniq = models.UniqueIndex(
        "(payment_id) WHERE state IN ('processing','unknown','pending_approval')",
        'Bu ödeme için devam eden bir iade/iptal işlemi var.')
    # Panel senkronunda aynı işlemin iki kez eklenmesini önler (NULL'lar ayrık sayılır)
    _payment_provider_ref_uniq = models.Constraint(
        'UNIQUE(payment_id, provider_ref)', 'Bu işlem zaten kayıtlı.')

    payment_id = fields.Many2one(
        'sanal.pos.payment', string='Ödeme Talebi', required=True,
        ondelete='restrict', index=True)
    kind = fields.Selection(
        [('void', 'İptal'), ('refund', 'İade')], string='Tür', required=True)
    amount = fields.Monetary(string='Tutar', currency_field='currency_id', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Para Birimi', related='payment_id.currency_id', store=True)
    state = fields.Selection(
        [('processing', 'İşleniyor'), ('pending_approval', 'Onay bekliyor'),
         ('done', 'Başarılı'), ('rejected', 'Reddedildi'),
         ('failed', 'Başarısız'), ('unknown', 'Belirsiz')],
        string='Durum', required=True, default='processing', index=True)
    source = fields.Selection(
        [('odoo', 'Odoo'), ('panel', 'Paratika paneli')], string='Kaynak', required=True, default='odoo')
    reason = fields.Char(string='Neden')
    user_id = fields.Many2one(
        'res.users', string='İşlemi Yapan', default=lambda self: self.env.user)
    provider_ref = fields.Char(string='Sağlayıcı İşlem No', copy=False)
    # 'rejected' satırda Paratika ret kodu/sebebi de bu alanlardadır (kullanıcı kararı).
    error_code = fields.Char(string='Hata / Ret Kodu')
    error_message = fields.Char(string='Hata / Ret Sebebi')
    # Eşleşen Paratika iade işleminin ham transactionStatus'ü (AP, IP, MR...) ve izinli
    # alanlardan kısa JSON; kart verisi yazılmaz (tasarım §5.4).
    provider_status = fields.Char(string='Paratika Durumu', copy=False)
    provider_status_detail = fields.Text(string='Paratika Yanıt Ayrıntısı', copy=False)
    # 72 saat uyarısı tek seferlik bayrağı (G3).
    pending_alert_sent = fields.Boolean(string='Uzun Bekleme Uyarısı Gönderildi', copy=False)
    done_at = fields.Datetime(string='Tamamlanma Zamanı')
    # Belirsiz uzlaştırması (KK-47, yönetici şartı 1): satır ancak en az 2 ayrı sorguda
    # bulunamaz ve ilk belirsizlikten 15 dk geçerse 'Başarısız' olur.
    unknown_since = fields.Datetime(string='Belirsizlik Başlangıcı', copy=False)
    not_found_count = fields.Integer(string='"Bulunamadı" Sorgu Sayısı', copy=False)

    def write(self, vals):
        if not self.env.su:
            raise UserError('İade geçmişi değiştirilemez.')
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError('İade geçmişi değiştirilemez.')
        return super().unlink()

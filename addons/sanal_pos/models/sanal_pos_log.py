# -*- coding: utf-8 -*-
"""Sanal POS API çağrı kaydı (tasarım §3.3, KK-39).

Gövdeler MASKELİDİR (sır değerleri ``***``); maskeleme yazan sağlayıcı katmanının
sorumluluğundadır. Yazım yalnız sağlayıcı katmanından ``sudo().create`` ile yapılır;
ACL yalnız yöneticiye okuma verir. Temizlik (günlük cron): 180 günden eski ve
``is_financial`` olmayan kayıtlar.
"""
from datetime import timedelta

from odoo import api, fields, models

PURGE_BATCH = 5000


class SanalPosLog(models.Model):
    _name = 'sanal.pos.log'
    _description = 'Sanal POS İşlem Kaydı'
    _order = 'id desc'

    # Günlük temizlik create_date'e göre çalışır
    _create_date_idx = models.Index('(create_date)')

    action = fields.Char(string='İşlem', required=True, index=True)
    provider = fields.Char(string='Sağlayıcı')
    environment = fields.Selection([('test', 'Test'), ('live', 'Canlı')], string='Ortam')
    payment_id = fields.Many2one(
        'sanal.pos.payment', string='Ödeme Talebi', ondelete='cascade', index=True)
    duration_ms = fields.Integer(string='Süre (ms)')
    http_status = fields.Integer(string='HTTP Durumu')
    response_code = fields.Char(string='Yanıt Kodu')
    error_code = fields.Char(string='Hata Kodu')
    success = fields.Boolean(string='Başarılı')
    request_body = fields.Text(string='İstek (maskeli)')
    response_body = fields.Text(string='Yanıt (maskeli)')
    is_financial = fields.Boolean(
        string='Finansal işlem', help='VOID/REFUND kayıtları temizlikten muaftır.')

    @api.model
    def _purge_old(self, days=180):
        """KK-39: ``days`` günden eski ve mali olmayan kayıtları siler (VOID/REFUND kalır)."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        Log = self.sudo()
        deleted = 0
        while True:
            batch = Log.search([('create_date', '<', cutoff), ('is_financial', '=', False)],
                               limit=PURGE_BATCH, order='id')
            if not batch:
                return deleted
            deleted += len(batch)
            batch.unlink()

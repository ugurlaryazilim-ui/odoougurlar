import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class ImageSyncLog(models.Model):
    """Her görsel yükleme işlemini kaydeder."""
    _name = 'ugurlar.image.sync.log'
    _description = 'Görsel Senkronizasyon Logu'
    _order = 'create_date desc'

    name = fields.Char(string='İşlem Adı', required=True)
    sync_type = fields.Selection([
        ('zip', 'ZIP Yükleme'),
        ('agent', 'Sync Agent'),
        ('manual', 'Manuel'),
    ], string='Yükleme Türü', default='zip')
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='running')
    total_files = fields.Integer(string='Toplam Dosya')
    matched_count = fields.Integer(string='Eşleşen')
    skipped_count = fields.Integer(string='Atlanan')
    error_count = fields.Integer(string='Hatalı')
    detail_log = fields.Text(string='Detay Log')
    start_date = fields.Datetime(string='Başlangıç', default=fields.Datetime.now)
    end_date = fields.Datetime(string='Bitiş')

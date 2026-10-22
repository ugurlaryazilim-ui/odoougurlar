import logging
import time

from odoo import api, fields, models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_GC_BATCH = 5000         # parti başına silinen satır
_GC_TIME_BUDGET = 60     # saniye; dolunca kalan sonraki günkü turda silinir


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

    # NEDEN: tablo sınırsız büyür (her yükleme/ajan turu bir satır); süre ICP'den okunur,
    # 0/geçersiz değer = hiçbir şey silinmez (K6, kullanıcı kararı 2026-10-22).
    # DIKKAT: silme partili ve süre bütçelidir (tek dev DELETE kilit/WAL şişirir). Parti başına
    # commit yalnız cron bağlamında (cron_id) yapılır; dışarıdan çağrıda tek parti silinir.
    @api.model
    def _cron_gc_old_logs(self):
        try:
            days = int(self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_images.log_retention_days', '180'))
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days) if days > 0 else None
        except (ValueError, OverflowError):
            cutoff = None
        if cutoff is None:
            return 0
        deadline = time.monotonic() + _GC_TIME_BUDGET
        in_cron = bool(self.env.context.get('cron_id'))
        total = 0
        last_id = 0
        while True:
            # NEDEN (A5 diğer Ö-2): eski "id IN (SELECT id ... create_date < c LIMIT n)" her partide
            # tabloyu baştan tarıyor, önceki partilerin ölü satırlarını (vacuum'a kadar) tekrar geziyordu.
            # Birincil anahtar sırasıyla kaldığı yerden devam edilir: tur başına tablo en fazla bir kez
            # gezilir, create_date indeksi gerekmez. Genç satırlar atlanır (sıra dışı eski satır da silinir).
            self.env.cr.execute(SQL(
                "SELECT id FROM %(t)s WHERE id > %(last)s AND create_date < %(c)s ORDER BY id LIMIT %(n)s",
                t=SQL.identifier(self._table), c=cutoff, last=last_id, n=_GC_BATCH))
            ids = [row[0] for row in self.env.cr.fetchall()]
            if ids:
                self.env.cr.execute(SQL("DELETE FROM %(t)s WHERE id = ANY(%(ids)s)",
                                        t=SQL.identifier(self._table), ids=ids))
            deleted = len(ids)
            total += deleted
            if deleted < _GC_BATCH or not in_cron:
                break
            last_id = ids[-1]
            self.env['ir.cron']._commit_progress(deleted)
            if time.monotonic() >= deadline:
                break
        self.invalidate_model()
        if total:
            _logger.info("%s log temizliği: %d kayıt silindi", self._name, total)
        return total

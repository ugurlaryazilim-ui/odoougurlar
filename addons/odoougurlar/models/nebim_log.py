import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class NebimSyncLog(models.Model):
    """Nebim senkronizasyon işlemlerinin log kayıtları."""
    _name = 'odoougurlar.sync.log'
    _description = 'Nebim Senkronizasyon Logu'
    _order = 'create_date desc'

    name = fields.Char(
        string='İşlem Adı',
        required=True,
    )
    sync_type = fields.Selection([
        ('product', 'Ürün Senkronizasyonu'),
        ('stock', 'Stok Güncelleme'),
        ('price', 'Fiyat Güncelleme'),
        ('invoice', 'Fatura Gönderimi'),
    ], string='Senkronizasyon Türü', required=True)
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
        ('partial', 'Kısmi Başarı'),
    ], string='Durum', default='running', required=True)
    start_date = fields.Datetime(
        string='Başlangıç',
        default=fields.Datetime.now,
    )
    end_date = fields.Datetime(
        string='Bitiş',
    )
    records_processed = fields.Integer(
        string='İşlenen Kayıt',
        default=0,
    )
    records_created = fields.Integer(
        string='Oluşturulan',
        default=0,
    )
    records_updated = fields.Integer(
        string='Güncellenen',
        default=0,
    )
    records_failed = fields.Integer(
        string='Başarısız',
        default=0,
    )
    error_details = fields.Text(
        string='Hata Detayları',
    )
    log_details = fields.Text(
        string='İşlem Detayları',
    )

    def auto_cleanup_logs(self):
        """
        Eski logları otomatik temizler (cron tarafından çağrılır).
        
        - Tamamlanmış loglar: 1 gün sonra silinir
        - Hatalı loglar: 7 gün sonra silinir
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoougurlar.nebim_log_auto_cleanup', 'True') != 'True':
            return

        from datetime import timedelta
        now = fields.Datetime.now()

        # Tamamlanmış logları 1 gün sonra sil
        cutoff_done = now - timedelta(days=1)
        old_done = self.sudo().search([
            ('state', 'in', ['done', 'running']),
            ('create_date', '<', cutoff_done),
        ])
        done_count = len(old_done)
        if old_done:
            old_done.unlink()

        # Hatalı logları 7 gün sonra sil
        cutoff_error = now - timedelta(days=7)
        old_errors = self.sudo().search([
            ('state', 'in', ['error', 'partial']),
            ('create_date', '<', cutoff_error),
        ])
        error_count = len(old_errors)
        if old_errors:
            old_errors.unlink()

        if done_count or error_count:
            _logger.info(
                "Log temizliği: %d tamamlanmış + %d hatalı log silindi",
                done_count, error_count
            )

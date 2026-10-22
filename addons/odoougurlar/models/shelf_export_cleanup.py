import logging
import time

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_GC_BATCH = 5000         # parti başına silinen ek
_GC_TIME_BUDGET = 60     # saniye; dolunca kalan sonraki günkü turda silinir
_XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class IrAttachmentShelfExport(models.Model):
    """Raf export'unun (stock.location.action_export_shelf_detail) bıraktığı Excel eklerini temizler."""
    _inherit = 'ir.attachment'

    @api.model
    def _shelf_export_gc_domain(self, cutoff):
        # DIKKAT: export eki hiçbir kayda bağlanmadan (res_model/res_id boş) oluşturulur; tanıma yalnız
        # bu birleşik ölçüte güvenir. Gevşetirsen kullanıcı yüklemeleri / rapor ekleri de silinir.
        # `_` LIKE joker karakteri olduğundan \_ ile kaçırılır.
        return [
            ('res_model', '=', False), ('res_id', 'in', (0, False)), ('res_field', '=', False),
            ('type', '=', 'binary'), ('mimetype', '=', _XLSX_MIME),
            ('name', '=like', r'raf\_detay\_listesi\_%.xlsx'),
            ('create_date', '<', cutoff),
        ]

    # NEDEN: her export bir xlsx'i filestore'a bırakır, hiçbir şey silmez; süre ICP'den okunur,
    # 0/geçersiz değer = hiçbir şey silinmez (K6, kullanıcı kararı 2026-10-22).
    # DIKKAT: partili + süre bütçeli; parti başına commit yalnız cron bağlamında (cron_id),
    # dışarıdan çağrıda tek parti silinir. ORM unlink: filestore dosyası da silinsin.
    @api.model
    def _cron_gc_shelf_exports(self):
        try:
            days = int(self.env['ir.config_parameter'].sudo().get_param(
                'odoougurlar.shelf_export_retention_days', '30'))
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days) if days > 0 else None
        except (ValueError, OverflowError):
            cutoff = None
        if cutoff is None:
            return 0
        deadline = time.monotonic() + _GC_TIME_BUDGET
        in_cron = bool(self.env.context.get('cron_id'))
        total = 0
        while True:
            batch = self.sudo().search(self._shelf_export_gc_domain(cutoff), limit=_GC_BATCH, order='id')
            batch.unlink()
            total += len(batch)
            if len(batch) < _GC_BATCH or not in_cron:
                break
            self.env['ir.cron']._commit_progress(len(batch))
            if time.monotonic() >= deadline:
                break
        if total:
            _logger.info("Raf export eki temizliği: %d ek silindi", total)
        return total

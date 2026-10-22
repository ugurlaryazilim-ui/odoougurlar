# -*- coding: utf-8 -*-
import logging
import time

from odoo import api, fields, models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_GC_BATCH = 5000         # parti başına silinen satır
_GC_TIME_BUDGET = 60     # saniye; dolunca kalan sonraki günkü turda silinir

class AdsSyncLog(models.Model):
    _name = 'ads.sync.log'
    _description = 'Sync History Log'
    _order = 'sync_date desc'

    account_id = fields.Many2one('ads.account', string='Account', required=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Sync Date', default=fields.Datetime.now)
    
    sync_type = fields.Selection([
        ('campaigns', 'Campaigns'),
        ('metrics', 'Metrics'),
        ('full', 'Full Sync')
    ], string='Sync Type', required=True)
    
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('partial', 'Partial')
    ], string='Status', required=True)
    
    message = fields.Text(string='Message')
    records_created = fields.Integer(string='Records Created', default=0)
    records_updated = fields.Integer(string='Records Updated', default=0)
    duration_seconds = fields.Float(string='Duration (seconds)', default=0.0)
    
    company_id = fields.Many2one('res.company', related='account_id.company_id', store=True)

    # NEDEN: tablo sınırsız büyür (her senkron turu bir satır); süre ICP'den okunur,
    # 0/geçersiz değer = hiçbir şey silinmez (K6, kullanıcı kararı 2026-10-22).
    # DIKKAT: silme partili ve süre bütçelidir (tek dev DELETE kilit/WAL şişirir). Parti başına
    # commit yalnız cron bağlamında (cron_id) yapılır; dışarıdan çağrıda tek parti silinir.
    @api.model
    def _cron_gc_old_logs(self):
        try:
            days = int(self.env['ir.config_parameter'].sudo().get_param(
                'ads_manager.log_retention_days', '180'))
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days) if days > 0 else None
        except (ValueError, OverflowError):
            cutoff = None
        if cutoff is None:
            return 0
        deadline = time.monotonic() + _GC_TIME_BUDGET
        in_cron = bool(self.env.context.get('cron_id'))
        total = 0
        while True:
            self.env.cr.execute(SQL(
                "DELETE FROM %(t)s WHERE id IN (SELECT id FROM %(t)s WHERE create_date < %(c)s LIMIT %(n)s)",
                t=SQL.identifier(self._table), c=cutoff, n=_GC_BATCH))
            deleted = self.env.cr.rowcount
            total += deleted
            if deleted < _GC_BATCH or not in_cron:
                break
            self.env['ir.cron']._commit_progress(deleted)
            if time.monotonic() >= deadline:
                break
        self.invalidate_model()
        if total:
            _logger.info("%s log temizliği: %d kayıt silindi", self._name, total)
        return total

import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class NebimDashboard(models.TransientModel):
    """
    Nebim Kontrol Paneli.
    Manuel senkronizasyon tetikleme ve durum görüntüleme.
    
    Aksiyonlar ayrı dosyalarda tanımlıdır:
    - nebim_dashboard_products.py: Ürün çekme ve test aksiyonları
    - nebim_dashboard_actions.py: Depo, stok, fatura, bağlantı aksiyonları
    """
    _name = 'odoougurlar.nebim.dashboard'
    _description = 'Nebim Kontrol Paneli'

    last_product_sync = fields.Datetime(
        string='Son Ürün Senk.',
        compute='_compute_last_syncs',
    )
    last_stock_sync = fields.Datetime(
        string='Son Stok Senk.',
        compute='_compute_last_syncs',
    )
    last_invoice_sync = fields.Datetime(
        string='Son Fatura Senk.',
        compute='_compute_last_syncs',
    )
    total_synced_products = fields.Integer(
        string='Senkronize Ürün',
        compute='_compute_stats',
    )
    pending_invoices = fields.Integer(
        string='Bekleyen Fatura',
        compute='_compute_stats',
    )
    total_errors_today = fields.Integer(
        string='Bugünkü Hatalar',
        compute='_compute_stats',
    )
    recent_log_ids = fields.Many2many(
        'odoougurlar.sync.log',
        string='Son Loglar',
        compute='_compute_recent_logs',
    )
    nebim_fetch_code = fields.Char(
        string='Ürün Kodu',
        help='Nebim ürün kodu girin (ör: 0/1015E)',
    )

    @api.depends_context('uid')
    def _compute_last_syncs(self):
        SyncLog = self.env['odoougurlar.sync.log'].sudo()
        for rec in self:
            for sync_type, field_name in [
                ('product', 'last_product_sync'),
                ('stock', 'last_stock_sync'),
                ('invoice', 'last_invoice_sync'),
            ]:
                last_log = SyncLog.search([
                    ('sync_type', '=', sync_type),
                    ('state', '=', 'done'),
                ], order='end_date desc', limit=1)
                setattr(rec, field_name, last_log.end_date if last_log else False)

    @api.depends_context('uid')
    def _compute_stats(self):
        for rec in self:
            rec.total_synced_products = self.env['product.template'].sudo().search_count([
                ('nebim_synced', '=', True),
            ])
            rec.pending_invoices = self.env['account.move'].sudo().search_count([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('nebim_sent', '=', False),
            ])
            today = fields.Date.today()
            rec.total_errors_today = self.env['odoougurlar.sync.log'].sudo().search_count([
                ('state', '=', 'error'),
                ('start_date', '>=', datetime.combine(today, datetime.min.time())),
            ])

    @api.depends_context('uid')
    def _compute_recent_logs(self):
        for rec in self:
            rec.recent_log_ids = self.env['odoougurlar.sync.log'].sudo().search(
                [], order='create_date desc', limit=20
            )

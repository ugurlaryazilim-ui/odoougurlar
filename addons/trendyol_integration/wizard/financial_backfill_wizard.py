from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TrendyolFinancialBackfillWizard(models.TransientModel):
    _name = 'trendyol.financial.backfill.wizard'
    _description = 'Trendyol Finans Geçmişini Tamamla'

    store_id = fields.Many2one('trendyol.store', string='Mağaza', required=True)
    period = fields.Selection([
        ('3', 'Son 3 ay'),
        ('6', 'Son 6 ay'),
        ('custom', 'Tarih aralığı'),
    ], string='Dönem', default='3', required=True)
    date_from = fields.Date(string='Başlangıç')
    date_to = fields.Date(string='Bitiş', default=fields.Date.context_today)
    chunk_count = fields.Integer(string="15 Günlük Parça", compute='_compute_range')
    info = fields.Char(compute='_compute_range')

    @api.depends('period', 'date_from', 'date_to')
    def _compute_range(self):
        for wiz in self:
            start, end = wiz._get_range()
            days = (end - start).days + 1 if start and end and end >= start else 0
            wiz.chunk_count = -(-days // 15) if days else 0
            wiz.info = (f"{start:%d.%m.%Y} → {end:%d.%m.%Y}: {days} gün, {wiz.chunk_count} parça. "
                        f"Arka planda çalışır (parça başına ~10 sn); mağaza formunda ilerleme görünür."
                        if days else '')

    def _get_range(self):
        today = fields.Date.context_today(self)
        if self.period in ('3', '6'):
            return today - timedelta(days=int(self.period) * 30), today
        return self.date_from, self.date_to

    def action_start(self):
        self.ensure_one()
        start, end = self._get_range()
        if not start or not end:
            raise UserError(_('Başlangıç ve bitiş tarihini girin.'))
        if start > end:
            raise UserError(_('Başlangıç tarihi bitişten sonra olamaz.'))
        if end > fields.Date.context_today(self):
            end = fields.Date.context_today(self)
        if self.store_id.backfill_next:
            raise UserError(_('Bu mağazada zaten süren bir geçmiş tamamlama var.'))
        self.store_id.write({
            'backfill_from': start,
            'backfill_to': end,
            'backfill_next': start,
            'backfill_created': 0,
        })
        cron = self.env.ref('trendyol_integration.cron_trendyol_financial_backfill', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Trendyol - Finans Geçmişi',
                'message': f'{start:%d.%m.%Y} → {end:%d.%m.%Y} arası {self.chunk_count} parça halinde '
                           f'arka planda çekiliyor. İlerlemeyi mağaza formunda görebilirsiniz.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

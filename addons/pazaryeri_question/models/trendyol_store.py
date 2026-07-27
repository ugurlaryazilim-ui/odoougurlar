from odoo import models, fields, api

class TrendyolStore(models.Model):
    _inherit = 'trendyol.store'
    
    question_sync_enabled = fields.Boolean('Soru Senkronizasyonu', default=True)
    question_sync_interval = fields.Integer('Soru Sync Aralığı (dk)', default=30)
    last_question_sync = fields.Datetime('Son Soru Senkronizasyonu', readonly=True)
    question_count = fields.Integer('Soru Sayısı', compute='_compute_question_count')
    question_ids = fields.One2many('marketplace.question', 'store_id', string='Sorular')
    
    @api.depends('question_ids')
    def _compute_question_count(self):
        data = self.env['marketplace.question'].sudo()._read_group(
            [('store_id', 'in', self.ids)],
            groupby=['store_id'], aggregates=['__count'],
        )
        counts = {store.id: count for store, count in data}
        for store in self:
            store.question_count = counts.get(store.id, 0)
    
    def action_sync_questions(self):
        """Manuel soru senkronizasyonu butonu."""
        self.ensure_one()
        Connector = self.env['trendyol.question.connector']
        result = Connector.sync_questions_for_store(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Soru Senkronizasyonu',
                'message': f'✅ Tamamlandı! Yeni: {result.get("created", 0)} | Güncellenen: {result.get("updated", 0)}',
                'type': 'success',
                'sticky': False,
            },
        }
    
    def action_view_questions(self):
        """Mağazanın sorularını görüntüle."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} Müşteri Soruları',
            'res_model': 'marketplace.question',
            'view_mode': 'list,form,kanban',
            'domain': [('store_id', '=', self.id)],
            'context': {'default_store_id': self.id, 'default_marketplace_type': 'trendyol'},
        }

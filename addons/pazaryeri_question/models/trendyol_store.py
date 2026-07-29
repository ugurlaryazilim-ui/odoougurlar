from datetime import datetime, timedelta
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

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
        Connector = self.env['trendyol.question.connector'].sudo()
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
    
    def action_sync_full_history(self):
        """Tüm geçmiş soruları çek — 2 haftalık pencerelerle geriye giderek."""
        self.ensure_one()
        _logger.info("Tam geçmiş sync başlıyor: %s", self.name)
        
        api = self.get_api()
        Connector = self.env['trendyol.question.connector'].sudo()
        
        now = datetime.now()
        total_created = 0
        total_updated = 0
        window = 0
        max_windows = 52  # ~1 yıl geriye git (52 x 14 gün)
        
        while window < max_windows:
            end_date = now - timedelta(days=14 * window)
            start_date = end_date - timedelta(days=14)
            
            page = 0
            window_questions = 0
            
            while True:
                params = {
                    'startDate': int(start_date.timestamp() * 1000),
                    'endDate': int(end_date.timestamp() * 1000),
                    'page': page,
                    'size': 50,
                    'orderByField': 'CreatedDate',
                    'orderByDirection': 'DESC',
                }
                
                result = api._request('GET', f'/qna/sellers/{self.seller_id}/questions/filter', params=params)
                
                if not result.get('success'):
                    break
                
                data = result.get('data', {})
                content = data.get('content', [])
                
                if not content:
                    break
                
                for question_data in content:
                    try:
                        with self.env.cr.savepoint():
                            res = Connector._process_question(question_data, self)
                            if res == 'created':
                                total_created += 1
                            elif res == 'updated':
                                total_updated += 1
                            window_questions += 1
                    except Exception as e:
                        _logger.error("Geçmiş sync soru hatası: %s", e)
                
                total_pages = data.get('totalPages', 0)
                if page >= total_pages - 1:
                    break
                page += 1
            
            _logger.info("Pencere %d (%s — %s): %d soru işlendi", 
                        window, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), window_questions)
            
            # Bu pencerede hiç soru yoksa geriye gitmesine gerek yok
            if window_questions == 0:
                _logger.info("Boş pencere, geçmiş sync tamamlanıyor.")
                break
            
            window += 1
        
        _logger.info("Tam geçmiş sync tamamlandı: %s | Yeni: %d | Güncellenen: %d", 
                     self.name, total_created, total_updated)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Geçmiş Soru Senkronizasyonu',
                'message': f'✅ Tamamlandı! Yeni: {total_created} | Güncellenen: {total_updated}',
                'type': 'success',
                'sticky': True,
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

from odoo import models, fields, api

class AmazonSyncLog(models.Model):
    _name = 'amazon.sync.log'
    _description = 'Amazon Senkronizasyon Logları'
    _order = 'create_date desc'

    store_id = fields.Many2one('amazon.store', string='Mağaza', required=True, ondelete='cascade')
    sync_type = fields.Selection([
        ('order', 'Sipariş Senkronizasyonu'),
        ('product', 'Ürün Senkronizasyonu'),
        ('tracking', 'Kargo Takip Senkronizasyonu')
    ], string='İşlem Tipi', required=True)
    
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Başarılı'),
        ('error', 'Hatalı')
    ], string='Durum', default='running', required=True)
    
    processed_count = fields.Integer('İşlenen', default=0)
    success_count = fields.Integer('Başarılı', default=0)
    error_count = fields.Integer('Hatalı', default=0)
    
    details = fields.Text('Detaylar')
    
    def mark_done(self, processed=0, created=0, failed=0, details=''):
        self.write({
            'state': 'done',
            'processed_count': processed,
            'success_count': created,
            'error_count': failed,
            'details': details
        })

    def mark_error(self, error_msg):
        self.write({
            'state': 'error',
            'details': error_msg
        })

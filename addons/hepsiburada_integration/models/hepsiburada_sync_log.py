from odoo import models, fields

class HepsiburadaSyncLog(models.Model):
    _name = 'hepsiburada.sync.log'
    _description = 'Hepsiburada Senkronizasyon Logu'
    _order = 'create_date desc'

    name = fields.Char(string='İşlem No', required=True, copy=False, readonly=True, default='Yeni')
    store_id = fields.Many2one('hepsiburada.store', string='Mağaza', required=True, ondelete='cascade')
    sync_type = fields.Selection([
        ('order', 'Sipariş Senkronizasyonu'),
        ('price', 'Fiyat Senkronizasyonu'),
        ('stock', 'Stok Senkronizasyonu')
    ], string='İşlem Tipi', required=True, default='order')
    
    state = fields.Selection([
        ('running', 'Çalışıyor'),
        ('done', 'Başarılı'),
        ('error', 'Hatalı')
    ], string='Durum', default='running')
    
    start_date = fields.Datetime(string='Başlangıç', default=fields.Datetime.now)
    end_date = fields.Datetime(string='Bitiş')
    
    records_processed = fields.Integer(string='İşlenen Kayıt', default=0)
    records_created = fields.Integer(string='Oluşturulan', default=0)
    records_updated = fields.Integer(string='Güncellenen', default=0)
    records_failed = fields.Integer(string='Hatalı Kayıt', default=0)
    
    log_details = fields.Text(string='İşlem Detayları')
    error_details = fields.Text(string='Hata Detayları')

    def mark_done(self, processed=0, created=0, updated=0, failed=0, details=''):
        self.write({
            'state': 'done' if failed == 0 else 'error',
            'end_date': fields.Datetime.now(),
            'records_processed': processed,
            'records_created': created,
            'records_updated': updated,
            'records_failed': failed,
            'log_details': details
        })

    def mark_error(self, error_msg):
        self.write({
            'state': 'error',
            'end_date': fields.Datetime.now(),
            'error_details': error_msg
        })

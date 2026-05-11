import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ImageSyncFile(models.Model):
    """İşlenmiş dosyaların kaydı — mükerrer işlem engelleme.
    
    Sync Agent bir dosyayı başarıyla Odoo'ya yüklediğinde bu tabloya yazar.
    Sonraki taramalarda dosya adı + boyut + değişiklik tarihi kontrol edilir.
    Dosya değişmişse (boyut veya tarih farklı) tekrar işlenir.
    """
    _name = 'ugurlar.image.sync.file'
    _description = 'İşlenmiş Görsel Dosyası'
    _order = 'sync_date desc'
    _rec_name = 'filename'

    filename = fields.Char(
        string='Dosya Adı',
        required=True,
        index=True,
        help='Görsel dosyasının adı (örn: 8691234_1.jpg)',
    )
    barcode = fields.Char(
        string='Barkod',
        index=True,
        help='Dosya adından çıkarılan barkod/referans kodu',
    )
    file_size = fields.Integer(
        string='Dosya Boyutu (byte)',
        help='Dosyanın son işlendiğindeki boyutu',
    )
    file_mtime = fields.Char(
        string='Değişiklik Tarihi',
        help='Dosyanın son değişiklik tarihi (ISO format)',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ürün Varyantı',
        ondelete='set null',
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Ürün Şablonu',
        ondelete='set null',
    )
    image_type = fields.Selection([
        ('main', 'Ana Resim'),
        ('extra', 'Ek Resim'),
    ], string='Resim Türü', default='main')
    image_order = fields.Integer(
        string='Sıra No',
        help='Dosya adındaki sıra numarası',
    )
    state = fields.Selection([
        ('done', 'Başarılı'),
        ('error', 'Hatalı'),
    ], string='Durum', default='done')
    error_message = fields.Text(string='Hata Mesajı')
    sync_date = fields.Datetime(
        string='İşlenme Tarihi',
        default=fields.Datetime.now,
    )
    color_propagated = fields.Boolean(
        string='Renk Yayma Yapıldı',
        default=False,
        help='Bu görsel renk kardeşlerine de yayıldı mı?',
    )
    sibling_count = fields.Integer(
        string='Kardeş Sayısı',
        help='Görselin yayıldığı varyant sayısı',
    )

    _sql_constraints = [
        ('unique_filename', 'unique(filename)', 'Bu dosya adı zaten kayıtlı!'),
    ]

    @api.model
    def is_file_processed(self, filename, file_size, file_mtime):
        """Dosyanın daha önce başarıyla işlenip işlenmediğini kontrol eder.
        
        Dosya boyutu veya değişiklik tarihi farklıysa → değişmiş demektir,
        tekrar işlenmesi gerekir.
        
        Returns: True if already processed (skip), False if needs processing
        """
        existing = self.search([
            ('filename', '=', filename),
            ('state', '=', 'done'),
        ], limit=1)
        
        if not existing:
            return False
        
        # Dosya değişmiş mi kontrol et
        if (existing.file_size != file_size or 
                existing.file_mtime != file_mtime):
            # Dosya değişmiş — eski kaydı sil, tekrar işlensin
            existing.unlink()
            return False
        
        return True

    @api.model
    def mark_processed(self, filename, barcode, file_size, file_mtime,
                       product_id=None, tmpl_id=None, image_type='main',
                       image_order=1, color_propagated=False, sibling_count=0):
        """Dosyayı başarıyla işlenmiş olarak kaydet."""
        existing = self.search([('filename', '=', filename)], limit=1)
        vals = {
            'filename': filename,
            'barcode': barcode,
            'file_size': file_size,
            'file_mtime': file_mtime,
            'product_id': product_id,
            'product_tmpl_id': tmpl_id,
            'image_type': image_type,
            'image_order': image_order,
            'state': 'done',
            'error_message': False,
            'sync_date': fields.Datetime.now(),
            'color_propagated': color_propagated,
            'sibling_count': sibling_count,
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    @api.model
    def mark_error(self, filename, barcode, file_size, file_mtime, error_msg):
        """Dosyayı hatalı olarak kaydet."""
        existing = self.search([('filename', '=', filename)], limit=1)
        vals = {
            'filename': filename,
            'barcode': barcode,
            'file_size': file_size,
            'file_mtime': file_mtime,
            'state': 'error',
            'error_message': error_msg,
            'sync_date': fields.Datetime.now(),
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

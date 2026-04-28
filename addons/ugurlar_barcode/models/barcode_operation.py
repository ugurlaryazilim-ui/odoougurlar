import logging
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class BarcodeOperation(models.Model):
    _name = 'ugurlar.barcode.operation'
    _description = 'Barkod Operasyon Kaydı'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='Operatör',
                              default=lambda self: self.env.uid, index=True)
    operation_type = fields.Selection([
        ('search', 'Stok Arama'),
        ('shelf_search', 'Raf Arama'),
        ('shelf_control', 'Raf Kontrol'),
        ('putaway', 'Raflama'),
        ('remove', 'Raftan Kaldırma'),
        ('picking', 'Sipariş Toplama'),
        ('counting', 'Sayım'),
        ('transfer', 'Transfer'),
        ('shelf_transfer', 'Raf Taşıma'),
        ('label', 'Etiket Yazdırma'),
    ], string='İşlem Türü', required=True, index=True)
    barcode = fields.Char('Taranan Barkod')
    product_id = fields.Many2one('product.product', string='Ürün')
    location_id = fields.Many2one('stock.location', string='Konum')
    quantity = fields.Float('Miktar', default=0)
    notes = fields.Text('Notlar')
    state = fields.Selection([
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='done')

    @api.autovacuum
    def _gc_old_operations(self):
        """Eski operasyon kayıtlarını otomatik temizle (Odoo autovacuum).

        Read-only operasyonlar 90 gün, yazma operasyonları 180 gün sonra silinir.
        """
        days = 90
        cutoff = fields.Datetime.now() - timedelta(days=days)

        # Read-only operasyonlar: güvenle silinebilir
        readonly_ops = self.search([
            ('create_date', '<', cutoff),
            ('operation_type', 'in', ['search', 'shelf_search', 'shelf_control', 'label']),
        ])
        count_ro = len(readonly_ops)
        if readonly_ops:
            readonly_ops.unlink()

        # Yazma operasyonları: 180 günden eskiler
        cutoff_write = fields.Datetime.now() - timedelta(days=180)
        write_ops = self.search([
            ('create_date', '<', cutoff_write),
            ('operation_type', 'not in', ['search', 'shelf_search', 'shelf_control', 'label']),
        ])
        count_wr = len(write_ops)
        if write_ops:
            write_ops.unlink()

        _logger.info(
            "Operasyon temizliği: %d okuma + %d yazma kaydı silindi (toplam: %d)",
            count_ro, count_wr, count_ro + count_wr)


import logging
import time
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class BarcodeOperation(models.Model):
    _name = 'ugurlar.barcode.operation'
    _description = 'Barkod Operasyon Kaydı'
    _order = 'create_date desc'
    _create_date_idx = models.Index('(create_date)')

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
        ('count_adjustment', 'Sayım Düzeltmesi'),
        ('transfer', 'Transfer'),
        ('shelf_transfer', 'Raf Taşıma'),
        ('label', 'Etiket Yazdırma'),
    ], string='İşlem Türü', required=True, index=True)
    barcode = fields.Char('Taranan Barkod')
    product_id = fields.Many2one('product.product', string='Ürün', index='btree_not_null')
    location_id = fields.Many2one('stock.location', string='Konum', index='btree_not_null')
    quantity = fields.Float('Miktar', default=0)
    notes = fields.Text('Notlar')
    state = fields.Selection([
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='done')

    # Sayım Oturumu Bağlantısı
    count_session_id = fields.Many2one('ugurlar.barcode.count.session', string='Sayım Fişi', ondelete='cascade', index=True)
    theoretical_qty = fields.Float('Sistem Adedi', default=0.0)
    difference_qty = fields.Float('Fark', compute='_compute_difference_qty', store=True)

    @api.depends('theoretical_qty', 'quantity')
    def _compute_difference_qty(self):
        for rec in self:
            rec.difference_qty = rec.quantity - rec.theoretical_qty

    GC_BATCH = 10000
    GC_TIME_BUDGET = 120   # sn; autovacuum turu başına

    @api.model
    def _gc_in_batches(self, domain, deadline):
        """Aday kayıtları GC_BATCH'lik parçalarla, süre bütçesi bitene dek sil; silinen sayısı döner."""
        total = 0
        while time.monotonic() < deadline:
            batch = self.search(domain, limit=self.GC_BATCH)
            if not batch:
                break
            batch.unlink()
            total += len(batch)
            if len(batch) < self.GC_BATCH:
                break
        return total

    @api.autovacuum
    def _gc_old_operations(self):
        """Eski operasyon kayıtlarını otomatik temizle (Odoo autovacuum).

        Read-only operasyonlar 90 gün, yazma operasyonları 180 gün sonra silinir.
        """
        days = 90
        cutoff = fields.Datetime.now() - timedelta(days=days)

        # NEDEN: günde 10 binden fazla okuma kaydı üretilen sistemde tek parti temizliği hiç yetişmezdi;
        # parça parça (10.000) silinir, tur süre bütçesiyle (GC_TIME_BUDGET sn) biter, kalanı ertesi gün alır.
        deadline = time.monotonic() + self.GC_TIME_BUDGET
        # Read-only operasyonlar: güvenle silinebilir
        count_ro = self._gc_in_batches([
            ('create_date', '<', cutoff),
            ('operation_type', 'in', ['search', 'shelf_search', 'shelf_control', 'label']),
        ], deadline)

        # Yazma operasyonları: 180 günden eskiler
        cutoff_write = fields.Datetime.now() - timedelta(days=180)
        # Sayım fişlerinin satırları silinmez (eski sayım fişleri boş kalıyordu)
        count_wr = self._gc_in_batches([
            ('create_date', '<', cutoff_write),
            ('operation_type', 'not in', ['search', 'shelf_search', 'shelf_control', 'label',
                                          'counting', 'count_adjustment']),
            ('count_session_id', '=', False),
        ], deadline)

        _logger.info(
            "Operasyon temizliği: %d okuma + %d yazma kaydı silindi (toplam: %d)",
            count_ro, count_wr, count_ro + count_wr)


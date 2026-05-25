from odoo import models, fields, api


class UgurlarTtsMessage(models.Model):
    _name = 'ugurlar.tts.message'
    _description = 'TTS Seslendirme Mesajları'
    _order = 'category, sequence, id'

    name = fields.Char('Açıklama', required=True, help='Bu seslendirmenin ne zaman çalıştığını açıklar')
    key = fields.Char('Anahtar', required=True, index=True, help='Frontend tarafından kullanılan tekil anahtar')
    message = fields.Char('Seslendirme Metni', required=True, help='TTS ile okunacak metin')
    category = fields.Selection([
        ('stock_search', 'Ürün Stok Arama'),
        ('shelf_search', 'Ürün Raf Arama'),
        ('shelf_control', 'Raf Kontrol'),
        ('putaway', 'Raflama'),
        ('bulk_putaway', 'Toplu Raflama'),
        ('shelf_transfer', 'Ürün Raf Taşıma'),
        ('shelf_move_all', 'Tüm Rafı Taşı'),
        ('shelf_validate', 'Raf Doğrulama'),
        ('shelf_clear_all', 'Toplu Raf Silme'),
        ('picking', 'Sipariş Toplama'),
        ('batch_picking', 'Rota Toplama'),
        ('packing', 'Paketleme'),
        ('counting', 'Sayım'),
        ('movements', 'Stok Hareketleri'),
        ('general', 'Genel'),
    ], string='Kategori', required=True, default='general')
    active = fields.Boolean('Aktif', default=True)
    sequence = fields.Integer('Sıra', default=10)

    _sql_constraints = [
        ('key_unique', 'UNIQUE(key)', 'Her seslendirme anahtarı benzersiz olmalıdır!'),
    ]

    @api.model
    def get_tts_config(self):
        """Tüm aktif TTS mesajlarını dict olarak döner"""
        messages = self.sudo().search([('active', '=', True)])
        return {
            msg.key: msg.message
            for msg in messages
        }

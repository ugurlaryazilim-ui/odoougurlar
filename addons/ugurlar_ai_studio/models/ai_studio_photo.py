import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class AiStudioPhoto(models.Model):
    """Çekilen ham fotoğraflar.

    Her çekim oturumunda ön, arka ve detay fotoğrafları saklar.
    Kalite kontrol bilgisi ve arka planı kaldırılmış versiyonu tutar.
    """
    _name = 'ai.studio.photo'
    _description = 'AI Stüdyo Fotoğraf'
    _order = 'photo_type, sequence, id'

    session_id = fields.Many2one(
        'ai.studio.session',
        string='Oturum',
        required=True,
        ondelete='cascade',
        index=True,
    )
    photo_type = fields.Selection([
        ('front', 'Ön Yüz'),
        ('back', 'Arka Yüz'),
        ('side', 'Yan Yüz'),
        ('detail', 'Detay'),
    ], string='Fotoğraf Tipi', required=True)
    image_original = fields.Image(
        string='Orijinal Fotoğraf',
        max_width=1920, max_height=1920,
        required=True,
    )
    image_processed = fields.Image(
        string='İşlenmiş Fotoğraf',
        max_width=1920, max_height=1920,
        help='Arka planı kaldırılmış versiyon',
    )
    quality_score = fields.Float(
        string='Kalite Puanı',
        digits=(5, 1),
        help='0-100 arası otomatik kalite değerlendirmesi',
    )
    quality_warnings = fields.Text(
        string='Kalite Uyarıları',
        help='JSON formatında kalite uyarıları',
    )
    sequence = fields.Integer(string='Sıra', default=10)
    product_id = fields.Many2one(
        related='session_id.product_id',
        string='Ürün',
        store=True,
    )

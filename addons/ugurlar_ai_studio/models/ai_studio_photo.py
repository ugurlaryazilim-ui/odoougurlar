import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

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
    set_line_id = fields.Many2one(
        'ai.studio.set.line',
        string='Takım Parçası',
        index=True,
    )
    photo_type = fields.Selection([
        ('front', 'Ön Yüz'),
        ('back', 'Arka Yüz'),
        ('side', 'Yan Yüz'),
        ('detail', 'Detay'),
    ], string='Fotoğraf Tipi', required=True)
    detail_placement = fields.Selection([
        ('front', 'Ön Yüzde'),
        ('back', 'Arka Yüzde'),
    ], string='Detay Konumu', default='front')
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

    @api.constrains('session_id', 'photo_type', 'detail_placement', 'set_line_id')
    def _check_photo_limits(self):
        """Bir oturumda (veya set parçasında) her açı ve detay konumundan en fazla 1 adet fotoğraf çekilebilir."""
        for photo in self:
            if not photo.session_id:
                continue
            domain = [
                ('session_id', '=', photo.session_id.id),
                ('photo_type', '=', photo.photo_type),
                ('id', '!=', photo.id),
            ]
            if photo.set_line_id:
                domain.append(('set_line_id', '=', photo.set_line_id.id))
            else:
                domain.append(('set_line_id', '=', False))

            if photo.photo_type == 'detail':
                placement = photo.detail_placement or 'front'
                domain.append(('detail_placement', '=', placement))
                existing = self.search_count(domain)
                if existing > 0:
                    placement_label = 'Ön Yüz Detayı' if placement == 'front' else 'Arka Yüz Detayı'
                    raise ValidationError(
                        _("Bu oturumda zaten 1 adet '%s' fotoğrafı mevcut! En fazla 1 adet Ön Detay ve 1 adet Arka Detay fotoğrafı eklenebilir.") % placement_label
                    )
            else:
                existing = self.search_count(domain)
                if existing > 0:
                    type_label = dict(self._fields['photo_type'].selection).get(photo.photo_type, photo.photo_type)
                    raise ValidationError(
                        _("Bu oturumda zaten 1 adet '%s' fotoğrafı mevcut! Her açıdan en fazla 1 adet fotoğraf eklenebilir.") % type_label
                    )

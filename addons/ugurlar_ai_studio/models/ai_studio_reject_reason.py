import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class AiStudioRejectReason(models.Model):
    """Red sebepleri kütüphanesi.

    AI üretimlerinin reddedilme sebeplerini standartlaştırır.
    Zaman içinde hangi hataların sık yaşandığını ölçmek için kullanılır.
    """
    _name = 'ai.studio.reject.reason'
    _description = 'AI Stüdyo Red Sebebi'
    _order = 'sequence, id'

    name = fields.Char(string='Red Sebebi', required=True, translate=True)
    code = fields.Char(string='Kod', help='Kısa tanımlama kodu')
    suggested_prompt = fields.Text(
        string='Önerilen Revizyon Promptu',
        help='Bu sebep seçildiğinde otomatik önerilen prompt',
    )
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(string='Aktif', default=True)
    count = fields.Integer(
        string='Kullanım Sayısı',
        compute='_compute_count',
    )

    def _compute_count(self):
        """Bu sebebin kaç kez seçildiğini hesapla."""
        gen_model = self.env['ai.studio.generation']
        for reason in self:
            reason.count = gen_model.search_count([
                ('reject_reason_id', '=', reason.id),
            ])

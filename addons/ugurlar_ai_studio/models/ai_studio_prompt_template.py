import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class AiStudioPromptTemplate(models.Model):
    """Prompt şablon kütüphanesi.

    Sık kullanılan prompt'ları kayıt altına alır.
    Global, kategori bazlı veya ürün bazlı scope destekler.
    """
    _name = 'ai.studio.prompt.template'
    _description = 'AI Stüdyo Prompt Şablonu'
    _order = 'name'

    name = fields.Char(string='Şablon Adı', required=True)
    scope = fields.Selection([
        ('global', 'Global'),
        ('category', 'Kategori Bazlı'),
        ('product', 'Ürün Bazlı'),
    ], string='Kapsam', default='global', required=True)
    category_id = fields.Many2one(
        'product.category',
        string='Ürün Kategorisi',
        help='Kapsam "Kategori Bazlı" ise hangi kategori için geçerli',
    )
    prompt_text = fields.Text(string='Prompt Metni', required=True)
    usage_count = fields.Integer(
        string='Kullanım Sayısı',
        compute='_compute_stats',
    )
    success_rate = fields.Float(
        string='Başarı Oranı (%)',
        compute='_compute_stats',
        digits=(5, 1),
    )
    active = fields.Boolean(string='Aktif', default=True)

    def _compute_stats(self):
        """Kullanım sayısı ve başarı oranını hesapla."""
        session_model = self.env['ai.studio.session']
        for template in self:
            groups = session_model._read_group(
                [('prompt_template_id', '=', template.id)],
                groupby=['state'],
                aggregates=['__count']
            )
            total = 0
            done_count = 0
            for state, count in groups:
                total += count
                if state == 'done':
                    done_count += count

            template.usage_count = total
            if total > 0:
                template.success_rate = (done_count / total) * 100.0
            else:
                template.success_rate = 0.0

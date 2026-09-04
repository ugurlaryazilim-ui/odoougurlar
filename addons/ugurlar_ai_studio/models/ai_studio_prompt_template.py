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
        
        self.usage_count = 0
        self.success_rate = 0.0
        
        if not self.ids:
            return
            
        groups = session_model._read_group(
            [('prompt_template_id', 'in', self.ids)],
            ['prompt_template_id', 'state'],
            ['__count']
        )
        
        stats = {}
        for template, state, count in groups:
            if template.id not in stats:
                stats[template.id] = {'total': 0, 'done': 0}
            stats[template.id]['total'] += count
            if state == 'done':
                stats[template.id]['done'] += count
                
        for template in self:
            ts = stats.get(template.id)
            if ts:
                template.usage_count = ts['total']
                template.success_rate = (ts['done'] / ts['total']) * 100.0 if ts['total'] > 0 else 0.0

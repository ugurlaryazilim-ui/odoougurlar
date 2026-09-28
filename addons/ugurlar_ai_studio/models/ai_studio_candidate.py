import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiStudioGenerationCandidate(models.Model):
    """Aynı istekte üretilen alternatif AI görseli.

    Seedream num_images > 1 ile çağrıldığında ilk görsel generation'ın ana
    görseli olur, diğerleri burada tutulur. Reviewer bir adayı seçtiğinde ana
    görselle yer değiştirir; sync agent her zaman generation.generated_image'ı
    dışarı aktardığı için başka bir değişiklik gerekmez.
    """
    _name = 'ai.studio.generation.candidate'
    _description = 'AI Üretim Adayı'
    _order = 'sequence, id'

    generation_id = fields.Many2one(
        'ai.studio.generation', string='Üretim', required=True,
        ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    image = fields.Image(string='Aday Görsel', attachment=True, required=True)

    def action_select(self):
        """Bu adayı ana görsel yap; önceki ana görsel aday olarak kalır."""
        self.ensure_one()
        gen = self.generation_id
        gen._check_ai_studio_group('reviewer')
        if gen.state != 'done':
            raise UserError(_('Sadece tamamlanmış üretimlerde aday seçilebilir.'))
        previous = gen.generated_image
        gen.write({
            'generated_image': self.image,
            'quality_details': _('Reviewer tarafından alternatif aday seçildi.'),
        })
        self.write({'image': previous})
        gen.session_id.message_post(body=_('%s görseli için alternatif aday seçildi.')
                                    % dict(gen._fields['photo_type'].selection).get(gen.photo_type, ''))
        return True

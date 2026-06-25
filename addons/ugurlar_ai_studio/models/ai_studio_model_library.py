import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiStudioModelLibrary(models.Model):
    """Manken Kutuphanesi.

    Onceden hazirlanmis manken gorsellerini cinsiyet, vucut tipi,
    ten rengi ve poz turune gore kategorize eder.
    Preset olusturulurken kutuphane mankeni secilerek hizli baslangic saglanir.
    """
    _name = 'ai.studio.model.library'
    _description = 'Manken Kutuphanesi'
    _order = 'sequence, name'

    name = fields.Char(string='Ad', required=True)
    sequence = fields.Integer(string='Sira', default=10)

    gender = fields.Selection([
        ('female', 'Kadin'),
        ('male', 'Erkek'),
        ('child', 'Cocuk'),
    ], string='Cinsiyet', required=True, default='female')

    body_type = fields.Selection([
        ('standard', 'Standart'),
        ('plus_size', 'Buyuk Beden'),
        ('petite', 'Kucuk Beden'),
    ], string='Vucut Tipi', default='standard')

    skin_tone = fields.Selection([
        ('light', 'Acik'),
        ('medium', 'Orta'),
        ('olive', 'Zeytin'),
        ('dark', 'Koyu'),
    ], string='Ten Rengi', default='medium')

    age_group = fields.Selection([
        ('young_adult', 'Genc Yetiskin'),
        ('adult', 'Yetiskin'),
        ('mature', 'Olgun'),
    ], string='Yas Grubu', default='adult')

    image_front = fields.Image(
        string='Onden Gorsel',
        max_width=1920, max_height=1920,
    )
    image_back = fields.Image(
        string='Arkadan Gorsel',
        max_width=1920, max_height=1920,
    )
    image_side = fields.Image(
        string='Yandan Gorsel',
        max_width=1920, max_height=1920,
    )

    source = fields.Selection([
        ('uploaded', 'Yuklenen'),
        ('ai_generated', 'AI Uretimi'),
        ('stock', 'Stok'),
    ], string='Kaynak', default='uploaded')

    pose_type = fields.Selection([
        ('straight', 'Duz Durus'),
        ('contrapposto', 'Kontrapposto'),
        ('walking', 'Yuruyus'),
    ], string='Poz Tipi', default='straight')

    active = fields.Boolean(string='Aktif', default=True)
    notes = fields.Text(string='Notlar')
    usage_count = fields.Integer(string='Kullanim Sayisi', default=0)

    preset_ids = fields.One2many(
        'ai.studio.model.preset',
        'library_mannequin_id',
        string='Kullanilan Presetler',
    )

    def action_apply_to_preset(self):
        """Kutuphane manken gorsellerini mevcut preset'e kopyalar.

        Aktif context'teki preset_id'yi kullanarak gorunturleri atar.
        """
        self.ensure_one()
        preset_id = self.env.context.get('active_id')
        if not preset_id:
            raise UserError(_('Aktif bir preset bulunamadi.'))

        preset = self.env['ai.studio.model.preset'].browse(preset_id)
        if not preset.exists():
            raise UserError(_('Preset bulunamadi.'))

        vals = {'library_mannequin_id': self.id}
        if self.image_front:
            vals['model_image_front'] = self.image_front
        if self.image_back:
            vals['model_image_back'] = self.image_back
        if self.image_side:
            vals['model_image_side'] = self.image_side

        preset.write(vals)

        # Kullanim sayacini artir
        self.sudo().write({'usage_count': self.usage_count + 1})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Manken Uygulandı'),
                'message': _('"%s" mankeni preset\'e uygulandı.') % self.name,
                'type': 'success',
                'sticky': False,
            },
        }

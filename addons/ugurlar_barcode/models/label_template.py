import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class LabelTemplate(models.Model):
    _name = 'ugurlar.label.template'
    _description = 'Etiket Şablonu'
    _order = 'is_default desc, name'

    name = fields.Char('Şablon Adı', required=True)
    width_mm = fields.Float('Genişlik (mm)', default=60, required=True)
    height_mm = fields.Float('Yükseklik (mm)', default=40, required=True)
    elements_json = fields.Text('Eleman Verisi (JSON)', default='[]')
    is_default = fields.Boolean('Varsayılan', default=False)
    user_id = fields.Many2one('res.users', string='Oluşturan',
                              default=lambda self: self.env.uid)

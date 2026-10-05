import re

from odoo import api, fields, models

PLACEHOLDER = re.compile(r'\{(\w+)\}')


class SmsSystemTemplate(models.Model):
    """SMS şablonu — {musteri}, {siparis} gibi yer tutucular gönderen modülün verdiği değerlerle doldurulur."""
    _name = 'sms.system.template'
    _description = 'SMS Şablonu'
    _order = 'name'

    name = fields.Char(string='Ad', required=True)
    code = fields.Char(string='Kod', help='Modüllerin şablonu bulmak için kullandığı teknik kod (ör. tailor_ready)')
    body = fields.Text(string='Metin', required=True)
    model = fields.Char(string='Kullanıldığı Model', help='Boşsa her yerde seçilebilir')
    active = fields.Boolean(default=True)
    placeholders = fields.Char(string='Yer Tutucular', compute='_compute_placeholders')

    _unique_code = models.Constraint('UNIQUE(code)', 'Bu kodda bir SMS şablonu zaten var!')

    @api.depends('body')
    def _compute_placeholders(self):
        for tpl in self:
            tpl.placeholders = ', '.join('{%s}' % p for p in dict.fromkeys(PLACEHOLDER.findall(tpl.body or '')))

    def render(self, values):
        """Yer tutucuları doldur; bilinmeyenler boş bırakılır."""
        self.ensure_one()
        values = values or {}
        return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), '') or ''), self.body or '').strip()

    @api.model
    def get_by_code(self, code):
        return self.search([('code', '=', code)], limit=1)

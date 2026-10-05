from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.turatel import normalize_number, prepare_text, segment_count


class SmsSendWizard(models.TransientModel):
    """Herhangi bir kayıttan 'SMS Gönder' penceresi.

    Context: default_number, default_res_model, default_res_id, default_template_code,
    sms_values (şablon yer tutucuları için dict).
    """
    _name = 'sms.system.send.wizard'
    _description = 'SMS Gönder'

    number = fields.Char(string='Cep Telefonu', required=True)
    template_id = fields.Many2one('sms.system.template', string='Şablon')
    body = fields.Text(string='Metin', required=True)
    res_model = fields.Char()
    res_id = fields.Integer()
    char_count = fields.Integer(string='Karakter', compute='_compute_counts')
    segments = fields.Integer(string='Parça (tahmini)', compute='_compute_counts')
    number_ok = fields.Boolean(compute='_compute_counts')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        code = self.env.context.get('default_template_code')
        if code and 'template_id' in fields_list:
            tpl = self.env['sms.system.template'].get_by_code(code)
            if tpl:
                res['template_id'] = tpl.id
                res['body'] = tpl.render(self.env.context.get('sms_values') or {})
        return res

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.body = self.template_id.render(self.env.context.get('sms_values') or {})

    @api.depends('body', 'number')
    def _compute_counts(self):
        ascii_mode = self.env['ir.config_parameter'].sudo().get_param('sms_system.ascii_mode') == 'True'
        for wiz in self:
            text, sms_type = prepare_text(wiz.body or '', ascii_mode=ascii_mode)
            wiz.char_count = len(text)
            wiz.segments = segment_count(text, sms_type) if text else 0
            wiz.number_ok = bool(normalize_number(wiz.number))

    def action_send(self):
        self.ensure_one()
        if not self.number_ok:
            raise UserError(_('Geçerli bir cep telefonu girin (ör. 0532 123 45 67).'))
        record = None
        if self.res_model and self.res_id and self.res_model in self.env:
            record = self.env[self.res_model].browse(self.res_id).exists() or None
        msg = self.env['sms.system.message'].send_sms(self.number, self.body, record=record,
                                                      template=self.template_id or None)
        states = dict(msg._fields['state'].selection)
        ok = msg.state in ('sent', 'test')
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('SMS'),
                'message': (_('SMS %s.') % states[msg.state].lower()) if ok else (msg.error or _('SMS gönderilemedi.')),
                'type': 'success' if ok else 'danger',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

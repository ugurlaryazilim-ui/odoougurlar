from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.turatel import ERROR_HINTS, TuratelError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sms_turatel_url = fields.Char(string='Turatel API Adresi', config_parameter='sms_system.turatel_url',
                                  help='Boşsa https://processor.smsorigin.com/xml/process.aspx kullanılır')
    sms_turatel_channel_code = fields.Char(string='Kanal Kodu', config_parameter='sms_system.turatel_channel_code',
                                           groups='base.group_system')
    sms_turatel_username = fields.Char(string='Kullanıcı Adı', config_parameter='sms_system.turatel_username',
                                       groups='base.group_system')
    sms_turatel_password = fields.Char(string='Şifre', config_parameter='sms_system.turatel_password',
                                       groups='base.group_system')
    sms_turatel_originator = fields.Char(string='Mesaj Başlığı', config_parameter='sms_system.turatel_originator',
                                         help='Turatel hesabında onaylı gönderici adı (en fazla 11 karakter)')
    sms_ascii_mode = fields.Boolean(string='Türkçe karakterleri dönüştür', config_parameter='sms_system.ascii_mode',
                                    help='ı ş ğ İ Ş Ğ harflerini i s g I S G yapar; mesaj daha az parçaya bölünür')
    sms_test_mode = fields.Boolean(string='Test modu', config_parameter='sms_system.test_mode', default=True,
                                   help='Açıkken SMS gönderilmez, yalnız kayıt oluşur')

    def action_sms_check_credit(self):
        self.ensure_one()
        self.execute()  # ekrandaki değerler kaydedilsin
        try:
            answer = self.env['sms.system.message'].check_credit()
        except TuratelError as e:
            raise UserError(str(e))
        hint = ERROR_HINTS.get(answer.strip())
        message = _('Turatel cevabı: %s') % answer
        if hint:
            message += _(' — bu bir hata kodu olabilir: %s') % hint
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Turatel Bağlantısı'), 'message': message,
                       'type': 'warning' if hint else 'success', 'sticky': True},
        }

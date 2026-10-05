from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.smartadm import SmartAdmError
from ..services.turatel import normalize_number

SOURCES = [
    ('HS_FIZIKSEL_ORTAM', 'Mağazada (fiziksel ortam)'),
    ('HS_ISLAK_IMZA', 'Islak imzalı form'),
    ('HS_ETKINLIK', 'Etkinlik'),
    ('HS_WEB', 'Web sitesi'),
    ('HS_CAGRI_MERKEZI', 'Çağrı merkezi'),
]
MAX_BUSINESS_DAYS = 3  # İYS kuralı H467: 3 iş gününden eski izin yüklenemez


def business_days_between(start, end):
    """start ile end arasındaki hafta içi gün sayısı (start günü hariç)."""
    days, day = 0, start.date()
    while day < end.date():
        day += timedelta(days=1)
        if day.weekday() < 5:
            days += 1
    return days


class SmsIysConsent(models.TransientModel):
    """Müşteriden ticari SMS izni al ve İYS'ye kaydet.

    1) Onay kodu: SmartADM müşteriye 6 haneli kod gönderir, kod girilince izin kaydolur.
    2) Form: kâğıt formla / sözlü alınmış izin, kaynak ve tarih ile yüklenir (en fazla 3 iş günü önce).
    """
    _name = 'sms.system.iys.consent'
    _description = 'İYS İzni Al'

    mobile = fields.Char(string='Cep Telefonu', required=True)
    name = fields.Char(string='Ad Soyad')
    method = fields.Selection([('code', 'Müşteriye onay kodu gönder'), ('form', 'Form ile alındı (imzalı / sözlü)')],
                              string='Yöntem', default='code', required=True)
    source = fields.Selection(SOURCES, string='İznin Alındığı Yer', default='HS_FIZIKSEL_ORTAM')
    consent_date = fields.Datetime(string='İzin Tarihi', default=fields.Datetime.now)
    list_id = fields.Many2one('sms.system.list', string='Eklenecek Liste')
    step = fields.Selection([('start', 'Başla'), ('code', 'Kod'), ('done', 'Bitti')], default='start')
    trigger_id = fields.Char(readonly=True)
    activation_key = fields.Char(string='Müşteriye Gelen Kod', size=6)
    result = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contact = self.env['sms.system.contact'].browse(self.env.context.get('default_contact_id'))
        if contact.exists():
            res.setdefault('mobile', contact.mobile)
            res.setdefault('name', contact.name)
        return res

    def _number(self):
        num = normalize_number(self.mobile)
        if not num:
            raise UserError(_('Geçerli bir cep telefonu girin.'))
        return num

    def _check_enabled(self):
        if not self.env['sms.system.iys']._enabled():
            raise UserError(_('İYS bağlantısı kapalı. Ayarlar > SMS > İYS bölümünden açın.'))

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('İYS İzni Al')}

    def _save_contact(self, source):
        num = self._number()
        Contact = self.env['sms.system.contact'].sudo()
        Contact.upsert_numbers([{'mobile': num, 'name': self.name}], 'manual', lists=self.list_id or None)
        contact = Contact.with_context(active_test=False).search([('mobile', '=', num)], limit=1)
        contact.write({'iys_status': 'approved', 'iys_checked_at': fields.Datetime.now(), 'iys_source': source})
        return contact

    def action_send_code(self):
        self.ensure_one()
        self._check_enabled()
        try:
            trigger_id = self.env['sms.system.iys']._client().trigger(self._number())
        except SmartAdmError as e:
            raise UserError(str(e)) from e
        self.write({'trigger_id': trigger_id, 'step': 'code'})
        return self._reopen()

    def action_approve(self):
        self.ensure_one()
        self._check_enabled()
        if not (self.activation_key or '').strip().isdigit():
            raise UserError(_('Müşterinin telefonuna gelen 6 haneli kodu girin.'))
        try:
            self.env['sms.system.iys']._client().approve(self.trigger_id, self.activation_key)
        except SmartAdmError as e:
            raise UserError(str(e)) from e
        self._save_contact('HS_MESAJ')
        self.write({'step': 'done', 'result': _('İzin İYS\'ye kaydedildi; numara ticari SMS alabilir.')})
        return self._reopen()

    def action_load_form(self):
        self.ensure_one()
        self._check_enabled()
        now = fields.Datetime.now()
        when = self.consent_date or now
        if when > now + timedelta(minutes=5):
            raise UserError(_('İzin tarihi ileri bir tarih olamaz.'))
        if business_days_between(when, now) > MAX_BUSINESS_DAYS:
            raise UserError(_('İYS kuralı: 3 iş gününden eski izinler yüklenemez.'))
        local = fields.Datetime.context_timestamp(self, when).replace(tzinfo=None)
        try:
            self.env['sms.system.iys']._client().contact_api_load(self._number(), True, local, self.source)
        except SmartAdmError as e:
            raise UserError(str(e)) from e
        self._save_contact(self.source)
        self.write({'step': 'done', 'result': _('İzin İYS\'ye yüklendi; numara ticari SMS alabilir.')})
        return self._reopen()

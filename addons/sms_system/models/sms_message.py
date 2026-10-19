import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.turatel import (MAX_SEGMENTS, TuratelClient, TuratelError, normalize_number, prepare_text,
                                segment_count)

_logger = logging.getLogger(__name__)

MAX_RETRY = 3
DEFAULT_USER_DAILY_LIMIT = 50


def test_mode_enabled(value):
    """Test modu tek kaynağı (K2): yalnız tam 'False' kapatır.

    Parametrenin yokluğu, boş değer, 'True', '0', 'false' ya da başka her değer test modunu AÇIK sayar:
    bozuk/silinmiş bir ayar canlı gönderime yol açmamalı.
    """
    return value != 'False'


def parse_user_daily_limit(value):
    """Kullanıcı başı günlük elle SMS sınırı: parametre yok/boş/bozuk/negatifse 50; '0' korunur (sınırsız)."""
    if not value:   # get_param yokluğu/boşu False döndürür; int(False) == 0 yanlışlıkla "sınırsız" olurdu
        return DEFAULT_USER_DAILY_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_USER_DAILY_LIMIT
    return limit if limit >= 0 else DEFAULT_USER_DAILY_LIMIT


class SmsSystemMessage(models.Model):
    """Gönderilen her SMS'in kaydı (numara başına bir kayıt)."""
    _name = 'sms.system.message'
    _description = 'SMS Gönderim Kaydı'
    _order = 'id desc'
    _rec_name = 'number'

    number = fields.Char(string='Numara', required=True, index=True)
    body = fields.Text(string='Metin', required=True)
    originator = fields.Char(string='Başlık')
    sms_type = fields.Selection([('1', 'Normal'), ('2', 'Türkçe karakterli')], string='Tür', default='1')
    segments = fields.Integer(string='Parça (tahmini)')
    state = fields.Selection([
        ('queued', 'Kuyrukta'),
        ('sending', 'Gönderiliyor'),
        ('sent', 'Gönderildi'),
        ('test', 'Test (gönderilmedi)'),
        ('error', 'Hata'),
    ], string='Durum', default='queued', required=True, index=True)
    provider_msg_id = fields.Char(string='Turatel Mesaj No', index=True)
    provider_answer = fields.Char(string='Sağlayıcı Cevabı')
    error = fields.Text(string='Hata')
    retry_count = fields.Integer(string='Deneme', default=0)
    delivery_report = fields.Text(string='İletim Raporu')
    sent_at = fields.Datetime(string='Gönderim Zamanı')
    res_model = fields.Char(string='Kaynak Model', index=True)
    res_id = fields.Integer(string='Kaynak Kayıt', index=True)
    template_id = fields.Many2one('sms.system.template', string='Şablon', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Gönderen', default=lambda self: self.env.user, index=True)
    campaign_id = fields.Many2one('sms.system.campaign', string='Toplu SMS', index=True, ondelete='cascade')
    manual = fields.Boolean(string='Elle Gönderildi', help='"Yeni SMS" penceresinden serbest metinle gönderildi')
    contact_id = fields.Many2one('sms.system.contact', string='Rehber Kişisi', index='btree_not_null',
                                 ondelete='set null')

    # ── Ayarlar ──

    @api.model
    def _settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        return {
            'url': icp.get_param('sms_system.turatel_url') or None,
            'channel_code': icp.get_param('sms_system.turatel_channel_code', ''),
            'username': icp.get_param('sms_system.turatel_username', ''),
            'password': icp.get_param('sms_system.turatel_password', ''),
            'originator': icp.get_param('sms_system.turatel_originator', ''),
            'ascii_mode': icp.get_param('sms_system.ascii_mode') == 'True',
            'test_mode': test_mode_enabled(icp.get_param('sms_system.test_mode')),
        }

    @api.model
    def _client(self, cfg=None):
        cfg = cfg or self._settings()
        return TuratelClient(cfg['channel_code'], cfg['username'], cfg['password'], url=cfg['url'])

    # ── Gönderim API'si (diğer modüller bunu kullanır) ──

    @api.model
    @api.private
    def send_sms(self, numbers, body=None, record=None, template=None, values=None, originator=None):
        """SMS gönder ve kayıtlarını döndür.

        numbers: tek numara ya da liste. body verilmezse template + values ile üretilir.
        record: kaynak kayıt (iz için); chatter'ı varsa gönderim notu düşülür.
        Geçersiz numara UserError verir. Sağlayıcı hatası kaydı 'error' bırakır (istisna fırlatmaz).
        RPC'ye kapalıdır (@api.private): yalnız Python'dan çağrılır. Kayıtlar sudo ile oluşturulur
        (normal kullanıcının mesaj ACL'i yalnız okuma) ve gönderen çağıran kullanıcıdır; dönen recordset
        çağıranın env'indedir (kendi kaydını rule_sms_message_own ile okur).
        """
        if isinstance(numbers, str):
            numbers = [numbers]
        if template and not body:
            body = template.render(values or {})
        if not (body or '').strip():
            raise UserError(_('SMS metni boş olamaz.'))
        normalized = []
        for raw in numbers:
            num = normalize_number(raw)
            if not num:
                raise UserError(_('Geçersiz cep telefonu: %s') % raw)
            if num not in normalized:
                normalized.append(num)

        cfg = self._settings()
        text, sms_type = prepare_text(body, ascii_mode=cfg['ascii_mode'])
        if segment_count(text, sms_type) > MAX_SEGMENTS:
            raise UserError(_('SMS metni çok uzun (%(n)s parça). En fazla %(max)s parça gönderilebilir; metni kısaltın.',
                              n=segment_count(text, sms_type), max=MAX_SEGMENTS))
        manual = bool(self.env.context.get('sms_manual'))
        if manual:
            self._check_manual_limit(len(normalized))
        sender = originator or cfg['originator']
        messages = self.sudo().create([{
            'user_id': self.env.uid,
            'number': num,
            'body': text,
            'originator': sender,
            'sms_type': sms_type,
            'segments': segment_count(text, sms_type),
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
            'template_id': template.id if template else False,
            'manual': manual,
        } for num in normalized])
        messages._deliver(cfg)
        if record and hasattr(record, 'message_post'):
            states = dict(self._fields['state'].selection)
            for msg in messages:
                record.message_post(body=_('SMS → %(num)s [%(state)s]: %(text)s') % {
                    'num': msg.number, 'state': states[msg.state], 'text': msg.body})
        return messages.with_env(self.env)

    @api.model
    def _check_manual_limit(self, count):
        """'Yeni SMS' ile serbest metin gönderiminde kullanıcı başı 24 saatlik sınır (yönetici muaf)."""
        if self.env.user.has_group('sms_system.group_sms_manager'):
            return
        limit = parse_user_daily_limit(self.env['ir.config_parameter'].sudo().get_param('sms_system.user_daily_limit'))
        if not limit:
            return
        since = fields.Datetime.now() - timedelta(days=1)
        used = self.sudo().search_count([('user_id', '=', self.env.uid), ('manual', '=', True),
                                         ('create_date', '>=', since)])
        if used + count > limit:
            raise UserError(_('Günlük elle SMS sınırınız doldu (%(limit)s). Yöneticinize başvurun.', limit=limit))

    def _deliver(self, cfg=None):
        """Kayıtları Turatel'e gönder (sudo ile çağrılır)."""
        cfg = cfg or self._settings()
        if not cfg['originator']:
            for msg in self:
                if not msg.originator:
                    msg.write({'state': 'error', 'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
            self = self.filtered(lambda m: m.originator)
        if cfg['test_mode']:
            self.write({'state': 'test', 'sent_at': fields.Datetime.now(), 'provider_answer': 'TEST'})
            return
        client = self._client(cfg)
        for msg in self:
            try:
                msg_id, answer = client.send([msg.number], msg.body, msg.originator, msg.sms_type)
                msg.write({'state': 'sent', 'provider_msg_id': msg_id, 'provider_answer': answer,
                           'sent_at': fields.Datetime.now(), 'error': False})
            except TuratelError as e:
                _logger.warning('SMS gönderilemedi (%s): %s', msg.id, e)
                # Kalıcı hatalar (hesap/başlık/kredi/numara) otomatik yeniden denenmez
                msg.write({'state': 'error', 'error': str(e),
                           'retry_count': msg.retry_count + 1 if e.retryable else MAX_RETRY})

    def _deliver_pack(self, cfg, client):
        """Aynı metni taşıyan kayıtları tek Turatel isteğiyle gönder (toplu SMS kuyruğu, sudo)."""
        if not self:
            return
        first = self[0]
        if not first.originator:
            self.write({'state': 'error', 'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
            return
        if cfg['test_mode']:
            self.write({'state': 'test', 'sent_at': fields.Datetime.now(), 'provider_answer': 'TEST'})
            return
        try:
            msg_id, answer = client.send(self.mapped('number'), first.body, first.originator, first.sms_type)
            self.write({'state': 'sent', 'provider_msg_id': msg_id, 'provider_answer': answer,
                        'sent_at': fields.Datetime.now(), 'error': False})
        except TuratelError as e:
            _logger.warning('Toplu SMS paketi gönderilemedi (%s numara): %s', len(self), e)
            self.write({'state': 'error', 'error': str(e)})

    # ── Butonlar / cron ──

    def action_retry(self):
        self.filtered(lambda m: m.state in ('error', 'queued') and not m.campaign_id).sudo()._deliver()

    def action_fetch_report(self):
        client = self._client()
        for msg in self.filtered('provider_msg_id'):
            try:
                msg.sudo().delivery_report = client.report(msg.provider_msg_id)[:2000]
            except TuratelError as e:
                msg.sudo().delivery_report = str(e)

    @api.model
    def _cron_retry_failed(self):
        """Ağ hatası vb. başarısız gönderimleri sınırlı sayıda yeniden dene (son 1 gün)."""
        since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        failed = self.sudo().search([('state', 'in', ('error', 'queued')), ('retry_count', '<', MAX_RETRY),
                                     ('campaign_id', '=', False), ('create_date', '>=', since)], limit=50)
        failed._deliver()

    @api.model
    @api.private
    def check_credit(self):
        """Ayarlar ekranındaki 'Bağlantı / Kredi' butonu."""
        return self._client().credit()

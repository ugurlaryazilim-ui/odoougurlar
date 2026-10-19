import logging
from datetime import timedelta

from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services.turatel import (MAX_SEGMENTS, TuratelClient, TuratelError, normalize_number, prepare_text,
                                segment_count)

_logger = logging.getLogger(__name__)

MAX_RETRY = 3
DEFAULT_USER_DAILY_LIMIT = 50
QUEUE_BATCH = 50
# Tekli kayıt bu kadar dakikadır 'gönderiliyor'daysa belirsiz sayılır (kampanyadaki eşikle aynı)
SINGLE_STUCK_MINUTES = 15
# Cron süresinin sonuna bu kadar saniye kala dur; kalanlar sonraki çalışmada
SINGLE_MIN_TIME_LEFT = 20


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
        ('uncertain', 'Belirsiz'),
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
    def send_sms(self, numbers, body=None, record=None, template=None, values=None, originator=None,
                 queue=False):
        """SMS gönder ve kayıtlarını döndür.

        numbers: tek numara ya da liste. body verilmezse template + values ile üretilir.
        record: kaynak kayıt (iz için); chatter'ı varsa gönderim notu düşülür.
        queue: True ise sağlayıcı çağrılmaz; kayıt 'queued' kalır ve tekli kuyruk cron'u tetiklenir
        (başlık yoksa 'error', test modunda 'test'). İstek süresini sağlayıcıya bağlamamak için (KK-B11).
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
        if record:
            # Sağlayıcıdan ÖNCE: yetkisiz kayıtta SMS hiç gitmez (sonra gelen AccessError kaydı geri alırdı, G-1)
            self._check_record_access(record)
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
        if queue:
            if messages._settle_without_provider(cfg):
                self._trigger_send_queue()
        else:
            messages._deliver(cfg)
        if record and hasattr(record, 'message_post'):
            self._post_sms_note(record, messages)
        return messages.with_env(self.env)

    @api.model
    def _check_record_access(self, record):
        """Kaynak kayda gönderim notu düşülebilir mi: chatter'lı kayıtta not yazma yetkisi (_mail_post_access,
        varsayılan write), diğerlerinde okuma. Yetkisizse AccessError; sağlayıcı çağrılmadan önce çalışır."""
        if hasattr(record, 'message_post'):
            operations = set(record._mail_get_operation_for_mail_message_operation('create').values())
        else:
            operations = {'read'}
        for operation in operations:
            record.check_access(operation)

    @api.model
    def _post_sms_note(self, record, messages):
        """Kaynak kayda gönderim notu. Sağlayıcı çağrısından sonra çalışır: hiçbir hata SMS kaydını (iz ve günlük
        sınır sayacı) geri aldırmamalı. Not savepoint içinde yazılır, hata yalnız loglanır."""
        states = dict(self._fields['state'].selection)
        try:
            with self.env.cr.savepoint():
                for msg in messages:
                    record.message_post(body=_('SMS → %(num)s [%(state)s]: %(text)s') % {
                        'num': msg.number, 'state': states[msg.state], 'text': msg.body})
        except Exception:  # noqa: BLE001 — SMS gitti/kuyrukta; not yazılamaması kaydı geri aldırmamalı
            _logger.warning('SMS gönderim notu kaynak kayda yazılamadı (%s,%s); SMS kayıtları korundu (%s)',
                            record._name, record.id, messages.ids, exc_info=True)

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

    def _settle_without_provider(self, cfg):
        """Sağlayıcıya gitmeden sonuçlanan kayıtları kapat, gönderilmesi gerekenleri döndür (sudo).

        Başlık yoksa kalıcı hata; test modunda 'test' (KK-A27). Senkron gönderim, kuyruk ve yeniden
        deneme aynı kapıdan geçer: test modu tek yerde uygulanır.
        """
        pending = self
        if not cfg['originator']:
            missing = pending.filtered(lambda m: not m.originator)
            # Kalıcı hata: başlık sonradan girilse de otomatik gönderilmez (retry_count=MAX)
            missing.write({'state': 'error', 'retry_count': MAX_RETRY,
                           'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
            pending -= missing
        if cfg['test_mode']:
            pending.write({'state': 'test', 'sent_at': fields.Datetime.now(), 'provider_answer': 'TEST'})
            return self.browse()
        return pending

    def _deliver(self, cfg=None):
        """Kayıtları Turatel'e gönder (sudo ile çağrılır)."""
        cfg = cfg or self._settings()
        pending = self._settle_without_provider(cfg)
        if not pending:
            return
        client = self._client(cfg)
        for msg in pending:
            try:
                msg_id, answer = client.send([msg.number], msg.body, msg.originator, msg.sms_type)
                msg.write({'state': 'sent', 'provider_msg_id': msg_id, 'provider_answer': answer,
                           'sent_at': fields.Datetime.now(), 'error': False})
            except TuratelError as e:
                _logger.warning('SMS gönderilemedi (%s): %s', msg.id, e)
                if e.uncertain:
                    # Gidip gitmediği belirsiz: asla otomatik yeniden gönderilmez (mükerrer SMS riski)
                    msg.write({'state': 'uncertain', 'error': str(e), 'retry_count': MAX_RETRY})
                else:
                    # Kalıcı hatalar (hesap/başlık/kredi/numara) otomatik yeniden denenmez
                    msg.write({'state': 'error', 'error': str(e),
                               'retry_count': msg.retry_count + 1 if e.retryable else MAX_RETRY})

    def _deliver_pack(self, cfg, client):
        """Aynı metni taşıyan kayıtları tek Turatel isteğiyle gönder (toplu SMS kuyruğu, sudo)."""
        if not self:
            return
        first = self[0]
        if not first.originator:
            self.write({'state': 'error', 'retry_count': MAX_RETRY,
                        'error': _('Mesaj başlığı (Originator) ayarlanmamış.')})
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
            if e.uncertain:
                # Paket Turatel'e ulaşmış olabilir: kayıtlar belirsiz kalır, "Hatalıları Yeniden Gönder" almaz
                self.write({'state': 'uncertain', 'error': str(e), 'retry_count': MAX_RETRY})
            else:
                self.write({'state': 'error', 'error': str(e)})

    # ── Butonlar / cron ──

    def action_retry(self):
        """'Yeniden Gönder': kampanyasız 'error' kayıtları kuyruğa alır; senkron göndermez, commit etmez.

        Belirsiz, gönderiliyor ya da başka bir işlemde kilitli kayıtlar atlanır (KK-A16, A17).
        retry_count değişmez; gönderim kuyruk cron'unun tetiklenmesiyle saniyeler içinde yapılır.
        Yalnız SMS yöneticisi: düğmedeki groups yalnız görünürlüktür, RPC yolunu sunucu tarafı denetim kapatır (G-3).
        """
        if not (self.env.su or self.env.user.has_group('sms_system.group_sms_manager')):
            raise AccessError(_('Yalnız SMS yöneticileri SMS yeniden gönderebilir.'))
        candidates = self.filtered(lambda m: m.state == 'error' and not m.campaign_id)
        queued = self.sudo()._lock_for_send(candidates.ids, ('error',))
        if queued:
            queued.write({'state': 'queued'})
            self._trigger_send_queue()
            message = _('%s kayıt kuyruğa alındı; birkaç saniye içinde gönderilir.') % len(queued)
        else:
            message = _('Kuyruğa alınacak kayıt yok.')
        skipped = len(self) - len(queued)
        if skipped:
            message += ' ' + _('%s kayıt atlandı (yalnız hatalı kayıtlar yeniden gönderilir; belirsiz, '
                               'gönderiliyor ya da başka bir işlemde olanlar atlanır).') % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'success' if queued else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_fetch_report(self):
        client = self._client()
        for msg in self.filtered('provider_msg_id'):
            try:
                msg.sudo().delivery_report = client.report(msg.provider_msg_id)[:2000]
            except TuratelError as e:
                msg.sudo().delivery_report = str(e)

    # ── Tekli kuyruk (KK-A16, A17, B11) ──

    @api.model
    def _trigger_send_queue(self):
        """Tekli kuyruk cron'unu hemen çalıştır. Cron kaydı yoksa (redeploy ile -u arası) atla:
        kuyruktaki kayıtları _cron_retry_failed en geç 15 dk içinde gönderir."""
        cron = self.env.ref('sms_system.cron_sms_send_queued', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _lock_for_send(self, ids, states):
        """Kayıtları kilitle ve durumu kilit altında yeniden doğrula; başka işlemin tuttuklarını atla.

        Döner: kilitlenen ve hâlâ `states` içindeki kayıtlar. Kilit, işlem commit edilene kadar sürer.
        REPEATABLE READ'de kayıt bu işlemin anlık görüntüsünden sonra başkasınca değiştirilmişse
        PostgreSQL SerializationFailure verir: kayıt şu an başka bir işlemde demektir, atlanır.
        """
        ids, states = tuple(ids), tuple(states)
        if not ids or not states:
            return self.browse()
        self.flush_model(['state'])
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    'SELECT id FROM sms_system_message WHERE id IN %s AND state IN %s '
                    'ORDER BY id FOR UPDATE SKIP LOCKED', (ids, states))
                locked_ids = [row[0] for row in self.env.cr.fetchall()]
        except pg_errors.SerializationFailure:
            _logger.info('SMS kaydı başka bir işlemde güncellendi, bu çalışmada atlandı (%s kayıt)', len(ids))
            return self.browse()
        locked = self.browse(locked_ids)
        locked.invalidate_recordset(['state'])
        return locked

    @api.model
    def _send_one_by_one(self, candidates, states):
        """Adayları kayıt kayıt gönder: kilit → 'sending' + commit (sağlayıcı çağrısından ÖNCE) → gönder
        → commit. Kayıt başına yapılır: toplu 'sending' süresi takılı kayıt eşiğini aşabilir ve hiç
        gönderilmemiş kayıtlar belirsize düşerdi. Döner: cron süresi bitti mi (True: dur)."""
        IrCron = self.env['ir.cron']
        cfg = self._settings()
        for msg_id in candidates.ids:
            msg = self._lock_for_send([msg_id], states)
            if not msg:
                continue
            msg.write({'state': 'sending'})
            IrCron._commit_progress()
            msg._deliver(cfg)
            if IrCron._commit_progress(1) < SINGLE_MIN_TIME_LEFT:
                return True
        return False

    @api.model
    def _cron_send_queued(self):
        """Tekli gönderim kuyruğu: kampanyasız 'queued' kayıtları gönderir.

        Önce 15 dk'dan uzun 'sending'de kalan tekli kayıtları belirsiz yapar (gidip gitmediği bilinmez,
        asla yeniden gönderilmez). Döner: cron süresi bitti mi.
        """
        Message = self.sudo()
        IrCron = self.env['ir.cron']
        stuck_before = fields.Datetime.now() - timedelta(minutes=SINGLE_STUCK_MINUTES)
        stuck = Message.search([('campaign_id', '=', False), ('state', '=', 'sending'),
                                ('write_date', '<', stuck_before)])
        stuck = Message._lock_for_send(stuck.ids, ('sending',))
        if stuck:
            _logger.warning('%s tekli SMS kaydı gönderiliyor durumunda takıldı, belirsiz yapıldı', len(stuck))
            stuck.write({'state': 'uncertain', 'retry_count': MAX_RETRY,
                         'error': _('Gönderim yarıda kesildi; iletilip iletilmediği belirsiz. '
                                    'Tekrar gönderilmedi (mükerrer olmasın diye).')})
        IrCron._commit_progress()
        last_id = 0
        while True:
            queued = Message.search([('campaign_id', '=', False), ('state', '=', 'queued'), ('id', '>', last_id)],
                                    order='id', limit=QUEUE_BATCH)
            if not queued:
                return False
            last_id = queued[-1].id
            if Message._send_one_by_one(queued, ('queued',)):
                return True

    @api.model
    def _cron_retry_failed(self):
        """Ağ hatası vb. geçici hatalı gönderimleri sınırlı sayıda yeniden dene (son 1 gün).

        Önce tekli kuyruğu boşaltır (kuyruk cron'u yokken de kuyruk 15 dk içinde gider). Yalnız 'error';
        belirsiz ve gönderiliyor kayıtlar asla yeniden gönderilmez.
        """
        if self._cron_send_queued():
            return
        since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        Message = self.sudo()
        failed = Message.search([('state', '=', 'error'), ('retry_count', '<', MAX_RETRY),
                                 ('campaign_id', '=', False), ('create_date', '>=', since)],
                                order='id', limit=QUEUE_BATCH)
        Message._send_one_by_one(failed, ('error',))

    @api.model
    @api.private
    def check_credit(self):
        """Ayarlar ekranındaki 'Bağlantı / Kredi' butonu."""
        return self._client().credit()

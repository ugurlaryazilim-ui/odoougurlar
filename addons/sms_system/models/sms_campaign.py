import logging
from collections import OrderedDict
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.turatel import MAX_SEGMENTS, prepare_text, segment_count
from .sms_template import PLACEHOLDER

_logger = logging.getLogger(__name__)

PACK_SIZE = 500          # Turatel'e tek istekte giden en fazla numara
MIN_TIME_LEFT = 20       # cron süresinin sonuna bu kadar saniye kala dur, kalan sonraki çalışmada
STUCK_MINUTES = 15
CREATE_CHUNK = 5000      # büyük kampanyada gönderim kayıtları parça parça oluşturulur       # 'gönderiliyor'da bu kadar kalan kayıt belirsiz sayılır (tekrar gönderilmez)


class SmsSystemCampaign(models.Model):
    """Toplu SMS: listelerdeki kişilere tek metin. Gönderimi cron kuyruğu paketler halinde yapar."""
    _name = 'sms.system.campaign'
    _description = 'Toplu SMS'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Başlık', required=True, tracking=True)
    message_type = fields.Selection([
        ('info', 'Bilgilendirme'),
        ('commercial', 'Ticari (kampanya / indirim)'),
        ('staff', 'Personel duyurusu'),
    ], string='İleti Türü', default='info', required=True, tracking=True,
        help='Ticari iletiler yalnız İYS onaylı numaralara gider ve sonuna ret bilgisi eklenir.')
    list_ids = fields.Many2many('sms.system.list', string='Alıcı Listeleri', required=True)
    template_id = fields.Many2one('sms.system.template', string='Şablon')
    body = fields.Text(string='Metin', required=True,
                       help='{ad} yazılırsa her kişiye kendi adı yazılır (bu durumda numara başı ayrı gönderilir).')
    scheduled_at = fields.Datetime(string='Planlanan Gönderim', help='Boşsa "Gönder" ile hemen başlar')
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('scheduled', 'Planlandı'),
        ('sending', 'Gönderiliyor'),
        ('done', 'Tamamlandı'),
        ('cancel', 'İptal'),
    ], string='Durum', default='draft', required=True, index=True, tracking=True)
    user_id = fields.Many2one('res.users', string='Oluşturan', default=lambda self: self.env.user, readonly=True)
    started_at = fields.Datetime(string='Başlama', readonly=True)
    finished_at = fields.Datetime(string='Bitiş', readonly=True)
    message_ids_sms = fields.One2many('sms.system.message', 'campaign_id', string='Gönderimler')

    # Önizleme (taslakta canlı hesap)
    final_body = fields.Text(string='Gönderilecek Metin', compute='_compute_preview')
    preview_count = fields.Integer(string='Alıcı (tahmini)', compute='_compute_preview')
    preview_skipped = fields.Integer(string='Atlanacak', compute='_compute_preview',
                                     help='Kara listede ya da (ticari ise) İYS onayı olmayan numaralar')
    preview_segments = fields.Integer(string='Parça / SMS', compute='_compute_preview')
    preview_credit = fields.Integer(string='Tahmini Kredi', compute='_compute_preview')
    personalized = fields.Boolean(string='Kişiye Özel', compute='_compute_preview')
    iys_enabled = fields.Boolean(compute='_compute_iys_enabled')

    # Sonuç
    skipped_count = fields.Integer(string='Atlanan', readonly=True)
    total_count = fields.Integer(string='Alıcı', compute='_compute_stats')
    sent_count = fields.Integer(string='Gönderilen', compute='_compute_stats')
    error_count = fields.Integer(string='Hatalı', compute='_compute_stats')
    pending_count = fields.Integer(string='Bekleyen', compute='_compute_stats')

    # ── Hesaplar ──

    def _icp(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def _build_body(self):
        self.ensure_one()
        body = (self.body or '').strip()
        if self.message_type == 'commercial':
            optout = (self._icp('sms_system.optout_text') or '').strip()
            if optout and optout not in body:
                body = '%s %s' % (body, optout)
        return body

    def _recipient_domain(self):
        self.ensure_one()
        domain = [('list_ids', 'in', self.list_ids.ids), ('opt_out', '=', False)]
        if self.message_type == 'commercial':
            domain.append(('iys_status', '=', 'approved'))
        return domain

    def _recipients(self):
        """(gönderilecek kişiler, atlanan sayısı) — numara bazında tekil."""
        self.ensure_one()
        Contact = self.env['sms.system.contact'].sudo()
        if not self.list_ids:
            return Contact, 0
        all_count = Contact.search_count([('list_ids', 'in', self.list_ids.ids)])
        contacts = Contact.search(self._recipient_domain(), order='id')
        return contacts, all_count - len(contacts)

    @api.depends('body', 'message_type', 'list_ids')
    def _compute_preview(self):
        ascii_mode = self._icp('sms_system.ascii_mode') == 'True'
        sample_name = _('Ayşe Yılmaz')
        for camp in self:
            body = camp._build_body()
            camp.personalized = bool(PLACEHOLDER.search(body))
            sample = PLACEHOLDER.sub(lambda m: sample_name if m.group(1) == 'ad' else '', body)
            text, sms_type = prepare_text(sample, ascii_mode=ascii_mode)
            camp.final_body = text
            camp.preview_segments = segment_count(text, sms_type) if text else 0
            if camp.state in ('draft', 'scheduled'):
                contacts, skipped = camp._recipients()
                camp.preview_count = len(contacts)
                camp.preview_skipped = skipped
            else:
                camp.preview_count = camp.total_count
                camp.preview_skipped = camp.skipped_count
            camp.preview_credit = camp.preview_count * camp.preview_segments

    def _compute_iys_enabled(self):
        enabled = self._icp('sms_system.iys_enabled') == 'True'
        for camp in self:
            camp.iys_enabled = enabled

    def _compute_stats(self):
        Message = self.env['sms.system.message'].sudo()
        data = {}
        for camp, state, count in Message._read_group([('campaign_id', 'in', self.ids)],
                                                      ['campaign_id', 'state'], ['__count']):
            data.setdefault(camp.id, {})[state] = count
        for camp in self:
            d = data.get(camp.id, {})
            camp.total_count = sum(d.values())
            camp.sent_count = d.get('sent', 0) + d.get('test', 0)
            camp.error_count = d.get('error', 0)
            camp.pending_count = d.get('queued', 0) + d.get('sending', 0)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.body = self.template_id.body

    # ── Kontroller ──

    def _check_can_send(self, count):
        self.ensure_one()
        if not self.list_ids:
            raise UserError(_('En az bir alıcı listesi seçin.'))
        if not (self.body or '').strip():
            raise UserError(_('SMS metni boş olamaz.'))
        if self.message_type == 'commercial' and self._icp('sms_system.iys_enabled') != 'True':
            raise UserError(_(
                'Ticari (kampanya/indirim) SMS için İYS izin kontrolü zorunludur. '
                'İYS (SmartADM) entegrasyonu henüz etkin değil; bilgilendirme ya da personel türünü kullanın.'))
        if self.preview_segments > MAX_SEGMENTS:
            raise UserError(_('Metin çok uzun (%(n)s parça). En fazla %(max)s parça gönderilebilir.',
                              n=self.preview_segments, max=MAX_SEGMENTS))
        if not count:
            raise UserError(_('Gönderilecek alıcı yok (listeler boş, kara listede ya da İYS onaylı değil).'))
        limit = int(self._icp('sms_system.daily_limit', '0') or 0)
        if limit:
            today = fields.Datetime.now() - timedelta(days=1)
            used = self.env['sms.system.message'].sudo().search_count([
                ('campaign_id', '!=', False), ('state', 'in', ('sent', 'test', 'queued', 'sending')),
                ('create_date', '>=', today)])
            if used + count > limit:
                raise UserError(_('Günlük toplu SMS sınırı aşılıyor: son 24 saatte %(used)s, bu gönderim %(count)s, '
                                  'sınır %(limit)s. Sınır Ayarlar > SMS ekranından değiştirilebilir.',
                                  used=used, count=count, limit=limit))

    def _commercial_hour_warning(self, when=None):
        if self.message_type != 'commercial':
            return ''
        tz = pytz.timezone(self.env.user.tz or 'Europe/Istanbul')
        local = pytz.utc.localize(when or fields.Datetime.now()).astimezone(tz)
        if not (9 <= local.hour < 21):
            return _(' Not: ticari SMS gece saatinde (%s) gönderiliyor.') % local.strftime('%H:%M')
        return ''

    def unlink(self):
        if self.filtered(lambda c: c.state in ('scheduled', 'sending', 'done')):
            raise UserError(_('Gönderilmiş ya da devam eden toplu SMS silinemez; iptal edebilirsiniz.'))
        return super().unlink()

    # ── Butonlar ──

    def action_confirm_send(self):
        """Gönder butonu: alıcı ve kredi sayısını gösteren onay penceresi."""
        self.ensure_one()
        contacts, _skipped = self._recipients()
        self._check_can_send(len(contacts))
        wiz = self.env['sms.system.campaign.confirm'].create({'campaign_id': self.id})
        return {'type': 'ir.actions.act_window', 'res_model': wiz._name, 'res_id': wiz.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Toplu SMS Onayı')}

    def action_send(self):
        """Gönder (planlı tarih varsa planla)."""
        for camp in self:
            if camp.state != 'draft':
                raise UserError(_('Yalnız taslak toplu SMS gönderilebilir.'))
            contacts, _skipped = camp._recipients()
            camp._check_can_send(len(contacts))
            if camp.scheduled_at and camp.scheduled_at > fields.Datetime.now():
                camp.state = 'scheduled'
                camp.message_post(body=_('%(n)s alıcıya planlandı.%(warn)s', n=len(contacts),
                                         warn=camp._commercial_hour_warning(camp.scheduled_at)))
                self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger(camp.scheduled_at)
            else:
                camp._start()
        self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger()
        return True

    def action_cancel(self):
        for camp in self:
            queued = camp.sudo().message_ids_sms.filtered(lambda m: m.state == 'queued')
            queued.unlink()
            camp.state = 'cancel' if not camp.sudo().message_ids_sms else 'done'
            camp.message_post(body=_('İptal edildi; %s bekleyen gönderim kaldırıldı.') % len(queued))

    def action_draft(self):
        self.filtered(lambda c: c.state in ('scheduled', 'cancel')).write({'state': 'draft'})

    def action_retry_errors(self):
        for camp in self:
            errors = camp.sudo().message_ids_sms.filtered(lambda m: m.state == 'error')
            if errors:
                errors.write({'state': 'queued', 'error': False})
                camp.state = 'sending'
                camp.finished_at = False
        self.env.ref('sms_system.cron_sms_campaign_queue').sudo()._trigger()

    def action_view_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': self.name, 'res_model': 'sms.system.message',
            'view_mode': 'list,form', 'domain': [('campaign_id', '=', self.id)],
            'context': {'search_default_group_state': 1},
        }

    # ── Kuyruk ──

    def _start(self):
        """Alıcıları dondur: her numara için kuyrukta bir gönderim kaydı oluştur."""
        self.ensure_one()
        contacts, skipped = self._recipients()
        self._check_can_send(len(contacts))
        cfg = self.env['sms.system.message']._settings()
        body = self._build_body()
        vals_list = []
        for contact in contacts:
            text = PLACEHOLDER.sub(lambda m: (contact.name or '') if m.group(1) == 'ad' else '', body)
            text, sms_type = prepare_text(text, ascii_mode=cfg['ascii_mode'])
            vals_list.append({
                'number': contact.mobile, 'body': text, 'originator': cfg['originator'],
                'sms_type': sms_type, 'segments': segment_count(text, sms_type),
                'campaign_id': self.id, 'contact_id': contact.id, 'state': 'queued',
                'res_model': self._name, 'res_id': self.id, 'template_id': self.template_id.id or False,
                'user_id': self.env.user.id,
            })
        Message = self.env['sms.system.message'].sudo()
        for i in range(0, len(vals_list), CREATE_CHUNK):
            Message.create(vals_list[i:i + CREATE_CHUNK])
        self.write({'state': 'sending', 'started_at': fields.Datetime.now(), 'skipped_count': skipped})
        self.message_post(body=_('%(n)s alıcıya gönderim başladı (%(s)s numara atlandı).%(warn)s',
                                 n=len(vals_list), s=skipped, warn=self._commercial_hour_warning()))

    @api.model
    def _cron_process_queue(self):
        """Planlananları başlat, kuyruktaki gönderimleri paketler halinde Turatel'e ilet."""
        IrCron = self.env['ir.cron']
        now = fields.Datetime.now()
        for camp in self.search([('state', '=', 'scheduled'), ('scheduled_at', '<=', now)]):
            try:
                camp._start()
            except UserError as e:
                camp.write({'state': 'draft'})
                camp.message_post(body=_('Planlı gönderim başlatılamadı: %s') % e)
            IrCron._commit_progress()

        Message = self.env['sms.system.message'].sudo()
        # Kesilen bir çalışmadan 'gönderiliyor'da kalanlar: gidip gitmediği bilinmez, tekrar gönderilmez
        stuck = Message.search([('campaign_id', '!=', False), ('state', '=', 'sending'),
                                ('write_date', '<', now - timedelta(minutes=STUCK_MINUTES))])
        if stuck:
            stuck.write({'state': 'error', 'error': _('Gönderim yarıda kesildi; iletilip iletilmediği belirsiz. '
                                                      'Tekrar gönderilmedi (mükerrer olmasın diye).')})

        cfg = Message._settings()
        client = Message._client(cfg)
        campaigns = self.search([('state', '=', 'sending')], order='id')
        remaining = Message.search_count([('campaign_id', 'in', campaigns.ids), ('state', '=', 'queued')])
        IrCron._commit_progress(remaining=remaining)
        for camp in campaigns:
            while True:
                queued = Message.search([('campaign_id', '=', camp.id), ('state', '=', 'queued')],
                                        order='id', limit=PACK_SIZE * 4)
                if not queued:
                    break
                for pack in self._make_packs(queued):
                    pack.write({'state': 'sending'})
                    IrCron._commit_progress()
                    pack._deliver_pack(cfg, client)
                    time_left = IrCron._commit_progress(len(pack))
                    if time_left < MIN_TIME_LEFT:
                        return
            if not Message.search_count([('campaign_id', '=', camp.id), ('state', 'in', ('queued', 'sending'))]):
                camp._finish()
                IrCron._commit_progress()

    @api.model
    def _make_packs(self, messages):
        """Aynı metin/başlık/türdeki numaraları en fazla PACK_SIZE'lık paketlere ayır."""
        groups = OrderedDict()
        for msg in messages:
            groups.setdefault((msg.body, msg.originator, msg.sms_type), []).append(msg.id)
        Message = self.env['sms.system.message'].sudo()
        for ids in groups.values():
            for i in range(0, len(ids), PACK_SIZE):
                yield Message.browse(ids[i:i + PACK_SIZE])

    def _finish(self):
        self.ensure_one()
        self.write({'state': 'done', 'finished_at': fields.Datetime.now()})
        self.message_post(body=_('Tamamlandı: %(sent)s gönderildi, %(err)s hatalı, %(skip)s atlandı.',
                                 sent=self.sent_count, err=self.error_count, skip=self.skipped_count))


class SmsSystemCampaignConfirm(models.TransientModel):
    _name = 'sms.system.campaign.confirm'
    _description = 'Toplu SMS Onayı'

    campaign_id = fields.Many2one('sms.system.campaign', required=True, ondelete='cascade')
    summary = fields.Html(compute='_compute_summary', sanitize=True)

    @api.depends('campaign_id')
    def _compute_summary(self):
        now = fields.Datetime.now()
        for wiz in self:
            camp = wiz.campaign_id
            if camp.scheduled_at and camp.scheduled_at > now:
                local = fields.Datetime.context_timestamp(camp, camp.scheduled_at)
                when = _('%s tarihinde') % local.strftime('%d.%m.%Y %H:%M')
            else:
                when = _('hemen')
            types = dict(camp._fields['message_type'].selection)
            wiz.summary = _(
                '<p><b>%(n)s</b> kişiye %(when)s gönderilecek (%(s)s numara atlanacak).</p>'
                '<p>Tahmini kredi: <b>%(c)s</b> (%(seg)s parça/SMS). Tür: %(t)s.</p>'
                '<p class="text-muted">Gönderim başladıktan sonra yalnız henüz gitmemiş mesajlar durdurulabilir.</p>',
                n=camp.preview_count, when=when, s=camp.preview_skipped, c=camp.preview_credit,
                seg=camp.preview_segments, t=types[camp.message_type])

    def action_confirm(self):
        self.ensure_one()
        self.campaign_id.action_send()
        return {'type': 'ir.actions.act_window_close'}

import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# İzinli durum geçişleri: kaynak durum -> gidilebilecek durumlar.
# Onay bekleyen reyon siparişi yalnız onay/ret ile ilerler (action_approve_reyon / action_reject_reyon).
ALLOWED_TRANSITIONS = {
    'waiting_approval': {'cancelled'},
    'pending': {'in_progress', 'cancelled'},
    'in_progress': {'completed', 'pending', 'cancelled'},
    'completed': {'delivered', 'in_progress', 'pending', 'cancelled'},
    # Teslim edilmiş sipariş yalnız terzi yöneticisi tarafından değiştirilebilir
    'delivered': set(),
    'cancelled': {'pending'},
}


class UgurlarTailorOrder(models.Model):
    """Terzi sipariş kaydı — Nebim faturasından ürün seçilip terzi hizmeti atanır."""
    _name = 'ugurlar.tailor.order'
    _description = 'Terzi Siparişi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Sipariş No', required=True, copy=False,
        readonly=True, default='Yeni',
    )

    # ── Nebim Fatura Bilgileri ──
    invoice_no = fields.Char(string='Fatura No', index=True, tracking=True)
    is_reyon = fields.Boolean(string='Reyon Siparişi', default=False, tracking=True)
    product_barcode = fields.Char(string='Barkod', required=True)
    product_code = fields.Char(string='Ürün Kodu')
    product_name = fields.Char(string='Ürün Adı')

    # ── Müşteri Bilgileri (Nebim'den) ──
    customer_name = fields.Char(string='Müşteri Adı', required=True)
    customer_phone = fields.Char(string='Müşteri Kodu', help="Nebim müşteri kodu (fatura view'ında telefon kolonu yok)")
    sales_person = fields.Char(string='Satış Personeli')

    # ── Terzi ve Hizmetler ──
    tailor_id = fields.Many2one(
        'ugurlar.tailor', string='Terzi',
        index=True, tracking=True,
    )
    line_ids = fields.One2many(
        'ugurlar.tailor.order.line', 'order_id',
        string='Hizmet Satırları',
    )
    total_price = fields.Float(
        string='Terzi Tutarı', digits=(10, 2),
        compute='_compute_total_price', store=True,
        help='Terziye ödenecek toplam (hakediş)',
    )

    # ── Müşteri ücreti / tahsilat ──
    customer_charge = fields.Float(string='Müşteri Ücreti', digits=(10, 2), tracking=True,
                                   help='Müşteriden alınan toplam ücret; 0 = ücretsiz')
    deposit = fields.Float(string='Kapora', digits=(10, 2), tracking=True)
    balance = fields.Float(string='Kalan', digits=(10, 2), compute='_compute_balance', store=True)
    is_paid = fields.Boolean(string='Ödendi', tracking=True)

    # ── Mağazadaki yer / performans ──
    location = fields.Char(string='Raf / Askı', tracking=True, index=True,
                           help='Hazır ürünün mağazada durduğu yer')
    duration_days = fields.Float(string='İş Süresi (gün)', digits=(10, 1), compute='_compute_duration',
                                 store=True, aggregator='avg', help='Sipariş açılışından Hazır olana kadar')
    late_done = fields.Integer(string='Geç Biten', compute='_compute_duration', store=True, aggregator='sum',
                               help='Söz verilen tarihten sonra Hazır olduysa 1')
    customer_order_count = fields.Integer(string='Müşterinin Siparişleri', compute='_compute_customer_order_count')

    # ── Durum Takibi ──
    state = fields.Selection([
        ('waiting_approval', 'Yönetici Onayı Bekliyor'),
        ('pending', 'Bekliyor'),
        ('in_progress', 'Terzide'),
        ('completed', 'Hazır'),
        ('delivered', 'Teslim Edildi'),
        ('cancelled', 'İptal Edildi'),
    ], string='Durum', default='pending', required=True, tracking=True, index=True)

    notes = fields.Text(string='Notlar')

    # ── Teslim sözü / müşteri iletişimi / fotoğraf ──
    promised_date = fields.Date(
        string='Söz Verilen Teslim', tracking=True,
        default=lambda self: self._default_promised_date(),
        help='Müşteriye söz verilen hazır olma tarihi; geçen siparişler "Geciken" görünür',
    )
    is_overdue = fields.Boolean(
        string='Gecikti', compute='_compute_is_overdue', search='_search_is_overdue',
    )
    customer_mobile = fields.Char(string='Müşteri Cep Telefonu', help='Hazır olunca SMS bildirimi için')
    ready_sms_sent = fields.Boolean(string='Hazır SMS Gönderildi', readonly=True, copy=False)
    reminder_count = fields.Integer(string='Hatırlatma SMS Sayısı', readonly=True, copy=False)
    last_reminder_at = fields.Datetime(string='Son Hatırlatma', readonly=True, copy=False)
    photo = fields.Image(string='Ürün Fotoğrafı', max_width=1280, max_height=1280, attachment=True)
    completed_at = fields.Datetime(string='Tamamlanma Tarihi', readonly=True)
    delivered_at = fields.Datetime(string='Teslim Tarihi', readonly=True)
    cancelled_at = fields.Datetime(string='İptal Tarihi', readonly=True)

    @api.model
    def _default_promised_date(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param('ugurlar_tailor.default_days', '3') or 3)
        return fields.Date.context_today(self) + timedelta(days=days)

    @api.depends('promised_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for order in self:
            order.is_overdue = bool(order.promised_date and order.promised_date < today
                                    and order.state in ('pending', 'in_progress'))

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Desteklenmeyen arama.'))
        domain = [('promised_date', '<', fields.Date.context_today(self)),
                  ('state', 'in', ('pending', 'in_progress'))]
        positive = (operator == '=') == value
        return domain if positive else ['!', '&'] + domain

    @api.depends('customer_charge', 'deposit', 'is_paid')
    def _compute_balance(self):
        for order in self:
            order.balance = 0.0 if order.is_paid else max((order.customer_charge or 0) - (order.deposit or 0), 0.0)

    @api.depends('create_date', 'completed_at', 'promised_date')
    def _compute_duration(self):
        for order in self:
            if order.create_date and order.completed_at:
                order.duration_days = round((order.completed_at - order.create_date).total_seconds() / 86400, 1)
                done = fields.Datetime.context_timestamp(order, order.completed_at).date()
                order.late_done = 1 if order.promised_date and done > order.promised_date else 0
            else:
                order.duration_days = 0.0
                order.late_done = 0

    def _customer_domain(self):
        self.ensure_one()
        keys = []
        if self.customer_mobile:
            keys.append(('customer_mobile', '=', self.customer_mobile))
        if self.customer_phone:
            keys.append(('customer_phone', '=', self.customer_phone))
        if not keys:
            return None
        return (['|'] * (len(keys) - 1)) + keys

    def _compute_customer_order_count(self):
        for order in self:
            domain = order._customer_domain() if order.id else None
            order.customer_order_count = self.search_count(domain + [('id', '!=', order.id)]) if domain else 0

    def action_view_customer_orders(self):
        self.ensure_one()
        domain = self._customer_domain() or [('id', '=', 0)]
        return {
            'type': 'ir.actions.act_window', 'name': _('Müşterinin Terzi Siparişleri'),
            'res_model': self._name, 'view_mode': 'list,form', 'domain': domain + [('id', '!=', self.id)],
        }

    def action_mark_paid(self):
        self.write({'is_paid': True})

    @api.depends('line_ids.price')
    def _compute_total_price(self):
        for order in self:
            order.total_price = sum(order.line_ids.mapped('price'))

    # ── Yetki / durum kontrolleri ──

    def _is_tailor_manager(self):
        return self.env.su or self.env.user.has_group('ugurlar_tailor.group_tailor_manager')

    def _check_can_approve_reyon(self):
        """Reyon onayı/reddi: şirketin reyon yöneticileri veya terzi yöneticisi."""
        if self._is_tailor_manager():
            return
        if self.env.user not in self.env.company.reyon_manager_ids:
            raise AccessError(_('Reyon siparişlerini yalnız reyon yöneticileri onaylayabilir veya reddedebilir.'))

    def _check_transition(self, new_state):
        if self._is_tailor_manager():
            return
        labels = dict(self._fields['state'].selection)
        for order in self:
            if new_state not in ALLOWED_TRANSITIONS.get(order.state, set()):
                raise UserError(_('%(order)s: "%(old)s" durumundan "%(new)s" durumuna geçilemez.') % {
                    'order': order.name,
                    'old': labels.get(order.state, order.state),
                    'new': labels.get(new_state, new_state),
                })

    def _link_html(self, label):
        self.ensure_one()
        return '<a href="/odoo/action-ugurlar_tailor.action_tailor_order/%s" target="_blank">%s: %s</a>' % (
            self.id, label, self.name)

    # ── Reyon onayı ──

    def action_approve_reyon(self):
        self._check_can_approve_reyon()
        for order in self:
            if order.state != 'waiting_approval':
                raise UserError(_('%s onay beklemiyor.') % order.name)
            order.with_context(tailor_state_ok=True).write({'state': 'pending'})
            order.activity_feedback(['mail.mail_activity_data_todo'])
            if order.create_uid:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=order.create_uid.id,
                    note=_('Reyon siparişiniz (%(name)s) onaylandı. %(link)s') % {
                        'name': order.name, 'link': order._link_html(_('Siparişe Git'))},
                )
                order.message_post(
                    body=_('Reyon siparişiniz (%s) onaylandı. Lütfen etiketi yazdırınız.') % order.name,
                    partner_ids=[order.create_uid.partner_id.id],
                    author_id=self.env.ref('base.partner_root').id,
                )

    def action_reject_reyon(self):
        """Reddedilen reyon siparişi silinmez, iptal edilir (geçmiş ve iz korunur)."""
        self._check_can_approve_reyon()
        for order in self:
            if order.state != 'waiting_approval':
                raise UserError(_('%s onay beklemiyor.') % order.name)
            order.with_context(tailor_state_ok=True).write(
                {'state': 'cancelled', 'cancelled_at': fields.Datetime.now()})
            order.activity_feedback(['mail.mail_activity_data_todo'])
            if order.create_uid:
                order.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=order.create_uid.id,
                    note=_('Reyon siparişiniz (%(name)s) reddedildi ve iptal edildi. %(link)s') % {
                        'name': order.name, 'link': order._link_html(_('Siparişe Git'))},
                )
                order.message_post(
                    body=_('Reyon siparişiniz (%(name)s) %(user)s tarafından reddedildi ve iptal edildi.') % {
                        'name': order.name, 'user': self.env.user.name},
                    partner_ids=[order.create_uid.partner_id.id],
                    author_id=self.env.ref('base.partner_root').id,
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('ugurlar.tailor.order') or 'Yeni'
            # Faturasız (reyon) sipariş her zaman yönetici onayından geçer
            if vals.get('is_reyon') and not self._is_tailor_manager():
                vals['state'] = 'waiting_approval'

        orders = super().create(vals_list)

        for order in orders:
            if order.is_reyon and order.state == 'waiting_approval':
                managers = order.env.company.reyon_manager_ids
                for manager in managers:
                    order.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=manager.id,
                        summary=_('Reyon Sipariş Onayı'),
                        note=_('Yeni bir faturasız reyon siparişi onayınızı bekliyor. %s')
                        % order._link_html(_('Siparişi İncele')),
                    )
                if managers:
                    order.message_post(
                        body=_('Yeni bir faturasız reyon siparişi onayınızı bekliyor.'),
                        partner_ids=managers.mapped('partner_id').ids,
                        author_id=self.env.ref('base.partner_root').id,
                    )
        return orders

    def write(self, vals):
        # Durum yalnız action_* metodları üzerinden değişir (geçiş kontrolü orada)
        if 'state' in vals and not self.env.context.get('tailor_state_ok') and not self._is_tailor_manager():
            self._check_transition(vals['state'])
        return super().write(vals)

    def _set_state(self, new_state, extra=None):
        self._check_transition(new_state)
        vals = dict(extra or {}, state=new_state)
        return self.with_context(tailor_state_ok=True).write(vals)

    def action_send_to_tailor(self):
        """Durumu 'Terzide' olarak güncelle."""
        self._set_state('in_progress')

    def action_mark_completed(self):
        """Durumu 'Hazır' olarak güncelle; ayar açıksa müşteriye SMS gönder."""
        self._set_state('completed', {'completed_at': fields.Datetime.now()})
        self._notify_ready_sms()

    # ── SMS (sms_system / Turatel) ──

    def _sms_values(self):
        """Şablon yer tutucuları: {musteri} {siparis} {urun} {teslim} {magaza} {konum}."""
        self.ensure_one()
        return {
            'musteri': self.customer_name or '',
            'siparis': self.name or '',
            'urun': self.product_name or self.product_code or '',
            'teslim': self.promised_date.strftime('%d.%m.%Y') if self.promised_date else '',
            'magaza': self.env.company.name or '',
            'konum': getattr(self, 'location', '') or '',
        }

    def _send_template_sms(self, code, number=None):
        """Şablonla SMS gönder; sms.system.message kaydını döndür (numara/şablon yoksa None)."""
        self.ensure_one()
        number = number or self.customer_mobile
        template = self.env['sms.system.template'].sudo().get_by_code(code)
        if not number or not template:
            return None
        return self.env['sms.system.message'].send_sms(
            number, template=template, values=self._sms_values(), record=self)

    def _notify_ready_sms(self):
        """'Hazır' olunca otomatik SMS (ayar açıksa, numara varsa, daha önce gönderilmediyse)."""
        if self.env['ir.config_parameter'].sudo().get_param('ugurlar_tailor.sms_ready_enabled') != 'True':
            return
        for order in self:
            if order.ready_sms_sent or not order.customer_mobile:
                continue
            try:
                msg = order._send_template_sms('tailor_ready')
                if msg and msg.state in ('sent', 'test'):
                    order.ready_sms_sent = True
            except UserError as e:  # geçersiz numara vb. durum değişikliğini engellemesin
                order.message_post(body=_('Hazır SMS gönderilemedi: %s') % e)

    def action_send_sms(self):
        """Formdaki 'SMS Gönder' — şablon seçilebilen pencere."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMS Gönder'),
            'res_model': 'sms.system.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_number': self.customer_mobile or '',
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_template_code': 'tailor_ready' if self.state == 'completed' else False,
                'sms_values': self._sms_values(),
            },
        }

    @api.model
    def _cron_ready_reminders(self):
        """Hazır olup X gündür teslim alınmamış siparişlere hatırlatma SMS'i (en çok N kez)."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('ugurlar_tailor.sms_reminder_enabled') != 'True':
            return
        days = int(icp.get_param('ugurlar_tailor.sms_reminder_days', '3') or 3)
        max_count = int(icp.get_param('ugurlar_tailor.sms_reminder_max', '2') or 2)
        limit = fields.Datetime.now() - timedelta(days=max(days, 1))
        orders = self.search([
            ('state', '=', 'completed'), ('customer_mobile', '!=', False),
            ('reminder_count', '<', max_count), ('completed_at', '<=', limit),
            '|', ('last_reminder_at', '=', False), ('last_reminder_at', '<=', limit),
        ], limit=200)
        for order in orders:
            try:
                msg = order._send_template_sms('tailor_reminder')
            except UserError as e:
                order.message_post(body=_('Hatırlatma SMS gönderilemedi: %s') % e)
                msg = None
            # Numara geçersiz/şablon yoksa da sayaç artar: her gün yeniden denenmesin
            order.write({'reminder_count': order.reminder_count + 1,
                         'last_reminder_at': fields.Datetime.now()})
            if msg is None:
                _logger.info('Terzi hatırlatma atlandı (%s)', order.name)

    def action_mark_delivered(self):
        """Durumu 'Teslim Edildi' olarak güncelle."""
        self._set_state('delivered', {'delivered_at': fields.Datetime.now()})

    def action_reset_to_pending(self):
        """Durumu 'Bekliyor' olarak sıfırla."""
        self._set_state('pending', {'completed_at': False, 'delivered_at': False, 'cancelled_at': False})

    def action_print_label(self):
        """Etiket yazdır — 3 nüsha PDF döndürür."""
        return self.env.ref('ugurlar_tailor.action_report_tailor_label').report_action(self)

    def action_cancel(self):
        """Siparişi iptal et."""
        self._set_state('cancelled', {'cancelled_at': fields.Datetime.now()})
        for order in self:
            order.message_post(
                body=_('Sipariş iptal edildi.'),
                message_type='notification',
            )

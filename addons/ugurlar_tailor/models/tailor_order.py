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
        string='Toplam Tutar', digits=(10, 2),
        compute='_compute_total_price', store=True,
    )

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

    def _notify_ready_sms(self):
        """Hazır bildirimi (Odoo SMS / IAP). Kapalıysa, numara yoksa ya da gönderilmişse atlanır."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('ugurlar_tailor.sms_ready_enabled') != 'True':
            return
        template = icp.get_param('ugurlar_tailor.sms_ready_text') or _(
            'Sayın {musteri}, {siparis} numaralı terzi siparişiniz hazırdır. Mağazamızdan teslim alabilirsiniz.')
        for order in self:
            if order.ready_sms_sent or not order.customer_mobile or not hasattr(order, '_message_sms'):
                continue
            body = template.replace('{musteri}', order.customer_name or '').replace('{siparis}', order.name or '')
            try:
                order._message_sms(body, sms_numbers=[order.customer_mobile])
                order.with_context(tailor_state_ok=True).ready_sms_sent = True
            except Exception as e:
                _logger.warning('Terzi hazır SMS gönderilemedi (%s): %s', order.name, e)

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

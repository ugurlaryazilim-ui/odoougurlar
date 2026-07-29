import logging
import uuid
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MarketplaceChatConversation(models.Model):
    _name = 'marketplace.chat.conversation'
    _inherit = ['mail.thread']
    _description = 'Canlı Sohbet Konuşması'
    _order = 'last_message_date desc'

    name = fields.Char('Konuşma', compute='_compute_name', store=True)
    conversation_uid = fields.Char(
        'Konuşma ID', required=True, index=True, readonly=True,
        default=lambda self: str(uuid.uuid4()),
    )
    marketplace_type = fields.Selection([
        ('shopify', 'Shopify'),
    ], string='Kanal', required=True, default='shopify')
    
    # Mağaza bilgisi — shopify_integration varsa bağlanır
    shop_domain = fields.Char('Mağaza Domain')
    
    # Müşteri bilgileri
    customer_name = fields.Char('Müşteri Adı')
    customer_email = fields.Char('Müşteri E-posta')
    customer_phone = fields.Char('Müşteri Telefon')
    partner_id = fields.Many2one('res.partner', string='Odoo Partner', compute='_compute_partner', store=True)
    
    # Durum
    state = fields.Selection([
        ('open', 'Açık'),
        ('assigned', 'Atanmış'),
        ('closed', 'Kapalı'),
    ], string='Durum', default='open', required=True, tracking=True)
    
    # Operatör
    operator_id = fields.Many2one('res.users', string='Operatör', tracking=True)
    
    # Mesajlar
    message_ids = fields.One2many('marketplace.chat.message', 'conversation_id', string='Mesajlar')
    message_count = fields.Integer('Mesaj Sayısı', compute='_compute_message_count', store=True)
    unread_count = fields.Integer('Okunmamış', compute='_compute_unread_count')
    last_message_date = fields.Datetime('Son Mesaj', compute='_compute_last_message', store=True)
    last_message_preview = fields.Char('Son Mesaj Önizleme', compute='_compute_last_message', store=True)
    
    # Sayfa / ürün bilgisi
    page_url = fields.Char('Sayfa URL')
    page_title = fields.Char('Sayfa Başlığı')
    product_name = fields.Char('Ürün Adı')
    
    # İlişkili marketplace.question (opsiyonel)
    question_id = fields.Many2one('marketplace.question', string='İlgili Soru')
    
    # Zaman damgaları
    started_date = fields.Datetime('Başlangıç', default=fields.Datetime.now, readonly=True)
    closed_date = fields.Datetime('Kapanış')
    first_response_date = fields.Datetime('İlk Cevap Süresi')
    
    # Metrikler
    rating = fields.Selection([
        ('1', '⭐'), ('2', '⭐⭐'), ('3', '⭐⭐⭐'), ('4', '⭐⭐⭐⭐'), ('5', '⭐⭐⭐⭐⭐'),
    ], string='Değerlendirme')
    color = fields.Integer('Renk')
    
    _conversation_uid_unique = models.Constraint(
        'UNIQUE(conversation_uid)',
        'Konuşma ID benzersiz olmalıdır!',
    )

    @api.depends('customer_name', 'customer_email', 'conversation_uid')
    def _compute_name(self):
        for rec in self:
            if rec.customer_name:
                rec.name = f"💬 {rec.customer_name}"
            elif rec.customer_email:
                rec.name = f"💬 {rec.customer_email}"
            else:
                rec.name = f"💬 Ziyaretçi ({rec.conversation_uid[:8]})"

    @api.depends('customer_email')
    def _compute_partner(self):
        """E-posta adresinden Odoo partner eşleştirmesi."""
        for rec in self:
            if rec.customer_email:
                partner = self.env['res.partner'].sudo().search([
                    ('email', '=ilike', rec.customer_email),
                ], limit=1)
                rec.partner_id = partner.id if partner else False
            else:
                rec.partner_id = False

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    def _compute_unread_count(self):
        for rec in self:
            rec.unread_count = self.env['marketplace.chat.message'].search_count([
                ('conversation_id', '=', rec.id),
                ('sender_type', '=', 'customer'),
                ('is_read', '=', False),
            ])

    @api.depends('message_ids.sent_date', 'message_ids.message_text')
    def _compute_last_message(self):
        for rec in self:
            last = self.env['marketplace.chat.message'].search([
                ('conversation_id', '=', rec.id),
            ], order='sent_date desc', limit=1)
            if last:
                rec.last_message_date = last.sent_date
                text = last.message_text or ''
                rec.last_message_preview = text[:80] + ('...' if len(text) > 80 else '')
            else:
                rec.last_message_date = rec.started_date
                rec.last_message_preview = ''

    def action_assign_to_me(self):
        """Konuşmayı kendime ata."""
        self.ensure_one()
        self.write({
            'operator_id': self.env.uid,
            'state': 'assigned',
        })

    def action_close(self):
        """Konuşmayı kapat."""
        self.ensure_one()
        self.write({
            'state': 'closed',
            'closed_date': fields.Datetime.now(),
        })

    def action_reopen(self):
        """Konuşmayı yeniden aç."""
        self.ensure_one()
        self.write({
            'state': 'open',
            'closed_date': False,
        })

    def action_send_reply(self):
        """Operatör cevap gönderme wizard'ı aç."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cevap Gönder',
            'res_model': 'marketplace.chat.reply.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_conversation_id': self.id},
        }

    def action_view_partner(self):
        """Partner kaydını aç."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Bu konuşmaya bağlı müşteri kaydı bulunamadı.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.partner_id.name,
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
        }


class MarketplaceChatMessage(models.Model):
    _name = 'marketplace.chat.message'
    _description = 'Sohbet Mesajı'
    _order = 'sent_date asc'

    conversation_id = fields.Many2one(
        'marketplace.chat.conversation', string='Konuşma',
        required=True, ondelete='cascade', index=True,
    )
    message_text = fields.Text('Mesaj', required=True)
    sender_type = fields.Selection([
        ('customer', 'Müşteri'),
        ('operator', 'Operatör'),
        ('bot', 'Otomatik Cevap'),
        ('system', 'Sistem'),
    ], string='Gönderen Tipi', required=True)
    sender_name = fields.Char('Gönderen Adı')
    sent_date = fields.Datetime('Gönderim Zamanı', default=fields.Datetime.now, required=True, index=True)
    is_read = fields.Boolean('Okundu', default=False)
    read_date = fields.Datetime('Okunma Zamanı')
    
    # Operatör bilgisi
    operator_id = fields.Many2one('res.users', string='Operatör')
    
    # Ek dosyalar
    attachment_url = fields.Char('Ek Dosya URL')
    attachment_type = fields.Selection([
        ('image', 'Resim'),
        ('file', 'Dosya'),
    ], string='Ek Tipi')

    def mark_as_read(self):
        """Mesajı okundu olarak işaretle."""
        unread = self.filtered(lambda m: not m.is_read)
        if unread:
            unread.write({
                'is_read': True,
                'read_date': fields.Datetime.now(),
            })


class MarketplaceChatReplyWizard(models.TransientModel):
    _name = 'marketplace.chat.reply.wizard'
    _description = 'Sohbet Cevap Wizard'

    conversation_id = fields.Many2one('marketplace.chat.conversation', string='Konuşma', required=True)
    reply_text = fields.Text('Cevabınız', required=True)
    template_id = fields.Many2one('marketplace.question.template', string='Hazır Şablon')

    @api.onchange('template_id')
    def _onchange_template(self):
        if self.template_id:
            self.reply_text = self.template_id.template_text

    def action_send(self):
        """Cevap gönder."""
        self.ensure_one()
        if not self.reply_text or len(self.reply_text.strip()) < 2:
            raise UserError(_('Lütfen bir cevap yazın.'))
        
        conv = self.conversation_id
        
        # Mesaj oluştur
        self.env['marketplace.chat.message'].create({
            'conversation_id': conv.id,
            'message_text': self.reply_text.strip(),
            'sender_type': 'operator',
            'sender_name': self.env.user.name,
            'operator_id': self.env.uid,
        })
        
        # İlk cevap süresi
        if not conv.first_response_date:
            conv.first_response_date = fields.Datetime.now()
        
        # Operatör ata
        if not conv.operator_id:
            conv.write({
                'operator_id': self.env.uid,
                'state': 'assigned',
            })
        
        # Müşteri mesajlarını okundu yap
        unread = self.env['marketplace.chat.message'].search([
            ('conversation_id', '=', conv.id),
            ('sender_type', '=', 'customer'),
            ('is_read', '=', False),
        ])
        unread.mark_as_read()
        
        return {'type': 'ir.actions.act_window_close'}

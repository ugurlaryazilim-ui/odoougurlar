import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiStudioGeneration(models.Model):
    """AI üretim sonuçları ve revizyon geçmişi.

    Her fotoğraf için AI'ın ürettiği sonuçları saklar.
    Onay/red mekanizması, revizyon zinciri ve maliyet takibi sağlar.
    """
    _name = 'ai.studio.generation'
    _description = 'AI Stüdyo Üretim'
    _order = 'session_id, photo_type, revision_number desc'

    session_id = fields.Many2one(
        'ai.studio.session',
        string='Oturum',
        required=True,
        ondelete='cascade',
        index=True,
    )
    source_photo_id = fields.Many2one(
        'ai.studio.photo',
        string='Kaynak Fotoğraf',
        ondelete='set null',
    )
    photo_type = fields.Selection([
        ('front', 'Ön Yüz'),
        ('back', 'Arka Yüz'),
        ('detail', 'Detay'),
    ], string='Fotoğraf Tipi')

    # --- Görseller ---
    original_image = fields.Image(
        string='Orijinal',
        max_width=1920, max_height=1920,
        help='Karşılaştırma için orijinal fotoğraf',
    )
    generated_image = fields.Image(
        string='AI Sonucu',
        max_width=1920, max_height=1920,
        help='AI tarafından üretilen görsel',
    )

    # --- Durum ---
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('processing', 'İşleniyor'),
        ('done', 'Tamamlandı'),
        ('failed', 'Başarısız'),
    ], string='Durum', default='pending', tracking=True)
    error_message = fields.Text(string='Hata Mesajı')

    # --- Onay ---
    is_approved = fields.Boolean(string='Onaylandı', default=False)
    is_primary = fields.Boolean(
        string='Ana Resim',
        default=False,
        help='Bu görsel ürünün ana resmi olarak ayarlanacak',
    )
    reject_reason_id = fields.Many2one(
        'ai.studio.reject.reason',
        string='Red Sebebi',
    )
    revision_prompt = fields.Text(
        string='Revizyon Talimatı',
        help='Red durumunda ek prompt talimatı',
    )

    # --- Revizyon Zinciri ---
    revision_number = fields.Integer(string='Versiyon', default=1)
    parent_generation_id = fields.Many2one(
        'ai.studio.generation',
        string='Önceki Versiyon',
        ondelete='set null',
    )
    child_generation_ids = fields.One2many(
        'ai.studio.generation',
        'parent_generation_id',
        string='Sonraki Versiyonlar',
    )

    # --- fal.ai Bilgileri ---
    fal_request_id = fields.Char(string='fal.ai İstek ID')
    fal_endpoint = fields.Char(string='Kullanılan Endpoint')
    generation_time_seconds = fields.Float(string='Üretim Süresi (sn)')
    provider = fields.Selection([
        ('fal', 'fal.ai'),
        ('replicate', 'Replicate'),
        ('custom', 'Özel'),
    ], string='AI Sağlayıcı', default='fal')

    # --- Maliyet ---
    cost = fields.Monetary(string='Maliyet', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Para Birimi',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
    )

    def action_approve(self):
        """Üretimi onayla."""
        for gen in self:
            if gen.state != 'done':
                raise UserError(_('Sadece tamamlanan üretimler onaylanabilir.'))
            gen.is_approved = True
            gen.session_id.message_post(
                body=_('%(type)s görseli onaylandı (v%(ver)s).') % {
                    'type': dict(gen._fields['photo_type'].selection).get(gen.photo_type, ''),
                    'ver': gen.revision_number,
                },
            )

    def action_reject(self):
        """Red dialog'u aç — revize için."""
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Sadece tamamlanan üretimler reddedilebilir.'))

        max_rev = int(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.max_revisions', '5'
        ))
        if self.revision_number >= max_rev:
            raise UserError(_(
                'Maksimum revize sayısına (%s) ulaşıldı. '
                'Devam etmek için yönetici onayı gerekli.'
            ) % max_rev)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Reddet ve Revize Et'),
            'res_model': 'ai.studio.generation',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'form_view_ref': 'ugurlar_ai_studio.view_generation_reject_form'},
        }

    def action_set_primary(self):
        """Bu görseli ana resim olarak işaretle."""
        self.ensure_one()
        # Aynı oturumdaki diğer primary'leri kaldır
        siblings = self.search([
            ('session_id', '=', self.session_id.id),
            ('is_primary', '=', True),
            ('id', '!=', self.id),
        ])
        siblings.write({'is_primary': False})
        self.is_primary = True

    def action_retry(self):
        """Başarısız üretimi tekrar dene."""
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('Sadece başarısız üretimler tekrar denenebilir.'))
        self.write({
            'state': 'pending',
            'error_message': False,
        })
        self.session_id._process_single_generation(self)

    @api.model
    def _cron_garbage_collect(self):
        """Reddedilen ve eski görselleri temizle."""
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.garbage_days', '7'
        ))
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(days=days)

        old_rejected = self.search([
            ('is_approved', '=', False),
            ('state', '=', 'done'),
            ('write_date', '<', cutoff),
            ('child_generation_ids', '=', False),  # Son versiyon değilse
        ])
        if old_rejected:
            _logger.info(
                'Çöp temizleme: %d eski reddedilen üretim siliniyor', len(old_rejected)
            )
            old_rejected.write({
                'generated_image': False,
                'original_image': False,
            })

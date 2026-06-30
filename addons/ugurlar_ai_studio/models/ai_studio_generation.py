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
        ('side', 'Yan Yüz'),
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
    ], string='Durum', default='pending')
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
    seed = fields.Integer(string='AI Seed', help='Üretimde kullanılan seed değeri')
    provider = fields.Selection([
        ('fal', 'fal.ai'),
        ('fashn', 'FASHN'),
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

    # --- Kalite ---
    quality_score = fields.Float(
        string='Kalite Puanı',
        digits=(5, 1),
        help='AI çıktısının otomatik kalite değerlendirmesi (0-100)',
    )
    quality_details = fields.Text(
        string='Kalite Detayları',
        help='Renk doğruluğu, çözünürlük vb. detaylı kalite bilgileri',
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
            # UI'daki "İşlenmiş Fotoğraf" alanına yansıt:
            if gen.source_photo_id and not self.env.context.get('is_review_popup'):
                gen.source_photo_id.image_processed = gen.generated_image

        if self.env.context.get('is_review_popup'):
            # İlk onaylamadan sonra sıradakine geç (Tinder style!)
            if self.source_photo_id:
                self.source_photo_id.image_processed = self.generated_image
            return self.action_next_generation()

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

    def action_next_generation(self):
        """İnceleme popup'ında bir sonraki onay bekleyen görsele geçer."""
        self.ensure_one()
        next_gen = self.search([
            ('session_id', '=', self.session_id.id),
            ('state', '=', 'done'),
            ('is_approved', '=', False),
            ('id', '!=', self.id)
        ], limit=1)
        
        if next_gen:
            return {
                'name': _('Görselleri İncele'),
                'type': 'ir.actions.act_window',
                'res_model': 'ai.studio.generation',
                'res_id': next_gen.id,
                'view_mode': 'form',
                'target': 'new',
                'context': self.env.context,
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bitti'),
                    'message': _('Onaylanacak başka görsel kalmadı. "Tamamla ve Kaydet" diyebilirsiniz.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

    def action_confirm_reject(self):
        """Reddet ve yeni versiyon oluştur (Popup içinden)."""
        self.ensure_one()
        if not self.reject_reason_id:
            raise UserError(_('Lütfen bir red sebebi seçin.'))
            
        # Mevcut olanı reddedilmiş işaretle
        self.is_approved = False
        self.state = 'done'
        self.session_id.message_post(body=_("%s görseli reddedildi, yeni versiyon üretilecek.") % self.photo_type)
        
        # Yeni versiyon oluştur
        new_gen = self.copy({
            'state': 'pending',
            'is_approved': False,
            'generated_image': False,
            'revision_number': self.revision_number + 1,
            'parent_generation_id': self.id,
            'error_message': False,
            'fal_request_id': False,
            'cost': 0.0,
            'quality_score': 0.0,
        })
        self.session_id._process_single_generation(new_gen)
        
        if self.env.context.get('is_review_popup'):
            return self.action_next_generation()

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

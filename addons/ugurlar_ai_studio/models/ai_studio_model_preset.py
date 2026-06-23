import logging
import base64
import threading

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiStudioModelPreset(models.Model):
    """Manken preset kütüphanesi.

    Farklı cinsiyet, vücut tipi, poz ve arka plan kombinasyonları tanımlar.
    AI ile manken fotoğrafı oluşturma desteği sunar.
    Her preset bir "marka dili" temsil eder.
    """
    _name = 'ai.studio.model.preset'
    _description = 'AI Stüdyo Manken Preseti'
    _order = 'usage_count desc, name'

    name = fields.Char(string='Preset Adı', required=True)
    gender = fields.Selection([
        ('female', 'Kadın'),
        ('male', 'Erkek'),
        ('child', 'Çocuk'),
        ('unisex', 'Unisex'),
    ], string='Cinsiyet', required=True, default='female')
    target_audience = fields.Char(
        string='Hedef Kitle',
        help='Örn: "Avrupa Premium", "Orta Doğu Lüks"',
    )
    age_range = fields.Char(string='Yaş Aralığı', help='Örn: "25-35"')
    body_type = fields.Selection([
        ('standard', 'Standart'),
        ('plus_size', 'Büyük Beden'),
        ('petite', 'Küçük Beden'),
    ], string='Vücut Tipi', default='standard')
    garment_type = fields.Selection([
        ('tops', 'Üst Giyim'),
        ('bottoms', 'Alt Giyim'),
        ('one_piece', 'Tek Parça / Elbise'),
        ('shoes', 'Ayakkabı'),
        ('bags', 'Çanta'),
        ('accessories', 'Aksesuar'),
    ], string='Ürün Tipi', required=True, default='tops')

    model_image_front = fields.Image(
        string='Önden Manken',
        max_width=1920, max_height=1920,
        help='Mankenin önden fotoğrafı (fal.ai model_image olarak gönderilir)',
    )
    model_image_back = fields.Image(
        string='Arkadan Manken',
        max_width=1920, max_height=1920,
        help='Mankenin arkadan fotoğrafı',
    )
    background_type = fields.Selection([
        ('white', 'Beyaz Stüdyo'),
        ('studio', 'Profesyonel Stüdyo'),
        ('lifestyle', 'Yaşam Tarzı'),
        ('transparent', 'Şeffaf'),
    ], string='Arka Plan', default='white')
    style_notes = fields.Text(
        string='Stil Notları',
        help='AI prompt\'a eklenecek stil açıklaması',
    )
    category_ids = fields.Many2many(
        'product.category',
        string='Önerilen Kategoriler',
        help='Bu preset hangi ürün kategorileri için önerilir',
    )
    default_prompt = fields.Text(
        string='Varsayılan Ek Prompt',
        help='Bu preset kullanıldığında otomatik eklenen prompt',
    )
    active = fields.Boolean(string='Aktif', default=True)
    preview_image = fields.Image(
        string='Önizleme',
        max_width=512, max_height=512,
        help='Preset sonuç örneği',
    )

    # --- AI Manken Oluşturma ---
    mannequin_prompt = fields.Text(
        string='Manken Oluşturma Promptu',
        help='AI ile manken oluşturmak için kullanılacak prompt',
    )
    mannequin_generation_state = fields.Selection([
        ('idle', 'Bekliyor'),
        ('generating', 'Oluşturuluyor...'),
        ('done', 'Tamamlandı'),
        ('failed', 'Başarısız'),
    ], string='Oluşturma Durumu', default='idle')

    # --- Computed İstatistikler ---
    usage_count = fields.Integer(
        string='Kullanım Sayısı',
        compute='_compute_stats',
    )
    approval_rate = fields.Float(
        string='Onay Oranı (%)',
        compute='_compute_stats',
        digits=(5, 1),
    )

    def _compute_stats(self):
        """Kullanım ve onay istatistiklerini hesapla."""
        session_model = self.env['ai.studio.session']
        gen_model = self.env['ai.studio.generation']
        for preset in self:
            sessions = session_model.search([
                ('model_preset_id', '=', preset.id),
            ])
            preset.usage_count = len(sessions)
            if sessions:
                gens = gen_model.search([
                    ('session_id', 'in', sessions.ids),
                    ('state', '=', 'done'),
                ])
                approved = gens.filtered('is_approved')
                preset.approval_rate = (
                    (len(approved) / len(gens)) * 100 if gens else 0.0
                )
            else:
                preset.approval_rate = 0.0

    def action_generate_mannequin(self):
        """AI ile manken fotoğrafı oluştur (ön ve arka)."""
        self.ensure_one()
        if not self.mannequin_prompt:
            raise UserError(_('Lütfen manken oluşturma promptu girin.'))

        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.fal_api_key'
        )
        if not api_key:
            raise UserError(_('fal.ai API anahtarı ayarlanmamış. Ayarlar menüsünden girin.'))

        self.mannequin_generation_state = 'generating'

        # Arka planda çalıştır
        thread = threading.Thread(
            target=self._generate_mannequin_thread,
            args=(self.id, self.mannequin_prompt, api_key),
        )
        thread.daemon = True
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Manken Oluşturuluyor'),
                'message': _('AI manken fotoğrafı oluşturuluyor. Tamamlandığında bildirim alacaksınız.'),
                'type': 'info',
                'sticky': False,
            },
        }

    def _generate_mannequin_thread(self, preset_id, prompt, api_key):
        """Thread içinde AI manken oluştur."""
        import os
        os.environ['FAL_KEY'] = api_key

        try:
            import fal_client
        except ImportError:
            _logger.error('fal-client kurulu değil. pip install fal-client')
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                preset = env['ai.studio.model.preset'].browse(preset_id)
                preset.write({'mannequin_generation_state': 'failed'})
            return

        try:
            # Önden manken oluştur
            front_prompt = f"{prompt}, front view, full body, standing pose, fashion model, studio photography, white background"
            result_front = fal_client.subscribe(
                'fal-ai/flux/schnell',
                arguments={
                    'prompt': front_prompt,
                    'image_size': {'width': 864, 'height': 1296},
                    'num_images': 1,
                },
            )

            # Arkadan manken oluştur
            back_prompt = f"{prompt}, back view, full body, standing pose, fashion model, studio photography, white background"
            result_back = fal_client.subscribe(
                'fal-ai/flux/schnell',
                arguments={
                    'prompt': back_prompt,
                    'image_size': {'width': 864, 'height': 1296},
                    'num_images': 1,
                },
            )

            # Görselleri indir ve kaydet
            import requests
            front_url = result_front['images'][0]['url']
            back_url = result_back['images'][0]['url']

            front_data = base64.b64encode(requests.get(front_url).content)
            back_data = base64.b64encode(requests.get(back_url).content)

            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                preset = env['ai.studio.model.preset'].browse(preset_id)
                preset.write({
                    'model_image_front': front_data,
                    'model_image_back': back_data,
                    'mannequin_generation_state': 'done',
                })

            _logger.info('Manken oluşturma tamamlandı: preset_id=%s', preset_id)

        except Exception as e:
            _logger.error('Manken oluşturma hatası: %s', e)
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                preset = env['ai.studio.model.preset'].browse(preset_id)
                preset.write({'mannequin_generation_state': 'failed'})

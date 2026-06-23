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
    _order = 'name'

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
            raise UserError(_(
                'fal.ai API anahtarı ayarlanmamış.\n'
                'Yapılandırma → Genel Ayarlar → AI Studio bölümünden girin.'
            ))

        self.mannequin_generation_state = 'generating'

        # Arka planda çalıştır
        thread = threading.Thread(
            target=self._generate_mannequin_thread,
            args=(self.id, self.mannequin_prompt, api_key,
                  self.gender, self.body_type, self.background_type),
        )
        thread.daemon = True
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Manken Oluşturuluyor'),
                'message': _(
                    'AI manken fotoğrafı oluşturuluyor (ön + arka).\n'
                    'İşlem 30-90 saniye sürebilir. Sayfayı yenileyin.'
                ),
                'type': 'info',
                'sticky': True,
            },
        }

    # ─── SaaS-tarzı Prompt Lock'lar ────────────────────────────────
    REALISM_LOCK = (
        "PHOTOREALISM MANDATE — This must look like an unretouched RAW "
        "photograph taken with a Hasselblad X2D. "
        "Render visible pores, subtle skin texture, natural lip lines, "
        "real skin translucency. Slight facial asymmetry is MANDATORY. "
        "HAIR: Individually resolved strands with natural flyaways. "
        "SKIN: Subsurface scattering, vellus hair on cheeks, natural tonal "
        "variation. NO porcelain/waxy/airbrushed/plastic skin. "
        "POSTURE: Relaxed contrapposto with natural weight shift. "
        "CAMERA: Natural sensor grain, medium-format RAW optic emulation."
    )

    STUDIO_LOCK = (
        "Environment: Pure minimalist fashion studio set. "
        "Seamless white cyclorama background (#FFFFFF). "
        "Clean floor-to-background transition with soft bounce light. "
        "No visible studio equipment, no props, no furniture. "
        "ONLY the model should exist in the frame."
    )

    ANATOMY_LOCK = (
        "ANATOMY LOCK: Exactly two arms, two legs, one head. "
        "Hands must have exactly five fingers each. "
        "No extra limbs, no ghosting effects, no warped proportions."
    )

    @staticmethod
    def _fal_api_call(endpoint, payload, api_key, timeout=120):
        """fal.ai SYNC REST API çağrısı — SaaS tarzı.

        Sync endpoint kullanır (https://fal.run/...), queue gerektirmez.
        Sonuç doğrudan döner.
        """
        import requests as req

        url = f'https://fal.run/{endpoint}'
        headers = {
            'Authorization': f'Key {api_key}',
            'Content-Type': 'application/json',
        }

        _logger.info('fal.ai API çağrısı: %s', endpoint)
        resp = req.post(url, json=payload, headers=headers, timeout=timeout)

        if resp.status_code != 200:
            error_text = resp.text[:500]
            _logger.error('fal.ai hata %s: %s', resp.status_code, error_text)
            raise Exception(f'fal.ai API hatası ({resp.status_code}): {error_text}')

        return resp.json()

    @staticmethod
    def _download_image_b64(url):
        """URL'den görsel indirip base64'e çevir."""
        import requests as req
        resp = req.get(url, timeout=60)
        resp.raise_for_status()
        return base64.b64encode(resp.content)

    def _generate_single_mannequin(self, prompt, api_key, view='front'):
        """Tek bir manken görseli oluştur (text-to-image)."""

        # SaaS tarzı prompt oluştur
        view_desc = 'front view' if view == 'front' else 'back view, facing away from camera'
        full_prompt = (
            f"{prompt}, {view_desc}, full body shot, standing pose, "
            f"fashion model photography, e-commerce catalog style. "
            f"{self.REALISM_LOCK} {self.STUDIO_LOCK} {self.ANATOMY_LOCK}"
        )

        # fal.ai flux-pro — yüksek kalite text-to-image
        result = self._fal_api_call(
            'fal-ai/flux-pro/v1.1',
            {
                'prompt': full_prompt,
                'image_size': {'width': 768, 'height': 1152},
                'num_images': 1,
                'safety_tolerance': 5,
                'output_format': 'png',
            },
            api_key,
            timeout=120,
        )

        images = result.get('images', [])
        if not images:
            raise Exception(f'fal.ai boş sonuç döndü ({view})')

        return self._download_image_b64(images[0]['url'])

    def _generate_mannequin_thread(self, preset_id, prompt, api_key,
                                    gender, body_type, bg_type):
        """Thread içinde AI manken oluştur."""
        try:
            # Gender/body hints
            gender_hints = {
                'female': 'young woman, 25 years old',
                'male': 'young man, 28 years old',
                'child': 'child, 8 years old',
                'unisex': 'androgynous young adult',
            }
            body_hints = {
                'standard': 'slim athletic build',
                'plus_size': 'plus size, curvy build',
                'petite': 'petite, slender build',
            }

            enhanced_prompt = (
                f"{prompt}, {gender_hints.get(gender, '')}, "
                f"{body_hints.get(body_type, 'standard build')}"
            )

            # Önden manken oluştur
            _logger.info('Manken oluşturuluyor (ön): preset_id=%s', preset_id)
            front_data = self._generate_single_mannequin(
                enhanced_prompt, api_key, view='front'
            )

            # Arkadan manken oluştur
            _logger.info('Manken oluşturuluyor (arka): preset_id=%s', preset_id)
            back_data = self._generate_single_mannequin(
                enhanced_prompt, api_key, view='back'
            )

            # DB'ye kaydet
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
            _logger.error('Manken oluşturma hatası: %s', e, exc_info=True)
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    preset = env['ai.studio.model.preset'].browse(preset_id)
                    preset.write({'mannequin_generation_state': 'failed'})
            except Exception:
                _logger.error('Durum güncelleme de başarısız oldu')

    # ─── Kıyafet Giydirme (nano-banana-pro/edit) ────────────────────
    @staticmethod
    def fal_tryon(garment_image_url, mannequin_image_url, prompt, api_key):
        """SaaS tarzı kıyafet giydirme — nano-banana-pro/edit.

        garment_image_url: Ürün fotoğrafı (fal storage URL)
        mannequin_image_url: Manken fotoğrafı (fal storage URL)
        prompt: Giydirme talimatı
        api_key: fal.ai key

        Returns: dict with 'images' list
        """
        import requests as req

        full_prompt = (
            f"OUTPUT EXACTLY ONE IMAGE. {prompt} "
            "Put the garment from the first image onto the model in the second image. "
            "Preserve the garment's exact color, fabric texture, stitching, and pattern details. "
            "Keep the model's face, skin tone, hair, and pose exactly the same. "
            "Professional e-commerce fashion photography, white studio background."
        )

        url = 'https://fal.run/fal-ai/nano-banana-pro/edit'
        headers = {
            'Authorization': f'Key {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'prompt': full_prompt,
            'image_urls': [garment_image_url, mannequin_image_url],
            'num_images': 1,
            'aspect_ratio': '3:4',
            'output_format': 'png',
            'safety_tolerance': '4',
            'resolution': '2K',
            'limit_generations': True,
        }

        _logger.info('nano-banana-pro/edit kıyafet giydirme çağrısı')
        resp = req.post(url, json=payload, headers=headers, timeout=180)

        if resp.status_code != 200:
            error_text = resp.text[:500]
            raise Exception(f'nano-banana API hatası ({resp.status_code}): {error_text}')

        return resp.json()


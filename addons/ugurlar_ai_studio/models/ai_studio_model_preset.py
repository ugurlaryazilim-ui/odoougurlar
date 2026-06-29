import logging
import base64
import threading
import time

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
    model_image_side = fields.Image(
        string='Yandan Manken',
        max_width=1920, max_height=1920,
        help='Mankenin yandan fotoğrafı',
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

    library_mannequin_id = fields.Many2one(
        'ai.studio.model.library',
        string='Kutuphane Mankeni',
        help='Kutuphaneden secilen manken',
    )

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

    @api.onchange('library_mannequin_id')
    def _onchange_library_mannequin_id(self):
        """Kutuphane mankeni secildiginde gorselleri preset'e kopyala."""
        if self.library_mannequin_id:
            mannequin = self.library_mannequin_id
            if mannequin.image_front:
                self.model_image_front = mannequin.image_front
            if mannequin.image_back:
                self.model_image_back = mannequin.image_back
            if mannequin.image_side:
                self.model_image_side = mannequin.image_side

    def action_save_to_library(self):
        """Mevcut preset'in manken gorsellerini kutupahneye kaydet."""
        self.ensure_one()
        if not self.model_image_front:
            raise UserError(_('Kutupahneye kaydetmek icin en az on gorsel gereklidir.'))

        library_vals = {
            'name': _('%s - Kutuphane Kopyasi') % self.name,
            'gender': self.gender if self.gender != 'unisex' else 'female',
            'body_type': self.body_type or 'standard',
            'source': 'ai_generated' if self.mannequin_generation_state == 'done' else 'uploaded',
            'image_front': self.model_image_front,
            'image_back': self.model_image_back or False,
            'image_side': self.model_image_side or False,
            'notes': _('"%s" presetinden kaydedildi.') % self.name,
        }

        library_entry = self.env['ai.studio.model.library'].create(library_vals)
        self.library_mannequin_id = library_entry.id

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Kütüphaneye Kaydedildi'),
                'message': _('Manken görselleri "%s" olarak kütüphaneye kaydedildi.') % library_entry.name,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_generate_mannequin(self):
        """AI ile manken fotoğrafı oluştur (ön ve arka)."""
        self.ensure_one()
        if not self.mannequin_prompt:
            raise UserError(_('Lütfen manken oluşturma promptu girin.'))

        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fashn_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'FASHN API anahtarı ayarlanmamış.\n'
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'fal.ai API anahtarı ayarlanmamış.\n'
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))

        self.mannequin_generation_state = 'generating'

        # Arka planda çalıştır
        thread = threading.Thread(
            target=self._generate_mannequin_thread,
            args=(self.id, self.mannequin_prompt, api_key,
                  self.gender, self.body_type, self.background_type, provider_type, self.env.uid),
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

    # ─── SaaS Prompt Lock Sistemi (20+ Lock) ──────────────────────────
    # SaaS projesinin sharedPrompts.ts'inden birebir uyarlanmıştır.

    # 1. Photorealism
    REALISM_LOCK = (
        "RAW photograph, photorealistic, shot on Hasselblad X2D 100C, "
        "real human being, NOT illustration, NOT cartoon, NOT 3D render, NOT anime, NOT drawing, NOT digital art, "
        "visible skin pores, natural skin texture with subsurface scattering, "
        "real facial asymmetry, wet corneal reflections, individual hair strands with flyaways, "
        "natural makeup, authentic editorial expression. "
        "CAMERA: 85mm f/1.8 lens, shallow depth of field, natural sensor grain."
    )

    # 2. Studio Environment
    STUDIO_LOCK = (
        "Environment: Pure, expansive, high-end minimalist fashion studio set. "
        "Bright, airy atmosphere with infinite white space. "
        "Seamless white studio cyclorama (#FFFFFF) only. "
        "Clean floor-to-background transition with soft, natural bounce light. "
        "No visible wall seams, no horizontal floor lines, no room corners. "
        "STUDIO EQUIPMENT BAN: No softboxes, no flash heads, no light stands, "
        "no umbrellas, no reflectors, no C-stands, no tripods, no cables. "
        "ONLY the model should exist in the frame."
    )

    # 3. Anatomy
    ANATOMY_LOCK = (
        "ANATOMY LOCK CRITICAL: Ensure exactly two arms, two legs, and one head. "
        "Hands must have exactly five fingers each. No double heads or double necks. "
        "No extra limbs, extra fingers, extra toes, or ghosting effects. "
        "No warped human proportions or detached limbs. "
        "Maintain physically plausible human weight distribution and bone structure. "
        "Joints must be naturally articulated. No impossible leg or arm angles."
    )

    # 4. Anti-Nude / Full Outfit (Profesyonel Tam Giyim Modu)
    ANTI_NUDE_LOCK = (
        "OUTFIT MANDATORY LOCK: The model MUST wear a professional neutral matching outfit. "
        "Model MUST wear: a simple solid-colored form-fitting crop top / sports bra, paired with casual long trousers (like beige or grey cotton pants), and clean white sneakers. "
        "No bare chest, no bare legs, no underwear look, no swimsuit look. The model must look fully clothed on the lower body. "
        "The crop top is form-fitting to facilitate virtual try-on, and the trousers and sneakers provide a complete professional look. "
        "ANY underwear-only look or barefoot look is a CRITICAL FAILURE."
    )

    # 5. Posture
    POSTURE_LOCK = (
        "Relaxed contrapposto with natural weight shift, slight shoulder drop, "
        "authentic core engagement. No stiff/mannequin/robotic pose. "
        "Effortless high-end editorial model with a relaxed, confident stance."
    )

    # 6. Identity Consistency (ön-arka tutarlılık)
    IDENTITY_LOCK = (
        "IDENTITY LOCK: Replicate the EXACT same model across all views: "
        "face shape, skin tone, hair (color, style, length, curl pattern), "
        "body proportions, age cues, and physical build. "
        "Replicate the EXACT same outfit across all views. "
        "Hair immutable: keep exact hair length, color, part direction, density. "
        "Do not add extensions or change style. "
        "Any deviation in identity is a CRITICAL FAILURE."
    )

    # 7. Negative Prompt
    NEGATIVE_LOCK = (
        "NEGATIVE: illustration, cartoon, anime, 3D render, digital painting, CGI, "
        "vector art, sketch, drawing, oil painting, watercolor, comic book style, "
        "extra arms, extra legs, extra fingers, duplicated face, double head, "
        "warped anatomy, deformed body, mannequin, doll, plastic skin, waxy skin, "
        "beauty filter, airbrushed, over-smooth, blurry, low quality, "
        "collage, split screen, multi-panel, grid layout, "
        "underwear look, nude model, hanger, flat-lay, product-only shot."
    )

    # 8. Premium Capture
    CAPTURE_LOCK = (
        "Ultra premium fashion photography, shot in professional studio, "
        "soft diffused key light, subtle fill light, clean white background. "
        "8K resolution, sharp focus on subject, photographic realism."
    )

    @staticmethod
    def _fal_api_call(endpoint, payload, api_key, timeout=120):
        """fal.ai API çağrısı — fal_client SDK ile kuyruk destekli."""
        import os
        os.environ['FAL_KEY'] = api_key

        try:
            import fal_client
        except ImportError:
            raise Exception('fal-client paketi kurulu değil. pip install fal-client')

        _logger.info('fal.ai API çağrısı (SDK): %s', endpoint)
        result = fal_client.subscribe(
            endpoint,
            arguments=payload,
            client_timeout=timeout,
        )
        return result

    @staticmethod
    def _download_image_b64(url):
        """URL'den görsel indirip base64'e çevir."""
        import requests as req
        resp = req.get(url, timeout=60)
        resp.raise_for_status()
        return base64.b64encode(resp.content)

    @staticmethod
    def _upload_to_fal(image_b64_bytes, api_key):
        """Base64 görsel datayı fal.ai CDN'e yükle, URL döndür.

        fal_client.upload() kullanır — otomatik retry,
        multipart upload ve CDN fallback desteği.
        """
        import os
        os.environ['FAL_KEY'] = api_key

        try:
            import fal_client
        except ImportError:
            _logger.warning('fal_client kurulu değil, upload yapılamadı')
            return None

        try:
            raw_data = base64.b64decode(image_b64_bytes)
            url = fal_client.upload(raw_data, 'image/png')
            return url
        except Exception as e:
            _logger.warning('fal CDN upload başarısız: %s', e)
            return None

    def _build_full_prompt(self, base_prompt, view='front'):
        """Tüm lock'ları birleştirerek tam prompt oluştur."""
        if view == 'front':
            view_desc = 'front view, facing camera directly'
        elif view == 'back':
            view_desc = 'back view, facing away from camera, showing full back'
        else:
            view_desc = 'side profile view, standing profile at 90 degree angle'

        return (
            f"RAW photo, photorealistic, real human being, {base_prompt}, {view_desc}, "
            f"full body shot from head to feet, standing pose, high-end fashion model photography. "
            f"{self.REALISM_LOCK} "
            f"{self.STUDIO_LOCK} "
            f"{self.ANATOMY_LOCK} "
            f"{self.ANTI_NUDE_LOCK} "
            f"{self.POSTURE_LOCK} "
            f"{self.CAPTURE_LOCK} "
            f"{self.NEGATIVE_LOCK}"
        )

    def _generate_mannequin_thread(self, preset_id, prompt, api_key,
                                    gender, body_type, bg_type, provider_type, uid):
        """Thread içinde AI manken oluştur — SaaS tarzı consistency ile."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks
        try:
            # Gender/body hints
            gender_hints = {
                'female': 'young woman, 25 years old, natural makeup',
                'male': 'young man, 28 years old, clean shaven',
                'child': 'child, 8 years old',
                'unisex': 'androgynous young adult, 24 years old',
            }
            body_hints = {
                'standard': 'slim athletic build, 170cm height',
                'plus_size': 'plus size, curvy build, 168cm height',
                'petite': 'petite, slender build, 158cm height',
            }

            # Ürün tipine göre kıyafet belirleme (Tam giyinik profesyonel model)
            outfit_hints_front = {
                'tops': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
                'bottoms': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
                'one_piece': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
                'shoes': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
                'bags': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
                'accessories': 'wearing a tight form-fitting solid-colored crop top, matching beige cotton trousers, and clean white sneakers',
            }

            outfit_hints_back = {
                'tops': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
                'bottoms': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
                'one_piece': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
                'shoes': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
                'bags': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
                'accessories': 'wearing a tight solid-colored sports bra that leaves the entire back completely bare and exposed, matching beige cotton trousers, and clean white sneakers',
            }

            garment_type = 'tops'
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, uid, {})
                    p = env['ai.studio.model.preset'].browse(preset_id)
                    garment_type = p.garment_type or 'tops'
            except Exception:
                pass

            enhanced_prompt_front = (
                f"{prompt}, {gender_hints.get(gender, 'young adult')}, "
                f"{body_hints.get(body_type, 'standard build')}, "
                f"{outfit_hints_front.get(garment_type, outfit_hints_front['tops'])}"
            )

            enhanced_prompt_back = (
                f"{prompt}, {gender_hints.get(gender, 'young adult')}, "
                f"{body_hints.get(body_type, 'standard build')}, "
                f"{outfit_hints_back.get(garment_type, outfit_hints_back['tops'])}"
            )

            enhanced_prompt_side = (
                f"{prompt}, {gender_hints.get(gender, 'young adult')}, "
                f"{body_hints.get(body_type, 'standard build')}, "
                f"{outfit_hints_front.get(garment_type, outfit_hints_front['tops'])}"
            )

            if provider_type == 'fashn':
                from ..services.fashn_provider import FashnProvider
                provider = FashnProvider(api_key)
                
                # FASHN model-create ile ön, arka ve yan manken oluştur
                _logger.info('FASHN ile manken oluşturuluyor (ön): preset_id=%s', preset_id)
                front_full_prompt = self._build_full_prompt(enhanced_prompt_front, view='front')
                front_data = provider.generate_mannequin(front_full_prompt)
                if not front_data:
                    raise Exception('FASHN ön görsel boş döndü')
                    
                _logger.info('FASHN ile manken oluşturuluyor (arka): preset_id=%s', preset_id)
                back_full_prompt = self._build_full_prompt(enhanced_prompt_back, view='back')
                back_data = provider.generate_mannequin(back_full_prompt)
                if not back_data:
                    raise Exception('FASHN arka görsel boş döndü')
                    
                _logger.info('FASHN ile manken oluşturuluyor (yan): preset_id=%s', preset_id)
                side_full_prompt = self._build_full_prompt(enhanced_prompt_side, view='side')
                side_data = provider.generate_mannequin(side_full_prompt)
            else:
                # fal.ai premium consistency flow
                _logger.info('fal.ai ile manken oluşturuluyor (ön): preset_id=%s', preset_id)
                front_full_prompt = self._build_full_prompt(enhanced_prompt_front, view='front')

                front_result = self._fal_api_call(
                    'fal-ai/flux-pro/v1.1',
                    {
                        'prompt': front_full_prompt,
                        'image_size': {'width': 864, 'height': 1296},
                        'num_images': 1,
                        'safety_tolerance': 5,
                        'output_format': 'png',
                    },
                    api_key,
                    timeout=120,
                )

                front_images = front_result.get('images', [])
                if not front_images:
                    raise Exception('fal.ai ön görsel boş döndü')

                front_url = front_images[0]['url']
                front_data = self._download_image_b64(front_url)

                # ═══ ARKADAN MANKEN ═══
                _logger.info('fal.ai ile manken oluşturuluyor (arka): preset_id=%s', preset_id)

                # Ön görseli fal storage'a yükle
                front_fal_url = self._upload_to_fal(front_data, api_key)

                if front_fal_url:
                    _logger.info('nano-banana-2/edit ile tutarli arka gorsel')
                    back_prompt = (
                        f"RAW photo, photorealistic, real human being, NOT illustration, NOT cartoon. "
                        f"OUTPUT EXACTLY ONE IMAGE. "
                        f"Show the EXACT SAME person from the reference image, "
                        f"but from the BACK VIEW — facing away from camera. "
                        f"SAME person, SAME trousers, SAME hair, SAME body, SAME skin tone. "
                        f"The top she is wearing is a crop top / sports bra that is open in the back, "
                        f"leaving her back bare and exposed, showing her skin. "
                        f"Only the camera angle changes to show the back. "
                        f"Professional studio fashion photography, white background. "
                        f"{self.IDENTITY_LOCK} {self.ANATOMY_LOCK}"
                    )

                    back_result = self._fal_api_call(
                        'fal-ai/nano-banana-2/edit',
                        {
                            'prompt': back_prompt,
                            'image_urls': [front_fal_url],
                            'num_images': 1,
                            'aspect_ratio': '3:4',
                            'output_format': 'png',
                            'safety_tolerance': '5',
                            'resolution': '2K',
                            'limit_generations': True,
                        },
                        api_key,
                        timeout=180,
                    )
                else:
                    _logger.info('Fallback: text-to-image ile arka görsel')
                    back_full_prompt = self._build_full_prompt(enhanced_prompt_back, view='back')
                    back_result = self._fal_api_call(
                        'fal-ai/flux-pro/v1.1',
                        {
                            'prompt': back_full_prompt,
                            'image_size': {'width': 768, 'height': 1152},
                            'num_images': 1,
                            'safety_tolerance': 5,
                            'output_format': 'png',
                        },
                        api_key,
                        timeout=120,
                    )

                back_images = back_result.get('images', [])
                if not back_images:
                    raise Exception('fal.ai arka görsel boş döndü')

                back_data = self._download_image_b64(back_images[0]['url'])

                # ═══ YANDAN MANKEN ═══
                _logger.info('fal.ai ile manken oluşturuluyor (yan): preset_id=%s', preset_id)
                side_data = False
                if front_fal_url:
                    _logger.info('nano-banana-2/edit ile tutarli yan gorsel')
                    side_prompt = (
                        f"RAW photo, photorealistic, real human being, NOT illustration, NOT cartoon. "
                        f"OUTPUT EXACTLY ONE IMAGE. "
                        f"Show the EXACT SAME person from the reference image, "
                        f"but from the SIDE PROFILE VIEW — standing profile, 90 degree angle. "
                        f"SAME person, SAME clothes, SAME hair, SAME body, SAME skin tone. "
                        f"Only the camera angle changes to show the side profile. "
                        f"Professional studio fashion photography, white background. "
                        f"{self.IDENTITY_LOCK} {self.ANATOMY_LOCK}"
                    )

                    try:
                        side_result = self._fal_api_call(
                            'fal-ai/nano-banana-2/edit',
                            {
                                'prompt': side_prompt,
                                'image_urls': [front_fal_url],
                                'num_images': 1,
                                'aspect_ratio': '3:4',
                                'output_format': 'png',
                                'safety_tolerance': '5',
                                'resolution': '2K',
                                'limit_generations': True,
                            },
                            api_key,
                            timeout=180,
                        )
                        side_images = side_result.get('images', [])
                        if side_images:
                            side_data = self._download_image_b64(side_images[0]['url'])
                    except Exception as e:
                        _logger.warning('Yandan manken oluşturulamadı, es geçiliyor: %s', e)

            # ═══ ÖNİZLEME: Ön görselin küçük kopyası ═══
            preview_data = front_data  # Aynı veri, Odoo otomatik resize eder

            # ═══ DB'ye kaydet ═══
            with self.pool.cursor() as cr:
                env = api.Environment(cr, uid, {})
                preset = env['ai.studio.model.preset'].browse(preset_id)
                preset.write({
                    'model_image_front': front_data,
                    'model_image_back': back_data,
                    'model_image_side': side_data or False,
                    'preview_image': preview_data,
                    'mannequin_generation_state': 'done',
                })
                cr.commit()

            _logger.info('Manken oluşturma tamamlandı: preset_id=%s', preset_id)

        except Exception as e:
            from ..services.fal_error_handler import parse_fal_error, format_fal_error_for_log
            parsed = parse_fal_error(e)
            _logger.error('Manken oluşturma hatası: %s', format_fal_error_for_log(e, f'preset={preset_id}'))
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, uid, {})
                    preset = env['ai.studio.model.preset'].browse(preset_id)
                    preset.write({'mannequin_generation_state': 'failed'})
                    cr.commit()
            except Exception:
                _logger.error('Durum güncelleme de başarısız oldu')

    # ─── Kıyafet Giydirme (nano-banana-2/edit) ────────────────────
    @staticmethod
    def fal_tryon(garment_image_url, mannequin_image_url, prompt, api_key):
        """SaaS tarzı kıyafet giydirme — nano-banana-2/edit (SDK)."""
        import os
        os.environ['FAL_KEY'] = api_key

        try:
            import fal_client
        except ImportError:
            raise Exception('fal-client paketi kurulu değil.')

        full_prompt = (
            f"OUTPUT EXACTLY ONE IMAGE. {prompt} "
            "Put the garment from the first image onto the model in the second image. "
            "Preserve the garment's exact color, fabric texture, stitching, and pattern details. "
            "Keep the model's face, skin tone, hair, and pose exactly the same. "
            "Professional e-commerce fashion photography, white studio background."
        )

        _logger.info('nano-banana-2/edit kıyafet giydirme çağrısı (SDK)')
        result = fal_client.subscribe(
            'fal-ai/nano-banana-2/edit',
            arguments={
                'prompt': full_prompt,
                'image_urls': [garment_image_url, mannequin_image_url],
                'num_images': 1,
                'aspect_ratio': '3:4',
                'output_format': 'png',
                'safety_tolerance': '4',
                'resolution': '2K',
                'limit_generations': True,
            },
            client_timeout=180,
        )
        return result



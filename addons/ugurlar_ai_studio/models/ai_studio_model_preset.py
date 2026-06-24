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

    # ─── SaaS Prompt Lock Sistemi (20+ Lock) ──────────────────────────
    # SaaS projesinin sharedPrompts.ts'inden birebir uyarlanmıştır.

    # 1. Photorealism
    REALISM_LOCK = (
        "PHOTOREALISM MANDATE — This must look like an unretouched RAW "
        "photograph taken with a Hasselblad X2D. "
        "FACE: visible pores on nose/cheeks/forehead, subtle undereye texture, "
        "natural lip dryness lines, real skin translucency. "
        "Slight facial asymmetry is MANDATORY — no perfectly symmetrical faces. "
        "EYES: Wet corneal reflection, visible iris fibres, natural eyelid crease. "
        "HAIR: Individually resolved strands with natural flyaways at crown and temples, "
        "gravity-affected density variation. NOT a smooth CG hair shader. "
        "SKIN: Subsurface scattering on ears/fingertips, vellus hair on cheeks and jawline, "
        "natural tonal variation. NO porcelain/waxy/airbrushed/plastic skin. "
        "EXPRESSION: Neutral editorial expression with authentic micro-tension. "
        "NOT a blank AI stare. "
        "CAMERA: Natural sensor grain, medium-format RAW optic emulation."
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

    # 4. Anti-Nude / Full Outfit (İç Çamaşırı / Sade Spor Giyim Modu)
    ANTI_NUDE_LOCK = (
        "OUTFIT MANDATORY LOCK: The model MUST wear minimal form-fitting activewear or underwear. "
        "Model MUST wear: a simple form-fitting neutral crop top / sports bra and matching boy shorts / briefs / leggings. "
        "No bare chest, no total nudity. The undergarments should be completely plain, neutral gray or black color, with no patterns. "
        "This is a mannequin preset — the model should be in tight, skin-hugging undergarments or sportswear "
        "so that clothes can be easily dressed over them by AI later. "
        "ANY actual total nudity (completely bare body) is a CRITICAL FAILURE."
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
        "NEGATIVE: extra arms, extra legs, extra fingers, duplicated face, "
        "double head, ghosting limbs, warped anatomy, deformed body, "
        "mannequin, doll, plastic/waxy/porcelain skin, CGI look, "
        "beauty filter, airbrushed, over-smooth, blurry, low quality, "
        "collage, split screen, multi-panel, grid layout, montage, "
        "interior room, furniture, flat-lay, hanger, product-only shot, "
        "bare midriff, bare chest, exposed stomach, underwear look, nude model, "
        "SMILING, HAPPY, LAUGHING, ROBOTIC, STIFF."
    )

    # 8. Premium Capture
    CAPTURE_LOCK = (
        "Ultra premium capture lock: emulate top-tier medium-format RAW capture. "
        "Preserve nuanced tonal roll-off, highlight retention, rich but natural blacks. "
        "Keep eyes, lashes, brows, lips, skin micro-relief tack-sharp at focal plane. "
        "No fake HDR halos, no clarity overdrive, no sharpening artifacts."
    )

    @staticmethod
    def _fal_api_call(endpoint, payload, api_key, timeout=120):
        """fal.ai SYNC REST API çağrısı."""
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

    @staticmethod
    def _upload_to_fal(image_b64_bytes, api_key):
        """Base64 görsel datayı fal.ai storage'a yükle, URL döndür."""
        import requests as req

        # Base64 bytes -> raw bytes
        raw_data = base64.b64decode(image_b64_bytes)

        url = 'https://fal.run/fal-ai/any-llm'  # dummy — we use storage
        # fal.ai REST storage upload
        upload_url = 'https://rest.alpha.fal.ai/storage/upload/initiate'
        headers = {
            'Authorization': f'Key {api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        # Initiate upload
        init_resp = req.post(upload_url, json={
            'content_type': 'image/png',
            'file_name': 'mannequin.png',
        }, headers=headers, timeout=30)

        if init_resp.status_code != 200:
            _logger.warning('fal storage upload başarısız: %s', init_resp.text[:300])
            return None

        init_data = init_resp.json()
        put_url = init_data.get('upload_url')
        file_url = init_data.get('file_url')

        if put_url:
            # Upload raw data
            req.put(put_url, data=raw_data, headers={
                'Content-Type': 'image/png',
            }, timeout=60)

        return file_url

    def _build_full_prompt(self, base_prompt, view='front'):
        """Tüm lock'ları birleştirerek tam prompt oluştur."""
        view_desc = (
            'front view, facing camera directly'
            if view == 'front'
            else 'back view, facing away from camera, showing full back'
        )

        return (
            f"{base_prompt}, {view_desc}, full body shot from head to feet, "
            f"standing pose, fashion model photography, e-commerce catalog style. "
            f"{self.REALISM_LOCK} "
            f"{self.STUDIO_LOCK} "
            f"{self.ANATOMY_LOCK} "
            f"{self.ANTI_NUDE_LOCK} "
            f"{self.POSTURE_LOCK} "
            f"{self.IDENTITY_LOCK} "
            f"{self.CAPTURE_LOCK} "
            f"{self.NEGATIVE_LOCK}"
        )

    def _generate_mannequin_thread(self, preset_id, prompt, api_key,
                                    gender, body_type, bg_type):
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

            # Ürün tipine göre kıyafet belirleme (İç çamaşırı / minimal spor giyim)
            outfit_hints = {
                'tops': 'wearing a tight simple sports bra, minimal shorts, barefoot',
                'bottoms': 'wearing a tight crop top, simple neutral briefs, barefoot',
                'one_piece': 'wearing a tight minimalist sports crop top and matching boy shorts, barefoot',
                'shoes': 'wearing a minimal sports bra and tight short leggings, bare feet',
                'bags': 'wearing a tight black crop top and simple grey sports shorts, barefoot',
                'accessories': 'wearing a simple neutral sports bra and basic boy shorts, barefoot',
            }

            garment_type = 'tops'
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    p = env['ai.studio.model.preset'].browse(preset_id)
                    garment_type = p.garment_type or 'tops'
            except Exception:
                pass

            enhanced_prompt = (
                f"{prompt}, {gender_hints.get(gender, 'young adult')}, "
                f"{body_hints.get(body_type, 'standard build')}, "
                f"{outfit_hints.get(garment_type, outfit_hints['tops'])}"
            )

            # ═══ ÖNDEN MANKEN ═══
            _logger.info('Manken oluşturuluyor (ön): preset_id=%s', preset_id)
            front_full_prompt = self._build_full_prompt(enhanced_prompt, view='front')

            front_result = self._fal_api_call(
                'fal-ai/flux-pro/v1.1',
                {
                    'prompt': front_full_prompt,
                    'image_size': {'width': 768, 'height': 1152},
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
            # Ön görseli referans olarak kullan — aynı kişi olsun
            _logger.info('Manken oluşturuluyor (arka): preset_id=%s', preset_id)

            # Ön görseli fal storage'a yüklemeyi dene
            front_fal_url = self._upload_to_fal(front_data, api_key)

            if front_fal_url:
                # nano-banana-pro/edit ile tutarlı arka görsel
                _logger.info('nano-banana-pro/edit ile tutarlı arka görsel')
                back_prompt = (
                    f"OUTPUT EXACTLY ONE IMAGE. "
                    f"Show the EXACT SAME person from the reference image, "
                    f"but from the BACK VIEW — facing away from camera. "
                    f"SAME person, SAME clothes, SAME hair, SAME body. "
                    f"Only the camera angle changes to show the back. "
                    f"{self.IDENTITY_LOCK} {self.ANTI_NUDE_LOCK} "
                    f"{self.ANATOMY_LOCK} {self.STUDIO_LOCK}"
                )

                back_result = self._fal_api_call(
                    'fal-ai/nano-banana-pro/edit',
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
                # Fallback: text-to-image ile arka görsel
                _logger.info('Fallback: text-to-image ile arka görsel')
                back_full_prompt = self._build_full_prompt(enhanced_prompt, view='back')
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

            # ═══ ÖNİZLEME: Ön görselin küçük kopyası ═══
            preview_data = front_data  # Aynı veri, Odoo otomatik resize eder

            # ═══ DB'ye kaydet ═══
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                preset = env['ai.studio.model.preset'].browse(preset_id)
                preset.write({
                    'model_image_front': front_data,
                    'model_image_back': back_data,
                    'preview_image': preview_data,
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
        """SaaS tarzı kıyafet giydirme — nano-banana-pro/edit."""
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



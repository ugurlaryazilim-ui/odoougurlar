import logging
import base64
import threading
import time

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiStudioSession(models.Model):
    """Ana çekim oturumu modeli.

    Barkod tarama → fotoğraf çekimi → AI işleme → onay/red → ürüne kaydetme
    akışının merkezi yönetim noktası. mail.thread ile bildirim desteği sağlar.
    """
    _name = 'ai.studio.session'
    _description = 'AI Stüdyo Çekim Oturumu'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Oturum No',
        readonly=True,
        default='/',
        copy=False,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ürün Varyantı',
        required=True,
        tracking=True,
        index=True,
    )
    product_barcode = fields.Char(
        related='product_id.barcode',
        string='Barkod',
    )
    product_image = fields.Image(
        related='product_id.image_128',
        string='Mevcut Ürün Resmi',
    )

    # --- Varyant Grubu ---
    apply_to_siblings = fields.Boolean(
        string='Tüm Bedenlere Uygula',
        help='Aynı kesimin tüm beden varyantlarına uygula',
    )
    sibling_product_ids = fields.Many2many(
        'product.product',
        string='Kardeş Varyantlar',
        compute='_compute_siblings',
    )

    # --- Durum ---
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('photos_ready', 'Fotoğraflar Hazır'),
        ('preprocessing', 'Ön İşlem'),
        ('processing', 'AI İşliyor'),
        ('review', 'Onay Bekliyor'),
        ('done', 'Tamamlandı'),
        ('cancelled', 'İptal'),
    ], string='Durum', default='draft', tracking=True, index=True)

    # --- AI Ayarları ---
    model_preset_id = fields.Many2one(
        'ai.studio.model.preset',
        string='Manken Preseti',
        tracking=True,
    )
    category = fields.Selection([
        ('tops', 'Üst Giyim'),
        ('bottoms', 'Alt Giyim'),
        ('one_piece', 'Tek Parça / Elbise'),
        ('shoes', 'Ayakkabı'),
        ('bags', 'Çanta'),
        ('accessories', 'Aksesuar'),
        ('auto', 'Otomatik'),
    ], string='Kategori', default='auto')
    quality_mode = fields.Selection([
        ('performance', 'Hızlı'),
        ('balanced', 'Dengeli'),
        ('quality', 'Kaliteli'),
    ], string='Kalite Modu', default='balanced')
    extra_prompt = fields.Text(string='İlave Talimat')
    prompt_template_id = fields.Many2one(
        'ai.studio.prompt.template',
        string='Prompt Şablonu',
    )

    # --- İlişkiler ---
    photo_ids = fields.One2many(
        'ai.studio.photo',
        'session_id',
        string='Fotoğraflar',
    )
    generation_ids = fields.One2many(
        'ai.studio.generation',
        'session_id',
        string='AI Üretimler',
    )

    # --- Kullanıcılar ---
    user_id = fields.Many2one(
        'res.users',
        string='Operatör',
        default=lambda self: self.env.user,
        tracking=True,
    )
    reviewer_id = fields.Many2one(
        'res.users',
        string='Onayıcı',
    )

    # --- İstatistikler ---
    total_cost = fields.Monetary(
        string='Toplam Maliyet',
        compute='_compute_stats',
        store=True,
        currency_field='currency_id',
    )
    revision_count = fields.Integer(
        string='Toplam Revizyon',
        compute='_compute_stats',
        store=True,
    )
    approval_rate = fields.Float(
        string='Onay Oranı (%)',
        compute='_compute_stats',
        store=True,
        digits=(5, 1),
    )
    photo_count = fields.Integer(
        string='Fotoğraf Sayısı',
        compute='_compute_photo_count',
    )
    generation_count = fields.Integer(
        string='Üretim Sayısı',
        compute='_compute_photo_count',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Para Birimi',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Şirket',
        default=lambda self: self.env.company,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Otomatik sıra numarası ata."""
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'ai.studio.session'
                ) or '/'
        return super().create(vals_list)

    @api.depends('product_id')
    def _compute_siblings(self):
        """Aynı template'in diğer varyantlarını bul."""
        for session in self:
            if session.product_id and session.product_id.product_tmpl_id:
                tmpl = session.product_id.product_tmpl_id
                siblings = tmpl.product_variant_ids - session.product_id
                session.sibling_product_ids = siblings
            else:
                session.sibling_product_ids = False

    @api.depends('generation_ids.cost', 'generation_ids.is_approved',
                 'generation_ids.revision_number', 'generation_ids.state')
    def _compute_stats(self):
        """Maliyet, revizyon ve onay istatistiklerini hesapla."""
        for session in self:
            gens = session.generation_ids
            session.total_cost = sum(gens.mapped('cost'))
            session.revision_count = sum(
                max(0, g.revision_number - 1) for g in gens
            )
            done_gens = gens.filtered(lambda g: g.state == 'done')
            if done_gens:
                approved = done_gens.filtered('is_approved')
                session.approval_rate = (len(approved) / len(done_gens)) * 100
            else:
                session.approval_rate = 0.0

    def _compute_photo_count(self):
        for session in self:
            session.photo_count = len(session.photo_ids)
            session.generation_count = len(session.generation_ids)

    def _crop_image_detail(self, image_base64, category='tops'):
        """Base64 formatındaki resmi Pillow ile kırpar ve base64 döner."""
        if not image_base64:
            return False
        try:
            import io
            import base64
            from PIL import Image
            
            # Base64 decode
            img_data = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_data))
            w, h = img.size
            
            # Kategoriye göre koordinatları belirle
            if category == 'bottoms':
                # Alt giyim için kalça/cep hizası
                left = int(w * 0.20)
                top = int(h * 0.42)
                right = int(w * 0.80)
                bottom = int(h * 0.75)
            else:
                # Üst giyim ve tek parça için göğüs/yaka hizası
                left = int(w * 0.22)
                top = int(h * 0.20)
                right = int(w * 0.78)
                bottom = int(h * 0.55)
                
            # Kırpma işlemi
            cropped_img = img.crop((left, top, right, bottom))
            
            # Tekrar base64'e dönüştür
            buffered = io.BytesIO()
            img_format = img.format or 'JPEG'
            cropped_img.save(buffered, format=img_format, quality=95)
            return base64.b64encode(buffered.getvalue())
        except Exception as e:
            _logger.error("Kırpma hatası: %s", e)
            return image_base64

    def _generate_inpainting_mask(self, image_base64, garment_type='tops'):
        """Base64 resmin boyutunda inpainting maskesi üretir.
        
        Tops: Belden aşağısını (pants/shoes) inpaint et. (y > h * 0.44)
        Bottoms: Belden yukarısını (tops/face) inpaint et. (y < h * 0.44)
        Full-body/Dress: Sadece ayakları (shoes) inpaint et. (y > h * 0.82)
        """
        if not image_base64:
            return False
        try:
            import io
            import base64
            from PIL import Image, ImageDraw
            
            img_data = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_data))
            w, h = img.size
            
            # Siyah maske oluştur (0 = edit yok)
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            
            category = garment_type or 'tops'
            if category == 'tops':
                # Üst giyim: alt kısmı boya (white = edit et)
                draw.rectangle([0, int(h * 0.44), w, h], fill=255)
            elif category == 'bottoms':
                # Alt giyim: üst kısmı boya
                draw.rectangle([0, 0, w, int(h * 0.44)], fill=255)
            else:
                # Full-body/elbise: sadece ayakkabı bölgesini boya
                draw.rectangle([0, int(h * 0.82), w, h], fill=255)
                
            buffered = io.BytesIO()
            mask.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue())
        except Exception as e:
            _logger.error("Maske üretme hatası: %s", e)
            return False

    def _remove_hanger_hook(self, image_base64):
        """Gorseldeki aski kancasini ve etiketleri temizler.

        Yontem:
        1. Ust %20'lik alani tara
        2. Dar cikintilari (aski kancasi) tespit et
        3. OpenCV inpainting ile temizle
        4. Alternatif: piksel bazli temizleme (OpenCV yoksa)
        """
        if not image_base64:
            return False
        try:
            import io
            import base64
            from PIL import Image

            img_data = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(img_data))

            # RGBA moduna cevir
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            w, h = img.size

            try:
                import cv2
                import numpy as np

                # PIL -> numpy (BGRA)
                img_array = np.array(img)
                alpha = img_array[:, :, 3]

                # Ust %20 alanin maske'sini olustur
                top_region = int(h * 0.20)
                mask = np.zeros((h, w), dtype=np.uint8)

                # Alpha kanalinda opak olan yerleri bul
                _, binary = cv2.threshold(alpha[:top_region], 30, 255, cv2.THRESH_BINARY)

                # Kontur analizi — dar cikintilari bul
                contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                for cnt in contours:
                    x, y, cw, ch = cv2.boundingRect(cnt)
                    area = cv2.contourArea(cnt)

                    # Aski kancasi ozellikleri:
                    # - Dar (genislik < resim genisliginin %15'i)
                    # - Uzun/ince (yukseklik/genislik orani > 1.5)
                    # - Kucuk alan
                    is_narrow = cw < (w * 0.15)
                    is_tall_and_thin = ch > cw * 1.5 if cw > 0 else False
                    is_small_area = area < (w * h * 0.02)

                    if is_narrow and (is_tall_and_thin or is_small_area):
                        # Bu bir aski kancasi — maskeye ekle
                        cv2.drawContours(mask[:top_region], [cnt], -1, 255, cv2.FILLED)
                        # Etrafina biraz tampon ekle
                        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                        mask[:top_region] = cv2.dilate(mask[:top_region], kernel, iterations=2)

                # Maske'de temizlenecek alan varsa
                if np.any(mask > 0):
                    # RGB kanallarini al (inpainting icin)
                    rgb = cv2.cvtColor(img_array[:, :, :3], cv2.COLOR_RGBA2BGR)
                    # Inpaint ile temizle
                    inpainted = cv2.inpaint(rgb, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
                    # Maskelenen alanlarin alpha'sini sifirla (seffaf yap)
                    img_array[:, :, 3][mask > 0] = 0

                    result_img = Image.fromarray(img_array)
                    buffered = io.BytesIO()
                    result_img.save(buffered, format='PNG')
                    _logger.info('Aski kancasi temizlendi (OpenCV inpainting)')
                    return base64.b64encode(buffered.getvalue())
                else:
                    # Temizlenecek alan yok
                    return image_base64

            except ImportError:
                # OpenCV yoksa eski yontem (piksel bazli)
                pixels = img.load()
                for y in range(int(h * 0.25)):
                    non_transparent_count = 0
                    for x in range(w):
                        r, g, b, a = pixels[x, y]
                        if a > 30:
                            non_transparent_count += 1

                    if non_transparent_count > 0 and non_transparent_count < (w * 0.10):
                        for x in range(w):
                            pixels[x, y] = (0, 0, 0, 0)
                    elif non_transparent_count >= (w * 0.10):
                        break

                buffered = io.BytesIO()
                img.save(buffered, format='PNG')
                return base64.b64encode(buffered.getvalue())

        except Exception as e:
            _logger.error("Aski kancasi temizleme hatasi: %s", e)
            return image_base64

    # --- Durum Geçişleri ---

    def action_photos_ready(self):
        """Fotoğraflar çekildi, AI'ya göndermeye hazır."""
        for session in self:
            if not session.photo_ids:
                raise UserError(_('En az bir fotoğraf çekilmeli.'))
            session.state = 'photos_ready'

    def action_start_processing(self):
        """AI işlemeyi başlat."""
        self.ensure_one()
        if not self.model_preset_id:
            raise UserError(_('Lütfen bir manken preseti seçin.'))
        if not self.photo_ids:
            raise UserError(_('Fotoğraf yok. Önce fotoğraf çekin.'))

        # Provider secimi ve API key kontrolu
        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fashn_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'FASHN API anahtarı ayarlanmamış. '
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key'
            )
            if not api_key:
                raise UserError(_(
                    'fal.ai API anahtarı ayarlanmamış. '
                    'Ayarlar → AI Stüdyo menüsünden girin.'
                ))

        # Ön yüz fotoğrafını doğrula
        photos_by_type = {p.photo_type: p for p in self.photo_ids}
        front_photo = photos_by_type.get('front')
        if not front_photo:
            raise UserError(_('AI işlemeyi başlatabilmek için en azından Ön Yüz fotoğrafı yüklenmiş olmalıdır.'))

        self.state = 'preprocessing'

        # Eski generation kayıtlarını temizle
        self.generation_ids.unlink()

        # 4 görsel çıktısı için generation kayıtlarını oluştur
        # 1. Ön Görsel
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': front_photo.id,
            'photo_type': 'front',
            'original_image': front_photo.image_original,
            'state': 'pending',
            'provider': provider_type,
        })

        # 2. Arka Görsel (varsa)
        back_photo = photos_by_type.get('back')
        if back_photo:
            self.env['ai.studio.generation'].create({
                'session_id': self.id,
                'source_photo_id': back_photo.id,
                'photo_type': 'back',
                'original_image': back_photo.image_original,
                'state': 'pending',
                'provider': provider_type,
            })

        # 3. Yan Görsel (varsa side_photo, yoksa front_photo kullanılır)
        side_photo = photos_by_type.get('side')
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': (side_photo or front_photo).id,
            'photo_type': 'side',
            'original_image': (side_photo or front_photo).image_original,
            'state': 'pending',
            'provider': provider_type,
        })

        # 4. Detay Görsel (varsa detail_photo, yoksa front_photo kullanılır)
        detail_photo = photos_by_type.get('detail')
        self.env['ai.studio.generation'].create({
            'session_id': self.id,
            'source_photo_id': (detail_photo or front_photo).id,
            'photo_type': 'detail',
            'original_image': (detail_photo or front_photo).image_original,
            'state': 'pending',
            'provider': provider_type,
        })

        # Eşzamanlı istek limiti kontrolü
        concurrent_limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.concurrent_limit', '2'
        ))
        active_processing = self.search_count([
            ('state', '=', 'processing'),
            ('id', '!=', self.id),
        ])
        if active_processing >= concurrent_limit:
            _logger.warning(
                'Eşzamanlı AI işlem limiti (%d) aşıldı. '
                'Aktif: %d. İşlem yine de başlatılıyor (kuyrukta bekleyecek).',
                concurrent_limit, active_processing,
            )

        # Arka planda AI işlemeyi başlat
        thread = threading.Thread(
            target=self._process_ai_thread,
            args=(self.id, api_key),
        )
        thread.daemon = True
        thread.start()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI İşleme Başladı'),
                'message': _('Fotoğraflar AI tarafından işleniyor. Tamamlandığında bildirim alacaksınız.'),
                'type': 'info',
                'sticky': False,
            },
        }

    @staticmethod
    def _create_provider(api_key, provider_type='fashn'):
        """Ayardaki secime gore provider olustur."""
        if provider_type == 'fashn':
            from ..services.fashn_provider import FashnProvider
            return FashnProvider(api_key)
        else:
            from ..services.fal_provider import FalProvider
            return FalProvider(api_key)

    def _process_single_generation_worker(self, session_id, gen_id, api_key, front_result_b64, outfit_consistency, front_seed, cached_analysis_data=None):
        """Worker thread for processing a single generation (used for parallelizing back and side views)."""
        _logger.info('Worker thread baslatildi (gen_id=%s)', gen_id)
        
        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            session = env['ai.studio.session'].browse(session_id)
            gen = env['ai.studio.generation'].browse(gen_id)
            preset = session.model_preset_id
            
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            fal_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            
            try:
                provider = self._create_provider(api_key, provider_type)
            except Exception as e:
                _logger.error('Worker AI provider olusturma hatasi: %s', e)
                return

            try:
                gen.write({'state': 'processing'})
                cr.commit()

                start_time = time.time()
                source_image = gen.original_image
                photo_type = gen.photo_type or 'front'

                # ═══ GÖRSEL ÖN İŞLEME PIPELINE ═══
                from ..services.garment_preprocessor import (
                    preprocess_garment_image,
                    convert_birefnet_output_to_rgb,
                )

                preprocessed = preprocess_garment_image(
                    source_image,
                    target_long_edge=864,
                )
                processed_b64 = preprocessed['image_base64']

                # ═══ APILER İÇİN URL VE FORMAT AYARLARI ═══
                model_image_field = 'model_image_front'
                if photo_type == 'back':
                    model_image_field = 'model_image_back'
                elif photo_type == 'side':
                    model_image_field = 'model_image_side'

                model_image_data = getattr(preset, model_image_field)
                if not model_image_data:
                    model_image_data = preset.model_image_front

                # Upload images
                model_url = provider.upload_image(model_image_data)
                garment_url = provider.upload_image(processed_b64)

                tryon_model = 'tryon-v1.6' if provider_type == 'fal' else 'tryon-v1.6'
                tryon_resolution = '1K'
                if provider_type == 'fashn':
                    tryon_model = preset.fashn_model_side if photo_type == 'side' else (preset.fashn_model_back if photo_type == 'back' else preset.fashn_model_front)
                    if not tryon_model:
                        tryon_model = 'tryon-v1.6'
                    tryon_resolution = '2K' if 'max' in tryon_model else '1K'

                # category mapping
                from ..services.garment_analyzer import map_to_fashn_category
                category_to_send = map_to_fashn_category(cached_analysis_data or {})

                # ═══ VIEW-SPESİFİK PROMPT ═══
                prompt_text = ""
                try:
                    all_locks = env['ai.studio.prompt.template'].search([
                        ('scope', '=', 'global'),
                        ('active', '=', True),
                    ])
                    prompt_locks = [l.prompt_text for l in all_locks]

                    from ..services.garment_analyzer import build_generation_prompt
                    built_prompt = build_generation_prompt(
                        cached_analysis_data or {}, {
                            'gender': preset.gender or 'female',
                            'body_type': preset.body_type or 'standard',
                            'target_audience': preset.target_audience or '',
                        },
                        prompt_locks,
                        session.extra_prompt or '',
                        photo_type=photo_type,
                        outfit_consistency=outfit_consistency,
                    )
                    prompt_text = built_prompt.get('positive', '')
                except Exception as pe:
                    _logger.warning('Worker: Prompt olusturma basarisiz (gen=%s): %s', gen.id, pe)

                # ═══ TRY-ON API ÇAĞRISI ═══
                tryon_result = provider.virtual_tryon(
                    model_image_url=model_url,
                    garment_image_url=garment_url,
                    category=category_to_send,
                    mode=session.quality_mode or 'quality',
                    model_name=tryon_model,
                    num_samples=1,
                    garment_photo_type='auto',
                    output_format='jpeg',
                    prompt=prompt_text,
                    resolution=tryon_resolution,
                    photo_type=photo_type,
                    seed=front_seed,
                )

                elapsed = time.time() - start_time

                # ═══ SONUCU İNDİR ═══
                import requests as req_lib
                import base64
                output_url = tryon_result.get('image_url', '')
                if not output_url:
                    image_urls = tryon_result.get('image_urls', [])
                    output_url = image_urls[0] if image_urls else ''

                if output_url:
                    if output_url.startswith('data:'):
                        raw = output_url.split(';base64,', 1)[1]
                        img_data = base64.b64decode(raw)
                    else:
                        img_data = req_lib.get(output_url, timeout=60).content

                    gen_b64 = base64.b64encode(img_data)
                    gen_seed = tryon_result.get('seed') or False

                    gen.write({
                        'generated_image': gen_b64,
                        'state': 'done',
                        'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                        'generation_time_seconds': elapsed,
                        'cost': tryon_result.get('cost', 0.05),
                        'seed': gen_seed,
                    })

                    # ═══ BACK/SIDE POST-PROCESSING: OUTFIT TUTARLILIĞI ═══
                    if front_result_b64 and outfit_consistency:
                        consistency_prompt = outfit_consistency.get('fullOutfitPrompt', '')
                        if consistency_prompt:
                            try:
                                _logger.info(
                                    'Worker: Post-processing outfit tutarliligi (flux-img2img+ipadapter) baslatiliyor (gen=%s, tip=%s)',
                                    gen.id, photo_type,
                                )
                                front_ref_url = provider.upload_image(front_result_b64)
                                current_url = provider.upload_image(gen_b64)

                                bottoms_desc = outfit_consistency.get('bottomsColor', '') + ' ' + outfit_consistency.get('bottomsType', '')
                                shoes_desc = outfit_consistency.get('shoesColor', '') + ' ' + outfit_consistency.get('shoesType', '')

                                edit_prompt = (
                                    f"RAW photo, photorealistic, professional fashion photography, studio lighting, white background. "
                                    f"A model wearing a top garment, matching the outfit from the reference image. "
                                    f"The model must wear the exact same {bottoms_desc.strip()} and the exact same {shoes_desc.strip()} "
                                    f"as shown in the reference image. Perfect color tone matching, high detail, 8k resolution."
                                )

                                import os
                                os.environ['FAL_KEY'] = fal_api_key

                                try:
                                    import fal_client
                                except ImportError:
                                    fal_client = None

                                if fal_client:
                                    # Maske üret ve fal.ai'a yükle
                                    mask_b64 = session._generate_inpainting_mask(gen_b64, garment_type=preset.garment_type or 'tops')
                                    mask_url = provider.upload_image(mask_b64) if mask_b64 else None

                                    arguments_to_send = {
                                        'prompt': edit_prompt,
                                        'image_url': current_url,
                                        'strength': 0.82,  # Maskeli alan için yüksek inpainting gücü
                                        'ip_adapters': [
                                            {
                                                'image_url': front_ref_url,
                                                'conditioning_scale': 0.85,
                                            }
                                        ],
                                        'num_images': 1,
                                        'aspect_ratio': '3:4',
                                        'enable_safety_checker': True,
                                    }
                                    if mask_url:
                                        arguments_to_send['mask_url'] = mask_url

                                    edit_result = fal_client.subscribe(
                                        'fal-ai/flux/schnell/image-to-image',
                                        arguments=arguments_to_send,
                                        client_timeout=300,
                                    )
                                    edit_images = edit_result.get('images', [])
                                    if edit_images:
                                        edit_url = edit_images[0].get('url', '')
                                        if edit_url:
                                            edit_data = req_lib.get(edit_url, timeout=60).content
                                            edited_b64 = base64.b64encode(edit_data)
                                            gen.write({
                                                'generated_image': edited_b64,
                                                'fal_endpoint': '%s/%s+consistency' % (provider_type, tryon_model),
                                                'cost': tryon_result.get('cost', 0.05) + 0.03,
                                            })
                                            gen_b64 = edited_b64
                                            _logger.info('Worker: Post-processing outfit tutarliligi tamamlandi (gen=%s)', gen.id)
                            except Exception as pp_e:
                                _logger.warning('Worker: Post-processing outfit tutarliligi basarisiz (gen=%s): %s', gen.id, pp_e)

                    # ═══ KALİTE KONTROL ═══
                    try:
                        from ..services.quality_checker import compute_quality_score
                        qc = compute_quality_score(source_image, gen_b64)
                        gen.write({
                            'quality_score': qc['score'],
                            'quality_details': qc['details'],
                        })
                    except Exception as qe:
                        _logger.debug('Worker: Kalite kontrol hatasi: %s', qe)

                else:
                    gen.write({
                        'state': 'failed',
                        'error_message': 'API sonuç döndürmedi.',
                    })

                cr.commit()

            except Exception as e:
                from ..services.fal_error_handler import parse_fal_error
                parsed = parse_fal_error(e)
                _logger.error('Worker: AI üretim hatası (gen=%s): %s', gen_id, e)
                gen.write({
                    'state': 'failed',
                    'error_message': parsed['message'][:500],
                })
                cr.commit()

    def _process_ai_thread(self, session_id, api_key):
        """Thread içinde tüm generation'ları işle (wrapper)."""
        try:
            self._process_ai_thread_body(session_id, api_key)
        except Exception as thread_err:
            _logger.exception("AI Thread: Beklenmeyen kritik hata olustu: %s", thread_err)
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    session = env['ai.studio.session'].browse(session_id)
                    session.write({'state': 'failed'})
                    session.message_post(body=_('Kritik Sistem Hatası: %s') % str(thread_err))
                    cr.commit()
            except Exception:
                pass

    def _process_ai_thread_body(self, session_id, api_key):
        """Thread içinde tüm generation'ları işle (body)."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks
        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            fal_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )

        try:
            provider = self._create_provider(api_key, provider_type)
        except ImportError as ie:
            _logger.error('AI provider kurulu degil: %s', ie)
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                session = env['ai.studio.session'].browse(session_id)
                session.write({'state': 'draft'})
                session.message_post(
                    body=_('Hata: AI provider Python paketi kurulu değil. (%s)') % str(ie)
                )
            return

        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            session = env['ai.studio.session'].browse(session_id)
            session.write({'state': 'processing'})
            cr.commit()

            preset = session.model_preset_id
            generations = session.generation_ids.filtered(
                lambda g: g.state == 'pending'
            )

            auto_bg = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.auto_bg_remove', 'True'
            ) == 'True'

            # ═══ AYARLARI YUKLE ═══
            tryon_model = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.tryon_model', 'tryon-max'
            )
            tryon_resolution = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.tryon_resolution', '2K'
            )

            # ═══ KIYAFET ANALIZINI CACHE'LE (tek API cagrisi) ═══
            cached_analysis = None
            try:
                front_gen = generations.filtered(lambda g: g.photo_type == 'front')
                if front_gen and front_gen[0].original_image:
                    from ..services.garment_preprocessor import preprocess_garment_image
                    _pre = preprocess_garment_image(front_gen[0].original_image, target_long_edge=864)
                    _pre_url = provider.upload_image(_pre['image_base64'])

                    from ..services.garment_analyzer import analyze_garment
                    cached_analysis = analyze_garment(
                        fal_api_key, _pre_url, gemini_api_key=gemini_api_key
                    )
                    _logger.info(
                        'Kıyafet analizi tamamlandı: %s %s, hasGraphic=%s',
                        cached_analysis.get('garmentType', '?'),
                        cached_analysis.get('primaryColor', '?'),
                        cached_analysis.get('hasGraphic', False),
                    )
            except Exception as ae:
                _logger.warning('Kıyafet analizi başarısız, varsayılan kullanılacak: %s', ae)

            # ═══ TÜM GENERATION'LARI İŞLE ═══
            # Cross-view tutarlılık verisi — front sonrası doldurulur
            outfit_consistency = None
            front_result_b64 = None  # Front try-on sonucu — back/side post-processing referansı
            front_seed = None  # Front try-on seed'i — back/side FASHN çağrısı için referans

            # Sıralama: front → back → side → detail
            ordered_gens = (
                generations.filtered(lambda g: g.photo_type == 'front')
                + generations.filtered(lambda g: g.photo_type == 'back')
                + generations.filtered(lambda g: g.photo_type == 'side')
                + generations.filtered(lambda g: g.photo_type == 'detail')
            )

            front_failed = False
            for gen in ordered_gens:
                photo_type = gen.photo_type or 'front'
                if front_failed:
                    gen.write({
                        'state': 'failed',
                        'error_message': _('Ön yüz üretimi başarısız olduğu için bu işlem iptal edildi.'),
                    })
                    cr.commit()
                    continue

                try:
                    gen.write({'state': 'processing'})
                    cr.commit()

                    start_time = time.time()
                    source_image = gen.original_image

                    from ..services.garment_preprocessor import (
                        preprocess_garment_image,
                        convert_birefnet_output_to_rgb,
                    )

                    preprocessed = preprocess_garment_image(source_image, target_long_edge=864)
                    processed_b64 = preprocessed['image_base64']

                    # ═══ DETAY FOTOĞRAFI: Manken Üzerinden Kırpma ═══
                    if photo_type == 'detail':
                        target_type = 'front'
                        if gen.source_photo_id and gen.source_photo_id.photo_type == 'detail':
                            if gen.source_photo_id.detail_placement == 'back':
                                target_type = 'back'

                        target_gen = session.generation_ids.filtered(
                            lambda g: g.photo_type == target_type and g.state == 'done' and g.generated_image
                        )
                        if not target_gen and target_type == 'back':
                            target_gen = session.generation_ids.filtered(
                                lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image
                            )

                        if target_gen:
                            detail_b64 = session._crop_image_detail(
                                target_gen[0].generated_image,
                                category=preset.garment_type or 'tops'
                            )
                            _logger.info('Detay kırpıldı (gen=%s) %s try-on sonucundan', gen.id, target_type)
                        else:
                            _logger.warning('Detay kırpma fallback: try-on sonucu bulunamadı (gen=%s)', gen.id)
                            if auto_bg and processed_b64:
                                try:
                                    bg_removed_b64 = provider.remove_background(processed_b64)
                                    bg_removed_data = base64.b64decode(bg_removed_b64)
                                    rgb_data = convert_birefnet_output_to_rgb(bg_removed_data)
                                    detail_b64 = base64.b64encode(rgb_data)
                                except Exception as e:
                                    _logger.warning('Detay BG remove başarısız: %s', e)
                                    detail_b64 = processed_b64
                            else:
                                detail_b64 = processed_b64

                        elapsed = time.time() - start_time
                        gen.write({
                            'generated_image': detail_b64,
                            'state': 'done',
                            'fal_endpoint': 'detail-crop' if target_gen else ('%s/bg-remove-detail' % provider_type),
                            'generation_time_seconds': elapsed,
                            'cost': 0.0 if target_gen else 0.01,
                        })

                        # KALİTE KONTROL
                        try:
                            from ..services.quality_checker import compute_quality_score
                            qc = compute_quality_score(source_image, detail_b64)
                            gen.write({
                                'quality_score': qc['score'],
                                'quality_details': qc['details'],
                            })
                        except Exception as qe:
                            _logger.debug('Kalite kontrol hatası: %s', qe)

                        cr.commit()
                        continue

                    # ═══ APILER İÇİN URL VE FORMAT AYARLARI ═══
                    model_image_field = 'model_image_front'
                    if photo_type == 'back':
                        model_image_field = 'model_image_back'
                    elif photo_type == 'side':
                        model_image_field = 'model_image_side'

                    model_image_data = getattr(preset, model_image_field)
                    if not model_image_data:
                        model_image_data = preset.model_image_front

                    if not model_image_data:
                        raise UserError(_('Preset manken resmi eksik.'))

                    # Upload images
                    model_url = provider.upload_image(model_image_data)
                    garment_url = provider.upload_image(processed_b64)

                    tryon_model = 'tryon-v1.6' if provider_type == 'fal' else 'tryon-v1.6'
                    tryon_resolution = '1K'
                    if provider_type == 'fashn':
                        tryon_model = getattr(preset, f'fashn_model_{photo_type}', False) or preset.fashn_model_front or 'tryon-v1.6'
                        tryon_resolution = '2K' if 'max' in tryon_model else '1K'

                    from ..services.garment_analyzer import map_to_fashn_category
                    category_to_send = map_to_fashn_category(cached_analysis)

                    # VIEW-SPESİFİK PROMPT OLUŞTURMA
                    prompt_text = ""
                    try:
                        all_locks = env['ai.studio.prompt.template'].search([
                            ('scope', '=', 'global'),
                            ('active', '=', True),
                        ])
                        prompt_locks = [l.prompt_text for l in all_locks]

                        analysis_data = cached_analysis or {}
                        preset_data = {
                            'gender': preset.gender or 'female',
                            'body_type': preset.body_type or 'standard',
                            'target_audience': preset.target_audience or '',
                        }

                        from ..services.garment_analyzer import build_generation_prompt
                        built_prompt = build_generation_prompt(
                            analysis_data, preset_data, prompt_locks,
                            session.extra_prompt or '',
                            photo_type=photo_type,
                            outfit_consistency=outfit_consistency,
                        )
                        prompt_text = built_prompt.get('positive', '')
                    except Exception as pe:
                        _logger.warning('Prompt oluşturma başarısız: %s', pe)

                    # TRY-ON API ÇAĞRISI
                    tryon_result = provider.virtual_tryon(
                        model_image_url=model_url,
                        garment_image_url=garment_url,
                        category=category_to_send,
                        mode=session.quality_mode or 'quality',
                        model_name=tryon_model,
                        num_samples=1,
                        garment_photo_type='auto',
                        output_format='jpeg',
                        prompt=prompt_text,
                        resolution=tryon_resolution,
                        photo_type=photo_type,
                        seed=front_seed,
                    )

                    elapsed = time.time() - start_time

                    # SONUCU İNDİR
                    import requests as req_lib
                    output_url = tryon_result.get('image_url', '')
                    if not output_url:
                        image_urls = tryon_result.get('image_urls', [])
                        output_url = image_urls[0] if image_urls else ''

                    if output_url:
                        if output_url.startswith('data:'):
                            raw = output_url.split(';base64,', 1)[1]
                            img_data = base64.b64decode(raw)
                        else:
                            img_data = req_lib.get(output_url, timeout=60).content

                        gen_b64 = base64.b64encode(img_data)
                        gen_seed = tryon_result.get('seed') or False
                        
                        gen.write({
                            'generated_image': gen_b64,
                            'state': 'done',
                            'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                            'generation_time_seconds': elapsed,
                            'cost': tryon_result.get('cost', 0.05),
                            'seed': gen_seed,
                        })

                        # ═══ FRONT SONRASI: REFERANS CACHE + KOMBİN GİYDİRME + OUTFIT ANALİZİ ═══
                        if photo_type == 'front':
                            if gen_seed:
                                front_seed = gen_seed

                            rec_bottoms = (cached_analysis or {}).get('recommendedBottoms', 'dark blue skinny jeans')
                            rec_shoes = (cached_analysis or {}).get('recommendedShoes', 'white sneakers')

                            try:
                                _logger.info('Front post-processing (ürüne en uygun kombin giydirme) başlatılıyor (gen=%s)', gen.id)
                                current_url = provider.upload_image(gen_b64)
                                
                                edit_prompt = (
                                    f"RAW photo, photorealistic, professional fashion photography, studio lighting, white background. "
                                    f"A model wearing a top garment. Change ONLY the bottoms and shoes of the model "
                                    f"to wear: {rec_bottoms} and {rec_shoes}. "
                                    f"KEEP the upper garment and pose and face exactly as they are. "
                                    f"Only the lower body style changes to match the styling advice."
                                )
                                
                                import os
                                os.environ['FAL_KEY'] = fal_api_key
                                
                                try:
                                    import fal_client
                                except ImportError:
                                    fal_client = None
                                    
                                if fal_client:
                                    mask_b64 = session._generate_inpainting_mask(gen_b64, garment_type=preset.garment_type or 'tops')
                                    mask_url = provider.upload_image(mask_b64) if mask_b64 else None

                                    arguments_to_send = {
                                        'prompt': edit_prompt,
                                        'image_url': current_url,
                                        'strength': 0.82,
                                        'num_images': 1,
                                        'aspect_ratio': '3:4',
                                        'enable_safety_checker': True,
                                    }
                                    if mask_url:
                                        arguments_to_send['mask_url'] = mask_url
                                    if front_seed:
                                        arguments_to_send['seed'] = int(front_seed)

                                    # Rate Limit / Concurrency Limit Retry Mekanizması
                                    import time
                                    max_retries = 3
                                    backoff_factor = 4
                                    edit_result = None
                                    for attempt in range(max_retries):
                                        try:
                                            edit_result = fal_client.subscribe(
                                                'fal-ai/flux/schnell/image-to-image',
                                                arguments=arguments_to_send,
                                                client_timeout=300,
                                            )
                                            break
                                        except Exception as e:
                                            error_str = str(e).lower()
                                            is_rate_limit = (
                                                'rate' in error_str or
                                                'limit' in error_str or
                                                '429' in error_str or
                                                'concurrent' in error_str
                                            )
                                            if is_rate_limit and attempt < max_retries - 1:
                                                sleep_time = backoff_factor * (2 ** attempt)
                                                _logger.warning(
                                                    "Front post-process Rate Limit asildi. %d saniye beklenip tekrar denenecek (Deneme %d/%d). Hata: %s",
                                                    sleep_time, attempt + 1, max_retries, e
                                                )
                                                time.sleep(sleep_time)
                                            else:
                                                raise
                                    edit_images = edit_result.get('images', [])
                                    if edit_images:
                                        edit_url = edit_images[0].get('url', '')
                                        if edit_url:
                                            edit_data = req_lib.get(edit_url, timeout=60).content
                                            edited_b64 = base64.b64encode(edit_data)
                                            gen.write({
                                                'generated_image': edited_b64,
                                            })
                                            gen_b64 = edited_b64
                                            _logger.info('Front post-processing (kombin giydirme) tamamlandı.')
                            except Exception as front_pp_e:
                                _logger.warning('Front post-processing kombin giydirme başarısız: %s', front_pp_e)

                            front_result_b64 = gen_b64

                            if outfit_consistency is None:
                                try:
                                    from ..services.garment_analyzer import analyze_outfit_consistency
                                    outfit_consistency = analyze_outfit_consistency(
                                        gen_b64,
                                        api_key=fal_api_key,
                                        gemini_api_key=gemini_api_key,
                                    )
                                except Exception as oe:
                                    _logger.warning('Outfit tutarlılık analizi başarısız: %s', oe)

                        # ═══ BACK/SIDE POST-PROCESSING: OUTFIT TUTARLILIĞI ═══
                        if photo_type in ('back', 'side') and front_result_b64 and outfit_consistency:
                            consistency_prompt = outfit_consistency.get('fullOutfitPrompt', '')
                            if consistency_prompt:
                                try:
                                    _logger.info(
                                        'Post-processing outfit tutarlılığı (flux-img2img+ipadapter) başlatılıyor (gen=%s, tip=%s)',
                                        gen.id, photo_type,
                                    )
                                    front_ref_url = provider.upload_image(front_result_b64)
                                    current_url = provider.upload_image(gen_b64)

                                    bottoms_desc = outfit_consistency.get('bottomsColor', '') + ' ' + outfit_consistency.get('bottomsType', '')
                                    shoes_desc = outfit_consistency.get('shoesColor', '') + ' ' + outfit_consistency.get('shoesType', '')

                                    edit_prompt = (
                                        f"RAW photo, photorealistic, professional fashion photography, studio lighting, white background. "
                                        f"A model wearing a top garment, matching the outfit from the reference image. "
                                        f"The model must wear the exact same {bottoms_desc.strip()} and the exact same {shoes_desc.strip()} "
                                        f"as shown in the reference image. Perfect color tone matching, high detail, 8k resolution."
                                    )

                                    import os
                                    os.environ['FAL_KEY'] = fal_api_key

                                    try:
                                        import fal_client
                                    except ImportError:
                                        fal_client = None

                                    if fal_client:
                                        mask_b64 = session._generate_inpainting_mask(gen_b64, garment_type=preset.garment_type or 'tops')
                                        mask_url = provider.upload_image(mask_b64) if mask_b64 else None

                                        arguments_to_send = {
                                            'prompt': edit_prompt,
                                            'image_url': current_url,
                                            'strength': 0.82,
                                            'ip_adapters': [
                                                {
                                                    'image_url': front_ref_url,
                                                    'conditioning_scale': 0.85,
                                                }
                                            ],
                                            'num_images': 1,
                                            'aspect_ratio': '3:4',
                                            'enable_safety_checker': True,
                                        }
                                        if mask_url:
                                            arguments_to_send['mask_url'] = mask_url
                                        if front_seed:
                                            arguments_to_send['seed'] = int(front_seed)

                                        # Rate Limit / Concurrency Limit Retry Mekanizması
                                        import time
                                        max_retries = 3
                                        backoff_factor = 4
                                        edit_result = None
                                        for attempt in range(max_retries):
                                            try:
                                                edit_result = fal_client.subscribe(
                                                    'fal-ai/flux/schnell/image-to-image',
                                                    arguments=arguments_to_send,
                                                    client_timeout=300,
                                                )
                                                break
                                            except Exception as e:
                                                error_str = str(e).lower()
                                                is_rate_limit = (
                                                    'rate' in error_str or
                                                    'limit' in error_str or
                                                    '429' in error_str or
                                                    'concurrent' in error_str
                                                )
                                                if is_rate_limit and attempt < max_retries - 1:
                                                    sleep_time = backoff_factor * (2 ** attempt)
                                                    _logger.warning(
                                                        "Back/Side post-process Rate Limit asildi. %d saniye beklenip tekrar denenecek (Deneme %d/%d). Hata: %s",
                                                        sleep_time, attempt + 1, max_retries, e
                                                    )
                                                    time.sleep(sleep_time)
                                                else:
                                                    raise
                                        edit_images = edit_result.get('images', [])
                                        if edit_images:
                                            edit_url = edit_images[0].get('url', '')
                                            if edit_url:
                                                edit_data = req_lib.get(edit_url, timeout=60).content
                                                edited_b64 = base64.b64encode(edit_data)
                                                gen.write({
                                                    'generated_image': edited_b64,
                                                    'fal_endpoint': '%s/%s+consistency' % (provider_type, tryon_model),
                                                    'cost': tryon_result.get('cost', 0.05) + 0.03,
                                                })
                                                gen_b64 = edited_b64
                                                _logger.info('Post-processing outfit tutarlılığı tamamlandı (gen=%s, tip=%s)', gen.id, photo_type)
                                except Exception as pp_e:
                                    _logger.warning('Post-processing outfit tutarlılığı başarısız (gen=%s): %s', gen.id, pp_e)

                        # KALİTE KONTROL
                        try:
                            from ..services.quality_checker import compute_quality_score
                            qc = compute_quality_score(source_image, gen_b64)
                            gen.write({
                                'quality_score': qc['score'],
                                'quality_details': qc['details'],
                            })
                        except Exception as qe:
                            _logger.debug('Kalite kontrol hatası: %s', qe)

                    else:
                        gen.write({
                            'state': 'failed',
                            'error_message': 'API sonuç döndürmedi.',
                        })
                        if photo_type == 'front':
                            front_failed = True

                    cr.commit()

                except Exception as e:
                    from ..services.fal_error_handler import parse_fal_error
                    parsed = parse_fal_error(e)
                    _logger.error('AI üretim hatası (gen=%s): %s', gen.id, e)
                    gen.write({
                        'state': 'failed',
                        'error_message': parsed['message'][:500],
                    })
                    if photo_type == 'front':
                        front_failed = True
                    cr.commit()

            # ═══ TÜM ÜRETİMLER TAMAMLANDI ═══
            session.write({'state': 'review'})
            session.message_post(
                body=_('AI üretimi tamamlandı. %d görsel onay bekliyor.') % len(session.generation_ids),
            )
            cr.commit()

    def _process_single_generation(self, generation):
        """Tek bir generation'ı yeniden işle (retry için)."""
        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        if provider_type == 'fashn':
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fashn_api_key'
            )
        else:
            api_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key'
            )
        if not api_key:
            raise UserError(_('AI API anahtarı ayarlanmamış.'))

        thread = threading.Thread(
            target=self._retry_generation_thread,
            args=(self.id, generation.id, api_key),
        )
        thread.daemon = True
        thread.start()

    def _retry_generation_thread(self, session_id, gen_id, api_key):
        """Tek generation retry thread'i (wrapper)."""
        try:
            self._retry_generation_thread_body(session_id, gen_id, api_key)
        except Exception as thread_err:
            _logger.exception("AI Retry Thread: Beklenmeyen kritik hata olustu: %s", thread_err)
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    gen = env['ai.studio.generation'].browse(gen_id)
                    gen.write({
                        'state': 'failed',
                        'error_message': _('Kritik Sistem Hatası: %s') % str(thread_err),
                    })
                    cr.commit()
            except Exception:
                pass

    def _retry_generation_thread_body(self, session_id, gen_id, api_key):
        """Tek generation retry thread'i (body)."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks
        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            fal_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.fal_api_key', ''
            )
            gemini_api_key = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            tryon_model = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.tryon_model', 'tryon-max'
            )
            tryon_resolution = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.tryon_resolution', '2K'
            )

            session = env['ai.studio.session'].browse(session_id)
            gen = env['ai.studio.generation'].browse(gen_id)
            photo_type = gen.photo_type or 'front'

            try:
                provider = self._create_provider(api_key, provider_type)

                gen.write({'state': 'processing'})
                cr.commit()

                source_image = gen.original_image
                preset = session.model_preset_id

                # ═══ DETAY İŞLEMİ — Manken Üzerinden Kırpma ═══
                if photo_type == 'detail':
                    # Tamamlanmış front try-on sonucunu bul
                    target_type = 'front'
                    if gen.source_photo_id and gen.source_photo_id.photo_type == 'detail':
                        if gen.source_photo_id.detail_placement == 'back':
                            target_type = 'back'

                    target_gen = session.generation_ids.filtered(
                        lambda g: g.photo_type == target_type and g.state == 'done' and g.generated_image
                    )
                    if not target_gen and target_type == 'back':
                        target_gen = session.generation_ids.filtered(
                            lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image
                        )

                    if target_gen:
                        detail_b64 = session._crop_image_detail(
                            target_gen[0].generated_image,
                            category=preset.garment_type or 'tops'
                        )
                    else:
                        # Fallback: BG remove
                        from ..services.garment_preprocessor import (
                            preprocess_garment_image,
                            convert_birefnet_output_to_rgb,
                        )
                        preprocessed = preprocess_garment_image(source_image, target_long_edge=864)
                        processed_b64 = preprocessed['image_base64']

                        auto_bg = env['ir.config_parameter'].sudo().get_param(
                            'ugurlar_ai_studio.auto_bg_remove', 'True'
                        ) == 'True'

                        if auto_bg and processed_b64:
                            try:
                                bg_removed_b64 = provider.remove_background(processed_b64)
                                try:
                                    bg_removed_data = base64.b64decode(bg_removed_b64)
                                    rgb_data = convert_birefnet_output_to_rgb(bg_removed_data)
                                    detail_b64 = base64.b64encode(rgb_data)
                                except Exception:
                                    detail_b64 = bg_removed_b64
                            except Exception:
                                detail_b64 = processed_b64
                        else:
                            detail_b64 = processed_b64

                    gen.write({
                        'generated_image': detail_b64,
                        'state': 'done',
                        'fal_endpoint': 'detail-crop' if target_gen else ('%s/bg-remove-detail' % provider_type),
                        'error_message': False,
                    })
                    cr.commit()
                    return

                # ═══ TRY-ON RETRY İŞLEMİ ═══
                auto_bg = env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.auto_bg_remove', 'True'
                ) == 'True'

                from ..services.garment_preprocessor import (
                    preprocess_garment_image,
                    convert_birefnet_output_to_rgb,
                )
                preprocessed = preprocess_garment_image(source_image, target_long_edge=864)
                processed_b64 = preprocessed['image_base64']

                if auto_bg and processed_b64:
                    try:
                        bg_removed_b64 = provider.remove_background(processed_b64)
                        try:
                            bg_removed_data = base64.b64decode(bg_removed_b64)
                            rgb_data = convert_birefnet_output_to_rgb(bg_removed_data)
                            rgb_b64 = base64.b64encode(rgb_data)
                        except Exception:
                            rgb_b64 = bg_removed_b64
                        cleaned_b64 = session._remove_hanger_hook(rgb_b64)
                        garment_url = provider.upload_image(cleaned_b64)
                    except Exception as e:
                        _logger.warning('Retry BG remove başarısız: %s', e)
                        garment_url = provider.upload_image(processed_b64)
                else:
                    garment_url = provider.upload_image(processed_b64)

                model_image_field = 'model_image_front'
                if photo_type == 'back':
                    model_image_field = 'model_image_back'
                elif photo_type == 'side':
                    model_image_field = 'model_image_side'
                model_image = getattr(preset, model_image_field, False) or preset.model_image_front
                if not model_image:
                    raise Exception('Preset manken resmi eksik.')

                model_url = provider.upload_image(model_image)

                cat = session.category
                if provider_type == 'fashn':
                    if cat == 'auto':
                        category_to_send = 'auto'
                    else:
                        category_to_send = {
                            'tops': 'tops',
                            'bottoms': 'bottoms',
                            'one_piece': 'one-pieces',
                        }.get(cat, 'tops')
                else:
                    if cat == 'auto':
                        cat_fallback = preset.garment_type or 'tops'
                        category_to_send = {
                            'tops': 'tops',
                            'bottoms': 'bottoms',
                            'one_piece': 'one-piece',
                        }.get(cat_fallback, 'tops')
                    else:
                        category_to_send = {
                            'tops': 'tops',
                            'bottoms': 'bottoms',
                            'one_piece': 'one-piece',
                        }.get(cat, 'tops')

                # ═══ CROSS-VIEW TUTARLILIK VERİSİ VE BAZ CACHE (Retry İçin) ═══
                outfit_consistency = None
                front_result_b64 = None
                front_seed = None

                if photo_type in ('back', 'side', 'detail'):
                    # Session içindeki tamamlanmış front kaydını bul
                    front_gen = session.generation_ids.filtered(lambda g: g.photo_type == 'front' and g.state == 'done')
                    if front_gen and front_gen[0].generated_image:
                        front_result_b64 = front_gen[0].generated_image
                        front_seed = front_gen[0].seed or False
                        try:
                            from ..services.garment_analyzer import analyze_outfit_consistency
                            outfit_consistency = analyze_outfit_consistency(
                                front_result_b64,
                                api_key=fal_api_key,
                                gemini_api_key=gemini_api_key,
                            )
                        except Exception as oe:
                            _logger.warning('Retry outfit tutarlılık analizi başarısız: %s', oe)

                # ═══ VIEW-SPESİFİK PROMPT ═══
                prompt_text = ""
                try:
                    all_locks = env['ai.studio.prompt.template'].search([
                        ('scope', '=', 'global'),
                        ('active', '=', True),
                    ])
                    prompt_locks = [l.prompt_text for l in all_locks]

                    from ..services.garment_analyzer import analyze_garment, build_generation_prompt
                    analysis = analyze_garment(fal_api_key, garment_url, gemini_api_key=gemini_api_key)

                    preset_data = {
                        'gender': preset.gender or 'female',
                        'body_type': preset.body_type or 'standard',
                        'target_audience': preset.target_audience or '',
                    }

                    built_prompt = build_generation_prompt(
                        analysis, preset_data, prompt_locks,
                        session.extra_prompt or '',
                        photo_type=photo_type,
                        outfit_consistency=outfit_consistency,
                    )
                    prompt_text = built_prompt.get('positive', '')
                except Exception as pe:
                    _logger.warning('Failed to build retry prompt: %s', pe)

                tryon_result = provider.virtual_tryon(
                    model_image_url=model_url,
                    garment_image_url=garment_url,
                    category=category_to_send,
                    mode=session.quality_mode or 'quality',
                    model_name=tryon_model,
                    num_samples=1,
                    garment_photo_type='auto',
                    output_format='jpeg',
                    prompt=prompt_text,
                    resolution=tryon_resolution,
                    photo_type=photo_type,
                    seed=front_seed,  # ← ÖN YÜZ SEED'İNİ ZORLA
                )

                output_url = tryon_result.get('image_url', '')
                if not output_url:
                    image_urls = tryon_result.get('image_urls', [])
                    output_url = image_urls[0] if image_urls else ''

                if output_url:
                    if output_url.startswith('data:'):
                        raw_b64 = output_url.split(';base64,', 1)[1]
                        img_data = base64.b64decode(raw_b64)
                    else:
                        import requests
                        img_data = requests.get(output_url, timeout=60).content

                    gen_b64 = base64.b64encode(img_data)
                    gen_seed = tryon_result.get('seed') or False
                    
                    gen.write({
                        'generated_image': gen_b64,
                        'state': 'done',
                        'error_message': False,
                        'seed': gen_seed,
                    })

                    # ═══ RETRY BACK/SIDE POST-PROCESSING: OUTFIT TUTARLILIĞI ═══
                    if photo_type in ('back', 'side') and front_result_b64 and outfit_consistency:
                        consistency_prompt = outfit_consistency.get('fullOutfitPrompt', '')
                        if consistency_prompt:
                            try:
                                _logger.info(
                                    'Retry post-processing outfit tutarlılığı (flux-img2img+ipadapter) başlatılıyor (gen=%s, tip=%s)',
                                    gen.id, photo_type,
                                )
                                front_ref_url = provider.upload_image(front_result_b64)
                                current_url = provider.upload_image(gen_b64)

                                bottoms_desc = outfit_consistency.get('bottomsColor', '') + ' ' + outfit_consistency.get('bottomsType', '')
                                shoes_desc = outfit_consistency.get('shoesColor', '') + ' ' + outfit_consistency.get('shoesType', '')

                                edit_prompt = (
                                    f"RAW photo, photorealistic, professional fashion photography, studio lighting, white background. "
                                    f"A model wearing a top garment, matching the outfit from the reference image. "
                                    f"The model must wear the exact same {bottoms_desc.strip()} and the exact same {shoes_desc.strip()} "
                                    f"as shown in the reference image. Perfect color tone matching, high detail, 8k resolution."
                                )

                                import os
                                os.environ['FAL_KEY'] = fal_api_key

                                try:
                                    import fal_client
                                except ImportError:
                                    fal_client = None

                                if fal_client:
                                    mask_b64 = session._generate_inpainting_mask(gen_b64, garment_type=preset.garment_type or 'tops')
                                    mask_url = provider.upload_image(mask_b64) if mask_b64 else None

                                    arguments_to_send = {
                                        'prompt': edit_prompt,
                                        'image_url': current_url,
                                        'strength': 0.82,
                                        'ip_adapters': [
                                            {
                                                'image_url': front_ref_url,
                                                'conditioning_scale': 0.85,
                                            }
                                        ],
                                        'num_images': 1,
                                        'aspect_ratio': '3:4',
                                        'enable_safety_checker': True,
                                    }
                                    if mask_url:
                                        arguments_to_send['mask_url'] = mask_url
                                    if front_seed:
                                        arguments_to_send['seed'] = int(front_seed)

                                    # Rate Limit / Concurrency Limit Retry Mekanizması
                                    import time
                                    max_retries = 3
                                    backoff_factor = 4
                                    edit_result = None
                                    for attempt in range(max_retries):
                                        try:
                                            edit_result = fal_client.subscribe(
                                                'fal-ai/flux/schnell/image-to-image',
                                                arguments=arguments_to_send,
                                                client_timeout=300,
                                            )
                                            break
                                        except Exception as e:
                                            error_str = str(e).lower()
                                            is_rate_limit = (
                                                'rate' in error_str or
                                                'limit' in error_str or
                                                '429' in error_str or
                                                'concurrent' in error_str
                                            )
                                            if is_rate_limit and attempt < max_retries - 1:
                                                sleep_time = backoff_factor * (2 ** attempt)
                                                _logger.warning(
                                                    "Retry post-process Rate Limit asildi. %d saniye beklenip tekrar denenecek (Deneme %d/%d). Hata: %s",
                                                    sleep_time, attempt + 1, max_retries, e
                                                )
                                                time.sleep(sleep_time)
                                            else:
                                                raise
                                    edit_images = edit_result.get('images', [])
                                    if edit_images:
                                        edit_url = edit_images[0].get('url', '')
                                        if edit_url:
                                            import requests as req_lib
                                            edit_data = req_lib.get(edit_url, timeout=60).content
                                            edited_b64 = base64.b64encode(edit_data)
                                            gen.write({
                                                'generated_image': edited_b64,
                                            })
                                            gen_b64 = edited_b64
                                            _logger.info(
                                                'Retry post-processing outfit tutarlılığı tamamlandı (gen=%s, tip=%s)',
                                                gen.id, photo_type,
                                            )
                            except Exception as pp_e:
                                _logger.warning('Retry post-processing outfit tutarlılığı başarısız: %s', pp_e)

                    # Kalite kontrol
                    try:
                        from ..services.quality_checker import compute_quality_score
                        qc = compute_quality_score(source_image, gen_b64)
                        gen.write({
                            'quality_score': qc['score'],
                            'quality_details': qc['details'],
                        })
                    except Exception:
                        pass

                cr.commit()

            except Exception as e:
                from ..services.fal_error_handler import parse_fal_error, format_fal_error_for_log
                parsed = parse_fal_error(e)
                _logger.error('Retry hatası: %s', format_fal_error_for_log(e, f'gen={gen_id}'))
                gen.write({
                    'state': 'failed',
                    'error_message': parsed['message'][:500],
                })
                cr.commit()

    def action_mark_done(self):
        """Onaylanmış görselleri ürüne kaydet ve oturumu tamamla."""
        self.ensure_one()
        approved = self.generation_ids.filtered(
            lambda g: g.is_approved and g.state == 'done'
        )
        if not approved:
            raise UserError(_('En az bir görsel onaylanmalı.'))

        try:
            self._save_to_product(approved)
        except Exception as e:
            _logger.error('Ürüne kaydetme hatası: %s', e)
            raise UserError(_(
                'Görseller ürüne kaydedilemedi: %s\n'
                'Lütfen tekrar deneyin veya yöneticinize başvurun.'
            ) % str(e)[:200])

        self.reviewer_id = self.env.user
        self.state = 'done'
        self.message_post(
            body=_('%d onaylı görsel ürüne kaydedildi.') % len(approved),
        )

    def _save_to_product(self, approved_generations):
        """Onaylanmış görselleri ürün kartına aktar.

        - is_primary olan → ürünün ana resmi (image_1920)
        - Diğerleri → product.image alternatif resimler

        Savepoint kullanarak hata durumunda transaction'ın
        abort olmasını engeller.
        """
        product = self.product_id
        if not product:
            raise UserError(_('Oturuma bağlı ürün bulunamadı.'))

        products = product
        if self.apply_to_siblings and self.sibling_product_ids:
            products |= self.sibling_product_ids

        # Ana resmi bul — tek kayıt garanti
        primary = approved_generations.filtered('is_primary')[:1]
        if not primary:
            # Primary seçilmemişse ilk onaylananı primary yap
            primary = approved_generations[0]
            primary.is_primary = True

        others = approved_generations - primary

        for prod in products:
            # ═══ ANA RESMİ ATA ═══
            try:
                # Önce product.product variant resmi, sonra template fallback
                if hasattr(prod, 'image_variant_1920'):
                    prod.image_variant_1920 = primary.generated_image
                else:
                    prod.image_1920 = primary.generated_image
            except Exception as e:
                _logger.warning(
                    'Ana resim ataması başarısız (prod=%s), template üzerinden deneniyor: %s',
                    prod.id, e,
                )
                try:
                    prod.product_tmpl_id.image_1920 = primary.generated_image
                except Exception as e2:
                    _logger.error('Template resmi de atanamadı: %s', e2)
                    raise UserError(_(
                        'Ürün ana resmi kaydedilemedi. Hata: %s'
                    ) % str(e2)[:200])

            # ═══ MEVCUT AI GÖRSELLERİNİ TEMİZLE (duplikasyonu önle) ═══
            try:
                existing_ai_images = self.env['product.image'].search([
                    ('product_tmpl_id', '=', prod.product_tmpl_id.id),
                    ('name', 'like', '% - AI (%'),
                ])
                if existing_ai_images:
                    existing_ai_images.unlink()
                    _logger.info(
                        'Mevcut %d AI görseli temizlendi (prod=%s)',
                        len(existing_ai_images), prod.id,
                    )
            except Exception as e:
                _logger.warning('Eski AI görselleri temizlenemedi: %s', e)

            # ═══ ALTERNATİF RESİMLERİ OLUŞTUR ═══
            sequence = 10
            for gen in others:
                try:
                    type_label = dict(
                        gen._fields['photo_type'].selection
                    ).get(gen.photo_type, 'Görsel')
                    self.env['product.image'].create({
                        'product_tmpl_id': prod.product_tmpl_id.id,
                        'name': f'{type_label} - AI ({gen.revision_number})',
                        'image_1920': gen.generated_image,
                        'sequence': sequence,
                    })
                    sequence += 10
                except Exception as e:
                    _logger.warning(
                        'Alternatif resim kaydedilemedi (gen=%s, prod=%s): %s',
                        gen.id, prod.id, e,
                    )
                    # Devam et — diğer görselleri kaydetmeye çalış

    def action_cancel(self):
        """Oturumu iptal et."""
        for session in self:
            session.state = 'cancelled'
            session.message_post(body=_('Oturum iptal edildi.'))

    def action_reset_draft(self):
        """Taslak durumuna geri dön."""
        for session in self:
            session.state = 'draft'

    @api.model
    def _cron_check_stuck_generations(self):
        """Processing durumunda 10 dakikadan uzun kalmış üretimleri kontrol et."""
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(minutes=10)

        stuck_sessions = self.search([
            ('state', 'in', ['preprocessing', 'processing']),
            ('write_date', '<', cutoff),
        ])
        for session in stuck_sessions:
            stuck_gens = session.generation_ids.filtered(
                lambda g: g.state == 'processing' and g.write_date < cutoff
            )
            for gen in stuck_gens:
                gen.write({
                    'state': 'failed',
                    'error_message': 'Zaman aşımı: 10 dakika içinde sonuç alınamadı.',
                })

            # Tüm generation'lar tamamlandıysa review'a geç
            pending = session.generation_ids.filtered(
                lambda g: g.state in ('pending', 'processing')
            )
            if not pending:
                session.write({'state': 'review'})
                session.message_post(
                    body=_('Bazı üretimler zaman aşımına uğradı. Sonuçları kontrol edin.'),
                )

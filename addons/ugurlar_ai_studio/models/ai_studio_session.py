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

    def _process_ai_thread(self, session_id, api_key):
        """Thread içinde tüm generation'ları işle."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks

        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
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

            # Try-on (giydirme) ve Detay üretimlerini ayır
            tryon_gens = generations.filtered(lambda g: g.photo_type in ('front', 'back', 'side'))
            detail_gens = generations.filtered(lambda g: g.photo_type == 'detail')

            # 1. Önce try-on üretimlerini gerçekleştir
            for gen in tryon_gens:
                try:
                    gen.write({'state': 'processing'})
                    cr.commit()

                    start_time = time.time()
                    source_image = gen.original_image

                    # ═══ GÖRSEL ÖN İŞLEME PIPELINE ═══
                    from ..services.garment_preprocessor import (
                        preprocess_garment_image,
                        convert_birefnet_output_to_rgb,
                    )

                    # Adım 1: Ürün görselini ön işle (beyaz denge, pozlama, resize, vb.)
                    preprocessed = preprocess_garment_image(
                        source_image,
                        target_long_edge=864,
                    )
                    processed_b64 = preprocessed['image_base64']
                    _logger.info(
                        'Ön işleme tamamlandı (gen=%s): %sx%s → %sx%s, adımlar=%s',
                        gen.id,
                        preprocessed['original_size'][0], preprocessed['original_size'][1],
                        preprocessed['final_size'][0], preprocessed['final_size'][1],
                        ', '.join(preprocessed['steps_applied']) or 'yok',
                    )

                    # Adım 2: Arka plan kaldırma + askı temizleme
                    if auto_bg and processed_b64:
                        try:
                            bg_removed_b64 = provider.remove_background(processed_b64)

                            # RGBA → RGB dönüşümü (BiRefNet/FASHN bg-remove)
                            try:
                                bg_removed_data = base64.b64decode(bg_removed_b64)
                                rgb_data = convert_birefnet_output_to_rgb(bg_removed_data)
                                rgb_b64 = base64.b64encode(rgb_data)
                            except Exception:
                                rgb_b64 = bg_removed_b64

                            # Askı temizleme işlemi
                            cleaned_b64 = session._remove_hanger_hook(rgb_b64)
                            garment_url = provider.upload_image(cleaned_b64)
                        except Exception as e:
                            _logger.warning('BG remove başarısız, ön işlenmiş görsel kullanılıyor: %s', e)
                            garment_url = provider.upload_image(processed_b64)
                    else:
                        garment_url = provider.upload_image(processed_b64)

                    # Manken resmini yükle
                    model_image_field = 'model_image_front'
                    if gen.photo_type == 'back':
                        model_image_field = 'model_image_back'
                    elif gen.photo_type == 'side':
                        model_image_field = 'model_image_side'
                    
                    model_image_data = getattr(preset, model_image_field)
                    if not model_image_data:
                        model_image_data = preset.model_image_front

                    if not model_image_data:
                        raise UserError(_('Preset manken resmi eksik.'))

                    model_url = provider.upload_image(model_image_data)

                    # Kategori belirleme — otomatik tespit veya manuel
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
                            try:
                                from ..services.garment_analyzer import analyze_garment, map_to_fashn_category
                                analysis = analyze_garment(api_key, garment_url)
                                analyzed_cat = map_to_fashn_category(analysis)
                                category_to_send = {
                                    'tops': 'tops',
                                    'bottoms': 'bottoms',
                                    'full-body': 'one-piece',
                                }.get(analyzed_cat, 'tops')
                                _logger.info(
                                    'Otomatik kategori tespiti (fal.ai): %s → %s (gen=%s)',
                                    analysis.get('garmentType', '?'), category_to_send, gen.id,
                                )
                            except Exception as e:
                                _logger.warning('Otomatik tespit başarısız, preset kullanılıyor: %s', e)
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

                    # Try-on model ve uretim sayisi ayarlari
                    tryon_model = env['ir.config_parameter'].sudo().get_param(
                        'ugurlar_ai_studio.tryon_model', 'tryon-v1.6'
                    )
                    num_samples = int(env['ir.config_parameter'].sudo().get_param(
                        'ugurlar_ai_studio.num_samples', '2'
                    ))

                    tryon_result = provider.virtual_tryon(
                        model_image_url=model_url,
                        garment_image_url=garment_url,
                        category=category_to_send,
                        mode=session.quality_mode or 'balanced',
                        model_name=tryon_model,
                        num_samples=num_samples,
                        garment_photo_type='auto',
                        output_format='jpeg',
                    )

                    elapsed = time.time() - start_time

                    # Sonuclari indir ve en iyisini sec
                    import requests
                    image_urls = tryon_result.get('image_urls', [])
                    if not image_urls and tryon_result.get('image_url'):
                        image_urls = [tryon_result['image_url']]

                    if image_urls:
                        best_data = None
                        best_size = 0

                        for img_url in image_urls:
                            if not img_url:
                                continue
                            # data URI ise decode et, URL ise indir
                            if img_url.startswith('data:'):
                                raw = img_url.split(';base64,', 1)[1]
                                img_data = base64.b64decode(raw)
                            else:
                                img_data = requests.get(img_url, timeout=60).content
                            if len(img_data) > best_size:
                                best_size = len(img_data)
                                best_data = img_data

                        if best_data:
                            _logger.info(
                                '%d sample uretildi, en iyi secildi: %.1fKB (gen=%s)',
                                len(image_urls), best_size / 1024, gen.id,
                            )
                            gen_b64 = base64.b64encode(best_data)
                            gen.write({
                                'generated_image': gen_b64,
                                'state': 'done',
                                'fal_endpoint': '%s/%s' % (provider_type, tryon_model),
                                'generation_time_seconds': elapsed,
                                'cost': tryon_result.get('cost', 0.05),
                            })

                            # Kalite kontrol — renk doğruluğu loglama
                            try:
                                from ..services.quality_checker import compute_quality_score
                                qc = compute_quality_score(source_image, gen_b64)
                                _logger.info(
                                    'Kalite kontrolu (gen=%s): skor=%.1f, %s',
                                    gen.id, qc['score'], qc['details'],
                                )
                            except Exception as qe:
                                _logger.debug('Kalite kontrol atlandi: %s', qe)
                        else:
                            gen.write({
                                'state': 'failed',
                                'error_message': 'API sonuç döndürmedi.',
                            })
                    else:
                        gen.write({
                            'state': 'failed',
                            'error_message': 'API sonuç döndürmedi.',
                        })

                    cr.commit()

                except Exception as e:
                    from ..services.fal_error_handler import parse_fal_error, format_fal_error_for_log
                    parsed = parse_fal_error(e)
                    _logger.error('AI üretim hatası: %s', format_fal_error_for_log(e, f'gen={gen.id}'))
                    gen.write({
                        'state': 'failed',
                        'error_message': parsed['message'][:500],
                    })
                    cr.commit()

            # 2. Sonra detay üretimlerini (kırpma işlemi ile) gerçekleştir
            for gen in detail_gens:
                try:
                    gen.write({'state': 'processing'})
                    cr.commit()

                    start_time = time.time()

                    # Hangi görselden kırpılacağını belirle (Ön veya Arka)
                    target_type = 'front'
                    if gen.source_photo_id and gen.source_photo_id.photo_type == 'detail':
                        if gen.source_photo_id.detail_placement == 'back':
                            target_type = 'back'

                    # İlgili tamamlanmış giydirme görselini bul
                    target_gen = session.generation_ids.filtered(
                        lambda g: g.photo_type == target_type and g.state == 'done' and g.generated_image
                    )

                    # Arka giydirme bulunamadıysa öne geri dön
                    if not target_gen and target_type == 'back':
                        target_gen = session.generation_ids.filtered(
                            lambda g: g.photo_type == 'front' and g.state == 'done' and g.generated_image
                        )

                    if target_gen:
                        # Görseli kırp
                        cropped_image = session._crop_image_detail(
                            target_gen[0].generated_image,
                            category=preset.garment_type or 'tops'
                        )
                        elapsed = time.time() - start_time
                        gen.write({
                            'generated_image': cropped_image,
                            'state': 'done',
                            'fal_endpoint': 'local-crop',
                            'generation_time_seconds': elapsed,
                            'cost': 0.0,  # Lokal kırpma ücretsizdir
                        })
                    else:
                        # Fallback: Eğer başarılı try-on görseli bulunamadıysa ama orijinal detay varsa, arka plan temizleyip kaydet
                        if gen.source_photo_id and gen.source_photo_id.image_original:
                            source_image = gen.source_photo_id.image_original
                            bg_removed_b64 = provider.remove_background(source_image)
                            elapsed = time.time() - start_time
                            gen.write({
                                'generated_image': bg_removed_b64,
                                'state': 'done',
                                'fal_endpoint': '%s/bg-remove' % provider_type,
                                'generation_time_seconds': elapsed,
                                'cost': 0.01,
                            })
                        else:
                            raise Exception("Kırpılacak başarılı giydirilmiş manken görseli bulunamadı.")

                    cr.commit()

                except Exception as e:
                    from ..services.fal_error_handler import parse_fal_error, format_fal_error_for_log
                    parsed = parse_fal_error(e)
                    _logger.error('AI detay üretim hatası: %s', format_fal_error_for_log(e, f'gen={gen.id}'))
                    gen.write({
                        'state': 'failed',
                        'error_message': parsed['message'][:500],
                    })
                    cr.commit()

            # Tüm üretimler tamamlandı
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
        """Tek generation retry thread'i."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks

        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            provider_type = env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.default_provider', 'fashn'
            )
            session = env['ai.studio.session'].browse(session_id)
            gen = env['ai.studio.generation'].browse(gen_id)

            # Aynı işlem mantığını uygula (basitleştirilmiş)
            try:
                provider = self._create_provider(api_key, provider_type)

                gen.write({'state': 'processing'})
                cr.commit()

                source_image = gen.original_image
                preset = session.model_preset_id

                # Detay ise kırpma işlemini yap
                if gen.photo_type == 'detail':
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
                        cropped_image = session._crop_image_detail(
                            target_gen[0].generated_image,
                            category=preset.garment_type or 'tops'
                        )
                        gen.write({
                            'generated_image': cropped_image,
                            'state': 'done',
                            'fal_endpoint': 'local-crop',
                            'error_message': False,
                        })
                    else:
                        # Fallback: başarılı try-on bulunamazsa background remove yap
                        if gen.source_photo_id and gen.source_photo_id.image_original:
                            try:
                                bg_removed_b64 = provider.remove_background(
                                    gen.source_photo_id.image_original
                                )
                                gen.write({
                                    'generated_image': bg_removed_b64,
                                    'state': 'done',
                                    'fal_endpoint': '%s/bg-remove' % provider_type,
                                    'error_message': False,
                                })
                            except Exception as e:
                                raise Exception(f"Kırpılacak görsel bulunamadı ve fallback arka plan kaldırma başarısız oldu: {e}")
                        else:
                            raise Exception("Kırpılacak başarılı giydirilmiş manken görseli bulunamadı.")
                    cr.commit()
                    return

                auto_bg = env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.auto_bg_remove', 'True'
                ) == 'True'

                # Arka plan kaldırma ve askı temizleme (ön işleme pipeline ile)
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
                        _logger.warning('Retry BG remove başarısız, ön işlenmiş kullanılıyor: %s', e)
                        garment_url = provider.upload_image(processed_b64)
                else:
                    garment_url = provider.upload_image(processed_b64)

                preset = session.model_preset_id
                model_image_field = 'model_image_front'
                if gen.photo_type == 'back':
                    model_image_field = 'model_image_back'
                elif gen.photo_type == 'side':
                    model_image_field = 'model_image_side'
                model_image = getattr(preset, model_image_field, False) or preset.model_image_front
                if not model_image:
                    raise Exception('Preset manken resmi eksik.')

                model_url = provider.upload_image(model_image)

                tryon_model = env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.tryon_model', 'tryon-v1.6'
                )

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

                tryon_result = provider.virtual_tryon(
                    model_image_url=model_url,
                    garment_image_url=garment_url,
                    category=category_to_send,
                    mode=session.quality_mode or 'balanced',
                    model_name=tryon_model,
                    garment_photo_type='auto',
                    output_format='jpeg',
                )

                output_url = tryon_result.get('image_url', '')

                if output_url:
                    if output_url.startswith('data:'):
                        raw_b64 = output_url.split(';base64,', 1)[1]
                        img_data = base64.b64decode(raw_b64)
                    else:
                        import requests
                        img_data = requests.get(output_url, timeout=60).content
                    gen.write({
                        'generated_image': base64.b64encode(img_data),
                        'state': 'done',
                        'error_message': False,
                    })
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

        self._save_to_product(approved)
        self.reviewer_id = self.env.user
        self.state = 'done'
        self.message_post(
            body=_('%d onaylı görsel ürüne kaydedildi.') % len(approved),
        )

    def _save_to_product(self, approved_generations):
        """Onaylanmış görselleri ürün kartına aktar.

        - is_primary olan → ürünün ana resmi (image_variant_1920)
        - Diğerleri → product.image alternatif resimler
        """
        product = self.product_id
        products = product
        if self.apply_to_siblings and self.sibling_product_ids:
            products |= self.sibling_product_ids

        # Ana resmi bul
        primary = approved_generations.filtered('is_primary')
        if not primary:
            # Primary seçilmemişse ilk onaylananı primary yap
            primary = approved_generations[0]
            primary.is_primary = True

        others = approved_generations - primary

        for prod in products:
            # Ana resmi ata
            prod.image_variant_1920 = primary.generated_image

            # Alternatif resimleri oluştur
            sequence = 10
            for gen in others:
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

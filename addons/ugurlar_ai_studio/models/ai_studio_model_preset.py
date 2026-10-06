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
    # Elbise/etek/şort çekimlerinde kullanılan "çıplak bacak + topuklu" manken sürümleri.
    # Seedream bir düzenleme modelidir: Image 1'deki pantolonu çoğu zaman korur ve
    # elbisenin altına giydirir. Bu yüzden pantolonlu manken hiç gönderilmez; ilk
    # ihtiyaçta bir kez türetilip burada saklanır (manken görseli değişince sıfırlanır).
    model_image_front_legs = fields.Image(string='Önden Manken (Çıplak Bacak)', max_width=1920,
                                          max_height=1920, attachment=True, copy=False)
    model_image_back_legs = fields.Image(string='Arkadan Manken (Çıplak Bacak)', max_width=1920,
                                         max_height=1920, attachment=True, copy=False)
    model_image_side_legs = fields.Image(string='Yandan Manken (Çıplak Bacak)', max_width=1920,
                                         max_height=1920, attachment=True, copy=False)
    # Alt giyim / tulum / takım çekimlerinde kullanılan "düz siyah tayt" manken sürümleri.
    # Mankenin kumaş pantolonu (kemer köprüsü, ön ütü çizgisi, fermuarlı ön) "in place of the
    # bottoms in Image 1" denince ürünle harmanlanıyor, lastikli örme pantolona köprü/tırnak
    # çiziliyordu. Yapısız tayt modele kopyalanacak parça bırakmaz. İlk ihtiyaçta bir kez türetilir.
    model_image_front_plain = fields.Image(string='Önden Manken (Düz Alt)', max_width=1920,
                                           max_height=1920, attachment=True, copy=False)
    model_image_back_plain = fields.Image(string='Arkadan Manken (Düz Alt)', max_width=1920,
                                          max_height=1920, attachment=True, copy=False)
    model_image_side_plain = fields.Image(string='Yandan Manken (Düz Alt)', max_width=1920,
                                          max_height=1920, attachment=True, copy=False)
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

        self.usage_count = 0
        self.approval_rate = 0.0

        if not self.ids:
            return

        session_groups = session_model._read_group(
            [('model_preset_id', 'in', self.ids)],
            ['model_preset_id'],
            ['__count']
        )
        usage_map = {preset.id: count for preset, count in session_groups}

        gen_groups = gen_model._read_group(
            [('session_id.model_preset_id', 'in', self.ids), ('state', '=', 'done')],
            ['session_id', 'is_approved'],
            ['__count']
        )
        
        gen_map = {}
        for session, is_approved, count in gen_groups:
            preset_id = session.model_preset_id.id
            if preset_id not in gen_map:
                gen_map[preset_id] = {'total': 0, 'approved': 0}
            gen_map[preset_id]['total'] += count
            if is_approved:
                gen_map[preset_id]['approved'] += count

        for preset in self:
            preset.usage_count = usage_map.get(preset.id, 0)
            stats = gen_map.get(preset.id)
            if stats and stats['total'] > 0:
                preset.approval_rate = (stats['approved'] / stats['total']) * 100.0
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

    # Kıyafet DEĞİŞTİRME dili: "remove the trousers / bare legs" fal içerik denetimine
    # (content_policy_violation) takılıyor. Mini etek bacakları açık bırakır; elbise
    # giydirilirken kıyafetin tamamı zaten değiştirilir.
    BARE_LEGS_EDIT_PROMPT = (
        "Image 1 shows a fashion model. Keep the same person, face, hair, body, pose, top, "
        "lighting and background exactly. Change only the lower-body outfit: the model now "
        "wears a plain black fitted mini skirt ending at mid-thigh and simple nude "
        "high-heeled pumps, with the lower legs visible below the skirt."
    )

    PLAIN_BOTTOMS_EDIT_PROMPT = (
        "Image 1 shows a fashion model. Keep the same person, face, hair, body, pose, top, shoes, "
        "lighting and background exactly. Change only the lower-body outfit: the model now wears "
        "plain black fitted stretch leggings, smooth and seamless, with a simple flat waistband, "
        "reaching the ankles."
    )

    def write(self, vals):
        # Manken görseli değişirse ondan türetilmiş çıplak bacak / düz alt sürümleri geçersizdir
        for view in ('front', 'back', 'side'):
            if 'model_image_%s' % view in vals:
                for suffix in ('_legs', '_plain'):
                    if 'model_image_%s%s' % (view, suffix) not in vals:
                        vals['model_image_%s%s' % (view, suffix)] = False
        return super().write(vals)

    def _get_plain_bottoms_mannequin(self, view, fal_api_key):
        """Alt giyim / tulum / takım için altında düz siyah tayt olan manken: (base64, maliyet).

        Bir kez Seedream ile türetilip saklanır; üretilemezse orijinal görsel döner.
        """
        self.ensure_one()
        base_field = 'model_image_%s' % view
        plain_field = base_field + '_plain'
        if self[plain_field]:
            return self[plain_field], 0.0
        if view != 'front' and not self[base_field]:
            return self._get_plain_bottoms_mannequin('front', fal_api_key)
        base = self[base_field]
        if not base or not fal_api_key:
            return base, 0.0
        from ..services.fal_provider import FalProvider
        try:
            data, cost = FalProvider(fal_api_key).single_image_edit(base, self.PLAIN_BOTTOMS_EDIT_PROMPT)
        except Exception as e:
            _logger.warning('Düz alt manken üretilemedi (preset=%s, %s): %s', self.id, view, e)
            return base, 0.0
        if not data:
            return base, 0.0
        plain_b64 = base64.b64encode(data)
        self.sudo().write({plain_field: plain_b64})
        _logger.info('Düz alt (tayt) manken türetildi ve saklandı (preset=%s, %s)', self.id, view)
        return plain_b64, cost

    def _get_bare_leg_mannequin(self, view, gemini_api_key, fal_api_key):
        """Elbise/etek/şort için bacakları açık manken görseli: (base64, maliyet).

        Önbellek yoksa: Gemini ile bacaklar kapalı mı bakılır; kapalıysa Seedream ile
        bir kez "çıplak bacak + topuklu" sürümü üretilip saklanır. Kontrol/üretim
        yapılamazsa orijinal görsel döner (üretim yine sonuç denetimiyle korunur).
        """
        self.ensure_one()
        base_field = 'model_image_%s' % view
        legs_field = base_field + '_legs'
        if self[legs_field]:
            return self[legs_field], 0.0
        if view != 'front' and not self[base_field]:
            # Bu açının kendi mankeni yok: ön mankenin sürümünü paylaş (ikinci kez ödeme yok)
            return self._get_bare_leg_mannequin('front', gemini_api_key, fal_api_key)
        base = self[base_field]
        if not base:
            return base, 0.0

        from ..services.garment_analyzer import mannequin_legs_covered
        covered = mannequin_legs_covered(gemini_api_key, base) if gemini_api_key else None
        if covered is False:
            self.sudo().write({legs_field: base})
            return base, 0.0
        if covered is None and self.garment_type == 'one_piece':
            return base, 0.0  # kontrol yapılamadı; elbise preset'i, olduğu gibi kullan
        if not fal_api_key:
            return base, 0.0

        from ..services.fal_provider import FalProvider
        try:
            data, cost = FalProvider(fal_api_key).single_image_edit(base, self.BARE_LEGS_EDIT_PROMPT)
        except Exception as e:
            _logger.warning('Çıplak bacak manken üretilemedi (preset=%s, %s): %s', self.id, view, e)
            return base, 0.0
        if not data:
            return base, 0.0
        legs_b64 = base64.b64encode(data)
        self.sudo().write({legs_field: legs_b64})
        _logger.info('Çıplak bacak manken türetildi ve saklandı (preset=%s, %s)', self.id, view)
        return legs_b64, cost

    def action_regenerate_mannequins(self):
        """Seçili presetlerin mankenlerini güncel promptla yeniden üret (toplu, sıralı).

        Eski manken görselleri önce kütüphaneye yedeklenir. Prompt'u olmayan (elle
        yüklenmiş) presetler atlanır.
        """
        if not (self.env.is_admin() or self.env.user.has_group('ugurlar_ai_studio.group_ai_studio_manager')):
            raise UserError(_('Bu işlem için AI Stüdyo yönetici yetkisi gereklidir.'))
        presets = self.filtered(lambda p: p.mannequin_prompt and p.mannequin_generation_state != 'generating')
        if not presets:
            raise UserError(_('Yeniden üretilecek preset yok (manken promptu olan ve şu an üretimde olmayan preset seçin).'))

        icp = self.env['ir.config_parameter'].sudo()
        provider_type = icp.get_param('ugurlar_ai_studio.default_provider', 'fashn')
        api_key = icp.get_param('ugurlar_ai_studio.fashn_api_key' if provider_type == 'fashn'
                                else 'ugurlar_ai_studio.fal_api_key')
        if not api_key:
            raise UserError(_('AI API anahtarı ayarlanmamış.'))

        for preset in presets.filtered('model_image_front'):
            previous_link = preset.library_mannequin_id
            preset.action_save_to_library()  # yedek
            preset.library_mannequin_id = previous_link  # yedek, preset'in kaynağı olmasın
        presets.write({'mannequin_generation_state': 'generating'})

        jobs = [(p.id, p.mannequin_prompt, p.gender, p.body_type, p.background_type) for p in presets]
        uid = self.env.uid

        def _run_all():
            for preset_id, prompt, gender, body_type, bg_type in jobs:
                self._generate_mannequin_thread(preset_id, prompt, api_key, gender, body_type,
                                                bg_type, provider_type, uid)

        def _start():
            thread = threading.Thread(target=_run_all)
            thread.daemon = True
            thread.start()
        self.env.cr.postcommit.add(_start)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Mankenler Yeniden Üretiliyor'),
                'message': _('%d preset sırayla işlenecek (her biri 1-3 dk). Eski görseller kütüphaneye yedeklendi.')
                           % len(presets),
                'type': 'info',
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

        # Arka planda çalıştır (commit sonrası)
        def _start_mannequin_thread():
            thread = threading.Thread(
                target=self._generate_mannequin_thread,
                args=(self.id, self.mannequin_prompt, api_key,
                      self.gender, self.body_type, self.background_type, provider_type, self.env.uid),
            )
            thread.daemon = True
            thread.start()
        self.env.cr.postcommit.add(_start_mannequin_thread)

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
                'sticky': False,
            },
        }

    # ─── Manken üretim promptları ────────────────────────────────────
    # Try-on şablonlarıyla (services/category_constants.py) uyumlu kıyafetler:
    # üst giyim çekiminde koyu kumaş pantolon + deri ayakkabı, alt giyimde sade üst,
    # elbisede çıplak bacak + topuklu. Böylece try-on modelin mankendeki pantolonu
    # "silmesine" gerek kalmaz. Seedream/FLUX negative_prompt desteklemediği için
    # istenmeyen şeyler listelenmez; istenen sonuç tarif edilir.
    MANNEQUIN_OUTFITS = {
        'tops': 'a plain fitted solid-color tank top, slim dark tailored trousers and simple dark leather shoes',
        'bottoms': 'a plain fitted neutral tank top, plain black fitted leggings and clean white minimal sneakers',
        'one_piece': 'a plain fitted solid-color sleeveless bodysuit, bare legs and simple nude high-heeled pumps',
        'shoes': 'a plain fitted solid-color tank top, slim dark trousers ending above the ankle',
        'bags': 'a plain fitted solid-color tank top, slim dark tailored trousers and simple dark leather shoes',
        'accessories': 'a plain fitted solid-color tank top, slim dark tailored trousers and simple dark leather shoes',
    }

    MANNEQUIN_VIEWS = {
        'front': 'front view, facing the camera',
        'back': 'back view, facing away from the camera, the whole back visible',
        # Try-on yan şablonu 45 derece ister; manken de aynı açıda olmalı
        'side': 'three-quarter side view, turned about 45 degrees',
    }

    MANNEQUIN_STYLE = (
        "Relaxed natural standing pose, arms at the sides, natural hands. "
        "The whole body from head to feet in frame with a little space above and below. "
        "Plain seamless white studio background, soft even lighting. "
        "Real person with natural skin texture, photorealistic editorial catalog photo. "
        "Only the model in the frame, no props, bags, studio equipment or text."
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
        """Manken için metinden görsel promptu (~90 kelime; FLUX metin sınırına sığar)."""
        return (
            f"Photorealistic full-body fashion catalog photo of {base_prompt}, "
            f"{self.MANNEQUIN_VIEWS.get(view, self.MANNEQUIN_VIEWS['front'])}. "
            f"{self.MANNEQUIN_STYLE}"
        )

    def _mannequin_view_edit_prompt(self, view, outfit):
        """Ön mankenden (Image 1) aynı kişinin arka/yan görünümünü üreten edit promptu."""
        return (
            f"Image 1 shows a fashion model. Show the same person, "
            f"{self.MANNEQUIN_VIEWS[view]}, wearing the same outfit ({outfit}) "
            f"with the same hair, face, body and skin tone. {self.MANNEQUIN_STYLE}"
        )

    def _generate_mannequin_thread(self, preset_id, prompt, api_key,
                                    gender, body_type, bg_type, provider_type, uid):
        """Thread içinde AI manken oluştur — SaaS tarzı consistency ile."""
        _logger.info("Mannequin Thread starting for preset %s with uid %s", preset_id, uid)
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

            garment_type = 'tops'
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                    p = env['ai.studio.model.preset'].browse(preset_id)
                    garment_type = p.garment_type or 'tops'
                    # Kullanıcının Türkçe manken tarifi İngilizce prompta çevrilmeden girmesin
                    if prompt and prompt.strip():
                        prompt = env['ai.studio.generation']._translate_prompt(prompt) or prompt
            except Exception:
                pass

            outfit = self.MANNEQUIN_OUTFITS.get(garment_type, self.MANNEQUIN_OUTFITS['tops'])
            # Aynı kişi/kıyafet tarifi tüm açılarda; açı _build_full_prompt'ta eklenir
            person = ', '.join(filter(None, [
                gender_hints.get(gender, 'young adult'),
                body_hints.get(body_type, 'standard build'),
                (prompt or '').strip(),
            ]))
            enhanced_prompt_front = enhanced_prompt_back = enhanced_prompt_side = (
                f"a {person}, wearing {outfit}"
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
                    _logger.info('seedream/v5/pro/edit ile tutarli arka gorsel')
                    back_prompt = self._mannequin_view_edit_prompt('back', outfit)

                    back_result = self._fal_api_call(
                        'bytedance/seedream/v5/pro/edit',
                        {
                            'prompt': back_prompt,
                            'image_urls': [front_fal_url],
                            'num_images': 1,
                            'output_format': 'png',
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
                            'image_size': {'width': 864, 'height': 1296},
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
                    _logger.info('seedream/v5/pro/edit ile tutarli yan gorsel')
                    side_prompt = self._mannequin_view_edit_prompt('side', outfit)

                    try:
                        side_result = self._fal_api_call(
                            'bytedance/seedream/v5/pro/edit',
                            {
                                'prompt': side_prompt,
                                'image_urls': [front_fal_url],
                                'num_images': 1,
                                'output_format': 'png',
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
                env = api.Environment(cr, uid, {'lang': 'tr_TR'})
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
                    env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                    preset = env['ai.studio.model.preset'].browse(preset_id)
                    preset.write({'mannequin_generation_state': 'failed'})
                    cr.commit()
            except Exception:
                _logger.error('Durum güncelleme de başarısız oldu')

    # ─── Kıyafet Giydirme (seedream/v5/pro/edit) ────────────────────


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

        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.fal_api_key'
        )
        if not api_key:
            raise UserError(_(
                'fal.ai API anahtarı ayarlanmamış. '
                'Ayarlar → AI Stüdyo menüsünden girin.'
            ))

        self.state = 'preprocessing'

        # Her fotoğraf için generation kaydı oluştur
        for photo in self.photo_ids:
            self.env['ai.studio.generation'].create({
                'session_id': self.id,
                'source_photo_id': photo.id,
                'photo_type': photo.photo_type,
                'original_image': photo.image_original,
                'state': 'pending',
                'provider': 'fal',
            })

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

    def _process_ai_thread(self, session_id, api_key):
        """Thread içinde tüm generation'ları işle."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks
        import os
        os.environ['FAL_KEY'] = api_key

        try:
            import fal_client
        except ImportError:
            _logger.error('fal-client kurulu değil. pip install fal-client')
            with self.pool.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                session = env['ai.studio.session'].browse(session_id)
                session.write({'state': 'draft'})
                session.message_post(
                    body=_('Hata: fal-client Python paketi kurulu değil.')
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

            for gen in generations:
                try:
                    gen.write({'state': 'processing'})
                    cr.commit()

                    start_time = time.time()
                    source_image = gen.original_image

                    # 1. Arka plan kaldırma (opsiyonel)
                    if auto_bg and source_image:
                        try:
                            garment_url = fal_client.upload(
                                base64.b64decode(source_image),
                                'image/jpeg',
                            )
                            bg_result = fal_client.subscribe(
                                'fal-ai/birefnet',
                                arguments={'image_url': garment_url},
                            )
                            garment_url = bg_result['image']['url']
                        except Exception as e:
                            _logger.warning('BG remove başarısız, orijinal kullanılıyor: %s', e)
                            garment_url = fal_client.upload(
                                base64.b64decode(source_image),
                                'image/jpeg',
                            )
                    else:
                        garment_url = fal_client.upload(
                            base64.b64decode(source_image),
                            'image/jpeg',
                        )

                    # 2. Manken resmini yükle
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

                    model_url = fal_client.upload(
                        base64.b64decode(model_image_data),
                        'image/jpeg',
                    )

                    # 3. Kategori belirleme
                    cat = session.category
                    if cat == 'auto':
                        cat = preset.garment_type or 'tops'
                    fal_category = {
                        'tops': 'tops',
                        'bottoms': 'bottoms',
                        'one_piece': 'one-piece',
                    }.get(cat, 'tops')

                    # 4. Endpoint belirleme
                    endpoint = env['ir.config_parameter'].sudo().get_param(
                        'ugurlar_ai_studio.default_endpoint',
                        'fal-ai/fashn/tryon/v1.6',
                    )

                    # 5. Virtual try-on çağrısı
                    result = fal_client.subscribe(
                        endpoint,
                        arguments={
                            'model_image': model_url,
                            'garment_image': garment_url,
                            'category': fal_category,
                            'mode': session.quality_mode or 'balanced',
                            'garment_photo_type': 'flat-lay',
                        },
                    )

                    elapsed = time.time() - start_time

                    # 6. Sonucu indir ve kaydet
                    import requests
                    output_url = ''
                    if 'images' in result and result['images']:
                        output_url = result['images'][0].get('url', '')
                    elif 'image' in result and result['image']:
                        output_url = result['image'].get('url', '')

                    if output_url:
                        img_data = requests.get(output_url, timeout=60).content
                        gen.write({
                            'generated_image': base64.b64encode(img_data),
                            'state': 'done',
                            'fal_endpoint': endpoint,
                            'generation_time_seconds': elapsed,
                            'cost': 0.075,  # FASHN tahmini maliyet
                        })
                    else:
                        gen.write({
                            'state': 'failed',
                            'error_message': 'API sonuç URL döndürmedi.',
                        })

                    cr.commit()

                except Exception as e:
                    _logger.error('AI üretim hatası (gen=%s): %s', gen.id, e)
                    gen.write({
                        'state': 'failed',
                        'error_message': str(e)[:500],
                    })
                    cr.commit()

            # Tüm üretimler tamamlandı
            session.write({'state': 'review'})
            session.message_post(
                body=_('AI üretimi tamamlandı. %d görsel onay bekliyor.') % len(generations),
            )
            cr.commit()

    def _process_single_generation(self, generation):
        """Tek bir generation'ı yeniden işle (retry için)."""
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.fal_api_key'
        )
        if not api_key:
            raise UserError(_('fal.ai API anahtarı ayarlanmamış.'))

        thread = threading.Thread(
            target=self._retry_generation_thread,
            args=(self.id, generation.id, api_key),
        )
        thread.daemon = True
        thread.start()

    def _retry_generation_thread(self, session_id, gen_id, api_key):
        """Tek generation retry thread'i."""
        time.sleep(1.5)  # Wait for main thread transaction to commit and release locks
        import os
        os.environ['FAL_KEY'] = api_key

        with self.pool.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            session = env['ai.studio.session'].browse(session_id)
            gen = env['ai.studio.generation'].browse(gen_id)

            # Aynı işlem mantığını uygula (basitleştirilmiş)
            try:
                import fal_client

                gen.write({'state': 'processing'})
                cr.commit()

                source_image = gen.original_image
                garment_url = fal_client.upload(
                    base64.b64decode(source_image), 'image/jpeg'
                )

                preset = session.model_preset_id
                model_image_field = 'model_image_front'
                if gen.photo_type == 'back':
                    model_image_field = 'model_image_back'
                elif gen.photo_type == 'side':
                    model_image_field = 'model_image_side'
                model_image = getattr(preset, model_image_field, False) or preset.model_image_front
                if not model_image:
                    raise Exception('Preset manken resmi eksik.')

                model_url = fal_client.upload(
                    base64.b64decode(model_image), 'image/jpeg'
                )

                endpoint = env['ir.config_parameter'].sudo().get_param(
                    'ugurlar_ai_studio.default_endpoint',
                    'fal-ai/fashn/tryon/v1.6',
                )

                result = fal_client.subscribe(
                    endpoint,
                    arguments={
                        'model_image': model_url,
                        'garment_image': garment_url,
                        'category': 'tops',
                        'mode': session.quality_mode or 'balanced',
                    },
                )

                import requests
                output_url = ''
                if 'images' in result and result['images']:
                    output_url = result['images'][0].get('url', '')
                elif 'image' in result and result['image']:
                    output_url = result['image'].get('url', '')

                if output_url:
                    img_data = requests.get(output_url, timeout=60).content
                    gen.write({
                        'generated_image': base64.b64encode(img_data),
                        'state': 'done',
                        'error_message': False,
                    })
                cr.commit()

            except Exception as e:
                _logger.error('Retry hatası (gen=%s): %s', gen_id, e)
                gen.write({
                    'state': 'failed',
                    'error_message': str(e)[:500],
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
                    'product_variant_id': prod.id,
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

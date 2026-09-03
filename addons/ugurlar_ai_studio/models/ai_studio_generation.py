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
    generation_mode = fields.Selection([
        ('single', 'Tekli'),
        ('set_combo', 'Kombin'),
    ], string='Üretim Modu', default='single')
    
    set_line_id = fields.Many2one(
        'ai.studio.set.line',
        string='Takım Parçası',
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

    original_image = fields.Image(
        string='Orijinal',
        max_width=1920, max_height=1920,
        compute='_compute_original_image',
        help='Karşılaştırma için orijinal fotoğraf',
    )

    @api.depends('source_photo_id.image_original')
    def _compute_original_image(self):
        for gen in self:
            if gen.source_photo_id and gen.source_photo_id.image_original:
                gen.original_image = gen.source_photo_id.image_original
            else:
                gen.original_image = False
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
    is_excluded = fields.Boolean(
        string='Hariç Tutuldu',
        default=False,
        help='Bu yön ürün kartına kaydedilirken hariç tutulacak',
    )
    is_exported_to_local = fields.Boolean(string='Klasöre Aktarıldı', default=False, index=True)
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
        string='Revizyon Talimati',
        help='Red durumunda ek prompt talimati (Turkce)',
    )
    revision_prompt_en = fields.Text(
        string='Revision (EN)',
        help='Ingilizce ceviri — AI modeline bu gonderilir',
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
    effective_reject_reason_id = fields.Many2one(
        'ai.studio.reject.reason',
        string='Etkin Red Sebebi',
        compute='_compute_effective_reject_reason',
        store=True,
    )

    # --- Ürün İlişkili Alanlar ---
    product_id = fields.Many2one(
        'product.product',
        string='Ürün Varyantı',
        related='session_id.product_id',
        store=True,
    )
    product_barcode = fields.Char(
        string='Barkod',
        related='session_id.product_barcode',
        store=True,
    )
    product_name = fields.Char(
        string='Ürün Adı',
        related='session_id.product_id.display_name',
        store=False,
    )

    @api.depends('reject_reason_id', 'parent_generation_id.reject_reason_id')
    def _compute_effective_reject_reason(self):
        for rec in self:
            reason = rec.reject_reason_id
            if not reason and rec.parent_generation_id:
                reason = rec.parent_generation_id.reject_reason_id
            rec.effective_reject_reason_id = reason or False

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

    def action_unapprove(self):
        """Üretim onayını geri al."""
        for gen in self:
            gen.is_approved = False
            gen.is_primary = False
            gen.session_id.message_post(
                body=_('%(type)s görselinin onayı geri alındı (v%(ver)s).') % {
                    'type': dict(gen._fields['photo_type'].selection).get(gen.photo_type, ''),
                    'ver': gen.revision_number,
                },
            )

    def action_toggle_exclude(self):
        """Hariç tutma durumunu değiştir (toggle)."""
        for gen in self:
            gen.is_excluded = not gen.is_excluded
            if gen.is_excluded:
                gen.is_approved = False
                gen.is_primary = False
                gen.session_id.message_post(
                    body=_('%(type)s görseli ürüne kaydedilirken hariç tutulacak (v%(ver)s).') % {
                        'type': dict(gen._fields['photo_type'].selection).get(gen.photo_type, ''),
                        'ver': gen.revision_number,
                    },
                )
            else:
                gen.session_id.message_post(
                    body=_('%(type)s görseli tekrar ürüne eklendi (v%(ver)s).') % {
                        'type': dict(gen._fields['photo_type'].selection).get(gen.photo_type, ''),
                        'ver': gen.revision_number,
                    },
                )
        return True

    @api.onchange('revision_prompt')
    def _onchange_revision_prompt(self):
        """Türkçe revizyon metnini İngilizce'ye çevir.
        
        Öncelik: deep-translator (ücretsiz Google Translate)
        Fallback: Gemini Flash API
        """
        if not self.revision_prompt or not self.revision_prompt.strip():
            self.revision_prompt_en = ''
            return
        
        # ═══ YÖNTEM 1: deep-translator (ÜCRETSİZ) ═══
        try:
            from deep_translator import GoogleTranslator
            translated = GoogleTranslator(source='tr', target='en').translate(self.revision_prompt)
            if translated:
                self.revision_prompt_en = translated
                return
        except ImportError:
            pass  # deep-translator kurulu değil, Gemini fallback
        except Exception:
            pass  # Rate limit veya hata, Gemini fallback
        
        # ═══ YÖNTEM 2: Gemini Flash (FALLBACK — ~$0.001) ═══
        try:
            gemini_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            if not gemini_key:
                self.revision_prompt_en = self.revision_prompt
                return
            
            import requests as _req
            prompt = (
                "Translate this fashion image editing instruction to clear, precise English. "
                "Context: This is an edit request for a fashion e-commerce photo. "
                "Return ONLY the English translation, nothing else.\n\n"
                f"Turkish instruction: {self.revision_prompt}"
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            resp = _req.post(url, json={
                'contents': [{'parts': [{'text': prompt}]}],
            }, headers={'Content-Type': 'application/json'}, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get('candidates', [])
                if candidates:
                    en_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
                    if en_text:
                        self.revision_prompt_en = en_text
                        return
            
            self.revision_prompt_en = self.revision_prompt
        except Exception:
            self.revision_prompt_en = self.revision_prompt

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
            ('reject_reason_id', '=', False),
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
                    'title': _('Tebrikler!'),
                    'message': _('Onaylanacak başka görsel kalmadı. Lütfen ana ekrandan "Tamamla ve Kaydet" diyerek işlemleri bitirin.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

    def action_confirm_reject(self):
        """Reddet ve yeni versiyon oluştur (Popup içinden).
        
        Revizyon talimatı varsa ve önceki görsel mevcutsa Seedream ile
        hedefli düzenleme yapılır. Aksi halde sıfırdan üretim yapılır.
        """
        self.ensure_one()
        if not self.reject_reason_id:
            raise UserError(_('Lütfen bir red sebebi seçin.'))
            
        # Mevcut olanı reddedilmiş işaretle
        self.is_approved = False
        self.state = 'done'
        self.session_id.message_post(body=_("%s görseli reddedildi, yeni versiyon üretilecek.") % self.photo_type)
        
        # Revizyon talimatı var mı? — İngilizce çeviri varsa onu kullan
        revision_text = ''
        # Önce İngilizce çeviriyi kontrol et (UI'da @api.onchange ile çevrildi)
        if self.revision_prompt_en:
            revision_text += self.revision_prompt_en
        elif self.revision_prompt:
            revision_text += self.revision_prompt
        if self.reject_reason_id.suggested_prompt:
            if revision_text:
                revision_text += ' '
            revision_text += self.reject_reason_id.suggested_prompt

        # Önceki görsel ve revizyon talimatı varsa → Seedream ile hedefli düzenleme
        use_seedream_edit = bool(revision_text and self.generated_image)
        revision_success = False
        
        if use_seedream_edit:
            try:
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(
                    'Seedream revizyonu baslatiliyor (gen=%s, tip=%s): %s',
                    self.id, self.photo_type, revision_text[:100],
                )
                
                session = self.session_id
                fal_api_key = session.fal_api_key or self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
                
                if fal_api_key:
                    from ..services.fal_provider import FalProvider
                    provider = FalProvider(fal_api_key)
                    
                    # Önceki görseli fal CDN'e yükle
                    parent_image_b64 = self.generated_image
                    if isinstance(parent_image_b64, bytes):
                        parent_image_b64 = parent_image_b64.decode('ascii')
                    
                    parent_image_url = provider.upload_image(parent_image_b64)
                    
                    # Seedream ile hedefli düzenleme — Figure 1 referansı
                    seedream_prompt = (
                        f"This is a fashion e-commerce photo (Figure 1). "
                        f"Apply ONLY this specific edit to Figure 1: {revision_text}. "
                        f"Keep everything else in Figure 1 exactly the same — "
                        f"same model, same pose, same hairstyle, same shoes, same background, same lighting. "
                        f"Change ONLY what is described above. Output one image. "
                    )
                    
                    import fal_client as _fal_client
                    result = _fal_client.subscribe(
                        'bytedance/seedream/v5/pro/edit',
                        arguments={
                            'prompt': seedream_prompt,
                            'image_urls': [parent_image_url],
                            'aspect_ratio': '2:3',
                            'output_format': 'png',
                            'resolution': '2k',
                        },
                        client_timeout=120,
                    )
                    
                    # Sonucu al
                    output_url = ''
                    if 'images' in result and result['images']:
                        output_url = result['images'][0].get('url', '')
                    elif 'image' in result and result['image']:
                        output_url = result['image'].get('url', '')
                    
                    if output_url:
                        import requests as req_lib
                        import base64
                        img_data = req_lib.get(output_url, timeout=60).content
                        from odoo.addons.ugurlar_ai_studio.models.ai_studio_session import _convert_to_jpeg
                        img_data = _convert_to_jpeg(img_data)
                        fixed_b64 = base64.b64encode(img_data).decode()
                        
                        # Yeni versiyon oluştur — Seedream sonucu ile
                        new_gen = self.copy({
                            'state': 'done',
                            'is_approved': False,
                            'generated_image': fixed_b64,
                            'revision_number': self.revision_number + 1,
                            'parent_generation_id': self.id,
                            'error_message': False,
                            'fal_request_id': False,
                            'cost': 0.05,
                            'quality_score': 0.0,
                            'fal_endpoint': 'fal/seedream-revision',
                        })
                        revision_success = True
                        _logger.info('Seedream revizyonu basarili (gen=%s → new=%s)', self.id, new_gen.id)
                    else:
                        _logger.warning('Seedream revizyonu sonuc dondurmedi, sifirdan uretim yapilacak (gen=%s)', self.id)
            except Exception as e:
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning('Seedream revizyonu hatasi, sifirdan uretim yapilacak (gen=%s): %s', self.id, e)
        
        if not revision_success:
            # Fallback: sıfırdan üretim (eski davranış)
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

    def action_mark_session_done(self):
        """Bu popup içinden tüm oturumu Tamamla ve Kaydet yapmak için."""
        self.ensure_one()
        if self.session_id:
            # Action döndürüyoruz ki sayfayı komple kapatsın ve listeye dönsün
            return self.session_id.action_mark_done()

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

    def action_open_session_review(self):
        """Oturumun form görünümünü açar."""
        self.ensure_one()
        return {
            'name': _('Oturum: %s') % self.session_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'ai.studio.session',
            'res_id': self.session_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cancel_revision_record(self):
        """Listeden veya formdan revizyonu iptal edip önceki haline döndür."""
        self.ensure_one()
        parent = self.parent_generation_id
        if not parent:
            raise UserError(_('Bu kaydın bağlı olduğu bir önceki versiyon bulunamadı.'))
        parent.write({
            'reject_reason_id': False,
            'revision_prompt': False,
            'revision_prompt_en': False,
            'state': 'done',
        })
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Revizyon İptal Edildi'),
                'message': _('Revizyon iptal edildi ve önceki görsel geri yüklendi.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model
    def action_recover_stuck_revisions_server(self):
        """10 dakikadan uzun süredir takılmış revizeleri başarısız durumuna çekerek kurtar."""
        self.env['ai.studio.session']._cron_check_stuck_generations()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Revizeler Kontrol Edildi'),
                'message': _('Takılmış veya yanıt vermeyen revizyonlar temizlendi ve güncellendi.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model
    def _cron_garbage_collect(self):
        """Reddedilen ve eski versiyonların görsellerini temizle (disk tasarrufu).

        KOŞULLAR (HEPSİ AYNI ANDA SAĞLANMALI):
        1. reject_reason_id VAR — gerçekten reddedilmiş (sadece onaylanmamış yetmez!)
        2. child_generation_ids VAR — yeni versiyonu üretilmiş (eski versiyon)
        3. Oturumu tamamlanmış (done) veya iptal edilmiş
        4. 7 günden eski

        ASLA TEMİZLENMEYECEKLER:
        - Henüz incelenmemiş (review durumundaki) oturumların görselleri
        - Son versiyon olan generation'lar (çocuğu yok = hâlâ gösterilecek)
        - Reddedilmemiş ama onaylanmamış generation'lar (beklemede olanlar)
        """
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.garbage_days', '7'
        ))
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(days=days)

        old_rejected = self.search([
            ('reject_reason_id', '!=', False),         # Gerçekten reddedilmiş
            ('child_generation_ids', '!=', False),      # Yeni versiyonu var (eski versiyon)
            ('session_id.state', 'in', ['done', 'cancelled']),  # Oturum tamamlanmış
            ('write_date', '<', cutoff),
            ('generated_image', '!=', False),           # Zaten temizlenmemişleri bul
        ])
        if old_rejected:
            _logger.info(
                'Çöp temizleme: %d eski reddedilen üretim görseli temizleniyor', len(old_rejected)
            )
            old_rejected.write({
                'generated_image': False,
                'original_image': False,
            })

    @api.model
    def action_recover_originals(self):
        """Cron garbage-collect tarafından yanlışlıkla silinen orijinal görselleri
        source_photo_id üzerinden geri yükle.

        Tamamen SQL bazlı: ir_attachment kayıtlarını kopyalayarak çalışır.
        Python belleğine hiç görsel yüklenmez — MemoryError riski sıfır.
        """
        cr = self.env.cr

        # 1. Kurtarılacak generation'ları bul:
        #    - original_image attachment'ı YOK
        #    - source_photo_id VAR
        #    - source photo'nun image_original attachment'ı VAR
        cr.execute("""
            SELECT g.id AS gen_id, g.source_photo_id AS photo_id
            FROM ai_studio_generation g
            WHERE g.source_photo_id IS NOT NULL
              AND g.state = 'done'
              AND g.reject_reason_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM ir_attachment a
                  WHERE a.res_model = 'ai.studio.generation'
                    AND a.res_field = 'original_image'
                    AND a.res_id = g.id
              )
              AND EXISTS (
                  SELECT 1 FROM ir_attachment a
                  WHERE a.res_model = 'ai.studio.photo'
                    AND a.res_field = 'image_original'
                    AND a.res_id = g.source_photo_id
              )
        """)
        rows = cr.fetchall()
        total = len(rows)
        _logger.info('Kurtarılacak toplam generation: %d', total)

        recovered = 0
        for gen_id, photo_id in rows:
            try:
                # ir_attachment kaydını SQL ile kopyala (binary Python'a hiç yüklenmez)
                cr.execute("""
                    INSERT INTO ir_attachment (
                        name, res_model, res_field, res_id, type,
                        db_datas, store_fname, file_size, checksum, mimetype,
                        create_uid, create_date, write_uid, write_date
                    )
                    SELECT
                        'original_image',
                        'ai.studio.generation',
                        'original_image',
                        %s,
                        a.type,
                        a.db_datas,
                        a.store_fname,
                        a.file_size,
                        a.checksum,
                        a.mimetype,
                        a.create_uid,
                        NOW() AT TIME ZONE 'UTC',
                        a.write_uid,
                        NOW() AT TIME ZONE 'UTC'
                    FROM ir_attachment a
                    WHERE a.res_model = 'ai.studio.photo'
                      AND a.res_field = 'image_original'
                      AND a.res_id = %s
                    LIMIT 1
                """, (gen_id, photo_id))
                cr.commit()
                recovered += 1
                if recovered % 10 == 0:
                    _logger.info('Kurtarma devam ediyor: %d / %d', recovered, total)
            except Exception as e:
                cr.rollback()
                _logger.warning('Generation %d kurtarılamadı: %s', gen_id, e)

        _logger.info(
            'Kurtarma tamamlandı: %d / %d generation orijinal görseli geri yüklendi.',
            recovered, total
        )
        return recovered

    @api.model
    def action_recover_from_fal_history(self):
        """fal.ai Platform API üzerinden geçmiş request'leri çekerek
        kayıp AI görsellerini kurtarır.

        Eşleştirme stratejisi:
        1. fal.ai'dan tüm nano-banana-2/edit request geçmişini çek
        2. Her request'in prompt'undan view type (FRONT/BACK/SIDE) tespit et
        3. Veritabanındaki generation kayıtlarıyla timestamp + photo_type eşle
        4. Output image URL'den görseli indir ve ir_attachment'a kaydet
        """
        import requests as http_requests
        import base64
        from datetime import datetime, timedelta

        cr = self.env.cr
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.fal_api_key', ''
        )
        if not api_key:
            _logger.error('fal.ai API key bulunamadı!')
            return {'error': 'API key yok', 'recovered': 0}

        # 1. Kayıp generation'ları çek (sadece fal endpoint olanlar)
        cr.execute("""
            SELECT g.id, g.create_date, g.photo_type, g.session_id
            FROM ai_studio_generation g
            WHERE g.state = 'done'
              AND g.reject_reason_id IS NULL
              AND g.photo_type IN ('front', 'back', 'side')
              AND (g.fal_endpoint IS NULL OR g.fal_endpoint LIKE '%%nano-banana%%' OR g.fal_endpoint LIKE '%%fal%%')
              AND NOT EXISTS (
                  SELECT 1 FROM ir_attachment a
                  WHERE a.res_model = 'ai.studio.generation'
                    AND a.res_field = 'generated_image'
                    AND a.res_id = g.id
              )
            ORDER BY g.create_date
        """)
        missing_gens = cr.fetchall()
        if not missing_gens:
            _logger.info('Kayıp fal.ai görseli yok.')
            return {'recovered': 0, 'total': 0}

        _logger.info('Kayıp fal.ai görseli: %d', len(missing_gens))

        # Session bazlı gruplama (aynı session'daki generation'lar yakın zamanlıdır)
        from collections import defaultdict
        session_gens = defaultdict(list)
        for gen_id, create_date, photo_type, session_id in missing_gens:
            session_gens[session_id].append({
                'id': gen_id,
                'create_date': create_date,
                'photo_type': photo_type,
            })

        # Tarih aralığını belirle
        min_date = min(g[1] for g in missing_gens) - timedelta(hours=1)
        max_date = max(g[1] for g in missing_gens) + timedelta(hours=1)

        # 2. fal.ai Platform API'den request geçmişini çek
        headers = {
            'Authorization': f'Key {api_key}',
            'Content-Type': 'application/json',
        }

        # fal endpoint ID'lerini belirle (eski + yeni)
        fal_endpoint_ids = [
            'fal-ai/nano-banana-2/edit',
            'bytedance/seedream/v5/pro/edit',
        ]

        all_fal_requests = []
        for endpoint_id in fal_endpoint_ids:
            cursor = None
            page = 0
            while True:
                params = {
                    'endpoint_id': endpoint_id,
                    'start': min_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'end': max_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'status': 'success',
                    'limit': 100,
                    'expand': 'payloads',
                }
                if cursor:
                    params['cursor'] = cursor

                try:
                    resp = http_requests.get(
                        'https://api.fal.ai/v1/models/requests/by-endpoint',
                        headers=headers,
                        params=params,
                        timeout=60,
                    )
                    if resp.status_code != 200:
                        _logger.warning(
                            'fal.ai API hata (%d): %s — Alternatif endpoint deneniyor...',
                            resp.status_code, resp.text[:200]
                        )
                        # Alternatif endpoint dene
                        resp = http_requests.get(
                            'https://api.fal.ai/v1/serverless/requests/by-endpoint',
                            headers=headers,
                            params=params,
                            timeout=60,
                        )
                        if resp.status_code != 200:
                            _logger.error(
                                'Alternatif fal.ai API de hata (%d): %s',
                                resp.status_code, resp.text[:200]
                            )
                            break

                    data = resp.json()
                    items = data.get('data', data.get('items', data.get('requests', [])))
                    if not items:
                        break

                    all_fal_requests.extend(items)
                    page += 1
                    _logger.info(
                        'fal.ai sayfa %d: %d istek çekildi (toplam: %d)',
                        page, len(items), len(all_fal_requests)
                    )

                    # Pagination — fal.ai gerçek key: next_cursor + has_more
                    has_more = data.get('has_more', False)
                    cursor = data.get('next_cursor')
                    if not has_more or not cursor:
                        break

                except Exception as e:
                    _logger.error('fal.ai API bağlantı hatası: %s', e)
                    break

        _logger.info('fal.ai toplam çekilen request: %d', len(all_fal_requests))
        if not all_fal_requests:
            return {'error': 'fal.ai geçmişi boş veya erişilemedi', 'recovered': 0}

        # 3. fal.ai request'lerini parse et
        def detect_view_type(prompt_text):
            """Prompt'tan view type tespit et"""
            if not prompt_text:
                return None
            prompt_upper = prompt_text.upper()
            if 'FRONT VIEW' in prompt_upper:
                return 'front'
            elif 'BACK VIEW' in prompt_upper or 'BACK view' in prompt_text:
                return 'back'
            elif 'SIDE VIEW' in prompt_upper or 'SIDE/THREE-QUARTER' in prompt_upper:
                return 'side'
            elif 'MACRO DETAIL' in prompt_upper or 'DETAIL SHOT' in prompt_upper:
                return 'detail'
            return None

        def parse_fal_request(req):
            """fal.ai request'ini parse et (gerçek API yapısı)"""
            result = {
                'request_id': req.get('request_id', req.get('id', '')),
                'timestamp': None,
                'view_type': None,
                'output_url': None,
                'seed': None,
            }

            # Timestamp — fal.ai gerçek key: ended_at
            end_time = req.get('ended_at', req.get('started_at', ''))
            if end_time:
                try:
                    if isinstance(end_time, str):
                        end_time = end_time.replace('Z', '+00:00')
                        result['timestamp'] = datetime.fromisoformat(end_time).replace(tzinfo=None)
                    elif isinstance(end_time, (int, float)):
                        result['timestamp'] = datetime.utcfromtimestamp(end_time / 1000 if end_time > 1e12 else end_time)
                except Exception:
                    pass

            # Input payload — fal.ai gerçek key: json_input
            input_data = req.get('json_input', req.get('input', {}))
            if isinstance(input_data, dict):
                prompt = input_data.get('prompt', '')
                result['view_type'] = detect_view_type(prompt)
                result['seed'] = input_data.get('seed')

            # Output payload — fal.ai gerçek key: json_output
            output_data = req.get('json_output', req.get('output', {}))
            if isinstance(output_data, dict):
                images = output_data.get('images', [])
                if images and isinstance(images, list) and len(images) > 0:
                    img = images[0]
                    if isinstance(img, dict):
                        result['output_url'] = img.get('url', '')
                    elif isinstance(img, str):
                        result['output_url'] = img

            return result

        parsed_requests = []
        for req in all_fal_requests:
            parsed = parse_fal_request(req)
            if parsed['view_type'] and parsed['output_url'] and parsed['timestamp']:
                parsed_requests.append(parsed)

        _logger.info('Parse edilen ve eşleştirmeye uygun request: %d', len(parsed_requests))

        # 4. Eşleştirme: timestamp yakınlığı + photo_type
        recovered = 0
        already_matched = set()  # Aynı fal request'in iki kere eşlenmesini önle

        for gen_id, create_date, photo_type, session_id in missing_gens:
            best_match = None
            best_diff = timedelta(minutes=10)  # Max 10 dakika fark

            for i, fal_req in enumerate(parsed_requests):
                if i in already_matched:
                    continue
                if fal_req['view_type'] != photo_type:
                    continue

                time_diff = abs(fal_req['timestamp'] - create_date)
                if time_diff < best_diff:
                    best_diff = time_diff
                    best_match = i

            if best_match is None:
                continue

            fal_req = parsed_requests[best_match]
            already_matched.add(best_match)

            # Output URL'den görseli indir
            try:
                img_resp = http_requests.get(fal_req['output_url'], timeout=60)
                if img_resp.status_code != 200:
                    _logger.warning(
                        'gen_id=%d: Görsel indirilemedi (HTTP %d) URL: %s',
                        gen_id, img_resp.status_code, fal_req['output_url'][:100]
                    )
                    continue

                img_b64 = base64.b64encode(img_resp.content).decode('utf-8')

                # Attachment oluştur
                content_type = img_resp.headers.get('content-type', 'image/png')
                self.env['ir.attachment'].sudo().create({
                    'name': 'generated_image',
                    'res_model': 'ai.studio.generation',
                    'res_field': 'generated_image',
                    'res_id': gen_id,
                    'type': 'binary',
                    'datas': img_b64,
                    'mimetype': content_type,
                })

                # fal_request_id'yi de kaydet
                cr.execute("""
                    UPDATE ai_studio_generation
                    SET fal_request_id = %s
                    WHERE id = %s AND (fal_request_id IS NULL OR fal_request_id = '')
                """, (fal_req['request_id'], gen_id))

                cr.commit()
                recovered += 1

                if recovered % 10 == 0:
                    _logger.info(
                        'fal.ai kurtarma: %d görsel kurtarıldı (fark: %s)',
                        recovered, best_diff
                    )

            except Exception as e:
                cr.rollback()
                _logger.warning('gen_id=%d kurtarılamadı: %s', gen_id, e)

        _logger.info(
            'fal.ai kurtarma tamamlandı: %d / %d görsel kurtarıldı.',
            recovered, len(missing_gens)
        )
        return {
            'recovered': recovered,
            'total': len(missing_gens),
            'fal_requests_fetched': len(all_fal_requests),
            'matched': len(already_matched),
        }

    @api.model
    def action_test_session_recovery(self, session_name='AIS/2026/01071'):
        """Spesifik bir oturum için fal.ai eşleştirmesini test et ve ekrana detay bas."""
        import requests as http_requests
        from datetime import datetime, timedelta

        cr = self.env.cr
        api_key = self.env['ir.config_parameter'].sudo().get_param('ugurlar_ai_studio.fal_api_key', '')
        
        if not api_key:
            _logger.error("HATA: fal.ai API key tanımlı değil!")
            return {"error": "API key yok"}

        # 1. Oturumu bul
        cr.execute("""
            SELECT s.id, s.name, s.create_date
            FROM ai_studio_session s
            WHERE s.name = %s
        """, (session_name,))
        session = cr.fetchone()
        if not session:
            _logger.error(f"HATA: {session_name} oturumu bulunamadı!")
            return {"error": "Oturum bulunamadı"}

        s_id, s_name, s_date = session
        _logger.info(f"=== OTURUM TESTİ: {s_name} (ID: {s_id}, Tarih: {s_date}) ===")

        # 2. Oturumdaki generation'ları bul
        cr.execute("""
            SELECT g.id, g.photo_type, g.create_date
            FROM ai_studio_generation g
            WHERE g.session_id = %s AND g.state = 'done' AND g.reject_reason_id IS NULL
            ORDER BY g.photo_type
        """, (s_id,))
        gens = cr.fetchall()

        if not gens:
            _logger.info("Bu oturumda done durumunda generation bulunamadı.")
            return {"error": "Generation yok"}

        # 48 saatlik geniş tarih penceresi (zaman dilimi farklarını kapsar)
        min_date = min(g[2] for g in gens) - timedelta(hours=24)
        max_date = max(g[2] for g in gens) + timedelta(hours=24)

        # 3. fal.ai API'sinden bu geniş tarih aralığındaki istekleri çek
        headers = {'Authorization': f'Key {api_key}'}
        all_requests = []
        cursor = None

        while True:
            params = {
                'endpoint_id': 'bytedance/seedream/v5/pro/edit',
                'start': min_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'end': max_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'status': 'success',
                'limit': 100,
                'expand': 'payloads',
            }
            if cursor:
                params['cursor'] = cursor

            try:
                resp = http_requests.get('https://api.fal.ai/v1/models/requests/by-endpoint', headers=headers, params=params, timeout=60)
                data = resp.json()
                items = data.get('items', [])
                all_requests.extend(items)
                if not data.get('has_more') or not data.get('next_cursor'):
                    break
                cursor = data.get('next_cursor')
            except Exception as e:
                _logger.error(f"API Hatası: {e}")
                break

        _logger.info(f"fal.ai'dan Çekilen Toplam Request Sayısı: {len(all_requests)}")

        # 4. Request'leri parse et
        def detect_view(prompt_text):
            if not prompt_text:
                return 'front'
            p = prompt_text.upper()
            if 'SHOW THE BACK VIEW' in p or 'BACK VIEW' in p:
                return 'back'
            elif 'SHOW THE SIDE VIEW' in p or 'SIDE VIEW' in p:
                return 'side'
            elif 'MACRO DETAIL' in p or 'CLOSE-UP DETAIL' in p:
                return 'detail'
            return 'front'

        parsed = []
        for req in all_requests:
            ended_at_str = req.get('ended_at', '')
            if not ended_at_str:
                continue
            try:
                dt = datetime.fromisoformat(ended_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                continue
            
            inp = req.get('json_input', {})
            prompt = inp.get('prompt', '') if isinstance(inp, dict) else ''
            v_type = detect_view(prompt)
            
            out = req.get('json_output', {})
            imgs = out.get('images', []) if isinstance(out, dict) else []
            url = imgs[0].get('url', '') if imgs else ''

            parsed.append({
                'req_id': req.get('request_id'),
                'timestamp': dt,
                'view_type': v_type,
                'url': url,
            })

        # 5. Eşleştirme yap
        results = []
        for gen_id, p_type, g_date in gens:
            best = None
            best_diff = timedelta(days=1)
            for req in parsed:
                if req['view_type'] == p_type:
                    diff = abs(req['timestamp'] - g_date)
                    if diff < best_diff:
                        best_diff = diff
                        best = req

            if best:
                res_info = f"✅ Tip: {p_type:<6} (Gen ID: {gen_id}) -> Eşleşti! | Gen Tarih: {g_date} | fal Tarih: {best['timestamp']} | Fark: {best_diff} | URL: {best['url']}"
                _logger.info(res_info)
                print(res_info)
                results.append({'gen_id': gen_id, 'photo_type': p_type, 'matched': True, 'url': best['url'], 'diff': str(best_diff)})
            else:
                res_info = f"❌ Tip: {p_type:<6} (Gen ID: {gen_id}) -> Eşleşme Bulunamadı!"
                _logger.info(res_info)
                print(res_info)
                results.append({'gen_id': gen_id, 'photo_type': p_type, 'matched': False})

        return results



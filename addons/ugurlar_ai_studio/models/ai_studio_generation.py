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
        # Prefetch source_photo_ids to avoid N+1 queries
        self.mapped('source_photo_id')
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
    retry_count = fields.Integer(string='Tekrar Deneme Sayısı', default=0)

    # --- Onay ---
    is_approved = fields.Boolean(string='Onaylandı', default=False)
    is_excluded = fields.Boolean(
        string='Hariç Tutuldu',
        default=False,
        help='Bu yön ürün kartına kaydedilirken hariç tutulacak',
    )
    is_exported_to_local = fields.Boolean(string='Klasöre Aktarıldı', default=False, index=True)
    candidate_ids = fields.One2many(
        'ai.studio.generation.candidate', 'generation_id', string='Alternatif Adaylar',
        help='Aynı istekte üretilen diğer görseller; reviewer birini ana görsel yapabilir.',
    )
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
    fal_request_id = fields.Char(string='fal.ai İstek ID', copy=False)
    fal_endpoint = fields.Char(string='Kullanılan Endpoint')
    fal_app = fields.Char(
        string='fal.ai Uygulama', copy=False,
        help='request_id ile birlikte sonucu fal kuyruğundan geri almak için gereken endpoint',
    )
    submitted_at = fields.Datetime(string='fal.ai Gönderim Zamanı', copy=False)
    error_type = fields.Char(string='Hata Tipi', copy=False)
    is_retryable = fields.Boolean(
        string='Yeniden Denenebilir', default=True, copy=False,
        help='Kalıcı hatalar (içerik politikası, geçersiz parametre...) otomatik yeniden denenmez',
    )
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

    def _check_ai_studio_group(self, level):
        """Model seviyesinde yetki kontrolü (RPC ile doğrudan çağrılara karşı)."""
        group = {
            'reviewer': 'ugurlar_ai_studio.group_ai_studio_reviewer',
            'manager': 'ugurlar_ai_studio.group_ai_studio_manager',
        }[level]
        if not (self.env.su or self.env.is_admin() or self.env.user.has_group(group)):
            raise UserError(_('Bu işlem için yetkiniz yok.'))

    def action_approve(self):
        """Üretimi onayla."""
        self._check_ai_studio_group('reviewer')
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
        self._check_ai_studio_group('reviewer')
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
        self._check_ai_studio_group('reviewer')
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

    def _translate_prompt(self, prompt_text):
        if not prompt_text or not prompt_text.strip():
            return ''
        
        # ═══ YÖNTEM 1: Gemini Flash (BİRİNCİL — güvenilir) ═══
        try:
            gemini_key = self.env['ir.config_parameter'].sudo().get_param(
                'ugurlar_ai_studio.gemini_api_key', ''
            )
            if gemini_key:
                import requests as _req
                prompt = (
                    "Translate this fashion image editing instruction to clear, precise English. "
                    "Context: This is an edit request for a fashion e-commerce photo. "
                    "Return ONLY the English translation, nothing else.\n\n"
                    f"Turkish instruction: {prompt_text}"
                )
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
                resp = _req.post(url, json={
                    'contents': [{'parts': [{'text': prompt}]}],
                }, headers={'Content-Type': 'application/json', 'x-goog-api-key': gemini_key}, timeout=10)
                
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get('candidates', [])
                    if candidates:
                        en_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
                        if en_text:
                            return en_text
        except Exception:
            pass  # Gemini başarısız, deep-translator dene
        
        # ═══ YÖNTEM 2: deep-translator (FALLBACK — ücretsiz) ═══
        try:
            from deep_translator import GoogleTranslator
            translated = GoogleTranslator(source='tr', target='en').translate(prompt_text)
            if translated:
                return translated
        except Exception:
            pass
        
        return prompt_text

    @api.onchange('revision_prompt')
    def _onchange_revision_prompt(self):
        """Türkçe revizyon metnini İngilizce'ye çevir (UI'dan tetiklenir)."""
        self.revision_prompt_en = self._translate_prompt(self.revision_prompt)


    @api.model_create_multi
    def create(self, vals_list):
        # Batch create'de çeviri yapmıyoruz — performans için
        # Onchange zaten UI'dan gelen kayıtlarda çeviriyi yapıyor
        return super().create(vals_list)

    def action_reject(self):
        """Red dialog'u aç — revize için."""
        self._check_ai_studio_group('reviewer')
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
        self._check_ai_studio_group('reviewer')
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
        self._check_ai_studio_group('reviewer')
        self.ensure_one()
        if not self.reject_reason_id:
            raise UserError(_('Lütfen bir red sebebi seçin.'))
            
        # Mevcut olanı reddedilmiş işaretle
        self.is_approved = False
        self.state = 'done'
        self.session_id.message_post(body=_("%s görseli reddedildi, yeni versiyon üretilecek.") % self.photo_type)
        
        # Revizyon (talimat varsa önce hedefli Seedream düzenlemesi, olmazsa yeniden
        # üretim) arka plan thread'inde yapılır: HTTP isteğinde uzun fal çağrısı yok.
        revision_success = False

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
                # Red nedeni YALNIZCA eski sürümde kalır: review ekranı red nedenli
                # kayıtları "eski sürüm" sayıp gizler
                'reject_reason_id': False,
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
        self._check_ai_studio_group('reviewer')
        self.ensure_one()
        if self.state != 'failed':
            raise UserError(_('Sadece başarısız üretimler tekrar denenebilir.'))
        from .ai_studio_session import CLEAR_FAL_REQUEST
        self.write(dict(CLEAR_FAL_REQUEST, state='pending', error_message=False))
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
        self._check_ai_studio_group('reviewer')
        self.ensure_one()
        if self.state not in ('pending', 'failed'):
            # İşlenen kayıt silinirse fal ücreti ödenir ama sonuç kaybolur
            raise UserError(_('Yalnızca bekleyen veya başarısız revizyonlar iptal edilebilir.'))
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

    def action_recover_stuck_revisions_server(self, *args, **kwargs):
        """Takılmış revizeleri yeniden kuyruğa alarak kurtar."""
        self._check_ai_studio_group('reviewer')
        from datetime import timedelta
        # Eğer kullanıcı belirli satırları seçip butona bastıysa doğrudan onları kurtar
        # fal'e gönderilmiş (request_id'li) işler yeniden kuyruğa ALINMAZ: sonuçları
        # cron tarafından fal'den okunur, yeniden göndermek ikinci kez ücret demektir
        submitted = lambda g: g.state == 'processing' and g.fal_request_id
        selected = self.filtered(lambda g: g.state in ('pending', 'processing') and not submitted(g))
        if selected:
            selected.write({
                'state': 'pending',
                'error_message': False,
            })
            count = len(selected)
        else:
            # Seçili yoksa 5 dakikadan uzun süredir takılmış tüm revizyonları kurtar
            cutoff = fields.Datetime.now() - timedelta(minutes=5)
            stuck = self.search([
                ('session_id.state', '=', 'review'),
                ('state', 'in', ['pending', 'processing']),
                ('write_date', '<', cutoff),
                '|', ('session_id.ai_lease_until', '=', False),
                ('session_id.ai_lease_until', '<', fields.Datetime.now()),
            ]).filtered(lambda g: not submitted(g))
            if stuck:
                stuck.write({
                    'state': 'pending',
                    'error_message': False,
                })
            count = len(stuck)

        if count:
            # Hemen cron'u da tetikle ki beklemeden kuyruktan başlasın
            self.env['ai.studio.session']._cron_check_stuck_generations()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Revizeler Kuyruğa Alındı'),
                'message': _('%d adet takılmış revizyon yeniden kuyruğa alındı ve işlenmeye başlandı.') % count if count else _('Takılmış revizyon bulunamadı, tüm işlemler güncel.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_batch_retry(self, *args, **kwargs):
        """Seçilen veya başarısız olan revizyonları toplu olarak sırayla tekrar dene."""
        self._check_ai_studio_group('reviewer')
        import threading
        failed_records = self.filtered(lambda g: g.state == 'failed')
        if not failed_records:
            failed_records = self.search([
                ('state', '=', 'failed'),
                '|', ('revision_number', '>', 1), ('parent_generation_id', '!=', False),
            ])

        if not failed_records:
            raise UserError(_('Tekrar denenecek başarısız revizyon bulunamadı.'))

        from .ai_studio_session import CLEAR_FAL_REQUEST
        failed_records.write(dict(CLEAR_FAL_REQUEST, state='pending', error_message=False))

        provider_type = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.default_provider', 'fashn'
        )
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'ugurlar_ai_studio.fashn_api_key' if provider_type == 'fashn' else 'ugurlar_ai_studio.fal_api_key'
        )
        if not api_key:
            raise UserError(_('AI API anahtarı ayarlanmamış.'))

        gen_ids = failed_records.ids
        uid = self.env.uid or 1

        # Commit'ten ÖNCE başlarsa thread kayıtları hâlâ 'failed' görür ve atlar
        def _start():
            thread = threading.Thread(
                target=self._batch_retry_worker_thread,
                args=(gen_ids, api_key, uid),
            )
            thread.daemon = True
            thread.start()
        self.env.cr.postcommit.add(_start)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Toplu Tekrar Deneme Başlatıldı'),
                'message': _('%d adet revizyon sırayla işlenmek üzere arka plana alındı. Durumları sayfayı yenileyerek takip edebilirsiniz.') % len(failed_records),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model
    def _batch_retry_worker_thread(self, gen_ids, api_key, uid):
        """Toplu revizyonları sırayla işleyen arka plan thread'i."""
        import time
        _logger.info("Toplu revizyon tekrar deneme thread'i baslatildi: %d adet", len(gen_ids))
        for gen_id in gen_ids:
            try:
                with self.pool.cursor() as cr:
                    env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                    gen = env['ai.studio.generation'].browse(gen_id)
                    if not gen.exists() or gen.state != 'pending':
                        continue
                    session_model = gen.session_id
                    session_id = session_model.id

                # Kira + semaphore sarmalayıcısı: oturum başka yerde işleniyorsa
                # generation 'pending' kalır ve cron devralır
                session_model._retry_generation_thread(session_id, gen_id, api_key, uid)
                time.sleep(1.0)
            except Exception as e:
                _logger.error("Toplu tekrar deneme hatası (gen=%s): %s", gen_id, e)
                try:
                    with self.pool.cursor() as cr:
                        env = api.Environment(cr, uid, {'lang': 'tr_TR'})
                        gen = env['ai.studio.generation'].browse(gen_id)
                        if gen.exists() and gen.state == 'pending':
                            gen.write({
                                'state': 'failed',
                                'error_message': _('Toplu işlem hatası: %s') % str(e),
                            })
                            cr.commit()
                except Exception:
                    pass
        _logger.info("Toplu revizyon tekrar deneme thread'i tamamlandi.")

    def action_batch_cancel(self, *args, **kwargs):
        """Seçilen revizyonları iptal edip önceki hallerine döndür."""
        self._check_ai_studio_group('reviewer')
        # İşlenen/tamamlanan revizyonlar silinmez (ücreti ödenmiş sonuç kaybolur)
        revisions = self.filtered(lambda g: g.parent_generation_id and g.state in ('pending', 'failed'))
        if not revisions:
            raise UserError(_('İptal edilecek bekleyen veya başarısız bir revizyon seçilmedi.'))
        count = 0
        for gen in revisions:
            parent = gen.parent_generation_id
            if parent and parent.exists():
                parent.write({
                    'reject_reason_id': False,
                    'revision_prompt': False,
                    'revision_prompt_en': False,
                    'state': 'done',
                })
            gen.unlink()
            count += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Revizyonlar İptal Edildi'),
                'message': _('%d adet revizyon iptal edildi ve önceki görseller geri yüklendi.') % count,
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
            })

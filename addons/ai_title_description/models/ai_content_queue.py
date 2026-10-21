# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging
import time
import traceback

_logger = logging.getLogger(__name__)


class AIContentQueue(models.Model):
    _name = 'ai.content.queue'
    _description = 'AI İçerik Üretim Kuyruğu'
    _order = 'priority asc, create_date asc'

    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade', index=True,
                                       string="Ürün")
    mode = fields.Selection([
        ('title', 'Sadece Başlık'),
        ('description', 'Sadece Açıklama'),
        ('both', 'Başlık + Açıklama')
    ], default='both', string="Mod")
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('processing', 'İşleniyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata')
    ], default='pending', index=True, string="Durum")
    error_message = fields.Text("Hata Mesajı")
    priority = fields.Integer("Öncelik", default=10)
    attempts = fields.Integer("Deneme Sayısı", default=0)
    max_attempts = fields.Integer("Maks Deneme", default=5)
    product_code = fields.Char("Ürün Kodu", compute='_compute_product_code', search='_search_product_code')

    @api.depends('product_tmpl_id.default_code', 'product_tmpl_id.product_variant_ids.default_code')
    def _compute_product_code(self):
        for rec in self:
            tmpl = rec.product_tmpl_id
            # Önce ana şablon iç referansı, yoksa ilk varyantın kodu
            code = tmpl.default_code
            if not code and tmpl.product_variant_ids:
                for variant in tmpl.product_variant_ids:
                    if variant.default_code:
                        code = variant.default_code
                        break
            rec.product_code = code or ''

    def _search_product_code(self, operator, value):
        return ['|',
                ('product_tmpl_id.default_code', operator, value),
                ('product_tmpl_id.product_variant_ids.default_code', operator, value)]

    product_barcode = fields.Char("Barkod", compute='_compute_product_barcode', search='_search_product_barcode')

    @api.depends('product_tmpl_id.barcode', 'product_tmpl_id.product_variant_ids.barcode')
    def _compute_product_barcode(self):
        for rec in self:
            tmpl = rec.product_tmpl_id
            barcode = tmpl.barcode
            if not barcode and tmpl.product_variant_ids:
                for variant in tmpl.product_variant_ids:
                    if variant.barcode:
                        barcode = variant.barcode
                        break
            rec.product_barcode = barcode or ''

    def _search_product_barcode(self, operator, value):
        return ['|',
                ('product_tmpl_id.barcode', operator, value),
                ('product_tmpl_id.product_variant_ids.barcode', operator, value)]

    # "Şimdi İşle"de HTTP isteği içinde senkron işlenecek en çok kayıt; kalanı cron kuyruğuna gider
    SYNC_PROCESS_LIMIT = 3
    # Cron çalışmasının süre bütçesi (sn): kayıt başı ~90 sn'ye kadar çıkabilen AI çağrılarıyla
    # 10 kayıtlık parti cron worker'ını dakikalarca tutuyordu
    CRON_TIME_BUDGET = 100

    @api.model
    def _trigger_queue_cron(self):
        """Kuyruk cron'unu hemen (bir sonraki cron turunda) çalıştırır; aralığı beklemez."""
        cron = self.env.ref('ai_title_description.ir_cron_ai_content_queue', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _cron_process_queue(self, batch_size=10, only_ids=None, time_budget=None):
        """Kuyruktan batch_size kadar ürün alıp AI içerik üretir.

        only_ids verilirse yalnızca o kuyruk kayıtları işlenir ("Şimdi İşle").
        Süre bütçesi (sn): yeni kayda başlamadan önce kontrol edilir; dolduysa durur ve iş
        kaldıysa kendini _trigger() ile yeniden tetikler. Varsayılan: cron çağrısında
        CRON_TIME_BUDGET, only_ids'li ("Şimdi İşle") çağrıda yok (zaten ≤ SYNC_PROCESS_LIMIT kayıt).
        """
        from datetime import timedelta
        started = time.monotonic()
        # DIKKAT: cron kaydı noupdate=1; bütçe XML'e değil buraya bağlı (-u ile güncellenmez)
        budget = time_budget if time_budget is not None else (None if only_ids else self.CRON_TIME_BUDGET)
        # 0. 20 dakikadan fazla 'processing' kalan takılı kayıtları sıfırla
        stuck_threshold = fields.Datetime.now() - timedelta(minutes=20)
        stuck_records = self.search([
            ('state', '=', 'processing'),
            ('write_date', '<', stuck_threshold)
        ])
        for stuck in stuck_records:
            stuck.attempts += 1
            _logger.warning("Kuyruk [%s] ürün [%s]: 20 dk'dan fazla işleniyor, takılı olarak işaretlendi (deneme: %s/%s).",
                            stuck.id, stuck.product_tmpl_id.name, stuck.attempts, stuck.max_attempts)
            if stuck.attempts >= stuck.max_attempts:
                stuck.state = 'error'
                stuck.error_message = 'İşlem zaman aşımına uğradı veya durduruldu (20 dk).'
            else:
                stuck.state = 'pending'
        if stuck_records:
            self.env.cr.commit()

        domain = [('state', '=', 'pending')]
        if only_ids:
            domain.append(('id', 'in', list(only_ids)))
        records = self.search(
            domain,
            limit=batch_size,
            order='priority asc, create_date asc'
        )
        if not records:
            return

        from ..services import get_ai_provider
        from ..services.prompt_engine import PromptEngine
        from ..services.title_validator import TitleValidator
        from ..services.vision_analyzer import VisionAnalyzer

        ICP = self.env['ir.config_parameter'].sudo()
        provider_type = ICP.get_param('ai_title_description.provider', 'gemini')
        gemini_key = ICP.get_param('ai_title_description.gemini_api_key')
        openai_key = ICP.get_param('ai_title_description.openai_api_key')

        if provider_type == 'openai':
            if not openai_key:
                _logger.error("AI İçerik Kuyruğu: OpenAI API key yapılandırılmamış.")
                return
            model_name = ICP.get_param('ai_title_description.openai_model', 'gpt-4o-mini')
        else:
            if not gemini_key:
                _logger.error("AI İçerik Kuyruğu: Gemini API key yapılandırılmamış.")
                return
            model_name = ICP.get_param('ai_title_description.gemini_model', 'gemini-2.5-flash')

        use_vision = ICP.get_param('ai_title_description.use_vision', 'True') == 'True'
        image_size = ICP.get_param('ai_title_description.image_size', 'image_1024')
        use_google = ICP.get_param('ai_title_description.use_google_suggest', 'True') == 'True'
        use_trendyol = ICP.get_param('ai_title_description.use_trendyol_suggest', 'True') == 'True'
        use_grounding = ICP.get_param('ai_title_description.use_search_grounding', 'True') == 'True'

        provider = get_ai_provider(provider_type, gemini_key, openai_key, model_name=model_name)
        pe = PromptEngine()
        tv = TitleValidator()
        va = VisionAnalyzer()

        processed = 0
        attempted_ids = []
        budget_hit = False
        for record in records:
            if budget and time.monotonic() - started >= budget:
                budget_hit = True
                break
            attempted_ids.append(record.id)
            record.state = 'processing'
            self.env.cr.commit()

            try:
                self.env.cr.execute('SAVEPOINT ai_queue_sp')

                product = record.product_tmpl_id

                # Görsel kontrolü — görseli olmayan ürünler atlanır
                if not product.image_1920:
                    record.write({
                        'state': 'error',
                        'error_message': 'Ürün görseli (ana görsel) bulunamadı. Lütfen önce görsel yükleyin.',
                    })
                    self.env.cr.execute('RELEASE SAVEPOINT ai_queue_sp')
                    self.env.cr.commit()
                    _logger.info("Kuyruk [%s] ürün [%s]: Görsel yok, atlandı.", record.id, product.name)
                    continue

                payload = product._extract_ai_payload()

                # 1. SEO Anahtar Kelime Keşfi
                seo_keywords = []
                try:
                    seed = payload.get('category', '').split(' / ')[-1] if payload.get('category') else payload.get('raw_name', '')
                    if seed:
                        seo_keywords = self.env['ai.keyword.cache']._get_keywords(
                            seed, use_google=use_google, use_trendyol=use_trendyol)
                except Exception as e:
                    _logger.warning("Kuyruk [%s]: Keyword keşfi başarısız: %s", record.id, e)

                # 2. Görsel Analiz
                image_base64 = None
                if use_vision and product.image_1920:
                    try:
                        image_base64 = va.extract_image_base64(product, image_field=image_size)
                    except Exception as e:
                        _logger.warning("Kuyruk [%s]: Görsel hazırlığı başarısız: %s", record.id, e)

                # 3. Prompt Oluştur
                system_prompt = pe.build_system_prompt()
                user_prompt = pe.build_user_prompt(
                    payload,
                    seo_keywords=seo_keywords,
                    image_included=bool(image_base64),
                    mode=record.mode,
                )

                # 4. AI API Çağrısı
                result = provider.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    image_base64=image_base64,
                    use_search_grounding=use_grounding if provider_type == 'gemini' else False,
                )

                # 5. Başlık Doğrulama
                trendyol_title = result.get('trendyol_title', '')
                validation = tv.validate_and_fix(trendyol_title)
                fixed_title = validation.get('fixed_title', trendyol_title)

                # 6. Ürüne Yaz
                product_vals = {
                    'ai_content_generated': True,
                    'ai_last_generated': fields.Datetime.now(),
                    'ai_generation_count': product.ai_generation_count + 1,
                }

                if record.mode in ('title', 'both'):
                    # Ürün adı olacak başlık da klişe/yasaklı kelime ve uzunluk temizliğinden geçer
                    ecommerce_title = (result.get('ecommerce_title') or '').strip()
                    if ecommerce_title:
                        ecommerce_title = tv.validate_and_fix(ecommerce_title, platform='genel')['fixed_title']
                    product_vals.update({
                        'ai_trendyol_title': fixed_title,
                        'ai_ecommerce_title': ecommerce_title,
                        'ai_meta_title': result.get('meta_title', ''),
                        'ai_seo_keywords': ', '.join(result.get('seo_keywords', [])),
                    })
                    # Ürün adını SADECE geçerli (boş olmayan) bir başlık varsa güncelle
                    new_name = ecommerce_title or fixed_title
                    if new_name:
                        product_vals.update(product._ai_name_vals(new_name))

                if record.mode in ('description', 'both'):
                    # Key features'ı HTML'e dahil et
                    key_features = result.get('key_features', [])
                    html_desc = result.get('html_description', '')
                    if key_features and '<ul>' not in html_desc:
                        features_html = '<ul>' + ''.join(f'<li>{f}</li>' for f in key_features) + '</ul>'
                        html_desc = features_html + html_desc

                    short_summary = result.get('short_summary', '')
                    product_vals.update({
                        'ai_short_description': short_summary,
                        'ai_html_description': html_desc,
                        'ai_meta_description': result.get('meta_description', ''),
                        'description': html_desc or short_summary,
                        # Satış açıklaması düz metin alanıdır (teklif/fatura satırı, etiket):
                        # HTML etiketleri görünmesin
                        'description_sale': product._ai_sale_text(html_desc, short_summary),
                    })

                # SEO anahtar kelimelerini E-Ticaret etiketlerine otomatik bağla
                seo_kws_str = product_vals.get('ai_seo_keywords') or ', '.join(result.get('seo_keywords', []))
                if seo_kws_str and product._ai_create_tags_enabled():
                    keywords = [k.strip() for k in seo_kws_str.split(',') if k.strip()]
                    if keywords:
                        tag_field = False
                        for fname in ['product_tag_ids', 'website_tag_ids', 'tag_ids']:
                            if fname in product._fields:
                                tag_field = fname
                                break
                        if tag_field:
                            target_model = product._fields[tag_field].comodel_name
                            TagModel = self.env[target_model]
                            tag_commands = []
                            for kw in keywords:
                                tag = TagModel.sudo().search([('name', '=ilike', kw)], limit=1)
                                if not tag:
                                    try:
                                        tag = TagModel.sudo().create({'name': kw})
                                    except Exception as e:
                                        _logger.warning("Kuyruk etiket oluşturulamadı '%s': %s", kw, e)
                                        continue
                                if tag:
                                    tag_commands.append((4, tag.id))
                            if tag_commands:
                                product_vals[tag_field] = tag_commands

                product.write(product_vals)

                # 7. Log Kaydet
                prompt_toks = result.get('_prompt_tokens', 0)
                comp_toks = result.get('_completion_tokens', 0)
                total_toks = result.get('_token_count', prompt_toks + comp_toks)

                # Eğer prompt/completion ayrışmamışsa ama total varsa, tahmini ayır
                if total_toks > 0 and prompt_toks == 0 and comp_toks == 0:
                    prompt_toks = int(total_toks * 0.7)  # ~70% prompt
                    comp_toks = total_toks - prompt_toks

                from ..services.cost_calculator import calculate_ai_cost
                cost = calculate_ai_cost(provider_type, model_name, prompt_tokens=prompt_toks, completion_tokens=comp_toks)

                _logger.info("Kuyruk [%s]: Token kullanımı — prompt=%d, completion=%d, total=%d, maliyet=$%.6f",
                             record.id, prompt_toks, comp_toks, total_toks, cost)

                self.env['ai.content.log'].sudo().create({
                    'product_tmpl_id': product.id,
                    'provider': provider_type,
                    'model_name': model_name,
                    'mode': record.mode,
                    'generated_title': fixed_title,
                    'generated_description': result.get('html_description', ''),
                    'applied': True,
                    'title_score': validation.get('score', 0),
                    'used_vision': bool(image_base64),
                    'seo_keywords_used': ', '.join(seo_keywords) if seo_keywords else '',
                    'prompt_tokens': prompt_toks,
                    'completion_tokens': comp_toks,
                    'token_count': total_toks,
                    'cost_estimate': cost,
                    'prompt_used': user_prompt[:5000],
                    'raw_response': str(result)[:5000],
                })

                self.env.cr.execute('RELEASE SAVEPOINT ai_queue_sp')
                record.state = 'done'
                record.error_message = False
                processed += 1

            except Exception as e:
                err_msg = f"{str(e)}\n{traceback.format_exc()}"
                _logger.error("Kuyruk [%s] ürün [%s] hata: %s", record.id, record.product_tmpl_id.name, e)
                # NEDEN: hata yalıtımı — geri alma/log/durum yazımı bile patlasa bozuk kayıt
                # cron'u durdurmaz; tam geri alma yapılıp kayıt hata durumuna düşürülür.
                try:
                    self.env.cr.execute('ROLLBACK TO SAVEPOINT ai_queue_sp')
                    self.env.invalidate_all()
                    # Google ücretlendirdi ama içerik kullanılamadı: harcama loglansın (bütçeye girsin)
                    with self.env.cr.savepoint():
                        self.env['ai.content.log']._log_failed_calls(
                            record.product_tmpl_id, provider_type, model_name, record.mode,
                            getattr(provider, 'failed_calls', None))
                except Exception:
                    _logger.exception("Kuyruk [%s]: hata sonrası temizlik başarısız, tam geri alma.", record.id)
                    self.env.cr.rollback()
                    self.env.invalidate_all()
                record = self.browse(record.id)
                record.attempts += 1
                record.state = 'error' if record.attempts >= record.max_attempts else 'pending'
                record.error_message = err_msg

            self.env.cr.commit()

        _logger.info("AI Kuyruk: %s/%s ürün başarıyla işlendi.", processed, len(records))
        # Süre bütçesi doldu: bu turda denenmeyen bekleyen kayıt kaldıysa cron'u hemen yeniden tetikle.
        # NEDEN: denenip hata ile 'pending'e dönenler hariç tutulur; yoksa API kesintisinde
        # cron aralıksız kendini tetikleyip aynı hatalı kayıtları döverdi.
        if budget_hit and self.search_count(
                [('state', '=', 'pending'), ('id', 'not in', attempted_ids)] +
                ([('id', 'in', list(only_ids))] if only_ids else []), limit=1):
            self._trigger_queue_cron()

    def action_reset_to_pending(self):
        """Kuyruk kaydını yeniden 'bekliyor' durumuna getirir (deneme sayısı ve maks deneme sıfırlanır)."""
        for record in self:
            record.write({
                'state': 'pending',
                'error_message': False,
                'attempts': 0,
                'max_attempts': 5,
            })

    def action_process_now(self):
        """Seçili kuyruk kayıtlarından en çok SYNC_PROCESS_LIMIT tanesini hemen (senkron) işler.

        NEDEN: kayıt başı ~90 sn'lik AI çağrısı HTTP worker'ını kilitliyordu (sınırsız kayıt).
        Fazlası 'pending' kalır ve kuyruk cron'u _trigger() ile hemen başlatılır.
        """
        todo = self.filtered(lambda r: r.state != 'done')
        if not todo:
            return True  # boşken limit=0 "sınırsız" olur ve tüm kuyruk işlenirdi
        todo.write({'state': 'pending'})
        now_ids = todo.ids[:self.SYNC_PROCESS_LIMIT]
        queued = len(todo) - len(now_ids)
        self._cron_process_queue(batch_size=len(now_ids), only_ids=now_ids)
        if queued:
            self._trigger_queue_cron()
        message = _('%(done)d kayıt şimdi işlendi.', done=len(now_ids))
        if queued:
            message = _('%(done)d kayıt şimdi işlendi, %(queued)d kayıt kuyruğa alındı '
                        '(arka planda sırayla işlenecek).', done=len(now_ids), queued=queued)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Şimdi İşle'),
                'message': message,
                'type': 'warning' if queued else 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_cancel(self):
        """Seçili kuyruk kayıtlarını durdurur / iptal eder."""
        cancelable = self.filtered(lambda r: r.state in ('pending', 'processing'))
        cancelable.write({
            'state': 'error',
            'error_message': 'Kullanıcı tarafından iptal edildi.',
        })
        return True

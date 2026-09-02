# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging
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
    max_attempts = fields.Integer("Maks Deneme", default=3)

    @api.model
    def _cron_process_queue(self, batch_size=10):
        """Kuyruktan batch_size kadar ürün alıp AI içerik üretir."""
        records = self.search(
            [('state', '=', 'pending')],
            limit=batch_size,
            order='priority asc, create_date asc'
        )
        if not records:
            return

        from ..services import get_ai_provider
        from ..services.prompt_engine import PromptEngine
        from ..services.keyword_discovery import KeywordDiscovery
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
        kd = KeywordDiscovery()
        tv = TitleValidator()
        va = VisionAnalyzer()

        processed = 0
        for record in records:
            record.state = 'processing'
            self.env.cr.commit()

            try:
                self.env.cr.execute('SAVEPOINT ai_queue_sp')

                product = record.product_tmpl_id
                payload = product._extract_ai_payload()

                # 1. SEO Anahtar Kelime Keşfi
                seo_keywords = []
                try:
                    seed = payload.get('category', '').split(' / ')[-1] if payload.get('category') else payload.get('raw_name', '')
                    if seed:
                        seo_keywords = kd.discover_keywords(seed, use_google=use_google, use_trendyol=use_trendyol)
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
                    ecommerce_title = result.get('ecommerce_title', '')
                    product_vals.update({
                        'ai_trendyol_title': fixed_title,
                        'ai_ecommerce_title': ecommerce_title,
                        'ai_meta_title': result.get('meta_title', ''),
                        'ai_seo_keywords': ', '.join(result.get('seo_keywords', [])),
                        'name': ecommerce_title or fixed_title,
                    })

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
                        'description_sale': html_desc,
                    })

                # SEO anahtar kelimelerini E-Ticaret etiketlerine otomatik bağla
                seo_kws_str = product_vals.get('ai_seo_keywords') or ', '.join(result.get('seo_keywords', []))
                if seo_kws_str:
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
                self.env['ai.content.log'].create({
                    'product_tmpl_id': product.id,
                    'mode': record.mode,
                    'generated_title': fixed_title,
                    'generated_description': result.get('html_description', ''),
                    'applied': True,
                    'title_score': validation.get('score', 0),
                    'used_vision': bool(image_base64),
                    'seo_keywords_used': ', '.join(seo_keywords) if seo_keywords else '',
                    'token_count': result.get('_token_count', 0),
                    'cost_estimate': result.get('_token_count', 0) * 0.00000015,  # ~$0.15/M tokens
                    'prompt_used': user_prompt[:5000],
                    'raw_response': str(result)[:5000],
                })

                self.env.cr.execute('RELEASE SAVEPOINT ai_queue_sp')
                record.state = 'done'
                record.error_message = False
                processed += 1

            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT ai_queue_sp')
                record.attempts += 1
                err_msg = f"{str(e)}\n{traceback.format_exc()}"
                _logger.error("Kuyruk [%s] ürün [%s] hata: %s", record.id, record.product_tmpl_id.name, e)

                if record.attempts >= record.max_attempts:
                    record.state = 'error'
                else:
                    record.state = 'pending'
                record.error_message = err_msg

            self.env.cr.commit()

        _logger.info("AI Kuyruk: %s/%s ürün başarıyla işlendi.", processed, len(records))

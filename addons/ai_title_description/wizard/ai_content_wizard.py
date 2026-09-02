# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)


class AIContentWizard(models.TransientModel):
    _name = 'ai.content.wizard'
    _description = 'AI İçerik Üretim Sihirbazı'

    product_tmpl_id = fields.Many2one('product.template', string='Ürün', required=True)
    mode = fields.Selection([
        ('title', 'Sadece Başlık'),
        ('description', 'Sadece Açıklama'),
        ('both', 'Başlık + Açıklama')
    ], default='both', string='Üretim Modu')

    # AI Sağlayıcı ve Model Seçimi
    provider = fields.Selection([
        ('gemini', 'Google Gemini'),
        ('openai', 'OpenAI (ChatGPT)')
    ], default='gemini', string='AI Sağlayıcı')

    gemini_model = fields.Selection([
        ('gemini-2.5-flash', 'Gemini 2.5 Flash (Hızlı & Ekonomik)'),
        ('gemini-2.5-pro', 'Gemini 2.5 Pro (Gelişmiş & Derin Analiz)'),
        ('gemini-2.0-flash', 'Gemini 2.0 Flash')
    ], default='gemini-2.5-flash', string='Gemini Modeli')

    openai_model = fields.Selection([
        ('gpt-4o-mini', 'GPT-4o Mini (Hızlı & Ekonomik)'),
        ('gpt-4o', 'GPT-4o (En Yüksek Kalite)')
    ], default='gpt-4o-mini', string='OpenAI Modeli')

    # Önizleme Alanları
    preview_trendyol_title = fields.Char('Trendyol Başlık Önizleme', size=100)
    preview_ecommerce_title = fields.Char('E-Ticaret Başlık Önizleme')
    preview_short_description = fields.Text('Kısa Açıklama Önizleme')
    preview_html_description = fields.Html('Zengin Açıklama Önizleme', sanitize=True)
    preview_meta_title = fields.Char('SEO Başlık Önizleme', size=60)
    preview_meta_description = fields.Text('SEO Açıklama Önizleme')
    preview_seo_keywords = fields.Char('Anahtar Kelimeler Önizleme')

    # Doğrulama
    title_score = fields.Integer('Başlık Skoru', readonly=True)
    title_char_count = fields.Integer('Karakter Sayısı', readonly=True)
    # Token ve Maliyet Takibi
    prompt_tokens = fields.Integer('Girdi Token', readonly=True)
    completion_tokens = fields.Integer('Çıktı Token', readonly=True)
    token_count = fields.Integer('Toplam Token', readonly=True)
    cost_estimate = fields.Float('Tahmini Maliyet ($)', digits=(10, 6), readonly=True)
    used_provider = fields.Char('Kullanılan Provider', readonly=True)
    used_model = fields.Char('Kullanılan Model', readonly=True)
    prompt_used = fields.Text('Kullanılan Prompt', readonly=True)
    raw_response = fields.Text('Ham AI Yanıtı', readonly=True)

    state = fields.Selection([
        ('draft', 'Hazır'),
        ('generated', 'Üretildi'),
        ('applied', 'Uygulandı')
    ], default='draft')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        if 'provider' in fields_list:
            res['provider'] = ICP.get_param('ai_title_description.provider', 'gemini')
        if 'gemini_model' in fields_list:
            res['gemini_model'] = ICP.get_param('ai_title_description.gemini_model', 'gemini-2.5-flash')
        if 'openai_model' in fields_list:
            res['openai_model'] = ICP.get_param('ai_title_description.openai_model', 'gpt-4o-mini')
        return res

    def action_generate(self):
        """AI ile içerik üret: SEO kelimeleri keşfet → Prompt oluştur → AI Provider'a gönder → Validate → Önizle"""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        
        provider_type = self.provider or ICP.get_param('ai_title_description.provider', 'gemini')
        gemini_key = ICP.get_param('ai_title_description.gemini_api_key')
        openai_key = ICP.get_param('ai_title_description.openai_api_key')

        if provider_type == 'openai':
            if not openai_key:
                raise UserError(_("Lütfen Ayarlar > AI Başlık & Açıklama bölümünden OpenAI API anahtarını girin."))
            model_name = self.openai_model or ICP.get_param('ai_title_description.openai_model', 'gpt-4o-mini')
        else:
            if not gemini_key:
                raise UserError(_("Lütfen Ayarlar > AI Başlık & Açıklama bölümünden Gemini API anahtarını girin."))
            model_name = self.gemini_model or ICP.get_param('ai_title_description.gemini_model', 'gemini-2.5-flash')

        # Ayarları oku
        use_vision = ICP.get_param('ai_title_description.use_vision', 'True') == 'True'
        image_size = ICP.get_param('ai_title_description.image_size', 'image_1024')
        use_google = ICP.get_param('ai_title_description.use_google_suggest', 'True') == 'True'
        use_trendyol = ICP.get_param('ai_title_description.use_trendyol_suggest', 'True') == 'True'
        use_grounding = ICP.get_param('ai_title_description.use_search_grounding', 'True') == 'True'

        # Servisleri import et
        from ..services import get_ai_provider
        from ..services.prompt_engine import PromptEngine
        from ..services.keyword_discovery import KeywordDiscovery
        from ..services.title_validator import TitleValidator
        from ..services.vision_analyzer import VisionAnalyzer

        product = self.product_tmpl_id
        payload = product._extract_ai_payload()

        # 1. SEO Anahtar Kelime Keşfi
        seo_keywords = []
        try:
            kd = KeywordDiscovery()
            seed = payload.get('category', '').split(' / ')[-1] if payload.get('category') else payload.get('raw_name', '')
            if seed:
                seo_keywords = kd.discover_keywords(seed, use_google=use_google, use_trendyol=use_trendyol)
                self.discovered_keywords = ', '.join(seo_keywords) if seo_keywords else ''
        except Exception as e:
            _logger.warning("Anahtar kelime keşfi başarısız: %s", e)
            self.discovered_keywords = _('Anahtar kelime keşfi başarısız oldu.')

        # 2. Görsel Analiz
        image_base64 = None
        if use_vision and product.image_1920:
            try:
                va = VisionAnalyzer()
                image_base64 = va.extract_image_base64(product, image_field=image_size)
            except Exception as e:
                _logger.warning("Görsel analiz hazırlığı başarısız: %s", e)

        # 3. Prompt Oluştur
        pe = PromptEngine()
        system_prompt = pe.build_system_prompt()
        user_prompt = pe.build_user_prompt(
            payload,
            seo_keywords=seo_keywords,
            image_included=bool(image_base64),
            mode=self.mode,
        )

        # 4. AI Provider Çağrısı
        try:
            provider = get_ai_provider(provider_type, gemini_key, openai_key, model_name=model_name)
            result = provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_base64=image_base64,
                use_search_grounding=use_grounding if provider_type == 'gemini' else False,
            )
        except ValueError as e:
            raise UserError(str(e))
        except Exception as e:
            _logger.error("AI API çağrısı başarısız (%s / %s): %s", provider_type, model_name, e)
            raise UserError(_("AI içerik üretimi başarısız oldu: %s") % str(e))

        # 5. Sonuçları önizleme alanlarına yaz
        self.preview_trendyol_title = result.get('trendyol_title', '')
        self.preview_ecommerce_title = result.get('ecommerce_title', '')
        self.preview_short_description = result.get('short_summary', '')
        self.preview_meta_title = result.get('meta_title', '')
        self.preview_meta_description = result.get('meta_description', '')

        # Key features'ı HTML description'a dahil et
        key_features = result.get('key_features', [])
        html_desc = result.get('html_description', '')
        if key_features and '<ul>' not in html_desc:
            features_html = '<ul>' + ''.join(f'<li>{f}</li>' for f in key_features) + '</ul>'
            html_desc = features_html + html_desc
        self.preview_html_description = html_desc

        # SEO keywords
        seo_kws = result.get('seo_keywords', [])
        self.preview_seo_keywords = ', '.join(seo_kws) if isinstance(seo_kws, list) else str(seo_kws)

        # 6. Token & Maliyet Hesapla
        prompt_toks = result.get('_prompt_tokens', 0)
        comp_toks = result.get('_completion_tokens', 0)
        total_toks = result.get('_token_count', prompt_toks + comp_toks)

        from ..services.cost_calculator import calculate_ai_cost
        cost = calculate_ai_cost(provider_type, model_name, prompt_tokens=prompt_toks, completion_tokens=comp_toks)

        self.prompt_tokens = prompt_toks
        self.completion_tokens = comp_toks
        self.token_count = total_toks
        self.cost_estimate = cost
        self.used_provider = provider_type
        self.used_model = model_name
        self.prompt_used = user_prompt[:5000]
        self.raw_response = str(result)[:5000]

        # 7. Başlık Doğrulama
        tv = TitleValidator()
        validation = tv.validate_and_fix(self.preview_trendyol_title or '')
        self.title_score = validation.get('score', 0)
        self.title_char_count = validation.get('char_count', 0)
        self.title_word_count = validation.get('word_count', 0)
        warnings = validation.get('warnings', [])
        self.title_warnings = '\n'.join(warnings) if warnings else _('Uyarı yok — başlık kurallara uygun.')

        # Düzeltilmiş başlığı kullan
        if validation.get('fixed_title'):
            self.preview_trendyol_title = validation['fixed_title']

        self.state = 'generated'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_regenerate(self):
        """Yeniden üret (farklı varyasyon veya farklı model ile)"""
        self.ensure_one()
        self.state = 'draft'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _apply_data(self, title=True, description=True):
        """Onaylanan içeriği ürün kartına kaydet"""
        self.ensure_one()
        product = self.product_tmpl_id
        vals = {
            'ai_content_generated': True,
            'ai_last_generated': fields.Datetime.now(),
            'ai_generation_count': product.ai_generation_count + 1,
        }

        if title:
            vals['ai_trendyol_title'] = self.preview_trendyol_title
            vals['ai_ecommerce_title'] = self.preview_ecommerce_title
            vals['ai_meta_title'] = self.preview_meta_title
            vals['ai_seo_keywords'] = self.preview_seo_keywords
            # Odoo ana ürün adını güncelle
            if self.preview_ecommerce_title:
                vals['name'] = self.preview_ecommerce_title
            elif self.preview_trendyol_title:
                vals['name'] = self.preview_trendyol_title

        if description:
            vals['ai_short_description'] = self.preview_short_description
            vals['ai_html_description'] = self.preview_html_description
            vals['ai_meta_description'] = self.preview_meta_description
            # Odoo ana iç notlar (description) ve satış açıklaması (description_sale) alanlarını ZENGİN AÇIKLAMA ile güncelle
            if self.preview_html_description:
                vals['description'] = self.preview_html_description
                vals['description_sale'] = self.preview_html_description
            elif self.preview_short_description:
                vals['description'] = self.preview_short_description

        # SEO anahtar kelimelerini E-Ticaret ürün etiketlerine ekle
        if self.preview_seo_keywords:
            keywords = [k.strip() for k in self.preview_seo_keywords.split(',') if k.strip()]
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
                                _logger.warning("Etiket oluşturulamadı '%s': %s", kw, e)
                                continue
                        if tag:
                            tag_commands.append((4, tag.id))
                    if tag_commands:
                        vals[tag_field] = tag_commands

        product.write(vals)

        # Üretim logunu kaydet
        self.env['ai.content.log'].sudo().create({
            'product_tmpl_id': product.id,
            'provider': self.used_provider or self.provider,
            'model_name': self.used_model or self.gemini_model,
            'mode': self.mode,
            'generated_title': self.preview_trendyol_title,
            'generated_description': self.preview_html_description,
            'title_score': self.title_score,
            'applied': True,
            'used_vision': bool(product.image_1920),
            'seo_keywords_used': self.preview_seo_keywords,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'token_count': self.token_count,
            'cost_estimate': self.cost_estimate,
            'prompt_used': self.prompt_used,
            'raw_response': self.raw_response,
        })

        self.state = 'applied'
        return {'type': 'ir.actions.act_window_close'}

    def action_apply(self):
        return self._apply_data(title=True, description=True)

    def action_apply_title_only(self):
        return self._apply_data(title=True, description=False)

    def action_apply_description_only(self):
        return self._apply_data(title=False, description=True)

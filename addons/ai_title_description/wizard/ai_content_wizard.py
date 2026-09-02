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
    title_word_count = fields.Integer('Kelime Sayısı', readonly=True)
    title_warnings = fields.Text('Uyarılar', readonly=True)
    discovered_keywords = fields.Text('Keşfedilen Anahtar Kelimeler', readonly=True)

    state = fields.Selection([
        ('draft', 'Hazır'),
        ('generated', 'Üretildi'),
        ('applied', 'Uygulandı')
    ], default='draft')

    def action_generate(self):
        """AI ile içerik üret: SEO kelimeleri keşfet → Prompt oluştur → Gemini'ye gönder → Validate → Önizle"""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('ai_title_description.gemini_api_key')
        if not api_key:
            raise UserError(_("Lütfen Ayarlar > AI Başlık & Açıklama bölümünden Gemini API anahtarını girin."))

        # Ayarları oku
        use_vision = ICP.get_param('ai_title_description.use_vision', 'True') == 'True'
        image_size = ICP.get_param('ai_title_description.image_size', 'image_1024')
        use_google = ICP.get_param('ai_title_description.use_google_suggest', 'True') == 'True'
        use_trendyol = ICP.get_param('ai_title_description.use_trendyol_suggest', 'True') == 'True'
        use_grounding = ICP.get_param('ai_title_description.use_search_grounding', 'True') == 'True'

        # Servisleri import et
        from ..services.gemini_provider import GeminiContentProvider
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

        # 4. Gemini API Çağrısı
        try:
            provider = GeminiContentProvider(api_key)
            result = provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_base64=image_base64,
                use_search_grounding=use_grounding,
            )
        except ValueError as e:
            raise UserError(str(e))
        except Exception as e:
            _logger.error("Gemini API çağrısı başarısız: %s", e)
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

        # 6. Başlık Doğrulama
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
        """Yeniden üret (farklı varyasyon)"""
        self.ensure_one()
        self.state = 'draft'
        return self.action_generate()

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

        if description:
            vals['ai_short_description'] = self.preview_short_description
            vals['ai_html_description'] = self.preview_html_description
            vals['ai_meta_description'] = self.preview_meta_description

        product.write(vals)

        # Üretim logunu kaydet
        self.env['ai.content.log'].create({
            'product_tmpl_id': product.id,
            'mode': self.mode,
            'generated_title': self.preview_trendyol_title,
            'generated_description': self.preview_html_description,
            'title_score': self.title_score,
            'applied': True,
            'seo_keywords_used': self.preview_seo_keywords,
        })

        self.state = 'applied'
        return {'type': 'ir.actions.act_window_close'}

    def action_apply(self):
        return self._apply_data(title=True, description=True)

    def action_apply_title_only(self):
        return self._apply_data(title=True, description=False)

    def action_apply_description_only(self):
        return self._apply_data(title=False, description=True)

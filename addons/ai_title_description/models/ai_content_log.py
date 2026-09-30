# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class AIContentLog(models.Model):
    _name = 'ai.content.log'
    _description = 'AI İçerik Üretim Geçmişi'
    _order = 'create_date desc'

    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade', index=True, string="Ürün")
    provider = fields.Selection([
        ('gemini', 'Google Gemini'),
        ('openai', 'OpenAI')
    ], string="AI Sağlayıcı")
    model_name = fields.Char("Model Adı")
    mode = fields.Selection([
        ('title', 'Başlık'),
        ('description', 'Açıklama'),
        ('both', 'Başlık + Açıklama')
    ], string="Mod")
    generated_title = fields.Char("Üretilen Başlık")
    generated_description = fields.Html("Üretilen Açıklama")
    applied = fields.Boolean("Uygulandı", default=False)
    title_score = fields.Integer("Başlık Skoru")
    used_vision = fields.Boolean("Görsel Analiz")
    seo_keywords_used = fields.Char("Kullanılan SEO Kelimeleri")
    prompt_tokens = fields.Integer("Girdi Token (Prompt)")
    completion_tokens = fields.Integer("Çıktı Token (Completion)")
    token_count = fields.Integer("Toplam Token")
    cost_estimate = fields.Float("Maliyet ($)", digits=(10, 6))
    prompt_used = fields.Text("Kullanılan Prompt")
    raw_response = fields.Text("Ham AI Yanıtı")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Bütçe yalnızca uyarır, üretimi asla durdurmaz / bozmaz
        try:
            # Savepoint: bildirimdeki bir DB hatası üretim işlemini (kaydı) geri almasın
            with self.env.cr.savepoint():
                self._notify_monthly_budget()
        except Exception as e:
            _logger.warning("AI bütçe uyarısı kontrol edilemedi: %s", e)
        return records

    @api.model
    def _month_spend(self):
        """Bu ay (sunucu tarihi) kaydedilen tahmini AI maliyeti ($)."""
        month_start = fields.Date.today().replace(day=1)
        groups = self.sudo()._read_group(
            [('create_date', '>=', fields.Datetime.to_datetime(month_start))],
            aggregates=['cost_estimate:sum'])
        return (groups and groups[0][0]) or 0.0

    @api.model
    def _notify_monthly_budget(self):
        """Aylık harcama ayarlanan tutarı geçince yöneticilere ayda BİR kez bildirim."""
        icp = self.env['ir.config_parameter'].sudo()
        budget = float(icp.get_param('ai_title_description.monthly_budget') or 0.0)
        if budget <= 0:
            return
        month_key = fields.Date.today().strftime('%Y-%m')
        if icp.get_param('ai_title_description.budget_notified_month') == month_key:
            return
        spend = self._month_spend()
        if spend < budget:
            return
        icp.set_param('ai_title_description.budget_notified_month', month_key)
        manager_group = self.env.ref('ai_title_description.group_ai_content_manager', raise_if_not_found=False)
        if not manager_group:
            return
        users = self.env['res.users'].sudo().search([
            ('all_group_ids', 'in', manager_group.id), ('share', '=', False), ('active', '=', True)])
        if not users:
            return
        self.env['mail.thread'].sudo().message_notify(
            partner_ids=users.partner_id.ids,
            subject="AI İçerik: aylık bütçe aşıldı",
            body=(f"<p>AI başlık/açıklama üretiminin bu ayki tahmini maliyeti "
                  f"<strong>${spend:.2f}</strong> oldu; ayarlanan uyarı tutarı ${budget:.2f}.</p>"
                  f"<p>Üretim durdurulmadı, devam ediyor. Ayrıntılar: AI İçerik → İçerik Geçmişi.</p>"),
        )
        _logger.info("AI İçerik aylık bütçe uyarısı gönderildi: $%.2f / $%.2f", spend, budget)

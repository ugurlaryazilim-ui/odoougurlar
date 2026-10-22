# -*- coding: utf-8 -*-
import logging
import time

from odoo import api, fields, models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_GC_BATCH = 5000         # parti başına silinen satır
_GC_TIME_BUDGET = 60     # saniye; dolunca kalan sonraki günkü turda silinir

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
    call_status = fields.Selection([
        ('ok', 'Başarılı'),
        ('error', 'Hata (ücretlendi)'),
        ('timeout', 'Zaman aşımı'),
    ], string="Çağrı Durumu", default='ok',
        help="Hata: Google yanıt verdi ve ücretlendirdi ama içerik kullanılamadı (kesik / boş / bozuk). "
             "Zaman aşımı: istek ücretlenmiş olabilir, token bilinmiyor.")

    # NEDEN: tablo sınırsız büyür (prompt + ham yanıt metinleri); süre ICP'den okunur,
    # 0/geçersiz değer = hiçbir şey silinmez (K6, kullanıcı kararı 2026-10-22).
    # DIKKAT: silme partili ve süre bütçelidir (tek dev DELETE kilit/WAL şişirir). Parti başına
    # commit yalnız cron bağlamında (cron_id) yapılır; dışarıdan çağrıda tek parti silinir.
    @api.model
    def _cron_gc_old_logs(self):
        try:
            days = int(self.env['ir.config_parameter'].sudo().get_param(
                'ai_title_description.log_retention_days', '180'))
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days) if days > 0 else None
        except (ValueError, OverflowError):
            cutoff = None
        if cutoff is None:
            return 0
        deadline = time.monotonic() + _GC_TIME_BUDGET
        in_cron = bool(self.env.context.get('cron_id'))
        total = 0
        last_id = 0
        while True:
            # NEDEN (A5 diğer Ö-2): eski "id IN (SELECT id ... create_date < c LIMIT n)" her partide
            # tabloyu baştan tarıyor, önceki partilerin ölü satırlarını (vacuum'a kadar) tekrar geziyordu.
            # Birincil anahtar sırasıyla kaldığı yerden devam edilir: tur başına tablo en fazla bir kez
            # gezilir, create_date indeksi gerekmez. Genç satırlar atlanır (sıra dışı eski satır da silinir).
            self.env.cr.execute(SQL(
                "SELECT id FROM %(t)s WHERE id > %(last)s AND create_date < %(c)s ORDER BY id LIMIT %(n)s",
                t=SQL.identifier(self._table), c=cutoff, last=last_id, n=_GC_BATCH))
            ids = [row[0] for row in self.env.cr.fetchall()]
            if ids:
                self.env.cr.execute(SQL("DELETE FROM %(t)s WHERE id = ANY(%(ids)s)",
                                        t=SQL.identifier(self._table), ids=ids))
            deleted = len(ids)
            total += deleted
            if deleted < _GC_BATCH or not in_cron:
                break
            last_id = ids[-1]
            self.env['ir.cron']._commit_progress(deleted)
            if time.monotonic() >= deadline:
                break
        self.invalidate_model()
        if total:
            _logger.info("%s log temizliği: %d kayıt silindi", self._name, total)
        return total

    @api.model
    def _log_failed_calls(self, product, provider, model_name, mode, calls):
        """Ücretlenmiş başarısız çağrıları ayrı transaction'da loglar: çağıranın rollback'i
        (kuyruk savepoint'i, sihirbazdaki UserError) harcama kaydını silmesin."""
        if not calls or not product:
            return
        from ..services.cost_calculator import calculate_ai_cost
        try:
            with self.env.registry.cursor() as cr:
                env = self.env(cr=cr)
                env['ai.content.log'].sudo().create([{
                    'product_tmpl_id': product.id,
                    'provider': provider,
                    'model_name': model_name,
                    'mode': mode,
                    'applied': False,
                    'call_status': c.get('status') or 'error',
                    'prompt_tokens': c.get('prompt_tokens', 0),
                    'completion_tokens': c.get('completion_tokens', 0),
                    'token_count': c.get('prompt_tokens', 0) + c.get('completion_tokens', 0),
                    'cost_estimate': calculate_ai_cost(provider, model_name,
                                                       prompt_tokens=c.get('prompt_tokens', 0),
                                                       completion_tokens=c.get('completion_tokens', 0)),
                    'raw_response': c.get('error') or '',
                } for c in calls])
        except Exception as e:
            _logger.warning("Başarısız AI çağrısı loglanamadı: %s", e)

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

from odoo import fields, models, tools

# gemini-2.5-flash liste fiyatı (USD / 1M token); ayarlardan değiştirilebilir.
# Çıkış fiyatına "thinking" token'ları dahildir.
GEMINI_INPUT_PRICE = 0.30
GEMINI_OUTPUT_PRICE = 2.50

USAGE_PROVIDERS = [
    ('gemini', 'Gemini'),
    ('fal', 'fal.ai'),
]
USAGE_STEPS = [
    ('analysis', 'Kıyafet analizi'),
    ('tag_detect', 'Etiket / alarm tespiti'),
    ('button_verify', 'Düğme doğrulama'),
    ('fastener_rewrite', 'Düğme metni düzeltme'),
    ('erase_check', 'Silme izi kontrolü'),
    ('view_construction', 'Arka / yan görünüm yapısı'),
    ('outfit', 'Kombin tutarlılığı'),
    ('quality_check', 'Doğruluk kontrolü'),
    ('mannequin_check', 'Manken bacak kontrolü'),
    ('translate', 'Çeviri'),
    ('analysis_fallback', 'Kıyafet analizi (fal yedeği)'),
    ('deleted_generation', 'Silinen üretim'),
    ('generation', 'Görsel üretimi'),
    ('other', 'Diğer'),
]


class AiStudioUsage(models.Model):
    """Her ücretli AI çağrısı için bir satır. Kayıtlar işlem thread'inden ayrı bir
    transaction'da ham SQL ile yazılır (ai_studio_session._make_usage_recorder)."""
    _name = 'ai.studio.usage'
    _description = 'AI Stüdyo Kullanım Kaydı'
    _order = 'id desc'
    _rec_name = 'step'

    # Oturum / üretim silinse de harcama kaydı kalır; ürün bu yüzden ayrıca saklanır
    session_id = fields.Many2one('ai.studio.session', string='Oturum', ondelete='set null', index=True)
    generation_id = fields.Many2one('ai.studio.generation', string='Üretim', ondelete='set null', index=True)
    product_id = fields.Many2one('product.product', string='Ürün Varyantı', ondelete='set null', index=True)
    user_id = fields.Many2one('res.users', string='Kullanıcı', ondelete='set null')
    provider = fields.Selection(USAGE_PROVIDERS, string='Sağlayıcı', required=True, index=True)
    step = fields.Selection(USAGE_STEPS, string='Adım', required=True)
    model = fields.Char(string='Model')
    input_tokens = fields.Integer(string='Giriş Token')
    output_tokens = fields.Integer(string='Çıkış Token', help='"Thinking" token\'ları dahil')
    image_count = fields.Integer(string='Görsel Sayısı')
    duration = fields.Float(string='Süre (sn)')
    status = fields.Selection([
        ('ok', 'Başarılı'),
        ('timeout', 'Zaman aşımı'),
        ('error', 'Hata'),
    ], string='Durum', default='ok', required=True,
        help='Zaman aşımı / hata: istek gönderildi ama token bilgisi alınamadı; maliyeti bilinmiyor.')
    cost = fields.Float(string='Maliyet (USD)', digits=(16, 6))

    def _keep_deleted_generation_costs(self, generations):
        """Silinen üretimlerin fal maliyetini kullanım kaydına taşır (rapordan kaybolmasın)."""
        self.sudo().create([{
            'session_id': gen.session_id.id,
            'product_id': gen.product_id.id,
            'user_id': gen.session_id.user_id.id,
            'provider': 'fal',
            'step': 'deleted_generation',
            'model': gen.fal_endpoint or gen.provider or '',
            'cost': gen.cost,
        } for gen in generations if gen.cost])


class AiStudioCostReport(models.Model):
    """Ürün başına net maliyet: kullanım kayıtları + üretimlerin fal maliyeti."""
    _name = 'ai.studio.cost.report'
    _description = 'AI Stüdyo Maliyet Analizi'
    _auto = False
    _order = 'date desc'
    _rec_name = 'step'

    date = fields.Datetime(string='Tarih', readonly=True)
    product_id = fields.Many2one('product.product', string='Ürün Varyantı', readonly=True)
    session_id = fields.Many2one('ai.studio.session', string='Oturum', readonly=True)
    user_id = fields.Many2one('res.users', string='Kullanıcı', readonly=True)
    provider = fields.Selection(USAGE_PROVIDERS, string='Sağlayıcı', readonly=True)
    step = fields.Selection(USAGE_STEPS, string='Adım', readonly=True)
    calls = fields.Integer(string='Çağrı Sayısı', readonly=True)
    input_tokens = fields.Integer(string='Giriş Token', readonly=True)
    output_tokens = fields.Integer(string='Çıkış Token', readonly=True)
    cost = fields.Float(string='Maliyet (USD)', digits=(16, 4), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW ai_studio_cost_report AS (
                SELECT u.id * 2 AS id, u.create_date AS date, u.product_id, u.session_id, u.user_id,
                       u.provider, u.step, 1 AS calls, u.input_tokens, u.output_tokens, u.cost
                  FROM ai_studio_usage u
                UNION ALL
                SELECT g.id * 2 + 1, g.create_date, g.product_id, g.session_id, s.user_id,
                       'fal', 'generation', 1, 0, 0, g.cost
                  FROM ai_studio_generation g
                  LEFT JOIN ai_studio_session s ON s.id = g.session_id
                 WHERE COALESCE(g.cost, 0) > 0
            )
        """)

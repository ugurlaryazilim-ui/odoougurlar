from odoo import fields, models

# gemini-2.5-flash liste fiyatı (USD / 1M token); ayarlardan değiştirilebilir.
# Çıkış fiyatına "thinking" token'ları dahildir.
GEMINI_INPUT_PRICE = 0.30
GEMINI_OUTPUT_PRICE = 2.50

USAGE_PROVIDERS = [
    ('gemini', 'Gemini'),
    ('fal', 'fal.ai'),
    ('fashn', 'FASHN'),
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
    ('mannequin', 'Manken üretimi'),
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

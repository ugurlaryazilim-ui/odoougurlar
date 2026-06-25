from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # --- Provider Secimi ---
    ai_studio_default_provider = fields.Selection([
        ('fal', 'fal.ai (Proxy)'),
        ('fashn', 'FASHN (Direkt API)'),
    ], string='AI Sağlayıcı',
        default='fashn',
        config_parameter='ugurlar_ai_studio.default_provider',
        help='Kullanılacak AI sağlayıcıyı seçin',
    )

    # --- API Anahtarlari ---
    ai_studio_fal_api_key = fields.Char(
        string='fal.ai API Anahtarı',
        config_parameter='ugurlar_ai_studio.fal_api_key',
        help='fal.ai dashboard\'tan alınan API key',
    )
    ai_studio_fashn_api_key = fields.Char(
        string='FASHN API Anahtarı',
        config_parameter='ugurlar_ai_studio.fashn_api_key',
        help='FASHN dashboard\'tan alınan API key (fa-XXXX formatında)',
    )
    ai_studio_gemini_api_key = fields.Char(
        string='Gemini API Anahtarı',
        config_parameter='ugurlar_ai_studio.gemini_api_key',
        help='Google Gemini API anahtarı. Boş bırakılırsa fal.ai (Proxy/any-llm) kullanılır.',
    )

    # --- Model Secimi ---
    ai_studio_tryon_model = fields.Selection([
        ('tryon-v1.6', 'Try-On v1.6 (Hızlı, 1 kredi)'),
        ('tryon-max', 'Try-On Max (Premium, 2-5 kredi)'),
    ], string='Try-On Modeli',
        default='tryon-v1.6',
        config_parameter='ugurlar_ai_studio.tryon_model',
        help='FASHN try-on modeli. Max daha kaliteli ama daha pahalı.',
    )

    # --- Uretim Ayarlari ---
    ai_studio_quality_mode = fields.Selection([
        ('performance', 'Hızlı'),
        ('balanced', 'Dengeli'),
        ('quality', 'Kaliteli'),
    ], string='Varsayılan Kalite Modu',
        default='balanced',
        config_parameter='ugurlar_ai_studio.quality_mode',
    )
    ai_studio_num_samples = fields.Integer(
        string='Üretim Sayısı (num_samples)',
        default=2,
        config_parameter='ugurlar_ai_studio.num_samples',
        help='Her istek için kaç görsel üretilsin (1-4). Fazlası maliyet artırır.',
    )
    ai_studio_auto_bg_remove = fields.Boolean(
        string='Otomatik Arka Plan Kaldırma',
        default=True,
        config_parameter='ugurlar_ai_studio.auto_bg_remove',
        help='Fotoğrafları AI\'ya göndermeden önce arka planı otomatik kaldır',
    )

    # --- Operasyonel ---
    ai_studio_max_revisions = fields.Integer(
        string='Maksimum Revizyon Sayısı',
        default=5,
        config_parameter='ugurlar_ai_studio.max_revisions',
        help='Süpervizör onayı gerektirmeden kaç revize yapılabilir',
    )
    ai_studio_garbage_days = fields.Integer(
        string='Çöp Temizleme (gün)',
        default=7,
        config_parameter='ugurlar_ai_studio.garbage_days',
        help='Reddedilen görseller kaç gün sonra temizlensin',
    )
    ai_studio_concurrent_limit = fields.Integer(
        string='Eşzamanlı İstek Limiti',
        default=2,
        config_parameter='ugurlar_ai_studio.concurrent_limit',
        help='Aynı anda kaç AI isteği gönderilebilir',
    )

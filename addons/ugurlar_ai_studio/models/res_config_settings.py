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
        default='tryon-max',
        config_parameter='ugurlar_ai_studio.tryon_model',
        help='FASHN try-on modeli. Max daha kaliteli ama daha pahalı.',
    )

    # --- Uretim Ayarlari ---
    ai_studio_quality_mode = fields.Selection([
        ('performance', 'Hızlı'),
        ('balanced', 'Dengeli'),
        ('quality', 'Kaliteli'),
    ], string='Varsayılan Kalite Modu',
        default='quality',
        config_parameter='ugurlar_ai_studio.quality_mode',
    )
    ai_studio_num_samples = fields.Integer(
        string='Üretim Sayısı (num_samples)',
        default=1,
        config_parameter='ugurlar_ai_studio.num_samples',
        help='Her istek için kaç görsel üretilsin (1-4). Fazlası maliyet artırır.',
    )
    ai_studio_tryon_resolution = fields.Selection([
        ('1K', '1K (Hızlı, düşük maliyet)'),
        ('2K', '2K (Dengeli)'),
        ('4K', '4K (Maksimum kalite)'),
    ], string='Try-On Çözünürlük',
        default='2K',
        config_parameter='ugurlar_ai_studio.tryon_resolution',
        help='tryon-max çözünürlük ayarı. 4K en iyi kalite ama daha pahalı.',
    )
    ai_studio_seedream_image_size = fields.Selection([
        ('hd', '1664×2496 — Yüksek detay ($0.135/görsel)'),
        ('standard', '1248×1872 — Standart ($0.0675/görsel)'),
    ], string='Seedream Çıktı Boyutu',
        default='hd',
        config_parameter='ugurlar_ai_studio.seedream_image_size',
        help='Seedream v5 Pro çıktı boyutu (2:3). Her iki boyut da Trendyol 1200×1800 '
             'gereksinimini karşılar; yüksek detay zoom kalitesi için daha iyidir.',
    )
    ai_studio_monthly_budget = fields.Float(
        string='Aylık AI Bütçesi (USD)',
        default=0.0,
        config_parameter='ugurlar_ai_studio.monthly_budget',
        help='Bu ay kaydedilen toplam AI maliyeti bu tutara ulaşınca yeni işlem başlatılamaz. 0 = limitsiz.',
    )
    ai_studio_candidate_count = fields.Integer(
        string='Ön Görünüm Aday Sayısı',
        default=1,
        config_parameter='ugurlar_ai_studio.candidate_count',
        help='Seedream ön görünüm için kaç alternatif üretsin (1-4). Reviewer en iyisini seçer; '
             'revizyon ihtiyacını azaltır. Her ek aday görsel başına ücretlendirilir.',
    )
    ai_studio_visual_qc = fields.Boolean(
        string='AI Görsel Denetim',
        default=True,
        config_parameter='ugurlar_ai_studio.visual_qc',
        help='Her üretimi Gemini ile elbise altında pantolon, bozuk el, görünür etiket gibi '
             'hatalara karşı denetler; bulunan hatalar kalite skorunu düşürür ve '
             'kalite detayında listelenir (görsel başına ~$0.001).',
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

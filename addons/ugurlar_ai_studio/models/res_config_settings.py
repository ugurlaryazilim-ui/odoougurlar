from odoo import api, fields, models


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

    ai_studio_tryon_model = fields.Selection([
        ('seedream_v4', "Seedream v4 Edit (seed'li — ön görünüm seed'i arka/yan çekimlere aktarılır)"),
        ('seedream_v5_pro', 'Seedream v5 Pro Edit (seed yok)'),
        ('fashn_v16', 'FASHN v1.6 Try-On (fal, özel giydirme modeli — 864×1296, ~$0.075/görsel)'),
    ], string='Giydirme Modeli',
        default='seedream_v4',
        config_parameter='ugurlar_ai_studio.fal_tryon_model',
        help="fal sağlayıcısında giydirme modeli. v4 Edit seed alır ve döndürür: ön görünümün seed'i ve "
             "görseli arka/yan çekimlere birlikte iletilir. v5 Pro Edit seed desteklemez. FASHN v1.6 "
             "ürün görselini tariften yeniden çizmez, piksellerini mankene taşır (istem kullanmaz); "
             "çıktısı daha küçüktür.",
    )
    ai_studio_seedream_image_size = fields.Selection([
        ('hd', '1664×2496 — Yüksek detay (v5 Pro: $0.135, v4: ~$0.03 /görsel)'),
        ('standard', '1248×1872 — Standart (v5 Pro: $0.0675, v4: ~$0.03 /görsel)'),
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
        help='Her üretimi Gemini ile elbise altında pantolon, bozuk el, görünür etiket gibi '
             'hatalara karşı denetler; bulunan hatalar kalite skorunu düşürür ve '
             'kalite detayında listelenir (görsel başına ~$0.001).',
    )
    ai_studio_auto_tag_fix = fields.Boolean(
        string='Görünür Hataları Otomatik Düzelt',
        default=True,
        help='AI görsel denetim sonuçta mağaza/alarm etiketi veya elbise altında pantolon görürse, '
             'görsel tek seferlik Seedream düzenlemesiyle düzeltilir (sadece hatalı görsellerde ~$0.07-0.135).',
    )
    ai_studio_fidelity_retry = fields.Boolean(
        string='Doğruluk Hatasında Yeniden Üret',
        default=True,
        help='Denetim sonuçta üründe olmayan bir detay (fermuar, halka, cep...) ya da kaybolan bir detay '
             'bulursa görsel bir kez yeniden üretilir ve daha doğru olan seçilir '
             '(sadece hatalı görsellerde ~$0.07-0.135).',
    )
    ai_studio_auto_bg_remove = fields.Boolean(
        string='Otomatik Arka Plan Kaldırma',
        default=True,
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

    # Varsayılanı AÇIK olan anahtarlar config_parameter ile tutulamaz: Odoo kutu
    # kapatılınca parametreyi SİLER, kod da eksik parametreyi 'True' okur — kutu
    # kapatılamıyordu. Bu yüzden açıkça 'True' / 'False' yazılıp okunur.
    _AIS_DEFAULT_ON_TOGGLES = {
        'ai_studio_visual_qc': 'ugurlar_ai_studio.visual_qc',
        'ai_studio_auto_tag_fix': 'ugurlar_ai_studio.auto_tag_fix',
        'ai_studio_fidelity_retry': 'ugurlar_ai_studio.fidelity_retry',
        'ai_studio_auto_bg_remove': 'ugurlar_ai_studio.auto_bg_remove',
    }

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env['ir.config_parameter'].sudo()
        for field_name, key in self._AIS_DEFAULT_ON_TOGGLES.items():
            res[field_name] = icp.get_param(key, 'True') == 'True'
        return res

    def set_values(self):
        super().set_values()
        icp = self.env['ir.config_parameter'].sudo()
        for field_name, key in self._AIS_DEFAULT_ON_TOGGLES.items():
            icp.set_param(key, 'True' if self[field_name] else 'False')

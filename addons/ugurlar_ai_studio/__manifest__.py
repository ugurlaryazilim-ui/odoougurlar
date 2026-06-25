{
    'name': 'AI Fotoğraf Stüdyosu',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Products',
    'summary': 'AI destekli ürün fotoğraf stüdyosu - Barkod tara, fotoğraf çek, AI ile manken üzerine giydir',
    'description': """
        Uğurlar AI Fotoğraf Stüdyosu
        ==============================

        Bu modül, e-ticaret ürün fotoğrafçılığı sürecini AI ile otomatikleştirir:

        * **Barkod Tarama**: Ürün varyantını barkod, SKU veya isim ile seç
        * **Fotoğraf Çekimi**: Mobil kamera ile ön, arka ve detay fotoğrafları çek
        * **AI Giydirme**: fal.ai FASHN ile ürünü manken üzerine giydir
        * **Onay/Red**: Yan yana karşılaştırma ile onayla veya revizeye gönder
        * **Otomatik Kayıt**: Onaylanan görselleri ürün kartına aktar

        Desteklenen AI Servisleri:
        - fal.ai (FASHN v1.6, Kolors, FLUX)
        - Provider-agnostic mimari (ileride genişletilebilir)
    """,
    'author': 'Uğurlar Yazılım',
    'website': 'https://ugurlar.com',
    'depends': ['base_setup', 'product', 'mail', 'ugurlar_images', 'ugurlar_barcode'],
    'data': [
        'security/ai_studio_security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/ai_studio_reject_reasons.xml',
        'data/ai_studio_prompt_locks.xml',
        'data/cron.xml',
        'data/ai_studio_model_library_seeds.xml',
        'views/ai_studio_session_views.xml',
        'views/ai_studio_generation_views.xml',
        'views/ai_studio_preset_views.xml',
        'views/ai_studio_prompt_views.xml',
        'views/ai_studio_reject_views.xml',
        'views/ai_studio_settings_views.xml',
        'views/ai_studio_templates.xml',
        'views/ai_studio_library_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ugurlar_ai_studio/static/src/css/studio.css',
            'ugurlar_ai_studio/static/src/css/camera.css',
            'ugurlar_ai_studio/static/src/css/comparison.css',
            'ugurlar_ai_studio/static/src/css/approval.css',
            'ugurlar_ai_studio/static/src/js/ai_studio_action.js',
            'ugurlar_ai_studio/static/src/js/screens/scan_screen.js',
            'ugurlar_ai_studio/static/src/js/screens/capture_screen.js',
            'ugurlar_ai_studio/static/src/js/screens/settings_screen.js',
            'ugurlar_ai_studio/static/src/js/screens/processing_screen.js',
            'ugurlar_ai_studio/static/src/js/screens/review_screen.js',
            'ugurlar_ai_studio/static/src/js/screens/batch_review.js',
            'ugurlar_ai_studio/static/src/js/screens/history_screen.js',
            'ugurlar_ai_studio/static/src/js/components/camera_capture.js',
            'ugurlar_ai_studio/static/src/js/components/image_comparison.js',
            'ugurlar_ai_studio/static/src/xml/scan_screen.xml',
            'ugurlar_ai_studio/static/src/xml/capture_screen.xml',
            'ugurlar_ai_studio/static/src/xml/settings_screen.xml',
            'ugurlar_ai_studio/static/src/xml/processing_screen.xml',
            'ugurlar_ai_studio/static/src/xml/review_screen.xml',
            'ugurlar_ai_studio/static/src/xml/batch_review.xml',
            'ugurlar_ai_studio/static/src/xml/history_screen.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

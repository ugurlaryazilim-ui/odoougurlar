# -*- coding: utf-8 -*-
{
    'name': 'Sosyal Medya & Yapay Zeka Yöneticisi',
    'version': '19.0.1.0.1',
    'summary': 'Sosyal Medya (WhatsApp, Instagram, Facebook, TikTok, YouTube) ve Yapay Zeka Desteği Yönetimi',
    'sequence': 10,
    'description': """
Sosyal Medya & Yapay Zeka Yöneticisi
====================================
Kapsamlı omnichannel gelen kutusu ve sosyal medya gönderi planlama aracı.
Özellikler:
- OWL tabanlı Tekil Gelen Kutusu (WhatsApp, FB, IG, YouTube, TikTok)
- Otomatik yanıtlar ve takvim randevuları için Yapay Zeka (OpenAI, Gemini, Ollama) entegrasyonu
- Gönderi Planlama (Post Scheduling)
- Ücretsiz WhatsApp mesajlaşması için WAHA / Evolution API entegrasyonu
    """,
    'category': 'Marketing/Social Marketing',
    'author': 'Antigravity',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'calendar', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/social_media_menus.xml',
        'views/res_config_settings_views.xml',
        'views/social_media_account_views.xml',
        'views/social_media_ai_rule_views.xml',
        'views/social_media_post_views.xml',
        'views/social_media_conversation_views.xml',
        'views/social_media_inbox_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'social_media_ai_manager/static/src/css/social_inbox.css',
            'social_media_ai_manager/static/src/components/**/*.js',
            'social_media_ai_manager/static/src/components/**/*.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}

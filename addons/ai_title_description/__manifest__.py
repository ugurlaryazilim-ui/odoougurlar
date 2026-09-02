# -*- coding: utf-8 -*-
{
    'name': 'AI Ürün Başlık & Açıklama Üretici',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Products',
    'summary': 'Gemini AI + Google SEO ile Trendyol/HB uyumlu ürün başlığı ve açıklama üretimi',
    'author': 'Uğurlar Yazılım',
    'website': 'https://ugurlar.com',
    'depends': ['product', 'base_setup', 'web'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ai_title_security.xml',
        'security/ir.model.access.csv',
        'data/prompt_templates.xml',
        'data/cron.xml',
        'data/server_actions.xml',
        'views/ai_content_log_views.xml',
        'views/ai_content_queue_views.xml',
        'views/ai_content_wizard_views.xml',
        'views/product_template_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_title_description/static/src/js/ai_generate_button.js',
            'ai_title_description/static/src/xml/ai_generate_button.xml',
            'ai_title_description/static/src/css/ai_title.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

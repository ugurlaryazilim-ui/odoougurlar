# -*- coding: utf-8 -*-
{
    'name': 'Ads Manager',
    'version': '19.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Meta & Google Ads Yönetimi, Analitik ve AI Optimizasyon',
    'description': """
        Meta (Facebook/Instagram) ve Google Ads entegrasyonu.
        Kampanya yönetimi, performans takibi, otomatik kural motoru ve AI destekli optimizasyon önerileri.
    """,
    'author': 'Uğurlar Yazılım',
    'website': 'https://www.ugurlar.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'web'],
    'data': [
        'security/ads_manager_security.xml',
        'security/ir.model.access.csv',
        'data/ads_rule_data.xml',
        'data/ir_cron_data.xml',
        'data/mail_template_data.xml',
        'reports/ads_report_actions.xml',
        'reports/ads_report_templates.xml',
        'views/ads_account_views.xml',
        'views/ads_campaign_views.xml',
        'views/ads_adset_views.xml',
        'views/ads_ad_views.xml',
        'views/ads_metric_views.xml',
        'views/ads_recommendation_views.xml',
        'views/ads_rule_views.xml',
        'views/ads_ai_provider_views.xml',
        'views/ads_wizard_views.xml',
        'views/ads_sync_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/ads_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ads_manager/static/src/dashboard/**/*',
            'ads_manager/static/src/components/**/*',
            'ads_manager/static/src/scss/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}

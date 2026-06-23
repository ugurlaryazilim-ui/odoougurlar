from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_studio_fal_api_key = fields.Char(
        string='fal.ai API Anahtarı',
        config_parameter='ugurlar_ai_studio.fal_api_key',
        help='fal.ai dashboard\'tan alınan API key',
    )
    ai_studio_default_provider = fields.Selection([
        ('fal', 'fal.ai'),
        ('replicate', 'Replicate'),
        ('custom', 'Özel'),
    ], string='Varsayılan AI Sağlayıcı',
        default='fal',
        config_parameter='ugurlar_ai_studio.default_provider',
    )
    ai_studio_default_endpoint = fields.Char(
        string='Varsayılan Endpoint',
        default='fal-ai/fashn/tryon/v1.6',
        config_parameter='ugurlar_ai_studio.default_endpoint',
        help='fal.ai model endpoint ID',
    )
    ai_studio_quality_mode = fields.Selection([
        ('performance', 'Hızlı'),
        ('balanced', 'Dengeli'),
        ('quality', 'Kaliteli'),
    ], string='Varsayılan Kalite Modu',
        default='balanced',
        config_parameter='ugurlar_ai_studio.quality_mode',
    )
    ai_studio_auto_bg_remove = fields.Boolean(
        string='Otomatik Arka Plan Kaldırma',
        default=True,
        config_parameter='ugurlar_ai_studio.auto_bg_remove',
        help='Fotoğrafları AI\'ya göndermeden önce arka planı otomatik kaldır',
    )
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

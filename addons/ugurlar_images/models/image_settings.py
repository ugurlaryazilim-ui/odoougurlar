import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Resim modülü ayarları — Odoo Ayarlar menüsünden yönetilir."""
    _inherit = 'res.config.settings'

    # -----------------------------------------------------------------
    #  Görsel Tarama Ayarları
    # -----------------------------------------------------------------
    image_separator = fields.Selection([
        ('_', 'Alt Tire ( _ )'),
        ('-', 'Tire ( - )'),
        ('.', 'Nokta ( . )'),
    ],
        string='Görsel Ayracı',
        config_parameter='ugurlar_images.image_separator',
        default='_',
        help='Ürün barkodu ile resim sırasını ayıran karakter.\n'
             'Örnek: 8691234_1.jpg  →  ayraç: _',
    )
    main_image_index = fields.Selection([
        ('0', '0 (sıfırdan başla)'),
        ('1', '1 (birden başla)'),
    ],
        string='Ana Resim Sırası',
        config_parameter='ugurlar_images.main_image_index',
        default='1',
        help='Dosya adındaki hangi numara ana ürün görseli (vitrin) olsun?\n'
             'Örn: "1" seçerseniz barkod_1.jpg ana resim olur.',
    )
    image_match_field = fields.Selection([
        ('barcode', 'Barkod (product.product)'),
        ('default_code', 'İç Referans (product.product)'),
    ],
        string='Eşleştirme Alanı',
        config_parameter='ugurlar_images.image_match_field',
        default='barcode',
        help='Dosya adındaki kod hangi ürün alanıyla eşleştirilsin?',
    )
    image_overwrite = fields.Boolean(
        string='Mevcut Görsellerin Üzerine Yaz',
        config_parameter='ugurlar_images.image_overwrite',
        default=True,
        help='Aktifse, ürünün mevcut görseli yeni gelen ile değiştirilir.\n'
             'Pasifse, görsel zaten varsa atlanır.',
    )

    # -----------------------------------------------------------------
    #  Sync Agent (Windows Arka Plan) Ayarları
    # -----------------------------------------------------------------
    sync_agent_enabled = fields.Boolean(
        string='Sync Agent Aktif',
        config_parameter='ugurlar_images.sync_agent_enabled',
        default=False,
        help='Windows Sync Agent bağlantısını aktifleştirir.',
    )
    sync_agent_api_key = fields.Char(
        string='API Anahtarı',
        config_parameter='ugurlar_images.sync_agent_api_key',
        groups='base.group_system',
        help='Windows Sync Agent uygulamasının Odoo\'ya bağlanmak için kullanacağı API anahtarı.',
    )

    def action_generate_api_key(self):
        """Sync Agent için rastgele bir API anahtarı üretir."""
        import secrets
        key = secrets.token_urlsafe(32)
        self.env['ir.config_parameter'].sudo().set_param(
            'ugurlar_images.sync_agent_api_key', key
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'API Anahtarı Oluşturuldu',
                'message': f'Yeni anahtar: {key}',
                'type': 'success',
                'sticky': True,
            },
        }

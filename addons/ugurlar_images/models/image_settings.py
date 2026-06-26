import logging
import secrets

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Selection key → gerçek karakter eşleştirmesi
SEPARATOR_MAP = {
    'underscore': '_',
    'dash': '-',
    'dot': '.',
}


class ResConfigSettings(models.TransientModel):
    """Resim modülü ayarları — Odoo Ayarlar menüsünden yönetilir."""
    _inherit = 'res.config.settings'

    # -----------------------------------------------------------------
    #  Görsel Tarama Ayarları
    # -----------------------------------------------------------------
    image_separator = fields.Selection([
        ('underscore', 'Alt Tire ( _ )'),
        ('dash', 'Tire ( - )'),
        ('dot', 'Nokta ( . )'),
    ],
        string='Görsel Ayracı',
        config_parameter='ugurlar_images.image_separator',
        default='underscore',
        help='Ürün barkodu ile resim sırasını ayıran karakter.\n'
             'Örnek: 8691234_1.jpg  →  ayraç: Alt Tire',
    )
    main_image_index = fields.Selection([
        ('idx0', '0 (sıfırdan başla)'),
        ('idx1', '1 (birden başla)'),
    ],
        string='Ana Resim Sırası',
        config_parameter='ugurlar_images.main_image_index',
        default='idx1',
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
    image_watch_folder = fields.Char(
        string='Görsel Klasör Yolu',
        config_parameter='ugurlar_images.image_watch_folder',
        default=r'\\nbsrv02\Online_Data\Pazaryerleri\entegre ürün görselleri',
        help='Sync Agent\'ın izleyeceği klasör yolu.\n'
             r'Ağ paylaşımı için UNC yol kullanın: \\sunucu\paylasim\klasor',
    )

    def action_generate_api_key(self):
        """Sync Agent için rastgele bir API anahtarı üretir."""
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

    def action_fix_existing_images(self):
        """Mevcut hatalı (product_tmpl_id'si boş) product.image kayıtlarını düzeltir."""
        images = self.env['product.image'].sudo().search([
            ('product_tmpl_id', '=', False),
            ('product_variant_id', '!=', False)
        ])
        
        fixed_count = 0
        for img in images:
            if img.product_variant_id and img.product_variant_id.product_tmpl_id:
                img.write({
                    'product_tmpl_id': img.product_variant_id.product_tmpl_id.id
                })
                fixed_count += 1
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Düzeltme Tamamlandı',
                'message': f'Toplam {fixed_count} adet ek görsel kaydına ürün şablon bilgisi başarıyla eklendi.',
                'type': 'success',
                'sticky': True,
            },
        }


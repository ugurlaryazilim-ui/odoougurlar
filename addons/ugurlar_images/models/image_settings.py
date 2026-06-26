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

    # -----------------------------------------------------------------
    #  Veri Düzeltme — image.fix.job modelinden okunan alanlar
    # -----------------------------------------------------------------
    fix_images_status = fields.Selection([
        ('idle', 'Beklemede'),
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata Oluştu'),
    ],
        string='Düzeltme Durumu',
        config_parameter='ugurlar_images.fix_images_status',
        default='idle',
    )
    fix_images_progress = fields.Char(
        string='İlerleme',
        config_parameter='ugurlar_images.fix_images_progress',
        default='0 / 0',
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

    # -----------------------------------------------------------------
    #  Görsel Düzeltme Aksiyonları — image.fix.job modeline yönlendirir
    # -----------------------------------------------------------------
    def action_fix_existing_images(self):
        """
        Mevcut hatalı product.image kayıtlarını düzeltmek için
        image.fix.job modeli üzerinde yeni bir iş oluşturur ve
        zamanlanmış görevi (cron) aktif eder.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        status = ICP.get_param('ugurlar_images.fix_images_status', 'idle')

        if status == 'running':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'İşlem Devam Ediyor',
                    'message': 'Görsel düzeltme işlemi zaten arka planda çalışmaktadır.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # image.fix.job üzerinde yeni iş oluştur ve cron'u aktif et
        self.env['image.fix.job'].sudo().start_fix()

        # Settings UI'da durum göstergelerini güncelle
        ICP.set_param('ugurlar_images.fix_images_status', 'running')
        ICP.set_param('ugurlar_images.fix_images_progress',
                       'Zamanlanmış görev kuyruğuna eklendi, arka planda başlıyor...')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'İşlem Başlatıldı',
                'message': ('Düzeltme işlemi arka plan Zamanlanmış Görev (Cron) kuyruğuna eklendi. '
                            'İlerlemeyi bu sayfayı yenileyerek takip edebilirsiniz.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reset_fix_status(self):
        """Sıkışmış veya durmuş düzeltme işleminin durumunu sıfırlar ve zamanlanmış görevi pasif yapar."""
        # image.fix.job üzerinde sıfırla
        self.env['image.fix.job'].sudo().reset_fix()

        # Settings UI'da durum göstergelerini sıfırla
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ugurlar_images.fix_images_status', 'idle')
        ICP.set_param('ugurlar_images.fix_images_progress', 'Sıfırlandı, yeniden başlatılabilir.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Durum Sıfırlandı',
                'message': 'Düzeltme durumu ve arka plan görevi sıfırlandı. Yeniden başlatabilirsiniz.',
                'type': 'success',
                'sticky': False,
            },
        }

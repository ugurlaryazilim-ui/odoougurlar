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
    #  Veri Düzeltme & Teşhis İlerleme Durumu
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

    @api.model
    def _cron_fix_existing_images(self):
        """Cron job to process image fixes in safe chunks, running up to 45 seconds per invocation."""
        import time
        start_time = time.time()
        
        ICP = self.env['ir.config_parameter'].sudo()
        status = ICP.get_param('ugurlar_images.fix_images_status', 'idle')
        
        if status != 'running':
            return
            
        # 1. Şablon ID'si boş olanları düzelt (Tek seferde en fazla 2000 adet)
        images_to_link = self.env['product.image'].sudo().search([
            ('product_tmpl_id', '=', False),
            ('product_variant_id', '!=', False)
        ], limit=2000)
        
        linked_count = 0
        if images_to_link:
            for img in images_to_link:
                if img.product_variant_id and img.product_variant_id.product_tmpl_id:
                    img.write({
                        'product_tmpl_id': img.product_variant_id.product_tmpl_id.id
                    })
                    linked_count += 1
            self.env.cr.commit()
            self.env.invalidate_all()
            
        # 2. Resim boyutları boş olanları 100'erli paketler halinde döngüde işle
        # Her döngüde geçen süreyi kontrol et, 45 saniyeyi geçerse dur ki cron timeout'a girmesin!
        processed = 0
        batch_size = 100
        
        # Toplam kalan sayısını al
        total_remaining = self.env['product.image'].sudo().search_count([
            ('image_1920', '!=', False),
            ('image_128', '=', False)
        ])
        
        if total_remaining == 0:
            # İşlenecek resim kalmadı!
            ICP.set_param('ugurlar_images.fix_images_status', 'done')
            ICP.set_param('ugurlar_images.fix_images_progress', 'Tamamlandı! Tüm görseller başarıyla boyutlandırıldı.')
            cron = self.env.ref('ugurlar_images.ir_cron_fix_existing_images', raise_if_not_found=False)
            if cron:
                cron.write({'active': False})
            self.env.cr.commit()
            return
            
        while True:
            # Geçen süreyi kontrol et (max 45 saniye)
            if time.time() - start_time > 45:
                _logger.info("Cron zaman sınırı (45s) aşıldı. Mevcut tur sonlandırılıyor. Bir sonraki cron turunda devam edecek.")
                break
                
            batch = self.env['product.image'].sudo().search([
                ('image_1920', '!=', False),
                ('image_128', '=', False)
            ], limit=batch_size)
            
            if not batch:
                break
                
            try:
                self.env.add_to_compute(self.env['product.image']._fields['image_128'], batch)
                self.env.add_to_compute(self.env['product.image']._fields['image_256'], batch)
                self.env.add_to_compute(self.env['product.image']._fields['image_512'], batch)
                self.env.add_to_compute(self.env['product.image']._fields['image_1024'], batch)
                batch._recompute_recordset()
            except Exception as batch_error:
                _logger.error("Cron görsel boyutlandırma batch hatası: %s", batch_error)
                
            processed += len(batch)
            self.env.cr.commit()
            self.env.invalidate_all()
            
        # Kalanı sorgula
        new_total_remaining = self.env['product.image'].sudo().search_count([
            ('image_1920', '!=', False),
            ('image_128', '=', False)
        ])
        
        if new_total_remaining == 0:
            ICP.set_param('ugurlar_images.fix_images_status', 'done')
            ICP.set_param('ugurlar_images.fix_images_progress', f'Tamamlandı! Toplam {processed} görsel boyutlandırıldı ve {linked_count} şablon bağlantısı onarıldı.')
            cron = self.env.ref('ugurlar_images.ir_cron_fix_existing_images', raise_if_not_found=False)
            if cron:
                cron.write({'active': False})
        else:
            ICP.set_param(
                'ugurlar_images.fix_images_progress',
                f'Arka planda devam ediyor... Kalan Görsel Sayısı: {new_total_remaining} ({linked_count} şablon bağlantısı onarıldı)'
            )
            
        self.env.cr.commit()

    def action_fix_existing_images(self):
        """Mevcut hatalı product.image kayıtlarını düzeltir ve boş thumbnail resimlerini cron görevini aktif ederek onarır."""
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
            
        ICP.set_param('ugurlar_images.fix_images_status', 'running')
        ICP.set_param('ugurlar_images.fix_images_progress', 'Zamanlanmış görev kuyruğuna ekleniyor...')
        
        # Cron görevini bul ve tetikle
        cron = self.env.ref('ugurlar_images.ir_cron_fix_existing_images', raise_if_not_found=False)
        if cron:
            cron.write({
                'active': True,
                'nextcall': fields.Datetime.now()
            })
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'İşlem Başlatıldı',
                'message': 'Düzeltme işlemi arka plan Zamanlanmış Görev (Cron) kuyruğuna eklendi. İlerlemeyi bu sayfayı yenileyerek takip edebilirsiniz.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reset_fix_status(self):
        """Sıkışmış veya durmuş düzeltme işleminin durumunu sıfırlar ve zamanlanmış görevi pasif yapar."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ugurlar_images.fix_images_status', 'idle')
        ICP.set_param('ugurlar_images.fix_images_progress', 'Sıfırlandı, yeniden başlatılabilir.')
        
        # Cron görevini pasifleştir
        cron = self.env.ref('ugurlar_images.ir_cron_fix_existing_images', raise_if_not_found=False)
        if cron:
            cron.write({'active': False})
            
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


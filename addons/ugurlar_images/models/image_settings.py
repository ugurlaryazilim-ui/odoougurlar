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

    def _run_background_fix(self, db_name, db_registry):
        """Arka planda çalışacak onarım ve boyutlandırma işlemi."""
        with db_registry.cursor() as cr:
            env = api.Environment(cr, 1, {}) # uid=1 (sistem yöneticisi)
            ICP = env['ir.config_parameter'].sudo()
            try:
                # 1. Şablon ID'si boş olanları düzelt
                images_to_link = env['product.image'].sudo().search([
                    ('product_tmpl_id', '=', False),
                    ('product_variant_id', '!=', False)
                ])
                
                linked_count = 0
                for img in images_to_link:
                    if img.product_variant_id and img.product_variant_id.product_tmpl_id:
                        img.write({
                            'product_tmpl_id': img.product_variant_id.product_tmpl_id.id
                        })
                        linked_count += 1
                
                cr.commit()
                
                # 2. Resim boyutları boş olanları batch'ler halinde yeniden hesaplat
                images_to_recompute = env['product.image'].sudo().search([
                    ('image_1920', '!=', False),
                    ('image_128', '=', False)
                ])
                
                total_count = len(images_to_recompute)
                ICP.set_param('ugurlar_images.fix_images_progress', f'0 / {total_count}')
                cr.commit()
                
                processed = 0
                batch_size = 500
                if total_count > 0:
                    for i in range(0, total_count, batch_size):
                        batch = images_to_recompute[i:i+batch_size]
                        env.add_to_compute(env['product.image']._fields['image_128'], batch)
                        env.add_to_compute(env['product.image']._fields['image_256'], batch)
                        env.add_to_compute(env['product.image']._fields['image_512'], batch)
                        env.add_to_compute(env['product.image']._fields['image_1024'], batch)
                        batch._recompute_recordset()
                        
                        processed += len(batch)
                        ICP.set_param('ugurlar_images.fix_images_progress', f'{processed} / {total_count} processed ({linked_count} template links fixed)')
                        cr.commit() # Veritabanına yaz ve RAM'i temizle
                
                ICP.set_param('ugurlar_images.fix_images_status', 'done')
                ICP.set_param('ugurlar_images.fix_images_progress', f'Tamamlandı! Toplam {processed} görsel boyutlandırıldı ve {linked_count} şablon bağlantısı onarıldı.')
                cr.commit()
                
            except Exception as e:
                _logger.error("Arka plan görsel düzeltme hatası: %s", e)
                ICP.set_param('ugurlar_images.fix_images_status', 'error')
                ICP.set_param('ugurlar_images.fix_images_progress', f'Hata: {str(e)}')
                cr.commit()

    def action_fix_existing_images(self):
        """Mevcut hatalı product.image kayıtlarını düzeltir ve boş thumbnail resimlerini asenkron thread olarak onarır."""
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
        ICP.set_param('ugurlar_images.fix_images_progress', 'Hazırlanıyor...')
        
        # Thread başlat
        db_name = self.env.cr.dbname
        db_registry = self.env.registry
        import threading
        thread = threading.Thread(target=self._run_background_fix, args=(db_name, db_registry))
        thread.daemon = True
        thread.start()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'İşlem Başlatıldı',
                'message': 'Düzeltme işlemi arka planda başlatıldı. İlerlemeyi bu sayfayı yenileyerek takip edebilirsiniz.',
                'type': 'success',
                'sticky': False,
            },
        }


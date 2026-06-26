import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ImageFixJob(models.Model):
    """
    Görsel düzeltme işlemlerini yöneten kalıcı model.

    Odoo 19 best practices:
      - Cron metodu kalıcı model üzerinde (TransientModel değil)
      - _commit_progress() ile resmi ilerleme raporlama
      - SQL bulk update ile şablon bağlantısı düzeltme
      - Cursor-based pagination (last_processed_id)
      - Savepoint ile per-record hata izolasyonu
    """
    _name = 'image.fix.job'
    _description = 'Görsel Düzeltme İşi'
    _order = 'id desc'

    state = fields.Selection([
        ('idle', 'Beklemede'),
        ('running', 'Çalışıyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], string='Durum', default='idle', required=True)
    progress_text = fields.Char(
        string='İlerleme',
        default='Henüz başlatılmadı',
    )
    last_processed_id = fields.Integer(
        string='Son İşlenen ID',
        default=0,
        help='Cursor-based pagination: cron kesilse bile kaldığı yerden devam eder.',
    )
    total_fixed_links = fields.Integer(
        string='Düzeltilen Bağlantı',
        default=0,
    )
    total_fixed_thumbs = fields.Integer(
        string='Düzeltilen Thumbnail',
        default=0,
    )
    links_done = fields.Boolean(
        string='Bağlantılar Tamamlandı',
        default=False,
    )
    error_log = fields.Text(
        string='Hata Günlüğü',
    )

    def write(self, vals):
        """
        Her durum değişikliğinde ir.config_parameter'ı da güncelle.
        Böylece res.config.settings üzerindeki alanlar her zaman güncel kalır.
        """
        result = super().write(vals)
        ICP = self.env['ir.config_parameter'].sudo()
        if 'state' in vals:
            ICP.set_param('ugurlar_images.fix_images_status', vals['state'])
        if 'progress_text' in vals:
            ICP.set_param('ugurlar_images.fix_images_progress', vals['progress_text'] or '')
        return result

    # ------------------------------------------------------------------
    #  Cron Metodu — Odoo 19 Resmi Pattern
    # ------------------------------------------------------------------
    @api.model
    def _cron_fix_images(self):
        """
        Zamanlanmış görev: görsel düzeltme işlemini batch halinde çalıştırır.

        Odoo 19 API'leri:
          • _commit_progress(n, remaining=r) → commit + ilerleme raporla
          • try_lock_for_update() → çakışma önleme (opsiyonel)
          • Savepoint → per-record hata izolasyonu
        """
        job = self.search([('state', '=', 'running')], limit=1)
        if not job:
            _logger.info("Görsel düzeltme: Aktif iş bulunamadı, cron durduruluyor.")
            return

        try:
            # ── Aşama 1: SQL ile bulk şablon bağlantısı düzeltme ──
            if not job.links_done:
                job._fix_template_links()

            # ── Aşama 2: Cursor-based thumbnail boyutlandırma ──
            job._fix_thumbnails()

        except Exception as e:
            _logger.exception("Görsel düzeltme cron genel hatası: %s", e)
            # Hatayı logla ama state'i 'running' bırak —
            # bir sonraki cron turunda kaldığı yerden devam eder
            try:
                job.write({
                    'progress_text': f'Geçici hata (yeniden denenecek): {str(e)[:200]}',
                    'error_log': (job.error_log or '') + f'\n[HATA] {e}',
                })
            except Exception:
                pass  # Write da başarısız olursa sessizce geç
            try:
                self.env['ir.cron']._commit_progress(0)
            except Exception:
                pass

    def _fix_template_links(self):
        """
        Aşama 1: product_tmpl_id boş olan product.image kayıtlarını
        tek SQL sorgusuyla toplu düzelt.

        Performans: 10.000+ kayıt < 1 saniye (ORM döngüsü dakikalar sürer).
        """
        self.ensure_one()
        _logger.info("Görsel düzeltme Aşama 1: Şablon bağlantıları SQL ile düzeltiliyor...")

        # Raw SQL öncesi ORM cache'i DB'ye yaz
        self.env['product.image'].flush_model(['product_tmpl_id', 'product_variant_id'])

        self.env.cr.execute("""
            UPDATE product_image pi
               SET product_tmpl_id = pp.product_tmpl_id
              FROM product_product pp
             WHERE pi.product_variant_id = pp.id
               AND pi.product_tmpl_id IS NULL
               AND pi.product_variant_id IS NOT NULL
        """)
        fixed_count = self.env.cr.rowcount

        # Raw SQL sonrası ORM cache'i geçersiz kıl
        self.env['product.image'].invalidate_model(['product_tmpl_id'])

        self.write({
            'links_done': True,
            'total_fixed_links': fixed_count,
            'progress_text': f'{fixed_count} şablon bağlantısı onarıldı. Thumbnail işlemi başlıyor...',
        })
        self.env['ir.cron']._commit_progress(fixed_count)
        _logger.info("Görsel düzeltme Aşama 1: %d şablon bağlantısı onarıldı.", fixed_count)

    def _fix_thumbnails(self):
        """
        Aşama 2: image_128 boş olan görsellerin thumbnail'lerini
        50'şerlik batch'ler halinde oluştur.

        • Cursor-based pagination (last_processed_id)
        • Savepoint ile per-record hata izolasyonu
        • _commit_progress() ile her batch sonrası commit
        """
        self.ensure_one()
        BATCH_SIZE = 50
        thumb_fields = ['image_128', 'image_256', 'image_512', 'image_1024']
        ProductImage = self.env['product.image'].sudo()

        domain = [
            ('id', '>', self.last_processed_id),
            ('image_1920', '!=', False),
            ('image_128', '=', False),
        ]
        batch = ProductImage.search(domain, limit=BATCH_SIZE, order='id ASC')

        if not batch:
            # ── Tüm işlem tamamlandı ──
            self.write({
                'state': 'done',
                'progress_text': (
                    f'Tamamlandı! {self.total_fixed_links} bağlantı + '
                    f'{self.total_fixed_thumbs} thumbnail onarıldı.'
                ),
            })
            cron = self.env.ref(
                'ugurlar_images.ir_cron_fix_existing_images',
                raise_if_not_found=False,
            )
            if cron:
                # Odoo 19: cron kendi kendini ORM ile deaktif edemez,
                # raw SQL ile bypass ediyoruz
                self.env.cr.execute(
                    "UPDATE ir_cron SET active = FALSE WHERE id = %s",
                    (cron.id,)
                )
            self.env['ir.cron']._commit_progress(0, remaining=0)
            _logger.info("Görsel düzeltme tamamlandı! Toplam: %d bağlantı, %d thumbnail",
                         self.total_fixed_links, self.total_fixed_thumbs)
            return

        processed = 0
        errors = []

        for img in batch:
            self.env.cr.execute("SAVEPOINT img_thumb")
            try:
                for fname in thumb_fields:
                    self.env.add_to_compute(
                        ProductImage._fields[fname], img,
                    )
                img._recompute_recordset()
                self.env.cr.execute("RELEASE SAVEPOINT img_thumb")
                processed += 1
            except Exception as e:
                self.env.cr.execute("ROLLBACK TO SAVEPOINT img_thumb")
                errors.append(f'id={img.id}: {e}')
                _logger.warning("Thumbnail hatası id=%s: %s", img.id, e)

        new_last_id = batch[-1].id
        remaining = ProductImage.search_count([
            ('id', '>', new_last_id),
            ('image_1920', '!=', False),
            ('image_128', '=', False),
        ])

        error_text = ''
        if errors:
            error_text = '\n'.join(errors[-10:])  # Son 10 hatayı tut

        self.write({
            'last_processed_id': new_last_id,
            'total_fixed_thumbs': self.total_fixed_thumbs + processed,
            'progress_text': (
                f'{self.total_fixed_thumbs + processed} thumbnail tamamlandı. '
                f'Kalan: ~{remaining}'
            ),
            'error_log': (self.error_log or '') + ('\n' + error_text if error_text else ''),
        })

        # Odoo 19 resmi commit + ilerleme raporlama
        should_continue = self.env['ir.cron']._commit_progress(
            processed, remaining=remaining,
        )

        _logger.info(
            "Görsel düzeltme batch: %d işlendi, kalan: ~%d, devam: %s",
            processed, remaining, bool(should_continue),
        )

    # ------------------------------------------------------------------
    #  Yardımcı: Yeni iş oluştur ve cron'u aktif et
    # ------------------------------------------------------------------
    @api.model
    def start_fix(self):
        """Ayarlar sayfasından çağrılan yardımcı. Yeni job oluşturur ve cron'u tetikler."""
        # Çalışan bir iş varsa uyar
        running = self.search([('state', '=', 'running')], limit=1)
        if running:
            return running

        job = self.create({
            'state': 'running',
            'progress_text': 'Zamanlanmış görev kuyruğuna ekleniyor...',
            'last_processed_id': 0,
            'total_fixed_links': 0,
            'total_fixed_thumbs': 0,
            'links_done': False,
            'error_log': '',
        })

        cron = self.env.ref(
            'ugurlar_images.ir_cron_fix_existing_images',
            raise_if_not_found=False,
        )
        if cron:
            cron.write({
                'active': True,
                'nextcall': fields.Datetime.now(),
            })

        return job

    @api.model
    def reset_fix(self):
        """Sıkışmış veya hatalı işi sıfırla ve cron'u durdur."""
        jobs = self.search([('state', 'in', ('running', 'error'))])
        if jobs:
            jobs.write({
                'state': 'idle',
                'progress_text': 'Sıfırlandı, yeniden başlatılabilir.',
            })

        cron = self.env.ref(
            'ugurlar_images.ir_cron_fix_existing_images',
            raise_if_not_found=False,
        )
        if cron:
            cron.active = False

    @api.model
    def get_current_status(self):
        """Ayarlar sayfası için güncel durum bilgisini döndür."""
        job = self.search([], limit=1, order='id desc')
        if job:
            return {
                'state': job.state,
                'progress': job.progress_text or '',
            }
        return {
            'state': 'idle',
            'progress': 'Henüz işlem yapılmadı.',
        }

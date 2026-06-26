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
    #  Cron Metodu
    # ------------------------------------------------------------------
    @api.model
    def _cron_fix_images(self):
        """Zamanlanmış görev: görsel düzeltme (ORM read + image_process)."""
        job = self.search([('state', '=', 'running')], limit=1)
        if not job:
            return

        try:
            if not job.links_done:
                job._fix_template_links()

            job._fix_thumbnails_safe()

        except Exception as e:
            _logger.exception("Görsel düzeltme cron hatası: %s", e)
            try:
                self.env.cr.rollback()
                self.env.cr.execute(
                    "UPDATE image_fix_job SET progress_text = %s WHERE id = %s",
                    (f'Hata (yeniden denenecek): {str(e)[:200]}', job.id),
                )
                self.env.cr.commit()
            except Exception:
                pass

    def _fix_template_links(self):
        """Aşama 1: product_tmpl_id boş olanları toplu düzelt."""
        self.ensure_one()
        _logger.info("Görsel düzeltme Aşama 1: Şablon bağlantıları...")

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
        self.env['product.image'].invalidate_model(['product_tmpl_id'])

        self.write({
            'links_done': True,
            'total_fixed_links': fixed_count,
            'progress_text': f'{fixed_count} bağlantı onarıldı. Thumbnail başlıyor...',
        })
        self.env.cr.commit()
        self.env.invalidate_all()
        _logger.info("Aşama 1 tamam: %d bağlantı onarıldı.", fixed_count)

    def _fix_thumbnails_safe(self):
        """
        Aşama 2: Thumbnail üretme — ORM read + image_process.

        ORM ile image_1920 okur (attachment/column storage fark etmez).
        image_process() ile boyutlandırır.
        Sonucu ORM write() ile yazar.
        Her turda sadece 2 görsel işler (sunucu çökmesini önler).
        """
        self.ensure_one()
        import time
        from odoo.tools import image as image_tools

        start_time = time.time()
        MAX_SECONDS = 15
        BATCH_SIZE = 2  # Her turda sadece 2 görsel — güvenli

        ProductImage = self.env['product.image'].sudo()

        # ── Kalan kayıtları bul (ORM — attachment desteği) ──
        domain = [
            ('id', '>', self.last_processed_id),
            ('image_1920', '!=', False),
            ('image_128', '=', False),
        ]
        total_remaining = ProductImage.search_count(domain)
        _logger.info(
            "Görsel düzeltme Aşama 2: last_id=%d, kalan=%d",
            self.last_processed_id, total_remaining,
        )

        if total_remaining == 0:
            # ── Tamamlandı — raw SQL ile güncelle (ORM cr.commit sonrası sorun yaratabilir) ──
            cr = self.env.cr
            done_text = (
                f'Tamamlandı! {self.total_fixed_links} bağlantı + '
                f'{self.total_fixed_thumbs} thumbnail onarıldı.'
            )
            cr.execute("""
                UPDATE image_fix_job
                SET state = 'done', progress_text = %s
                WHERE id = %s
            """, (done_text, self.id))
            cr.execute("""
                UPDATE ir_config_parameter
                SET value = 'done'
                WHERE key = 'ugurlar_images.fix_images_status'
            """)
            cr.execute("""
                UPDATE ir_config_parameter
                SET value = %s
                WHERE key = 'ugurlar_images.fix_images_progress'
            """, (done_text,))
            cron = self.env.ref(
                'ugurlar_images.ir_cron_fix_existing_images',
                raise_if_not_found=False,
            )
            if cron:
                cr.execute(
                    "UPDATE ir_cron SET active = FALSE WHERE id = %s",
                    (cron.id,)
                )
            cr.commit()
            self.env.invalidate_all()
            _logger.info(
                "Görsel düzeltme TAMAMLANDI! %d bağlantı, %d thumbnail",
                self.total_fixed_links, self.total_fixed_thumbs,
            )
            return

        # ── Batch al ──
        images = ProductImage.search(domain, limit=BATCH_SIZE, order='id ASC')
        _logger.info("Görsel düzeltme batch: %d görsel bulundu", len(images))

        processed = 0
        job_id = self.id
        current_total = self.total_fixed_thumbs

        for img in images:
            elapsed = time.time() - start_time
            if elapsed > MAX_SECONDS:
                _logger.info("Zaman limiti (%.0fs). Durduruluyor.", elapsed)
                break

            img_id = img.id
            _logger.info("Thumbnail işleniyor: id=%d", img_id)

            try:
                # ── ORM ile image_1920 oku (attachment desteği) ──
                raw_data = img.image_1920
                if not raw_data:
                    _logger.warning("id=%d: image_1920 boş, atlanıyor.", img_id)
                    self._update_progress_sql(
                        img_id, current_total + processed,
                        total_remaining - processed, job_id,
                    )
                    continue

                _logger.info("id=%d: %d byte image_1920 okundu", img_id, len(raw_data))

                # ── image_process ile boyutlandır ──
                t0 = time.time()
                img_1024 = image_tools.image_process(raw_data, size=(1024, 1024))
                img_512 = image_tools.image_process(raw_data, size=(512, 512))
                img_256 = image_tools.image_process(raw_data, size=(256, 256))
                img_128 = image_tools.image_process(raw_data, size=(128, 128))
                _logger.info(
                    "id=%d: resize tamamlandı (%.1fs)",
                    img_id, time.time() - t0,
                )

                # Belleği serbest bırak
                del raw_data

                # ── Sonucu yaz ──
                # with_context: recompute ve tracking'i devre dışı bırak
                img.with_context(
                    tracking_disable=True,
                    no_recompute=True,
                ).write({
                    'image_1024': img_1024,
                    'image_512': img_512,
                    'image_256': img_256,
                    'image_128': img_128,
                })
                del img_1024, img_512, img_256, img_128

                processed += 1
                _logger.info("id=%d: thumbnail yazıldı ✓", img_id)

            except Exception as e:
                _logger.exception("Thumbnail HATASI id=%d: %s", img_id, e)
                self.env.cr.rollback()

            # ── Her görselden sonra ilerlemeyi kaydet ve commit ──
            self._update_progress_sql(
                img_id, current_total + processed,
                total_remaining - processed, job_id,
            )

        self.env.invalidate_all()
        _logger.info(
            "Görsel düzeltme batch bitti: %d işlendi (%.0fs), kalan: ~%d",
            processed, time.time() - start_time,
            max(0, total_remaining - processed),
        )

    def _update_progress_sql(self, last_id, total_thumbs, remaining, job_id):
        """İlerlemeyi raw SQL ile güncelle ve commit et."""
        try:
            cr = self.env.cr
            progress = (
                f'{total_thumbs} thumbnail tamamlandı. '
                f'Kalan: ~{max(0, remaining)}'
            )
            cr.execute("""
                UPDATE image_fix_job
                SET last_processed_id = %s,
                    total_fixed_thumbs = %s,
                    progress_text = %s
                WHERE id = %s
            """, (last_id, total_thumbs, progress, job_id))
            cr.execute("""
                UPDATE ir_config_parameter
                SET value = %s
                WHERE key = 'ugurlar_images.fix_images_progress'
            """, (progress,))
            cr.execute("""
                UPDATE ir_config_parameter
                SET value = %s
                WHERE key = 'ugurlar_images.fix_images_status'
            """, ('running',))
            cr.commit()
        except Exception as e:
            _logger.warning("İlerleme güncelleme hatası: %s", e)

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

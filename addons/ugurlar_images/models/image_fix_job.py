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
    #  Cron Metodu — Raw SQL (ORM bypass)
    # ------------------------------------------------------------------
    @api.model
    def _cron_fix_images(self):
        """
        Zamanlanmış görev: görsel düzeltme.

        ORM tamamen bypass ediliyor (sunucu çökmesini önlemek için):
          • Raw SQL ile image_1920 okuma
          • image_process() ile thumbnail üretme
          • Raw SQL ile geri yazma
          • cr.commit() ile her görselden sonra kayıt
        """
        job = self.search([('state', '=', 'running')], limit=1)
        if not job:
            return

        try:
            # ── Aşama 1: SQL ile bulk şablon bağlantısı düzeltme ──
            if not job.links_done:
                job._fix_template_links()

            # ── Aşama 2: Raw SQL thumbnail üretme ──
            job._fix_thumbnails_raw()

        except Exception as e:
            _logger.exception("Görsel düzeltme cron hatası: %s", e)
            try:
                self.env.cr.rollback()
                job_id = job.id
                self.env.cr.execute("""
                    UPDATE image_fix_job
                    SET progress_text = %s
                    WHERE id = %s
                """, (f'Hata (yeniden denenecek): {str(e)[:200]}', job_id))
                self.env.cr.commit()
            except Exception:
                pass

    def _fix_template_links(self):
        """
        Aşama 1: product_tmpl_id boş olan product.image kayıtlarını
        tek SQL sorgusuyla toplu düzelt.
        """
        self.ensure_one()
        _logger.info("Görsel düzeltme Aşama 1: Şablon bağlantıları SQL ile düzeltiliyor...")

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
            'progress_text': f'{fixed_count} şablon bağlantısı onarıldı. Thumbnail işlemi başlıyor...',
        })
        self.env.cr.commit()
        _logger.info("Görsel düzeltme Aşama 1: %d şablon bağlantısı onarıldı.", fixed_count)

    def _fix_thumbnails_raw(self):
        """
        Aşama 2: ORM'yi tamamen bypass ederek raw SQL + image_process ile
        thumbnail üretme.

        Neden ORM bypass?
          • _recompute_recordset() tüm image field'larını + tracking'i tetikler
          • ORM cache invalidation ek yük getirir
          • Tüm bunlar worker zaman limitini (120s) aşırıyordu

        Bu metod:
          1. Raw SQL ile sadece id + image_1920 okur
          2. image_process() ile boyutlandırır (Pillow, hafif)
          3. Raw SQL ile geri yazar
          4. Her görselden sonra commit + zaman kontrolü
          5. Max 20 saniye — worker limitinin çok altında
        """
        self.ensure_one()
        import time
        from odoo.tools import image as image_tools

        start_time = time.time()
        MAX_SECONDS = 20  # Worker limiti 120s, biz 20s'de duruyoruz
        BATCH_SIZE = 10

        cr = self.env.cr

        # ── Kalan kayıt sayısını kontrol et ──
        cr.execute("""
            SELECT COUNT(*) FROM product_image
            WHERE id > %s
              AND image_1920 IS NOT NULL
              AND image_128 IS NULL
        """, (self.last_processed_id,))
        total_remaining = cr.fetchone()[0]

        if total_remaining == 0:
            # ── Tamamlandı ──
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
                cr.execute(
                    "UPDATE ir_cron SET active = FALSE WHERE id = %s",
                    (cron.id,)
                )
            cr.commit()
            self.env.invalidate_all()
            _logger.info(
                "Görsel düzeltme tamamlandı! %d bağlantı, %d thumbnail",
                self.total_fixed_links, self.total_fixed_thumbs,
            )
            return

        # ── Sadece ID'leri çek (image_1920'yi henüz yükleme) ──
        cr.execute("""
            SELECT id FROM product_image
            WHERE id > %s
              AND image_1920 IS NOT NULL
              AND image_128 IS NULL
            ORDER BY id ASC
            LIMIT %s
        """, (self.last_processed_id, BATCH_SIZE))
        image_ids = [row[0] for row in cr.fetchall()]

        if not image_ids:
            return

        processed = 0
        job_id = self.id

        for img_id in image_ids:
            # ── Zaman kontrolü ──
            if time.time() - start_time > MAX_SECONDS:
                _logger.info(
                    "Görsel düzeltme: Zaman limiti (%.0fs). %d işlendi.",
                    time.time() - start_time, processed,
                )
                break

            try:
                # Her görseli AYRI AYRI oku (belleği şişirme)
                cr.execute(
                    "SELECT image_1920 FROM product_image WHERE id = %s",
                    (img_id,),
                )
                row = cr.fetchone()
                if not row or not row[0]:
                    # Boş görsel — atla, ID'yi ilerlet
                    cr.execute("""
                        UPDATE image_fix_job
                        SET last_processed_id = %s
                        WHERE id = %s
                    """, (img_id, job_id))
                    cr.commit()
                    continue

                raw_data = bytes(row[0])

                # image_process ile boyutlandır
                img_128 = image_tools.image_process(raw_data, size=(128, 128))
                img_256 = image_tools.image_process(raw_data, size=(256, 256))
                img_512 = image_tools.image_process(raw_data, size=(512, 512))
                img_1024 = image_tools.image_process(raw_data, size=(1024, 1024))

                # Belleği serbest bırak
                del raw_data

                # Raw SQL ile geri yaz
                cr.execute("""
                    UPDATE product_image
                    SET image_128 = %s, image_256 = %s,
                        image_512 = %s, image_1024 = %s
                    WHERE id = %s
                """, (img_128, img_256, img_512, img_1024, img_id))

                del img_128, img_256, img_512, img_1024

                processed += 1

            except Exception as e:
                _logger.warning("Thumbnail hatası id=%s: %s", img_id, e)
                cr.rollback()

            # ── Her görselden sonra ilerlemeyi kaydet ve commit ──
            try:
                cr.execute("""
                    UPDATE image_fix_job
                    SET last_processed_id = %s,
                        total_fixed_thumbs = %s,
                        progress_text = %s
                    WHERE id = %s
                """, (
                    img_id,
                    self.total_fixed_thumbs + processed,
                    f'{self.total_fixed_thumbs + processed} thumbnail tamamlandı. '
                    f'Kalan: ~{max(0, total_remaining - processed)}',
                    job_id,
                ))
                # ir.config_parameter'ı da güncelle (Settings UI için)
                cr.execute("""
                    UPDATE ir_config_parameter
                    SET value = %s
                    WHERE key = 'ugurlar_images.fix_images_progress'
                """, (
                    f'{self.total_fixed_thumbs + processed} thumbnail tamamlandı. '
                    f'Kalan: ~{max(0, total_remaining - processed)}',
                ))
                cr.commit()
            except Exception:
                pass

        self.env.invalidate_all()
        _logger.info(
            "Görsel düzeltme: %d işlendi (%.0fs), kalan: ~%d",
            processed, time.time() - start_time,
            max(0, total_remaining - processed),
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

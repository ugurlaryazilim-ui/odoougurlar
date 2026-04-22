import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Batch boyutu — her seferde kaç ürün grubu (template) işlenecek
BATCH_SIZE = 50


class NebimService(models.AbstractModel):
    """
    Nebim senkronizasyon servis katmanı.
    
    Connector ve Processor'ları birleştirerek üst düzey iş akışlarını yönetir.
    Cron görevleri bu servis üzerinden tetiklenir.
    
    Ürün senkronizasyonu batch processing kullanır:
    1. Nebim'den tüm veri tek seferde çekilir (API sınırı)
    2. ItemCode'a göre gruplandırılır
    3. BATCH_SIZE'lık gruplar halinde işlenir
    4. Her batch sonrası commit yapılır (bellek ve transaction koruması)
    5. İlerleme sync.log'a yazılır
    """
    _name = 'odoougurlar.nebim.service'
    _description = 'Nebim Senkronizasyon Servisi'

    # -----------------------------------------------------------------
    #  Ürün Senkronizasyonu — Batch Processing
    # -----------------------------------------------------------------
    def sync_products(self):
        """
        DEPRECATED — Kuyruk tabanlı sisteme geçildi.
        Yeni senkronizasyon: odoougurlar.product.queue.enqueue_products()
        Bu metod geriye uyum için kuyruğu tetikler.
        """
        _logger.warning("sync_products() deprecated. Kuyruk sistemi kullanılıyor.")
        queue = self.env['odoougurlar.product.queue']
        result = queue.enqueue_products(mode='daily')
        return {
            'processed': result.get('total_groups', 0),
            'created': 0, 'updated': 0, 'failed': 0,
        }

    # -----------------------------------------------------------------
    #  Stok & Fiyat Güncelleme
    # -----------------------------------------------------------------
    def sync_stock_prices(self, mode='incremental'):
        """
        Nebim'den stok bilgilerini çekip Odoo'yu günceller.
        
        mode:
            'full'        → Day=36500 (tüm stoklar - ilk kurulum)
            'incremental' → Day=1 (son 1 günün değişimleri)
        """
        day_map = {
            'full': '36500',
            'incremental': '1',
        }
        day_value = day_map.get(mode, '1')
        log_name = 'Stok Güncelleme' if mode == 'incremental' else 'Stok İlk Kurulum'

        log = self._create_log(f'{log_name} (Day={day_value})', 'stock')
        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_inventory = connector._get_sp_name('inventory')

            _logger.info("Stok SP çağrılıyor: %s Day=%s", sp_inventory, day_value)
            stock_data = connector.run_proc(
                sp_inventory,
                [{'Name': 'Day', 'Value': day_value}]
            )

            if not stock_data:
                self._finish_log(log, 'done', note=f'Nebim\'den stok verisi gelmedi (Day={day_value}).')
                _logger.info("Stok SP boş döndü (Day=%s) - değişiklik yok.", day_value)
                return

            items_list = stock_data if isinstance(stock_data, list) else [stock_data]
            _logger.info("Nebim'den %d stok satırı çekildi (Day=%s)", len(items_list), day_value)

            processor = self.env['odoougurlar.stock.processor']
            stats = processor.process_stock_prices(items_list)

            # Log'a kaydet — not_found + failed = records_failed
            log_stats = {
                'processed': stats.get('processed', 0),
                'created': 0,
                'updated': stats.get('updated', 0),
                'failed': stats.get('not_found', 0) + stats.get('failed', 0),
            }
            note = (
                f"Stok Güncelleme Detay (Day={day_value}):\n"
                f"  İşlenen: {stats.get('processed', 0)}\n"
                f"  Güncellenen: {stats.get('updated', 0)}\n"
                f"  Atlandı (stok aynı): {stats.get('skipped', 0)}\n"
                f"  Bulunamadı: {stats.get('not_found', 0)}\n"
                f"  Hata: {stats.get('failed', 0)}"
            )
            not_found_samples = stats.get('not_found_samples', [])
            if not_found_samples:
                note += f"\n\n  Bulunamayan Ürün Örnekleri:\n  " + "\n  ".join(not_found_samples)
            self._finish_log(log, 'done', stats=log_stats, note=note)
            _logger.info(
                "Stok güncelleme tamamlandı: %d işlendi, %d güncellendi, %d atlandı, %d bulunamadı, %d hata",
                stats.get('processed', 0), stats.get('updated', 0),
                stats.get('skipped', 0), stats.get('not_found', 0), stats.get('failed', 0)
            )
        except Exception as e:
            self._finish_log(log, 'error', error=str(e))
            _logger.error("Stok güncelleme başarısız: %s", str(e))

    # -----------------------------------------------------------------
    #  Fatura Gönderimi
    # -----------------------------------------------------------------
    def sync_invoices(self):
        """Onaylanmış ve henüz Nebim'e gönderilmemiş faturaları Nebim'e iletir."""
        log = self._create_log('Fatura Gönderimi', 'invoice')
        try:
            processor = self.env['odoougurlar.invoice.processor']
            stats = processor.process_invoices()

            self._finish_log(log, 'done', stats=stats)
            _logger.info(
                "Fatura gönderimi tamamlandı: %d işlendi, %d başarılı, %d hata",
                stats.get('processed', 0), stats.get('updated', 0),
                stats.get('failed', 0)
            )
        except Exception as e:
            self._finish_log(log, 'error', error=str(e))
            _logger.error("Fatura gönderimi başarısız: %s", str(e))

    # -----------------------------------------------------------------
    #  Log Yardımcıları
    # -----------------------------------------------------------------
    def _create_log(self, name, sync_type):
        """Yeni senkronizasyon log kaydı oluşturur."""
        return self.env['odoougurlar.sync.log'].sudo().create({
            'name': name,
            'sync_type': sync_type,
            'state': 'running',
            'start_date': fields.Datetime.now(),
        })

    def _finish_log(self, log, state, stats=None, error=None, note=None):
        """Log kaydını tamamlar."""
        vals = {
            'state': state,
            'end_date': fields.Datetime.now(),
        }
        if stats:
            vals.update({
                'records_processed': stats.get('processed', 0),
                'records_created': stats.get('created', 0),
                'records_updated': stats.get('updated', 0),
                'records_failed': stats.get('failed', 0),
            })
        if error:
            vals['error_details'] = error
        if note:
            vals['log_details'] = note
        try:
            log.sudo().write(vals)
        except Exception:
            _logger.warning("Sync log güncelleme hatası: %s", log.id)

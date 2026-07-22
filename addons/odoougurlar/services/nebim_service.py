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
    @api.private
    def _create_log(self, name, sync_type):
        """Yeni senkronizasyon log kaydı oluşturur."""
        return self.env['odoougurlar.sync.log'].sudo().create({
            'name': name,
            'sync_type': sync_type,
            'state': 'running',
            'start_date': fields.Datetime.now(),
        })

    @api.private
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
    # -----------------------------------------------------------------
    #  Maliyet Güncelleme (Birim Maliyet)
    # -----------------------------------------------------------------
    def sync_product_costs(self):
        """
        Nebim'den ürün maliyetlerini (NetMaliyet) çekip Odoo'da standard_price günceller.
        vw_UrunBirimMaliyetleri tablosuna dayalı SP'yi kullanır.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('odoougurlar.nebim_sync_cost_enabled', 'False') == 'True'
    # -----------------------------------------------------------------
    #  Maliyet Güncelleme (Birim Maliyet)
    # -----------------------------------------------------------------
    def sync_product_costs(self):
        """
        Nebim'den ürün maliyetlerini (NetMaliyet) çekip Odoo'da standard_price günceller.
        vw_UrunBirimMaliyetleri tablosuna dayalı SP'yi kullanır.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('odoougurlar.nebim_sync_cost_enabled', 'False') == 'True'
        if not enabled:
            _logger.info("Maliyet senkronizasyonu kapalı.")
            return

        sp_name = ICP.get_param('odoougurlar.nebim_sp_product_cost', 'usp_UrunEkstresi_BirimMaliyetHesapla')
        
        log_id = self._create_sync_log('cost')
        stats = {'processed': 0, 'updated': 0, 'failed': 0}
        connector = self.env['odoougurlar.nebim.connector']
        
        try:
            # SP çağır
            _logger.info(f"Maliyet SP çağrılıyor: {sp_name}")
            results = connector.run_proc(sp_name)
            if not results or not isinstance(results, list):
                self._update_sync_log(log_id, 'completed', stats, note="Nebim'den maliyet verisi dönmedi.")
                return stats
            
            stats['processed'] = len(results)
            
            # Verileri belleğe al: barkod veya productcode'a göre NetMaliyet veya Price2 eşlemesi
            cost_by_code = {}
            for row in results:
                product_code = str(row.get('ProductCode', '')).strip()
                barcode = str(row.get('Barcode', '')).strip()
                net_maliyet = row.get('NetMaliyet')
                if net_maliyet is None:
                    net_maliyet = row.get('Price2', 0.0)
                
                if barcode:
                    cost_by_code[barcode] = float(net_maliyet)
                if product_code:
                    cost_by_code[product_code] = float(net_maliyet)
            
            if not cost_by_code:
                self._update_sync_log(log_id, 'completed', stats, note="İşlenecek geçerli ürün kodu/barkod bulunamadı.")
                return stats
                
            # Odoo'daki ürünleri bul
            keys = list(cost_by_code.keys())
            
            # Limit IN query size
            BATCH_SIZE = 1000
            for i in range(0, len(keys), BATCH_SIZE):
                batch_keys = keys[i:i+BATCH_SIZE]
                products = self.env['product.product'].search([
                    '|',
                    ('default_code', 'in', batch_keys),
                    ('barcode', 'in', batch_keys)
                ])
                
                # Güncelle
                for product in products:
                    try:
                        new_cost = cost_by_code.get(product.barcode)
                        if new_cost is None:
                            new_cost = cost_by_code.get(product.default_code)
                            
                        if new_cost is not None and round(product.standard_price, 2) != round(new_cost, 2):
                            product.standard_price = new_cost
                            stats['updated'] += 1
                    except Exception as e:
                        stats['failed'] += 1
                        _logger.error("Ürün maliyet güncelleme hatası: %s - %s", product.display_name, e)
            
            self._update_sync_log(log_id, 'completed', stats)
            
        except Exception as e:
            self._update_sync_log(log_id, 'failed', error=str(e))
            
        return stats

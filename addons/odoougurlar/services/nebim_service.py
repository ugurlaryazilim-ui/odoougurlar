import logging
from collections import defaultdict
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Stok / maliyet senkronizasyonu tek seferde bir tane (pg advisory lock anahtarları)
NEBIM_STOCK_SYNC_LOCK = 812345001
NEBIM_COST_SYNC_LOCK = 812345002

# Maliyet tam taramasında her commit'te işlenen varyant sayısı
COST_BATCH_SIZE = 500

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
        # Çalışan batch'i silip veriyi ikinci kez çekmesin (otomatik sync cron'u ile çakışıyordu)
        if queue.sudo().search_count([('state', 'in', ['pending', 'processing'])]):
            _logger.info("sync_products atlandı: kuyrukta işlenen kayıt var.")
            return {'processed': 0, 'created': 0, 'updated': 0, 'failed': 0}
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

        # Cron ile "Stok Güncelle" / "Tüm Stokları Çek" aynı anda çalışmasın (processor ara
        # commit yaptığından transaction kilidi yetmez: oturum kilidi)
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", [NEBIM_STOCK_SYNC_LOCK])
        if not self.env.cr.fetchone()[0]:
            _logger.info("Stok güncelleme atlandı: başka bir stok senkronizasyonu çalışıyor.")
            return
        try:
            self._sync_stock_prices_locked(mode, day_value, log_name)
        finally:
            # Oturum kilidi bağlantıda kalır: transaction bozulmuş olsa bile mutlaka bırakılmalı
            try:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", [NEBIM_STOCK_SYNC_LOCK])
            except Exception:
                self.env.cr.rollback()
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", [NEBIM_STOCK_SYNC_LOCK])

    @api.private
    def _sync_stock_prices_locked(self, mode, day_value, log_name):
        log = self._create_log(f'{log_name} (Day={day_value})', 'stock')
        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_inventory = connector._get_sp_name('inventory')

            _logger.debug("Stok SP çağrılıyor: %s Day=%s", sp_inventory, day_value)
            stock_data = connector.run_proc(
                sp_inventory,
                [{'Name': 'Day', 'Value': day_value}]
            )

            if not stock_data:
                self._finish_log(log, 'done', note=f'Nebim\'den stok verisi gelmedi (Day={day_value}).')
                _logger.debug("Stok SP boş döndü (Day=%s) - değişiklik yok.", day_value)
                return

            items_list = stock_data if isinstance(stock_data, list) else [stock_data]
            _logger.debug("Nebim'den %d stok satırı çekildi (Day=%s)", len(items_list), day_value)

            processor = self.env['odoougurlar.stock.processor']
            # Parmak izi anahtarı mod başına: Day=1 ve Day=36500 sonuçları birbirinin yerine geçmez.
            stats = processor.process_stock_prices(
                items_list, fingerprint_key='stock_sp_%s' % mode)

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
                f"  Atlandı (depo hariç): {stats.get('skipped_warehouse', 0)}\n"
                f"  Atlandı (stok aynı): {stats.get('skipped_same', 0)}"
                f"{' (SP sonucu önceki çalışmayla aynı)' if stats.get('fingerprint_hit') else ''}\n"
                f"  Bulunamadı: {stats.get('not_found', 0)}\n"
                f"  Hata: {stats.get('failed', 0)}"
            )
            not_found_samples = stats.get('not_found_samples', [])
            if not_found_samples:
                note += f"\n\n  Bulunamayan Ürün Örnekleri:\n  " + "\n  ".join(not_found_samples)
            self._finish_log(log, 'done', stats=log_stats, note=note)
            # (işlemci zaten özet loglar; burada yalnız iş yapıldıysa INFO)
            _logger.log(
                logging.INFO if log_stats['updated'] or log_stats['failed'] else logging.DEBUG,
                "Stok güncelleme tamamlandı (%s): %d işlendi, %d güncellendi, %d depo + %d aynı atlandı, "
                "%d bulunamadı, %d hata",
                mode, stats.get('processed', 0), stats.get('updated', 0),
                stats.get('skipped_warehouse', 0), stats.get('skipped_same', 0),
                stats.get('not_found', 0), stats.get('failed', 0)
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
        Günlük tam tarama: Nebim Ürün Bilgileri SP'sindeki (sp_GetItemDetails) Price2'yi
        (KDV dahil maliyet) varyantların standard_price alanına aynen yazar.

        Ürün senkronu da aynı alanı yazar; bu cron Nebim'de yalnız maliyeti değişen
        (ürün senkronuna düşmeyen) ürünleri yakalar. Eşleme: Barcode1 → Barcode2 (Odoo barkodu,
        sonra nebim_barcode) → ItemSku.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoougurlar.nebim_sync_cost_enabled', 'False') not in ('True', 'true', '1'):
            _logger.info("Maliyet senkronizasyonu kapalı.")
            return

        # Partiler arası commit var: transaction kilidi yetmez, oturum kilidi
        self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", [NEBIM_COST_SYNC_LOCK])
        if not self.env.cr.fetchone()[0]:
            _logger.info("Maliyet senkronizasyonu atlandı: başka bir maliyet senkronizasyonu çalışıyor.")
            return
        try:
            return self._sync_product_costs_locked()
        finally:
            try:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", [NEBIM_COST_SYNC_LOCK])
            except Exception:
                self.env.cr.rollback()
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", [NEBIM_COST_SYNC_LOCK])

    @api.private
    def _sync_product_costs_locked(self):
        log = self._create_log('Maliyet Senkronizasyonu (Price2)', 'price')
        self.env.cr.commit()
        stats = {'processed': 0, 'updated': 0, 'failed': 0}
        try:
            connector = self.env['odoougurlar.nebim.connector']
            sp_name = connector._get_sp_name('item_details')
            _logger.info("Maliyet SP çağrılıyor: %s Day=36500", sp_name)
            results = connector.run_proc(sp_name, [{'Name': 'Day', 'Value': '36500'}])
            rows = results if isinstance(results, list) else ([results] if results else [])
            if not rows:
                self._finish_log(log, 'done', stats=stats, note="Nebim'den ürün verisi dönmedi.")
                return stats

            processor = self.env['odoougurlar.product.processor']
            by_b1, by_b2, by_sku = {}, {}, {}
            for row in rows:
                cost = processor._nebim_cost(row)
                if not cost:
                    continue
                stats['processed'] += 1
                for key, target in (('Barcode1', by_b1), ('Barcode2', by_b2), ('ItemSku', by_sku)):
                    value = str(row.get(key) or '').strip()
                    if value:
                        target[value] = cost

            barcodes = list(set(by_b1) | set(by_b2))
            # NEDEN: tek OR'lu sorgu hiçbir indeksi kullanamayıp tabloyu tarıyordu; üç dal ayrı
            # indeksleri kullanır (barcode, default_code, nebim_barcode GIN ifade indeksi), UNION tekilleştirir.
            # DIKKAT: üçüncü dalın ifadesi product.py `_nebim_barcode_list_idx` ile birebir aynı olmalı.
            self.env.cr.execute("""
                SELECT id, barcode, default_code, nebim_barcode FROM product_product
                WHERE active AND barcode = ANY(%(bc)s::text[])
                UNION
                SELECT id, barcode, default_code, nebim_barcode FROM product_product
                WHERE active AND default_code = ANY(%(sku)s::text[])
                UNION
                SELECT id, barcode, default_code, nebim_barcode FROM product_product
                WHERE active AND string_to_array(replace(nebim_barcode, ' ', ''), ',') && %(bc)s::text[]
            """, {'bc': barcodes, 'sku': list(by_sku)})
            cost_by_product = {}
            for pid, barcode, code, nebim_barcode in self.env.cr.fetchall():
                # Odoo barkodu Nebim'dekinden farklı olabilir: virgülle birleşik Nebim barkodları da denenir
                extra = [b.strip() for b in (nebim_barcode or '').split(',') if b.strip()]
                cost = (by_b1.get(barcode) or by_b2.get(barcode)
                        or next((by_b1.get(b) or by_b2.get(b) for b in extra if by_b1.get(b) or by_b2.get(b)), None)
                        or by_sku.get(code))
                if cost:
                    cost_by_product[pid] = cost

            Product = self.env['product.product'].sudo()
            ids = list(cost_by_product)
            for i in range(0, len(ids), COST_BATCH_SIZE):
                batch = Product.browse(ids[i:i + COST_BATCH_SIZE])
                to_write = defaultdict(list)
                for product in batch:
                    cost = cost_by_product[product.id]
                    if round(product.standard_price, 2) != cost:
                        to_write[cost].append(product.id)
                for cost, pids in to_write.items():
                    try:
                        with self.env.cr.savepoint():
                            Product.browse(pids).write({'standard_price': cost})
                        stats['updated'] += len(pids)
                    except Exception as e:
                        stats['failed'] += len(pids)
                        _logger.error("Maliyet yazılamadı (%s ürün, %.2f): %s", len(pids), cost, e)
                self.env.cr.commit()
                self.env.invalidate_all()

            unmatched = stats['processed'] - len(cost_by_product)
            note = (f"Nebim: {len(rows)} satır, {stats['processed']} maliyetli | "
                    f"Eşleşen ürün: {len(cost_by_product)} | Güncellenen: {stats['updated']}")
            if unmatched > 0:
                note += f" | Odoo'da bulunamayan (yaklaşık): {unmatched}"
            self._finish_log(log, 'done', stats=stats, note=note)
            _logger.info("Maliyet senkronizasyonu: %s", note)
        except Exception as e:
            self.env.cr.rollback()
            _logger.exception("Maliyet senkronizasyonu başarısız")
            self._finish_log(log, 'error', stats=stats, error=str(e))
        return stats

import logging
import json
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Her batch'te kaç ürün grubu (ItemCode) işlenecek
BATCH_SIZE = 200

# Batch log güncelleme counter'ı (her 5 batch'te 1 log commit)
_batch_log_counter = 0


class NebimProductQueue(models.Model):
    """
    Nebim ürün senkronizasyon kuyruğu.
    
    Profesyonel Odoo yaklaşımı (OCA/queue_job pattern):
    1. Kullanıcı "Ürün Senkronizasyonu" butonuna basar
    2. Nebim'den tüm veri çekilir
    3. ItemCode'a göre gruplanır, her grup bir kuyruk kaydı olarak saklanır
    4. ir.cron tetiklenir → batch batch işler → commit → tekrar tetikler
    5. İlerleme sync.log'da takip edilir
    """
    _name = 'odoougurlar.product.queue'
    _description = 'Nebim Ürün Senkronizasyon Kuyruğu'
    _order = 'id'

    item_code = fields.Char('Ürün Kodu', required=True, index=True)
    raw_data = fields.Text('Ham JSON Verisi')
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('processing', 'İşleniyor'),
        ('done', 'Tamamlandı'),
        ('error', 'Hata'),
    ], default='pending', index=True)
    error_message = fields.Text('Hata Mesajı')
    batch_id = fields.Char('Batch ID', index=True)
    result = fields.Char('Sonuç')  # 'created' veya 'updated'

    # -----------------------------------------------------------------
    #  Kuyruğa Ekleme (Kullanıcı Butonu Çağırır)
    # -----------------------------------------------------------------
    @api.model
    def enqueue_products(self, mode='full'):
        """
        Nebim'den ürünleri çekip kuyruğa ekler.
        
        Args:
            mode: 'full'   = tüm ürünler (Day=3650, ~10 yıl)
                  'daily'  = son 1 günde değişenler (Day=1)
                  'hourly' = son 1 günde değişenler (Day=1, SP saatlik desteklemez)
        
        Returns:
            dict: {total_items, total_groups, batch_id}
        """
        import uuid

        connector = self.env['odoougurlar.nebim.connector']
        sp_items = connector._get_sp_name('item_details')

        # Day parametresi
        day_map = {'full': '36500', 'daily': '1', 'hourly': '1'}
        day_value = day_map.get(mode, '1')
        _logger.info("Nebim'den ürünler çekiliyor (mod: %s, Day: %s)...", mode, day_value)

        items = connector.run_proc(sp_items, [{'Name': 'Day', 'Value': day_value}])

        if not items:
            return {'total_items': 0, 'total_groups': 0, 'batch_id': None}

        items_list = items if isinstance(items, list) else [items]
        _logger.info("Nebim'den %d satır çekildi.", len(items_list))

        # ItemCode'a göre grupla
        grouped = defaultdict(list)
        for item in items_list:
            code = (item.get('ItemCode') or '').strip()
            if code:
                grouped[code].append(item)

        # Eski bekleyen kayıtları temizle
        self.sudo().search([('state', 'in', ['pending', 'processing'])]).unlink()

        # Benzersiz batch ID oluştur
        batch_id = str(uuid.uuid4())[:8]

        # Kuyruk kayıtlarını oluştur
        queue_vals = []
        for item_code, variants in grouped.items():
            queue_vals.append({
                'item_code': item_code,
                'raw_data': json.dumps(variants, ensure_ascii=False),
                'state': 'pending',
                'batch_id': batch_id,
            })

        # Toplu create (hızlı)
        if queue_vals:
            self.sudo().create(queue_vals)
            self.env.cr.commit()

        total_groups = len(grouped)
        _logger.info(
            "Kuyruğa %d ürün grubu eklendi (batch: %s, toplam satır: %d)",
            total_groups, batch_id, len(items_list)
        )

        # Log kaydı oluştur
        self.env['odoougurlar.sync.log'].sudo().create({
            'name': f'Ürün Senkronizasyonu ({mode})',
            'sync_type': 'product',
            'state': 'running',
            'start_date': fields.Datetime.now(),
            'log_details': (
                f"Mod: {mode}\n"
                f"Nebim'den {len(items_list)} satır çekildi\n"
                f"{total_groups} benzersiz ürün kuyruğa eklendi\n"
                f"Batch: {batch_id}"
            ),
        })
        self.env.cr.commit()

        # Cron'u tetikle — hemen ilk batch'i işlesin
        try:
            cron = self.env.ref('odoougurlar.cron_process_product_queue', raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
        except Exception as e:
            _logger.warning("Cron tetikleme hatası: %s", str(e))

        return {
            'total_items': len(items_list),
            'total_groups': total_groups,
            'batch_id': batch_id,
        }

    # -----------------------------------------------------------------
    #  Batch İşleme (Cron Çağırır)
    # -----------------------------------------------------------------
    @api.model
    def process_queue_batch(self):
        """
        Kuyruktan BATCH_SIZE kadar bekleyen kaydı alır ve işler.
        Her kayıt kendi savepoint'inde çalışır.
        İşlem sonrası commit yapılır.
        Bekleyen kayıt varsa cron'u tekrar tetikler.
        """
        pending = self.sudo().search([
            ('state', '=', 'pending'),
        ], limit=BATCH_SIZE, order='id')

        if not pending:
            # Kuyruk bitti: log'u kapat
            self._finalize_sync_log()
            _logger.info("Kuyruk boş, batch işleme tamamlandı.")
            return

        processor = self.env['odoougurlar.product.processor']
        processor._init_cache()  # Batch başında cache yükle

        batch_created = 0
        batch_updated = 0
        batch_failed = 0

        for record in pending:
            try:
                record.sudo().write({'state': 'processing'})
                with self.env.cr.savepoint():
                    variants = json.loads(record.raw_data)
                    result = processor._process_product_group(record.item_code, variants)
                    record.sudo().write({
                        'state': 'done',
                        'result': result,
                    })
                    if result == 'created':
                        batch_created += 1
                    else:
                        batch_updated += 1

            except Exception as e:
                record.sudo().write({
                    'state': 'error',
                    'error_message': str(e),
                })
                batch_failed += 1
                _logger.error("Kuyruk hatası [%s]: %s", record.item_code, str(e))

        # Batch commit
        self.env.cr.commit()

        # İstatistikleri güncelle
        total_done = self.sudo().search_count([('state', '=', 'done')])
        total_error = self.sudo().search_count([('state', '=', 'error')])
        total_pending = self.sudo().search_count([('state', '=', 'pending')])
        total_all = total_done + total_error + total_pending

        progress_pct = int(((total_done + total_error) / max(total_all, 1)) * 100)

        _logger.info(
            "Batch tamamlandı: +%d oluşturuldu, ~%d güncellendi, x%d hata | "
            "Toplam ilerleme: %d/%d (%%%d) | Kalan: %d",
            batch_created, batch_updated, batch_failed,
            total_done + total_error, total_all, progress_pct, total_pending
        )

        # Sync log güncelle (her 5 batch'te 1 kez = daha az commit)
        # Module-level counter kullanılır çünkü self üzerinde attribute kalıcı olmaz
        global _batch_log_counter
        _batch_log_counter += 1
        if _batch_log_counter % 5 == 0 or total_pending == 0:
            self._update_sync_log(total_done, total_error, total_pending, total_all, progress_pct)

        # Bekleyen varsa cron'u tekrar tetikle
        if total_pending > 0:
            try:
                cron = self.env.ref('odoougurlar.cron_process_product_queue', raise_if_not_found=False)
                if cron:
                    cron.sudo()._trigger()
            except Exception:
                pass

    def _update_sync_log(self, done, errors, pending, total, pct):
        """Çalışan sync log'u günceller."""
        log = self.env['odoougurlar.sync.log'].sudo().search([
            ('sync_type', '=', 'product'),
            ('state', '=', 'running'),
        ], order='id desc', limit=1)

        if log:
            log.write({
                'records_processed': done + errors,
                'records_created': done,
                'records_failed': errors,
                'log_details': (
                    f"İlerleme: {done + errors}/{total} (%%{pct})\n"
                    f"✅ Tamamlanan: {done}\n"
                    f"❌ Hatalı: {errors}\n"
                    f"⏳ Bekleyen: {pending}"
                ),
            })
            try:
                self.env.cr.commit()
            except Exception:
                pass

    def _finalize_sync_log(self):
        """Tüm kuyruk bitince log'u kapat."""
        log = self.env['odoougurlar.sync.log'].sudo().search([
            ('sync_type', '=', 'product'),
            ('state', '=', 'running'),
        ], order='id desc', limit=1)

        if log:
            total_done = self.sudo().search_count([('state', '=', 'done')])
            total_error = self.sudo().search_count([('state', '=', 'error')])

            # Hata detaylarını topla
            error_records = self.sudo().search([('state', '=', 'error')], limit=50)
            error_details = '\n'.join(
                f"❌ {r.item_code}: {r.error_message}" for r in error_records
            )

            log.write({
                'state': 'done',
                'end_date': fields.Datetime.now(),
                'records_processed': total_done + total_error,
                'records_created': total_done,
                'records_failed': total_error,
                'log_details': (
                    f"Senkronizasyon tamamlandı!\n"
                    f"✅ Başarılı: {total_done}\n"
                    f"❌ Hatalı: {total_error}\n"
                    + (f"\nHata Detayları:\n{error_details}" if error_details else "")
                ),
            })
            try:
                self.env.cr.commit()
            except Exception:
                pass

            _logger.info("Ürün senkronizasyonu tamamlandı: %d başarılı, %d hata", total_done, total_error)

    # -----------------------------------------------------------------
    #  Otomatik Senkronizasyon (Cron Çağırır)
    # -----------------------------------------------------------------
    @api.model
    def auto_sync_cron(self):
        """
        Cron tarafından çağrılır. Ayarlarda otomatik senkronizasyon
        aktifse, seçili moda göre ürünleri kuyruğa ekler.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        auto_sync = ICP.get_param('odoougurlar.nebim_auto_sync', 'False')

        if auto_sync not in ('True', 'true', '1', True):
            _logger.debug("Otomatik senkronizasyon kapalı, atlanıyor.")
            return

        # Zaten bekleyen kuyruk varsa tekrar çekme
        pending = self.sudo().search_count([('state', 'in', ['pending', 'processing'])])
        if pending > 0:
            _logger.info(
                "Otomatik sync atlanıyor: %d kayıt hâlâ işleniyor.", pending
            )
            return

        mode = ICP.get_param('odoougurlar.nebim_sync_mode', 'daily')
        # Full mod otomatik senkronizasyonda kullanılmaz
        if mode == 'full':
            mode = 'daily'

        _logger.info("Otomatik ürün senkronizasyonu başlatılıyor (mod: %s)...", mode)
        try:
            result = self.enqueue_products(mode=mode)
            _logger.info(
                "Otomatik sync: %d ürün kuyruğa eklendi (toplam %d satır)",
                result['total_groups'], result['total_items']
            )
        except Exception as e:
            _logger.error("Otomatik sync hatası: %s", str(e))

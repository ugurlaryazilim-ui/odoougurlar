import hashlib
import json
import logging
import time

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# ─── Stok Sync'ten Hariç Tutulan Depolar ──────────────────────────────
# Bu depolardaki stok Nebim cron ile güncellenmez.
# Raf import ile yerleştirilen stok korunur.
# Sipariş karşılanınca Odoo düşer, fatura Nebim'e gider.
SKIP_STOCK_SYNC_WAREHOUSES = {'002'}  # X Depo (İnternet Mağaza Depo)

# Bu satır sayısına kadar cache yalnız Nebim'den gelen ürünler için yüklenir (dakikalık
# artımlı sync genelde birkaç bin satır). Üstünde (ilk kurulum) tüm ürünler yüklenir.
RESTRICTED_CACHE_MAX_ROWS = 20000

# Aynı SP sonucu (parmak izi) için işlemin en çok kaç saniye atlanacağı; sonra yine Nebim değerine eşitlenir.
FINGERPRINT_MAX_AGE = 600

# (db adı, anahtar) → (sha1, zaman). NEDEN: ir.config_parameter yazımı tüm worker'larda registry
# önbelleğini temizler (sık değişen Nebim verisinde dakikalık fırtına); süreç içi bellek yeter,
# cron başka worker'a düşerse yalnız bir kez fazladan işlenir. Stored alan/tablo yok.
_FINGERPRINTS = {}

# ─── Module-Level Cache ───────────────────────────────────────────────
_STOCK_CACHE = {
    'loaded': False,
    'barcode_map': {},     # barcode → product.product id
    'sku_map': {},         # default_code (ItemSku) → product.product id
    'variant_map': {},     # (nebim_code, variant_code) → product.product id
    'template_map': {},    # nebim_code → [product.product ids]
    'warehouse_map': {},   # warehouse_code → location_id
    'skip_location_ids': set(),  # stok sync atlanacak location_id'ler
    'default_location_id': None,
}


class StockProcessor(models.AbstractModel):
    """
    Nebim'den gelen stok verilerini Odoo'da güncelleyen processor.
    Cache sistemi ile yüksek performans.
    """
    _name = 'odoougurlar.stock.processor'
    _description = 'Nebim Stok Processor'

    # =================================================================
    #  Cache
    # =================================================================
    @api.private
    def _init_stock_cache(self, force=False, stock_data=None):
        """Eşleme verilerini belleğe yükler.

        stock_data verilirse (ve RESTRICTED_CACHE_MAX_ROWS'u aşmıyorsa) yalnız bu satırlardaki
        barkod / SKU / ürün kodlarına ait ürünler yüklenir: önceden dakikalık sync her
        çalışmada ~230 bin ürünü üç kez tarıyordu. Eşleme kuralları (öncelik sırası) aynıdır.
        """
        global _STOCK_CACHE
        if _STOCK_CACHE['loaded'] and not force:
            _logger.debug("Stok cache zaten yüklü, atlanıyor.")
            return
        restricted = stock_data is not None and len(stock_data) <= RESTRICTED_CACHE_MAX_ROWS
        barcodes = skus = item_codes = None
        if restricted:
            barcodes, skus, item_codes = set(), set(), set()
            for item in stock_data:
                for key in ('Barcode1', 'Barcode2'):
                    value = (item.get(key) or '').strip()
                    if value:
                        barcodes.add(value)
                sku = (item.get('ItemSku') or '').strip()
                if sku:
                    skus.add(sku)
                code = (item.get('ItemCode') or '').strip()
                if code:
                    item_codes.add(code)
            barcodes, skus, item_codes = list(barcodes), list(skus), list(item_codes)
            _logger.debug("Stok cache yükleniyor (yalnız gelen %d satırın ürünleri)...", len(stock_data))
        else:
            _logger.debug("Stok cache yükleniyor...")

        # 1. Barcode → product_id  (iki adımlı: barcode öncelikli)
        _STOCK_CACHE['barcode_map'] = {}

        # Adım 1: barcode alanı — her zaman öncelikli
        if restricted:
            self.env.cr.execute("""
                SELECT barcode, id FROM product_product
                WHERE active = true AND barcode = ANY(%s)
            """, [barcodes])
        else:
            self.env.cr.execute("""
                SELECT barcode, id FROM product_product
                WHERE active = true AND barcode IS NOT NULL AND barcode != ''
            """)
        for barcode, pid in self.env.cr.fetchall():
            _STOCK_CACHE['barcode_map'][barcode] = pid

        # Adım 2: nebim_barcode — sadece barcode map'te yoksa ekle (üzerine yazmaz)
        if restricted:
            # DIKKAT: ifade product.py `_nebim_barcode_list_idx` ile birebir aynı kalmalı (GIN indeksi).
            self.env.cr.execute("""
                SELECT id, nebim_barcode FROM product_product
                WHERE active = true
                  AND string_to_array(REPLACE(nebim_barcode, ' ', ''), ',') && %s::text[]
            """, [barcodes])
        else:
            self.env.cr.execute("""
                SELECT id, nebim_barcode FROM product_product
                WHERE active = true AND nebim_barcode IS NOT NULL AND nebim_barcode != ''
            """)
        for pid, nebim_barcode in self.env.cr.fetchall():
            for bc in nebim_barcode.split(','):
                bc = bc.strip()
                if bc and bc not in _STOCK_CACHE['barcode_map']:
                    _STOCK_CACHE['barcode_map'][bc] = pid

        # 2. default_code (ItemSku) → product_id
        _STOCK_CACHE['sku_map'] = {}
        if restricted:
            self.env.cr.execute("""
                SELECT id, default_code
                FROM product_product
                WHERE active = true AND default_code = ANY(%s)
            """, [skus])
        else:
            self.env.cr.execute("""
                SELECT id, default_code
                FROM product_product
                WHERE active = true AND default_code IS NOT NULL
            """)
        for pid, default_code in self.env.cr.fetchall():
            _STOCK_CACHE['sku_map'][default_code] = pid

        # 3. (nebim_code, variant_code) → product_id + template_map
        _STOCK_CACHE['variant_map'] = {}
        _STOCK_CACHE['template_map'] = {}
        if restricted:
            self.env.cr.execute("""
                SELECT pp.id, pt.nebim_code, pp.nebim_variant_code
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE pt.nebim_code = ANY(%s)
                  AND pp.active = true
            """, [item_codes])
        else:
            self.env.cr.execute("""
                SELECT pp.id, pt.nebim_code, pp.nebim_variant_code
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE pt.nebim_code IS NOT NULL
                  AND pp.active = true
            """)
        for pid, nebim_code, variant_code in self.env.cr.fetchall():
            if variant_code:
                _STOCK_CACHE['variant_map'][(nebim_code, variant_code)] = pid
            if nebim_code not in _STOCK_CACHE['template_map']:
                _STOCK_CACHE['template_map'][nebim_code] = []
            _STOCK_CACHE['template_map'][nebim_code].append(pid)

        # 4. Warehouse → location_id
        self._load_warehouse_cache()

        # Kısmi cache "yüklü" sayılmaz (başka bir çağrı tüm ürünleri bekleyebilir)
        _STOCK_CACHE['loaded'] = not restricted

        _logger.debug(
            "Stok cache yüklendi: %d barcode, %d sku, %d variant, %d template, %d warehouse, default_loc=%s",
            len(_STOCK_CACHE['barcode_map']),
            len(_STOCK_CACHE['sku_map']),
            len(_STOCK_CACHE['variant_map']),
            len(_STOCK_CACHE['template_map']),
            len(_STOCK_CACHE['warehouse_map']),
            _STOCK_CACHE['default_location_id'],
        )

    @api.private
    def _load_warehouse_cache(self):
        """Depo → lokasyon eşlemesi, atlanacak lokasyonlar ve varsayılan lokasyon (birkaç satır, ucuz)."""
        _STOCK_CACHE['warehouse_map'] = {}
        _STOCK_CACHE['skip_location_ids'] = set()
        for wh in self.env['stock.warehouse'].sudo().search([]):
            if wh.nebim_warehouse_code:
                _STOCK_CACHE['warehouse_map'][wh.nebim_warehouse_code] = wh.lot_stock_id.id
            if wh.code:
                _STOCK_CACHE['warehouse_map'][wh.code] = wh.lot_stock_id.id
            # Hariç tutulan depoları kaydet
            if wh.code in SKIP_STOCK_SYNC_WAREHOUSES:
                _STOCK_CACHE['skip_location_ids'].add(wh.lot_stock_id.id)
                _logger.debug(
                    "  Stok sync ATLANACAK depo: %s (kod: %s, loc_id: %d)",
                    wh.name, wh.code, wh.lot_stock_id.id,
                )
        default_wh = self.env['stock.warehouse'].sudo().search([], limit=1)
        _STOCK_CACHE['default_location_id'] = default_wh.lot_stock_id.id if default_wh else None

    @api.private
    def _row_location_id(self, item):
        """Satırın yazılacağı lokasyon (bilinmeyen depo kodu → varsayılan depo); yoksa None."""
        wh_code = (item.get('WarehouseCode') or '').strip()
        return _STOCK_CACHE['warehouse_map'].get(wh_code) or _STOCK_CACHE.get('default_location_id')

    # =================================================================
    #  Ana İşlem
    # =================================================================
    @api.private
    def _finalize_stats(self, stats):
        """`skipped` toplamını yazar ve özeti loglar (iş yapılmadıysa DEBUG: dakikalık cron gürültüsü)."""
        stats['skipped'] = stats['skipped_warehouse'] + stats['skipped_same']
        worked = stats['updated'] or stats['not_found'] or stats['failed']
        _logger.log(
            logging.INFO if worked else logging.DEBUG,
            "Stok güncelleme tamamlandı: %d işlendi, %d güncellendi, %d depo nedeniyle atlandı, "
            "%d aynı miktar nedeniyle atlandı, %d bulunamadı, %d hata",
            stats['processed'], stats['updated'], stats['skipped_warehouse'],
            stats['skipped_same'], stats['not_found'], stats['failed'],
        )
        return stats

    @api.private
    def _stock_fingerprint(self, rows):
        """Satırların sırasızdan bağımsız sha1 parmak izi."""
        lines = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
        return hashlib.sha1('\n'.join(lines).encode()).hexdigest()

    def process_stock_prices(self, stock_data, fingerprint_key=None):
        """
        Nebim stok verisini toplu işler.
        Cache üzerinden varyant eşleme — ~0 sorgu/satır.

        fingerprint_key verilirse: atlanan depolar ayıklandıktan sonra kalan satırların parmak izi
        süreç içi bellekteki önceki çalışmayla aynıysa (ve FINGERPRINT_MAX_AGE dolmadıysa) işlem yapılmaz.
        """
        stats = {
            'processed': len(stock_data), 'updated': 0, 'skipped': 0,
            'skipped_warehouse': 0, 'skipped_same': 0,
            'not_found': 0, 'failed': 0, 'not_found_samples': [],
        }

        # NEDEN: 002 (İnternet Depo) satırları ürün/quant cache'i yüklenmeden ÖNCE ayıklanır; eskiden
        # her dakika binlerce 002 satırı için cache + quant sorguları çalışıp hepsi atlanıyordu.
        # Lokasyon kararı satır döngüsündekiyle aynı (`_row_location_id`).
        self._load_warehouse_cache()
        skip_locations = _STOCK_CACHE['skip_location_ids']
        rows = [item for item in stock_data if self._row_location_id(item) not in skip_locations]
        stats['skipped_warehouse'] = len(stock_data) - len(rows)
        if not rows:
            return self._finalize_stats(stats)

        digest = None
        if fingerprint_key:
            digest = self._stock_fingerprint(rows)
            prev_digest, prev_time = _FINGERPRINTS.get((self.env.cr.dbname, fingerprint_key), (None, 0))
            # DIKKAT: süre sınırı bilinçli. Eskiden her dakika Nebim değerine yazıldığı için Odoo
            # tarafındaki sapma (teslimat düşümü, elle düzeltme) ≤1 dk'da kendiliğinden düzeliyordu;
            # parmak izi tek başına bunu Nebim verisi değişene kadar durdururdu.
            if prev_digest == digest and time.time() - prev_time < FINGERPRINT_MAX_AGE:
                stats['skipped_same'] = len(rows)
                stats['fingerprint_hit'] = True
                return self._finalize_stats(stats)

        stock_data = rows
        self._init_stock_cache(force=True, stock_data=stock_data)  # Her sync'te taze cache

        write_errors = 0

        # Mevcut quant'ları toplu yükle
        quant_map = {}  # (product_id, location_id) → (quant_id, current_qty)
        location_ids = list(set(_STOCK_CACHE['warehouse_map'].values()))
        if _STOCK_CACHE['default_location_id']:
            location_ids.append(_STOCK_CACHE['default_location_id'])
        location_ids = list(set(lid for lid in location_ids if lid))

        # Yalnız bu turda eşleşen ürünlerin quant'ları (önceden depolardaki tüm quant'lar)
        matched_ids = {self._find_product_id(item) for item in stock_data}
        matched_ids.discard(None)
        matched_ids = list(matched_ids) or [0]

        if location_ids:
            self.env.cr.execute("""
                SELECT id, product_id, location_id, COALESCE(quantity, 0)
                FROM stock_quant
                WHERE location_id IN %s AND product_id = ANY(%s)
            """, (tuple(location_ids), matched_ids))
            for qid, prod_id, loc_id, qty in self.env.cr.fetchall():
                quant_map[(prod_id, loc_id)] = (qid, float(qty or 0))

        # ── Alt raf quant'ları: raflanmış ürünleri ana depoya yazma ──
        # (product_id, parent_loc_id) → [(child_quant_id, child_loc_id, child_qty), ...]
        # NEDEN: eskiden yalnız ilk/son quant id'si tutuluyor ve miktarı quant_map'te
        # (yalnız kök lokasyonlar) arıyordu; bulamayınca mevcut=0 sayıp her turda yeniden yazıyordu.
        shelf_product_map = {}
        parent_loc_ids = list(set(_STOCK_CACHE['warehouse_map'].values()))
        parent_loc_ids = [lid for lid in parent_loc_ids if lid]
        if parent_loc_ids:
            self.env.cr.execute("""
                SELECT sq.product_id, pl.id AS parent_loc_id,
                       sq.id AS quant_id, sq.location_id AS child_loc_id,
                       sq.quantity
                FROM stock_quant sq
                JOIN stock_location cl ON sq.location_id = cl.id
                JOIN stock_location pl ON cl.parent_path LIKE pl.parent_path || '%%'
                   AND cl.id != pl.id
                WHERE pl.id IN %s
                  AND cl.usage = 'internal'
                  AND sq.quantity > 0
                  AND sq.product_id = ANY(%s)
                ORDER BY sq.id
            """, (tuple(parent_loc_ids), matched_ids))
            for prod_id, ploc_id, qid, cloc_id, cqty in self.env.cr.fetchall():
                shelf_product_map.setdefault((prod_id, ploc_id), []).append(
                    (qid, cloc_id, float(cqty or 0)))

        _logger.debug("Quant cache yüklendi: %d quant, %d location, %d raflanmış ürün",
                      len(quant_map), len(location_ids), len(shelf_product_map))

        batch_updates = []  # (quant_id, new_qty)
        batch_creates = []  # (product_id, location_id, qty)
        not_found_samples = stats['not_found_samples']

        for item in stock_data:
            try:
                # Varyantı bul — cache ile (0 sorgu)
                product_id = self._find_product_id(item)
                if not product_id:
                    stats['not_found'] += 1
                    if len(not_found_samples) < 100:
                        not_found_samples.append(
                            f"{item.get('ItemCode', '?')}-{item.get('ColorCode', '?')}-{item.get('ItemDim1Code', '?')}"
                        )
                    continue

                # Stok miktarı (None-safe)
                raw_qty = item.get('Inventory')
                if raw_qty is None:
                    raw_qty = item.get('QtyOnHand')
                if raw_qty is None:
                    raw_qty = 0
                qty = float(raw_qty)

                # Lokasyon bul
                # (Hariç tutulan depolar, ör. X Depo raflanmış stok, yukarıda daha baştan ayıklandı.)
                location_id = self._row_location_id(item)
                if not location_id:
                    stats['failed'] += 1
                    continue

                # Quant kontrol
                # Raflanmış ürünse, ana depoya değil alt raf quant'ına yönlendir
                shelf_quants = shelf_product_map.get((product_id, location_id))
                if shelf_quants:
                    # Karşılaştırma depo toplamıyla yapılır (kök quant + raf quant'ları)
                    root_cached = quant_map.get((product_id, location_id))
                    root_qty = root_cached[1] if root_cached else 0.0
                    total_qty = root_qty + sum(q[2] for q in shelf_quants)
                    if abs(total_qty - qty) <= 0.001:
                        stats['skipped_same'] += 1
                        continue
                    if len(shelf_quants) > 1:
                        # DIKKAT: farkı hangi rafa yazacağımız belirsiz; rafları ezmemek için yazma.
                        _logger.warning(
                            "Stok: ürün %d birden çok raf quant'ına sahip (%d adet), Nebim=%s "
                            "depo toplamı=%s; yazma yapılmadı",
                            product_id, len(shelf_quants), qty, total_qty,
                        )
                        stats['skipped_same'] += 1
                        continue
                    child_qid, _child_loc, child_qty = shelf_quants[0]
                    # Fark tek rafa yazılır; kök quant'a dokunulmaz (kök 0 ise hedef = Nebim miktarı)
                    new_child_qty = child_qty + (qty - total_qty)
                    if new_child_qty < -0.001:
                        _logger.warning(
                            "Stok: ürün %d için raf miktarı negatif olurdu (Nebim=%s, kök=%s, raf=%s); "
                            "yazma yapılmadı", product_id, qty, root_qty, child_qty,
                        )
                        stats['skipped_same'] += 1
                        continue
                    batch_updates.append((child_qid, new_child_qty))
                    stats['updated'] += 1
                    continue

                quant_key = (product_id, location_id)
                existing = quant_map.get(quant_key)

                if existing:
                    qid, current_qty = existing
                    current_qty = float(current_qty or 0)
                    if abs(current_qty - qty) > 0.001:
                        batch_updates.append((qid, qty))
                        stats['updated'] += 1
                    else:
                        stats['skipped_same'] += 1
                else:
                    if abs(qty) > 0.001:
                        batch_creates.append((product_id, location_id, qty))
                        stats['updated'] += 1
                    else:
                        stats['skipped_same'] += 1

            except Exception as e:
                stats['failed'] += 1
                if stats['failed'] <= 5:
                    _logger.exception("Stok satır hatası: %s", str(e))

        # Toplu ORM güncelleme (inventory_mode ile)
        StockQuant = self.env['stock.quant'].sudo().with_context(inventory_mode=True)
        if batch_updates:
            _logger.info("Stok toplu güncelleme: %d quant", len(batch_updates))
            for i in range(0, len(batch_updates), 500):
                chunk = batch_updates[i:i+500]
                for qid, qty in chunk:
                    try:
                        quant = StockQuant.browse(qid)
                        quant.write({'quantity': qty})
                    except Exception as e:
                        write_errors += 1
                        _logger.warning("Quant güncelleme hatası id=%d: %s", qid, str(e))
                # BİLİNÇLİ TERCİH: Büyük stok batch'lerinde (10K+ satır) bellek taşmasını
                # engellemek için chunk sonrası commit yapılır. Partial update riski kabul edilir.
                self.env.cr.commit()

        if batch_creates:
            _logger.info("Stok toplu oluşturma: %d quant", len(batch_creates))
            for i in range(0, len(batch_creates), 100):
                chunk = batch_creates[i:i+100]
                for prod_id, loc_id, qty in chunk:
                    try:
                        StockQuant.create({
                            'product_id': prod_id,
                            'location_id': loc_id,
                            'quantity': qty,
                        })
                    except Exception as e:
                        write_errors += 1
                        _logger.warning("Quant oluşturma hatası prod=%d loc=%d: %s", prod_id, loc_id, str(e))
                # BİLİNÇLİ TERCİH: Bkz. yukarıdaki açıklama.
                self.env.cr.commit()

        if not_found_samples:
            _logger.warning(
                "Stok: %d ürün Odoo'da bulunamadı. Örnekler: %s",
                stats['not_found'], ', '.join(not_found_samples)
            )

        # Hatasız tamamlanan çalışmanın parmak izi kaydedilir; hatalıysa bir sonraki dakika yeniden denenir.
        # (not_found hata sayılmaz: Odoo'da olmayan ürünler kalıcı olabilir; yeni ürün süre sınırıyla yakalanır.)
        if digest and not stats['failed'] and not write_errors:
            _FINGERPRINTS[(self.env.cr.dbname, fingerprint_key)] = (digest, time.time())
        return self._finalize_stats(stats)

    @api.private
    def _find_product_id(self, item):
        """Cache'den varyant ID'si bulur — 0 sorgu."""
        barcode1 = (item.get('Barcode1') or '').strip()
        barcode2 = (item.get('Barcode2') or '').strip()
        item_code = (item.get('ItemCode') or '').strip()
        color_code = (item.get('ColorCode') or '').strip()
        size_code = (item.get('ItemDim1Code') or '').strip()
        item_sku = (item.get('ItemSku') or '').strip()

        # 1. Barcode1
        if barcode1 and barcode1 in _STOCK_CACHE['barcode_map']:
            return _STOCK_CACHE['barcode_map'][barcode1]

        # 2. Barcode2
        if barcode2 and barcode2 in _STOCK_CACHE['barcode_map']:
            return _STOCK_CACHE['barcode_map'][barcode2]

        # 3. ItemSku (default_code)
        if item_sku and item_sku in _STOCK_CACHE['sku_map']:
            return _STOCK_CACHE['sku_map'][item_sku]

        # 4. Variant code (ColorCode-ItemDim1Code)
        if item_code and color_code and size_code:
            variant_code = f"{color_code}-{size_code}"
            key = (item_code, variant_code)
            if key in _STOCK_CACHE['variant_map']:
                return _STOCK_CACHE['variant_map'][key]

        # 5. Sadece ColorCode
        if item_code and color_code:
            key = (item_code, color_code)
            if key in _STOCK_CACHE['variant_map']:
                return _STOCK_CACHE['variant_map'][key]

        # 6. Tek varyantlı ürün
        if item_code and item_code in _STOCK_CACHE['template_map']:
            variants = _STOCK_CACHE['template_map'][item_code]
            if len(variants) == 1:
                return variants[0]

        return None

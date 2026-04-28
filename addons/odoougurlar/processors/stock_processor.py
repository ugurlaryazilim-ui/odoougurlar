import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# ─── Module-Level Cache ───────────────────────────────────────────────
_STOCK_CACHE = {
    'loaded': False,
    'barcode_map': {},     # barcode → product.product id
    'sku_map': {},         # default_code (ItemSku) → product.product id
    'variant_map': {},     # (nebim_code, variant_code) → product.product id
    'template_map': {},    # nebim_code → [product.product ids]
    'warehouse_map': {},   # warehouse_code → location_id
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
    def _init_stock_cache(self, force=False):
        """Tüm eşleme verilerini belleğe yükler."""
        global _STOCK_CACHE
        if _STOCK_CACHE['loaded'] and not force:
            _logger.debug("Stok cache zaten yüklü, atlanıyor.")
            return
        _logger.info("Stok cache yükleniyor...")

        # 1. Barcode → product_id
        _STOCK_CACHE['barcode_map'] = {}
        self.env.cr.execute("""
            SELECT id, barcode, nebim_barcode
            FROM product_product
            WHERE active = true
        """)
        for pid, barcode, nebim_barcode in self.env.cr.fetchall():
            if barcode:
                _STOCK_CACHE['barcode_map'][barcode] = pid
            if nebim_barcode:
                for bc in nebim_barcode.split(','):
                    bc = bc.strip()
                    if bc:
                        _STOCK_CACHE['barcode_map'][bc] = pid

        # 2. default_code (ItemSku) → product_id
        _STOCK_CACHE['sku_map'] = {}
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
        _STOCK_CACHE['warehouse_map'] = {}
        for wh in self.env['stock.warehouse'].sudo().search([]):
            if wh.nebim_warehouse_code:
                _STOCK_CACHE['warehouse_map'][wh.nebim_warehouse_code] = wh.lot_stock_id.id
            if wh.code:
                _STOCK_CACHE['warehouse_map'][wh.code] = wh.lot_stock_id.id

        # Varsayılan depo
        default_wh = self.env['stock.warehouse'].sudo().search([], limit=1)
        _STOCK_CACHE['default_location_id'] = default_wh.lot_stock_id.id if default_wh else None

        _STOCK_CACHE['loaded'] = True

        _logger.info(
            "Stok cache yüklendi: %d barcode, %d sku, %d variant, %d template, %d warehouse, default_loc=%s",
            len(_STOCK_CACHE['barcode_map']),
            len(_STOCK_CACHE['sku_map']),
            len(_STOCK_CACHE['variant_map']),
            len(_STOCK_CACHE['template_map']),
            len(_STOCK_CACHE['warehouse_map']),
            _STOCK_CACHE['default_location_id'],
        )

    # =================================================================
    #  Ana İşlem
    # =================================================================
    def process_stock_prices(self, stock_data):
        """
        Nebim stok verisini toplu işler.
        Cache üzerinden varyant eşleme — ~0 sorgu/satır.
        """
        self._init_stock_cache(force=True)  # Her sync'te taze cache

        stats = {'processed': 0, 'updated': 0, 'skipped': 0, 'not_found': 0, 'failed': 0}

        # Mevcut quant'ları toplu yükle
        quant_map = {}  # (product_id, location_id) → (quant_id, current_qty)
        location_ids = list(set(_STOCK_CACHE['warehouse_map'].values()))
        if _STOCK_CACHE['default_location_id']:
            location_ids.append(_STOCK_CACHE['default_location_id'])
        location_ids = list(set(lid for lid in location_ids if lid))

        if location_ids:
            self.env.cr.execute("""
                SELECT id, product_id, location_id, COALESCE(quantity, 0)
                FROM stock_quant
                WHERE location_id IN %s
            """, (tuple(location_ids),))
            for qid, prod_id, loc_id, qty in self.env.cr.fetchall():
                quant_map[(prod_id, loc_id)] = (qid, float(qty or 0))

        # ── Alt raf quant'ları: raflanmış ürünleri ana depoya yazma ──
        # (product_id, parent_loc_id) → (child_quant_id, child_loc_id)
        shelf_product_map = {}
        parent_loc_ids = list(set(_STOCK_CACHE['warehouse_map'].values()))
        parent_loc_ids = [lid for lid in parent_loc_ids if lid]
        if parent_loc_ids:
            self.env.cr.execute("""
                SELECT sq.product_id, pl.id AS parent_loc_id,
                       sq.id AS quant_id, sq.location_id AS child_loc_id
                FROM stock_quant sq
                JOIN stock_location cl ON sq.location_id = cl.id
                JOIN stock_location pl ON cl.parent_path LIKE pl.parent_path || '%%'
                   AND cl.id != pl.id
                WHERE pl.id IN %s
                  AND cl.usage = 'internal'
                  AND sq.quantity > 0
            """, (tuple(parent_loc_ids),))
            for prod_id, ploc_id, qid, cloc_id in self.env.cr.fetchall():
                shelf_product_map[(prod_id, ploc_id)] = (qid, cloc_id)

        _logger.info("Quant cache yüklendi: %d quant, %d location, %d raflanmış ürün",
                      len(quant_map), len(location_ids), len(shelf_product_map))

        batch_updates = []  # (quant_id, new_qty)
        batch_creates = []  # (product_id, location_id, qty)
        not_found_samples = []

        for item in stock_data:
            stats['processed'] += 1
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
                wh_code = (item.get('WarehouseCode') or '').strip()
                location_id = _STOCK_CACHE['warehouse_map'].get(wh_code)
                if not location_id:
                    location_id = _STOCK_CACHE.get('default_location_id')
                if not location_id:
                    stats['failed'] += 1
                    continue

                # Quant kontrol
                # Raflanmış ürünse, ana depoya değil alt raf quant'ına yönlendir
                shelf_info = shelf_product_map.get((product_id, location_id))
                if shelf_info:
                    child_qid, child_loc_id = shelf_info
                    # Quant zaten alt rafta; güncellemeyi oraya yap
                    quant_key = (product_id, child_loc_id)
                    existing = (child_qid, 0)  # güncelleme için
                    # Mevcut child quant qty'yi quant_map'ten al
                    cached = quant_map.get(quant_key)
                    if cached:
                        existing = cached
                else:
                    quant_key = (product_id, location_id)
                    existing = quant_map.get(quant_key)

                if existing:
                    qid, current_qty = existing
                    current_qty = float(current_qty or 0)
                    if abs(current_qty - qty) > 0.001:
                        batch_updates.append((qid, qty))
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    if abs(qty) > 0.001:
                        batch_creates.append((product_id, location_id, qty))
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1

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
                        _logger.warning("Quant oluşturma hatası prod=%d loc=%d: %s", prod_id, loc_id, str(e))
                # BİLİNÇLİ TERCİH: Bkz. yukarıdaki açıklama.
                self.env.cr.commit()

        if not_found_samples:
            _logger.warning(
                "Stok: %d ürün Odoo'da bulunamadı. Örnekler: %s",
                stats['not_found'], ', '.join(not_found_samples)
            )

        stats['not_found_samples'] = not_found_samples

        _logger.info(
            "Stok güncelleme tamamlandı: %d işlendi, %d güncellendi, "
            "%d atlandı, %d bulunamadı, %d hata",
            stats['processed'], stats['updated'], stats['skipped'],
            stats['not_found'], stats['failed']
        )
        return stats

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

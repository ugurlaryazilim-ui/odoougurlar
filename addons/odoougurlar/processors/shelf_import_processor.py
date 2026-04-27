import logging
import os

from odoo import models, fields

_logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data'
)

# Depo eşleme: HamurLabs depo adı → Odoo warehouse kodu
DEPOT_MAP = {
    'X Depo': '002',                   # İNTERNET MAĞAZA DEPO
    'HEYKEL MAĞAZA DEPO': 'D001',      # HEYKEL MAĞAZA DEPO
}


class ShelfImportProcessor(models.AbstractModel):
    _name = 'odoougurlar.shelf.import.processor'
    _description = 'HamurLabs Raf Import Processor'

    def import_shelves(self):
        """
        HamurLabs Excel dosyalarından raf lokasyonları ve
        ürün-raf eşlemelerini Odoo'ya import eder.
        """
        try:
            import pandas as pd
        except ImportError:
            _logger.error("pandas kütüphanesi bulunamadı!")
            return {'error': 'pandas kütüphanesi bulunamadı'}

        stats = {
            'locations_created': 0,
            'locations_existing': 0,
            'products_placed': 0,
            'products_not_found': 0,
            'errors': 0,
        }

        # ─── 1. RAF DOSYALARINI İŞLE ──────────────────────────
        shelf_files = [
            ('x depo raflar.xls', 'X Depo'),
            ('heykel depo raf.xls', 'HEYKEL MAĞAZA DEPO'),
        ]

        # barcode → location_id eşleme cache
        barcode_to_location = {}

        for filename, depot_name in shelf_files:
            filepath = os.path.join(DATA_DIR, filename)
            if not os.path.exists(filepath):
                _logger.warning("Dosya bulunamadı: %s", filepath)
                continue

            _logger.info("Raf dosyası okunuyor: %s", filename)
            df = pd.read_excel(filepath, engine='openpyxl')
            _logger.info("  %d satır okundu", len(df))

            # ── Sütun ismi normalleştirme (TR ↔ EN desteği) ──
            column_map = {
                # İngilizce → Türkçe (kodun beklediği form)
                'Path': 'Yol',
                'Name': 'Adı',
                'Unique Code': 'Tekil Barkod',
                'Total Quantity': 'Toplam Adet',
                'Type': 'Sipariş Tipi',
                'Code': 'Kod',
                'Is Pick': 'Toplama mı',
                'Warehouse': 'Depo',
            }
            df.rename(columns=column_map, inplace=True)
            _logger.info("  Sütunlar: %s", ', '.join(df.columns[:5]))

            # Ana stok lokasyonunu bul
            wh_code = DEPOT_MAP.get(depot_name)
            warehouse = self.env['stock.warehouse'].sudo().search(
                [('code', '=', wh_code)], limit=1
            )
            if not warehouse:
                _logger.error("Depo bulunamadı: %s (kod: %s)", depot_name, wh_code)
                continue

            parent_location_id = warehouse.lot_stock_id.id
            _logger.info("  Depo: %s (loc_id=%d)", warehouse.name, parent_location_id)

            # Hiyerarşi cache: path_part → location_id
            path_cache = {}

            for idx, row in df.iterrows():
                try:
                    yol = str(row.get('Yol', '')).strip()
                    adi = str(row.get('Adı', '')).strip()
                    barkod = str(row.get('Tekil Barkod', '')).strip()

                    if not yol or not barkod:
                        continue

                    # Yol parse: "X Depo - XA1 - K1 - 001" → parts
                    parts = [p.strip() for p in yol.split(' - ')]
                    if len(parts) < 2:
                        continue

                    # İlk kısım depo adı, geri kalanı hiyerarşi
                    hierarchy = parts[1:]  # ['XA1', 'K1', '001']

                    # Üst lokasyonları kademeli oluştur
                    current_parent = parent_location_id
                    for i, part in enumerate(hierarchy):
                        cache_key = f"{wh_code}:{'/'.join(hierarchy[:i+1])}"

                        if cache_key in path_cache:
                            current_parent = path_cache[cache_key]
                            continue

                        # Bu seviyede var mı?
                        existing = self.env['stock.location'].sudo().search([
                            ('name', '=', part),
                            ('location_id', '=', current_parent),
                            ('usage', '=', 'internal'),
                        ], limit=1)

                        if existing:
                            path_cache[cache_key] = existing.id
                            current_parent = existing.id
                        else:
                            # Son seviye mi? (raf bin) → barcode ata
                            is_leaf = (i == len(hierarchy) - 1)
                            vals = {
                                'name': part,
                                'location_id': current_parent,
                                'usage': 'internal',
                            }
                            if is_leaf and barkod:
                                vals['barcode'] = barkod

                            new_loc = self.env['stock.location'].sudo().create(vals)
                            path_cache[cache_key] = new_loc.id
                            current_parent = new_loc.id
                            if is_leaf:
                                stats['locations_created'] += 1

                    # Son lokasyonun barcode → location_id
                    leaf_key = f"{wh_code}:{'/'.join(hierarchy)}"
                    barcode_to_location[barkod] = path_cache.get(leaf_key, current_parent)

                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 5:
                        _logger.error("Raf import hatası row=%d: %s", idx, str(e))

            self.env.cr.commit()
            _logger.info("  %s rafları tamamlandı", depot_name)

        _logger.info(
            "Raf import: %d oluşturuldu, %d barcode eşlendi",
            stats['locations_created'], len(barcode_to_location)
        )

        # Mevcut raf barkodlarını da cache'e ekle
        self.env.cr.execute("""
            SELECT barcode, id FROM stock_location
            WHERE barcode IS NOT NULL AND barcode != ''
        """)
        for bc, loc_id in self.env.cr.fetchall():
            if bc not in barcode_to_location:
                barcode_to_location[bc] = loc_id

        # ─── 2. ÜRÜN-RAF EŞLEMELERİNİ İŞLE ──────────────────
        product_files = [
            ('x depo ürünler.xlsx', 'X Depo'),
            ('heykel depo ürünler.xlsx', 'HEYKEL MAĞAZA DEPO'),
        ]

        # Ürün barcode → product_id cache
        self.env.cr.execute("""
            SELECT barcode, id FROM product_product
            WHERE barcode IS NOT NULL AND barcode != '' AND active = true
        """)
        product_barcode_map = {bc: pid for bc, pid in self.env.cr.fetchall()}

        # nebim_barcode'ları da ekle
        self.env.cr.execute("""
            SELECT nebim_barcode, id FROM product_product
            WHERE nebim_barcode IS NOT NULL AND nebim_barcode != '' AND active = true
        """)
        for nbc, pid in self.env.cr.fetchall():
            for bc in nbc.split(','):
                bc = bc.strip()
                if bc and bc not in product_barcode_map:
                    product_barcode_map[bc] = pid

        _logger.info("Ürün barcode cache: %d ürün", len(product_barcode_map))

        StockQuant = self.env['stock.quant'].sudo().with_context(inventory_mode=True)
        not_found_samples = []

        for filename, depot_name in product_files:
            filepath = os.path.join(DATA_DIR, filename)
            if not os.path.exists(filepath):
                _logger.warning("Dosya bulunamadı: %s", filepath)
                continue

            _logger.info("Ürün-raf dosyası okunuyor: %s", filename)
            df = pd.read_excel(filepath, engine='openpyxl')
            _logger.info("  %d satır okundu", len(df))

            # Depo lokasyon ID'lerini önceden bul
            wh_code = DEPOT_MAP.get(depot_name)
            wh = self.env['stock.warehouse'].sudo().search(
                [('code', '=', wh_code)], limit=1
            )
            fallback_location_id = wh.lot_stock_id.id if wh else None

            # Quant cache: (product_id, location_id) → quant record
            all_loc_ids = list(set(barcode_to_location.values()))
            if fallback_location_id:
                all_loc_ids.append(fallback_location_id)
            all_loc_ids = list(set(lid for lid in all_loc_ids if lid))

            quant_cache = {}
            if all_loc_ids:
                existing_quants = StockQuant.search([
                    ('location_id', 'in', all_loc_ids),
                ])
                for q in existing_quants:
                    quant_cache[(q.product_id.id, q.location_id.id)] = q

            _logger.info("  Quant cache: %d kayıt yüklendi", len(quant_cache))

            for idx, row in df.iterrows():
                try:
                    barkod = str(row.get('Barkod', '') or '').strip()
                    ean = str(row.get('EAN', '') or '').strip()
                    raf_tekil = str(row.get('Raf Tekil Kodu', '') or '').strip()
                    raf_miktar = row.get('Raf Miktarı', 0)

                    try:
                        raf_miktar = float(raf_miktar)
                    except (ValueError, TypeError):
                        raf_miktar = 0

                    if raf_miktar <= 0:
                        continue

                    product_id = product_barcode_map.get(barkod) or product_barcode_map.get(ean)
                    if not product_id:
                        stats['products_not_found'] += 1
                        if len(not_found_samples) < 10:
                            not_found_samples.append(f"{row.get('Ürün Kodu', '?')}-{barkod}")
                        continue

                    location_id = barcode_to_location.get(raf_tekil)
                    if not location_id:
                        if raf_tekil.isdigit() and fallback_location_id:
                            location_id = fallback_location_id
                        if not location_id:
                            stats['products_not_found'] += 1
                            continue

                    # Dict lookup ile quant kontrol (0 sorgu)
                    cache_key = (product_id, location_id)
                    existing = quant_cache.get(cache_key)

                    if existing:
                        existing.write({'quantity': raf_miktar})
                    else:
                        new_quant = StockQuant.create({
                            'product_id': product_id,
                            'location_id': location_id,
                            'quantity': raf_miktar,
                        })
                        quant_cache[cache_key] = new_quant
                    stats['products_placed'] += 1

                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 5:
                        _logger.error("Ürün-raf hatası row=%d: %s", idx, str(e))

            self.env.cr.commit()
            _logger.info("  %s ürün eşlemeleri tamamlandı", depot_name)

        if not_found_samples:
            _logger.warning(
                "Ürün-raf: %d ürün bulunamadı. Örnekler: %s",
                stats['products_not_found'], ', '.join(not_found_samples)
            )

        _logger.info(
            "Raf import tamamlandı: %d lokasyon, %d ürün yerleştirildi, %d bulunamadı, %d hata",
            stats['locations_created'], stats['products_placed'],
            stats['products_not_found'], stats['errors']
        )

        return stats

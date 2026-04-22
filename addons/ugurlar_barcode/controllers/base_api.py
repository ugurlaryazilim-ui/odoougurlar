"""Ortak yardımcı fonksiyonlar — tüm controller'lar bu mixin'i kullanır."""
import json
import logging
import time
import hashlib

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Basit in-process duplicate guard (son istek hash'i + timestamp)
_last_requests = {}  # key: user_id + endpoint + args_hash → timestamp
_DEBOUNCE_SECONDS = 0.5  # 500ms içinde aynı istek tekrarlanırsa atla


class BarcodeApiBase(http.Controller):
    """Ortak yardımcı fonksiyonlar."""

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False, default=str),
            content_type='application/json',
            status=status,
        )

    def _check_duplicate_request(self, endpoint, *args):
        """Aynı kullanıcıdan 500ms içinde tekrarlanan aynı isteği algıla.

        Returns:
            True if duplicate (should skip), False if OK to proceed
        """
        try:
            uid = request.env.uid or 0
            args_str = str(args)
            key = f"{uid}:{endpoint}:{hashlib.md5(args_str.encode()).hexdigest()}"
            now = time.time()

            last_time = _last_requests.get(key, 0)
            if now - last_time < _DEBOUNCE_SECONDS:
                return True  # Duplicated

            _last_requests[key] = now

            # Bellek temizliği: 1000'den fazla kayıt varsa eski olanları sil
            if len(_last_requests) > 1000:
                cutoff = now - 60
                expired = [k for k, v in _last_requests.items() if v < cutoff]
                for k in expired:
                    del _last_requests[k]
        except Exception:
            pass
        return False

    def _find_product(self, barcode):
        """Barkod ile ürün bul (barcode + nebim_barcode + default_code)."""
        Product = request.env['product.product'].sudo()
        product = Product.search([('barcode', '=', barcode)], limit=1)
        if not product:
            # Performans Optimizasyonu: Sadece barkodu içeren ürünleri DB'den çek
            products = Product.search([('nebim_barcode', 'ilike', barcode)])
            for p in products:
                if barcode in (p.nebim_barcode or '').split(','):
                    return p
        if not product:
            product = Product.search([('default_code', '=', barcode)], limit=1)
        return product

    def _find_location(self, barcode):
        """Barkod veya isim ile stok lokasyonu bul."""
        Location = request.env['stock.location'].sudo()
        location = Location.search([
            ('barcode', '=', barcode), ('usage', '=', 'internal'),
        ], limit=1)
        if not location:
            location = Location.search([
                ('name', 'ilike', barcode), ('usage', '=', 'internal'),
            ], limit=1)
        return location

    def _get_marka(self, tmpl, cache=None):
        """Template'tan marka bilgisini al (cache destekli)."""
        if cache is not None and tmpl.id in cache:
            return cache[tmpl.id]
        marka = ''
        for line in tmpl.attribute_line_ids:
            if line.attribute_id.name == 'Marka' and line.attribute_id.create_variant == 'no_variant':
                marka = ', '.join(line.value_ids.mapped('name'))
                break
        if cache is not None:
            cache[tmpl.id] = marka
        return marka

    # ═══ GÜVENLİ STOK İŞLEMLERİ ═══

    def _safe_update_quant(self, product, location, qty_delta):
        """Stok miktarını güvenli şekilde güncelle.

        Odoo'nun _update_available_quantity API'sini kullanır.
        Concurrency lock ile race-condition önlenir.

        Args:
            product: product.product recordset
            location: stock.location recordset
            qty_delta: + ekle, - çıkar

        Returns:
            Güncellenmiş toplam miktar
        """
        StockQuant = request.env['stock.quant'].sudo()

        # Concurrency Lock
        request.env.cr.execute(
            "SELECT id, quantity FROM stock_quant WHERE product_id=%s AND location_id=%s FOR UPDATE",
            (product.id, location.id)
        )
        row = request.env.cr.fetchone()

        if row:
            existing = StockQuant.browse(row[0])
            new_qty = existing.quantity + qty_delta
            if new_qty <= 0:
                existing.sudo().unlink()
                return 0
            else:
                existing.sudo().write({'quantity': new_qty})
                return new_qty
        elif qty_delta > 0:
            StockQuant.create({
                'product_id': product.id,
                'location_id': location.id,
                'quantity': qty_delta,
            })
            return qty_delta
        return 0

    def _safe_move_quant(self, product, source_loc, target_loc, quantity):
        """Ürünü bir raftan diğerine güvenli şekilde taşı.

        Her iki taraf da concurrency lock ile korunur.

        Args:
            product: product.product
            source_loc: kaynak stock.location
            target_loc: hedef stock.location
            quantity: taşınacak miktar

        Returns:
            (success: bool, error_msg: str or None)
        """
        # Kaynak kontrol ve lock
        request.env.cr.execute(
            "SELECT id, quantity FROM stock_quant WHERE product_id=%s AND location_id=%s AND quantity > 0 FOR UPDATE",
            (product.id, source_loc.id)
        )
        source_row = request.env.cr.fetchone()

        if not source_row:
            return False, f'{product.name} kaynak rafta bulunamadı'

        source_qty = source_row[1]
        if source_qty < quantity:
            return False, f'Yetersiz stok! Kaynak: {source_qty}, İstenen: {quantity}'

        StockQuant = request.env['stock.quant'].sudo()
        source_quant = StockQuant.browse(source_row[0])

        # Kaynaktan düş
        new_source = source_qty - quantity
        if new_source <= 0:
            source_quant.unlink()
        else:
            source_quant.write({'quantity': new_source})

        # Hedefe ekle (lock ile)
        request.env.cr.execute(
            "SELECT id, quantity FROM stock_quant WHERE product_id=%s AND location_id=%s FOR UPDATE",
            (product.id, target_loc.id)
        )
        target_row = request.env.cr.fetchone()

        if target_row:
            target_quant = StockQuant.browse(target_row[0])
            target_quant.write({'quantity': target_quant.quantity + quantity})
        else:
            StockQuant.create({
                'product_id': product.id,
                'location_id': target_loc.id,
                'quantity': quantity,
            })

        return True, None


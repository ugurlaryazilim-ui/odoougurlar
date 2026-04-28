"""Raf İşlemleri API — shelf_search, shelf_control, putaway, remove_from_shelf."""
import logging
from markupsafe import Markup

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class ShelfApiController(BarcodeApiBase):
    """Raf arama, kontrol, raflama ve raftan kaldırma API'leri."""

    # ─── RAF ARAMA (ürün barkodu ile raf bul) ─────────────
    @http.route('/ugurlar_barcode/api/shelf_search', type='json', auth='user')
    def shelf_search(self, barcode='', **kw):
        """Ürün barkodu ile ürünün bulunduğu rafları bul (HamurLabs uyumlu)."""
        if not barcode:
            return {'error': 'Barkod giriniz'}

        barcode = barcode.strip()
        product = self._find_product(barcode)

        if not product:
            return {'error': f'Ürün bulunamadı: {barcode}'}

        tmpl = product.product_tmpl_id
        _marka_cache = {}

        # Ürün özelliklerini al
        color = ''
        size = ''
        for ptav in product.product_template_attribute_value_ids:
            attr_name = ptav.attribute_id.name
            if attr_name == 'Renk':
                color = ptav.name
            elif attr_name == 'Beden':
                size = ptav.name

        marka = self._get_marka(tmpl, _marka_cache)

        # Raf konumları
        quants = request.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])

        total_stock = sum(q.quantity for q in quants)
        shelves = []
        for q in quants:
            loc = q.location_id
            shelves.append({
                'location_name': loc.complete_name,
                'location_barcode': loc.barcode or '',
                'quantity': q.quantity,
                'warehouse': loc.warehouse_id.name if loc.warehouse_id else '',
                'location_id': loc.id,
            })

        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'shelf_search',
            'barcode': barcode,
            'product_id': product.id,
            'state': 'done',
        })

        return {
            'product': {
                'id': product.id,
                'name': product.name,
                'code': tmpl.nebim_code or product.default_code or '',
                'barcode': product.barcode or '',
                'color': color,
                'size': size,
                'marka': marka,
                'price': product.list_price,
                'total_stock': total_stock,
            },
            'shelves': shelves,
        }

    # ─── RAF KONTROL (raf barkodu ile ürünleri listele) ───
    @http.route('/ugurlar_barcode/api/shelf_control', type='json', auth='user')
    def shelf_control(self, barcode='', **kw):
        """Raf barkodu/adı ile o raftaki ürünleri listele (HamurLabs uyumlu)."""
        if not barcode:
            return {'error': 'Raf barkodu giriniz'}

        barcode = barcode.strip()
        location = self._find_location(barcode)

        if not location:
            return {'error': f'Raf bulunamadı: {barcode}'}

        quants = request.env['stock.quant'].sudo().search([
            ('location_id', '=', location.id),
            ('quantity', '>', 0),
        ])

        _marka_cache = {}
        products = []
        for q in quants:
            p = q.product_id
            tmpl = p.product_tmpl_id
            products.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode or '',
                'code': tmpl.nebim_code or p.default_code or '',
                'marka': self._get_marka(tmpl, _marka_cache),
                'quantity': q.quantity,
            })

        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'shelf_control',
            'barcode': barcode,
            'location_id': location.id,
            'state': 'done',
        })

        return {
            'location': {
                'id': location.id,
                'name': location.name,
                'complete_name': location.complete_name,
                'barcode': location.barcode or '',
                'warehouse': location.warehouse_id.name if location.warehouse_id else '',
            },
            'products': products,
            'total_products': len(products),
            'total_quantity': sum(p['quantity'] for p in products),
        }

    # ─── RAFLAMA (ürün → raf) ─────────────────────────────
    @http.route('/ugurlar_barcode/api/putaway', type='json', auth='user')
    def putaway(self, product_barcode='', shelf_barcode='', quantity=1, **kw):
        """Ürünü rafa yerleştir (concurrency-safe)."""
        if not product_barcode or not shelf_barcode:
            return {'error': 'Ürün ve raf barkodu gerekli'}

        product_barcode = product_barcode.strip()
        shelf_barcode = shelf_barcode.strip()
        quantity = float(quantity or 1)

        product = self._find_product(product_barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {product_barcode}'}

        dest_location = self._find_location(shelf_barcode)
        if not dest_location:
            return {'error': f'Raf bulunamadı: {shelf_barcode}'}

        # Güvenli stok güncelleme
        self._safe_update_quant(product, dest_location, quantity)

        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'putaway',
            'barcode': product_barcode,
            'product_id': product.id,
            'location_id': dest_location.id,
            'quantity': quantity,
            'state': 'done',
        })

        # Ürün chatter log
        user = request.env.user
        msg = Markup(
            '<b>📦 Raflama:</b> <em>%s</em> tarafından '
            '<b>%d</b> adet '
            '<b>%s</b> rafına yerleştirildi.'
        ) % (user.name, int(quantity), dest_location.complete_name)
        self._log_chatter(product, msg)

        return {
            'success': True,
            'message': f'{product.name} → {dest_location.complete_name} ({quantity} adet)',
            'product_name': product.name,
            'location_name': dest_location.complete_name,
            'quantity': quantity,
        }

    # ─── RAFTAN KALDIRMA ──────────────────────────────────
    @http.route('/ugurlar_barcode/api/remove_from_shelf', type='json', auth='user')
    def remove_from_shelf(self, product_barcode='', shelf_barcode='', quantity=1, **kw):
        """Ürünü raftan kaldır (concurrency-safe)."""
        if not product_barcode or not shelf_barcode:
            return {'error': 'Ürün ve raf barkodu gerekli'}

        product_barcode = product_barcode.strip()
        shelf_barcode = shelf_barcode.strip()
        quantity = float(quantity or 1)

        product = self._find_product(product_barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {product_barcode}'}

        location = self._find_location(shelf_barcode)
        if not location:
            return {'error': f'Raf bulunamadı: {shelf_barcode}'}

        # Mevcut stok kontrolü (ORM — lock ile)
        row = self._lock_quant(product.id, location.id, positive_only=True)
        if not row:
            return {'error': 'Bu üründe rafta stok yok'}

        # Güvenli stok güncelleme (negatif delta = çıkarma)
        self._safe_update_quant(product, location, -quantity)

        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'remove',
            'barcode': product_barcode,
            'product_id': product.id,
            'location_id': location.id,
            'quantity': quantity,
            'state': 'done',
        })

        # Ürün chatter log
        user = request.env.user
        msg = Markup(
            '<b>📤 Raftan Kaldırma:</b> <em>%s</em> tarafından '
            '<b>%d</b> adet '
            '<b>%s</b> rafından kaldırıldı.'
        ) % (user.name, int(quantity), location.complete_name)
        self._log_chatter(product, msg)

        return {
            'success': True,
            'message': f'{product.name} raftan kaldırıldı ({quantity} adet)',
        }

    # ─── RAF TAŞIMA (kaynak → hedef) ──────────────────────
    @http.route('/ugurlar_barcode/api/shelf_transfer', type='json', auth='user')
    def shelf_transfer(self, product_barcode='', source_shelf_barcode='',
                       target_shelf_barcode='', quantity=1, reason='', **kw):
        """Ürünü bir raftan başka bir rafa taşı (concurrency-safe)."""
        if not product_barcode or not source_shelf_barcode or not target_shelf_barcode:
            return {'error': 'Ürün, kaynak raf ve hedef raf barkodu gerekli'}

        product_barcode = product_barcode.strip()
        source_shelf_barcode = source_shelf_barcode.strip()
        target_shelf_barcode = target_shelf_barcode.strip()
        quantity = float(quantity or 1)

        if source_shelf_barcode == target_shelf_barcode:
            return {'error': 'Kaynak ve hedef raf aynı olamaz'}

        product = self._find_product(product_barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {product_barcode}'}

        source_loc = self._find_location(source_shelf_barcode)
        if not source_loc:
            return {'error': f'Kaynak raf bulunamadı: {source_shelf_barcode}'}

        target_loc = self._find_location(target_shelf_barcode)
        if not target_loc:
            return {'error': f'Hedef raf bulunamadı: {target_shelf_barcode}'}

        # Güvenli taşıma (her iki tarafta lock)
        success, error = self._safe_move_quant(product, source_loc, target_loc, quantity)
        if not success:
            return {'error': error}

        # İşlem kaydı
        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'shelf_transfer',
            'barcode': product_barcode,
            'product_id': product.id,
            'location_id': target_loc.id,
            'quantity': quantity,
            'state': 'done',
        })

        # Ürün chatter log
        user = request.env.user
        reason_map = {
            'reorganize': 'Reorganizasyon', 'demand': 'Talep Değişimi',
            'damage': 'Hasar', 'return': 'İade',
            'season': 'Sezon Değişimi', 'other': 'Diğer',
        }
        reason_txt = reason_map.get(reason, '')
        msg = Markup(
            '<b>🔄 Raf Taşıma:</b> <em>%s</em> tarafından '
            '<b>%d</b> adet '
            '<b>%s</b> &rarr; <b>%s</b> taşındı.'
        ) % (user.name, int(quantity), source_loc.complete_name, target_loc.complete_name)
        if reason_txt:
            msg += Markup(' <i>(Neden: %s)</i>') % reason_txt
        self._log_chatter(product, msg)

        return {
            'success': True,
            'message': f'{product.name}: {source_loc.complete_name} → {target_loc.complete_name} ({int(quantity)} adet)',
            'product_name': product.name,
            'source_location': source_loc.complete_name,
            'target_location': target_loc.complete_name,
            'quantity': quantity,
        }

    # ─── TÜM RAFI TAŞI ──────────────────────────────────────
    @http.route('/ugurlar_barcode/api/shelf_move_all', type='json', auth='user')
    def shelf_move_all(self, source_barcode='', target_barcode='', reason='', **kw):
        """Kaynak raftaki TÜM ürünleri hedef rafa taşı (concurrency-safe)."""
        source_barcode = (source_barcode or '').strip()
        target_barcode = (target_barcode or '').strip()

        if not source_barcode or not target_barcode:
            return {'error': 'Kaynak ve hedef raf barkodu gerekli'}

        if source_barcode == target_barcode:
            return {'error': 'Kaynak ve hedef raf ayni olamaz'}

        source_loc = self._find_location(source_barcode)
        if not source_loc:
            return {'error': f'Kaynak raf bulunamadi: {source_barcode}'}

        target_loc = self._find_location(target_barcode)
        if not target_loc:
            return {'error': f'Hedef raf bulunamadi: {target_barcode}'}

        # Kaynak raftaki tüm ürünler
        StockQuant = request.env['stock.quant'].sudo()
        source_quants = StockQuant.search([
            ('location_id', '=', source_loc.id),
            ('quantity', '>', 0),
        ])

        if not source_quants:
            return {'error': 'Kaynak rafta urun yok'}

        user = request.env.user
        reason_map = {
            'reorganize': 'Reorganizasyon', 'demand': 'Talep Degisimi',
            'damage': 'Hasar', 'return': 'Iade',
            'season': 'Sezon Degisimi', 'other': 'Diger',
        }
        reason_txt = reason_map.get(reason, '')

        moved_count = 0
        total_quantity = 0

        for quant in source_quants:
            product = quant.product_id
            qty = quant.quantity

            # Güvenli taşıma (lock ile)
            success, _ = self._safe_move_quant(product, source_loc, target_loc, qty)
            if not success:
                continue

            # İşlem kaydı
            request.env['ugurlar.barcode.operation'].sudo().create({
                'operation_type': 'shelf_transfer',
                'barcode': product.barcode or '',
                'product_id': product.id,
                'location_id': target_loc.id,
                'quantity': qty,
                'notes': f'Tum raf tasima: {source_loc.complete_name} -> {target_loc.complete_name}',
                'state': 'done',
            })

            # Varyant chatter log
            msg = Markup(
                '<b>&#x1F69A; Tüm Raf Taşıma:</b> <em>%s</em> tarafından '
                '<b>%d</b> adet '
                '<b>%s</b> &rarr; <b>%s</b> taşındı.'
            ) % (user.name, int(qty), source_loc.complete_name, target_loc.complete_name)
            if reason_txt:
                msg += Markup(' <i>(Neden: %s)</i>') % reason_txt
            self._log_chatter(product, msg)

            moved_count += 1
            total_quantity += qty

        return {
            'success': True,
            'moved_count': moved_count,
            'total_quantity': int(total_quantity),
            'source': source_loc.complete_name,
            'target': target_loc.complete_name,
            'message': f'{moved_count} urun {source_loc.complete_name} -> {target_loc.complete_name} tasindi',
        }

    # ─── TOPLU RAF SİLME ─────────────────────────────────────
    @http.route('/ugurlar_barcode/api/shelf_clear_all', type='json', auth='user')
    def shelf_clear_all(self, shelf_barcode='', **kw):
        """Raftaki TÜM ürünleri kaldır (concurrency-safe)."""
        shelf_barcode = (shelf_barcode or '').strip()
        if not shelf_barcode:
            return {'error': 'Raf barkodu gerekli'}

        location = self._find_location(shelf_barcode)
        if not location:
            return {'error': f'Raf bulunamadi: {shelf_barcode}'}

        StockQuant = request.env['stock.quant'].sudo()
        quants = StockQuant.search([
            ('location_id', '=', location.id),
            ('quantity', '>', 0),
        ])

        if not quants:
            return {'error': 'Rafta urun yok'}

        user = request.env.user
        cleared_count = 0
        total_quantity = 0

        for quant in quants:
            product = quant.product_id
            qty = quant.quantity

            # İşlem kaydı
            request.env['ugurlar.barcode.operation'].sudo().create({
                'operation_type': 'remove',
                'barcode': product.barcode or '',
                'product_id': product.id,
                'location_id': location.id,
                'quantity': qty,
                'notes': f'Toplu raf silme: {location.complete_name}',
                'state': 'done',
            })

            # Varyant chatter log
            msg = Markup(
                '<b>&#x1F5D1; Toplu Raf Silme:</b> <em>%s</em> tarafından '
                '<b>%d</b> adet '
                '<b>%s</b> rafından kaldırıldı.'
            ) % (user.name, int(qty), location.complete_name)
            self._log_chatter(product, msg)

            # Güvenli kaldırma (lock ile)
            self._safe_update_quant(product, location, -qty)

            cleared_count += 1
            total_quantity += qty

        return {
            'success': True,
            'cleared_count': cleared_count,
            'total_quantity': int(total_quantity),
            'shelf': location.complete_name,
            'message': f'{cleared_count} urun {location.complete_name} rafindan kaldirildi',
        }

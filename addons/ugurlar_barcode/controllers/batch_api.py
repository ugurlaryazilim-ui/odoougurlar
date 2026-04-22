"""Batch Toplama Listesi API — batch_list, batch_detail, batch_create."""
import logging

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class BatchApiController(BarcodeApiBase):
    """Toplama listesi (batch) API'leri.

    _get_product_location_map helper'ı buradaki batch_detail ve
    batch_route_items tarafından paylaşılır.
    """

    def _get_product_location_map(self, batch, detailed=False):
        """Batch'teki ürünlerin raf konumlarını toplu sorgula.

        Args:
            batch: stock.picking.batch recordset
            detailed: True ise lokasyon parçalarını da döndür

        Returns:
            dict: {product_id: location_name} veya
                  {product_id: {'location_name': ..., 'location_parts': ...}}
        """
        product_ids = batch.picking_ids.mapped('move_ids.product_id').ids
        result = {}

        warehouse = batch.picking_type_id.warehouse_id
        if not product_ids or not warehouse or not warehouse.lot_stock_id:
            return result

        quants = request.env['stock.quant'].sudo().search([
            ('product_id', 'in', product_ids),
            ('location_id', 'child_of', warehouse.lot_stock_id.id),
            ('quantity', '>', 0),
        ], order='quantity desc')

        for q in quants:
            if q.product_id.id in result:
                continue

            loc = q.location_id
            location_name = loc.complete_name or loc.name

            if not detailed:
                result[q.product_id.id] = location_name
            else:
                parts = [p.strip() for p in location_name.split('/')]
                if len(parts) >= 5:
                    location_parts = {
                        'warehouse': f"{parts[0]}/{parts[1]}",
                        'zone': parts[2],
                        'section': parts[3],
                        'shelf': parts[4],
                    }
                elif len(parts) == 4:
                    location_parts = {
                        'warehouse': f"{parts[0]}/{parts[1]}",
                        'zone': parts[2],
                        'section': '',
                        'shelf': parts[3],
                    }
                elif len(parts) == 3:
                    location_parts = {
                        'warehouse': parts[0],
                        'zone': parts[1],
                        'section': '',
                        'shelf': parts[2],
                    }
                else:
                    location_parts = {
                        'warehouse': parts[0] if len(parts) > 0 else '',
                        'zone': parts[1] if len(parts) > 1 else '',
                        'section': '',
                        'shelf': '',
                    }

                result[q.product_id.id] = {
                    'location_name': location_name,
                    'location_parts': location_parts,
                }

        return result

    @http.route('/ugurlar_barcode/api/batch_list', type='jsonrpc', auth='user')
    def batch_list(self, **kw):
        """Günün batch'lerini listele."""
        from datetime import datetime, timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        batches = request.env['stock.picking.batch'].sudo().search([
            ('schedule_time', '>=', today),
            ('schedule_time', '<', tomorrow),
        ], order='schedule_time desc')

        if not batches:
            # Bugün batch yoksa son 7 gündeki tümünü al
            batches = request.env['stock.picking.batch'].sudo().search([
                ('time_window', '!=', False),
            ], order='schedule_time desc', limit=20)

        result = []
        for b in batches:
            result.append({
                'id': b.id,
                'name': b.name,
                'state': b.state,
                'time_window': b.time_window or '',
                'schedule_time': str(b.schedule_time or ''),
                'total_orders': b.total_orders,
                'total_items': b.total_items,
                'available_count': b.available_count,
                'other_warehouse_count': b.other_warehouse_count,
                'unavailable_count': b.unavailable_count,
                'user': b.user_id.name or '',
            })

        return {'batches': result, 'total': len(result)}

    @http.route('/ugurlar_barcode/api/batch_detail', type='jsonrpc', auth='user')
    def batch_detail(self, batch_id=0, **kw):
        """Batch detayı — picking'ler ve ürün satırları."""
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Batch bulunamadı'}

        pickings = []
        all_products = {}  # product_id → toplam bilgi (rota sıralaması için)

        # Toplu ürün lokasyon haritası
        location_dict = self._get_product_location_map(batch, detailed=False)

        for p in batch.picking_ids.sorted(key=lambda x: x.name):
            picking_lines = []
            for move in p.move_ids:
                product = move.product_id
                barcode = product.barcode or ''

                # Ürün raf konumunu toplu dict üzerinden al
                location = location_dict.get(product.id, '')

                line_data = {
                    'move_id': move.id,
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'barcode': barcode,
                    'demand_qty': move.product_uom_qty,
                    'done_qty': move.quantity,
                    'location': location,
                    'image_url': f'/web/image/product.product/{product.id}/image_128',
                }
                picking_lines.append(line_data)

                # Toplam ürün listesi (rota için)
                key = product.id
                if key not in all_products:
                    all_products[key] = {
                        'product_id': product.id,
                        'product_name': product.display_name,
                        'barcode': barcode,
                        'location': location,
                        'total_qty': 0,
                        'collected_qty': 0,
                    }
                all_products[key]['total_qty'] += move.product_uom_qty
                all_products[key]['collected_qty'] += move.quantity

            pickings.append({
                'id': p.id,
                'name': p.name,
                'partner': p.partner_id.name or '',
                'origin': p.origin or '',
                'state': p.state,
                'availability_status': p.availability_status or '',
                'source_warehouse_info': p.source_warehouse_info or '',
                'lines': picking_lines,
            })

        # Rota sıralaması: lokasyona göre sırala
        route_products = sorted(
            all_products.values(),
            key=lambda x: x.get('location', '') or 'ZZZ')

        return {
            'batch': {
                'id': batch.id,
                'name': batch.name,
                'state': batch.state,
                'time_window': batch.time_window or '',
                'total_orders': batch.total_orders,
                'total_items': batch.total_items,
            },
            'pickings': pickings,
            'route_products': route_products,
        }

    @http.route('/ugurlar_barcode/api/batch_create_now', type='jsonrpc', auth='user')
    def batch_create_now(self, **kw):
        """Manuel batch oluştur — şu anki zaman penceresi."""
        Schedule = request.env['ugurlar.picking.schedule'].sudo()
        schedules = Schedule.search([('active', '=', True)], limit=1)
        if not schedules:
            return {'error': 'Aktif toplama zamanlaması bulunamadı'}

        try:
            batch = schedules[0]._create_batch_for_current_window()
            if batch:
                return {
                    'success': True,
                    'batch_id': batch.id,
                    'batch_name': batch.name,
                    'total_orders': batch.total_orders,
                }
            return {'error': 'Bu zaman diliminde bekleyen sipariş yok'}
        except Exception as e:
            return {'error': str(e)}

    # ═══════════════════════════════════════════════════════
    # ROTA TOPLAMA (WAVE PICKING) API'LERİ
    # ═══════════════════════════════════════════════════════

    @http.route('/ugurlar_barcode/api/batch_route_items', type='jsonrpc', auth='user')
    def batch_route_items(self, batch_id=0, **kw):
        """Rota ürünlerini raf lokasyonuna göre sıralı döndür."""
        try:
            batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
            if not batch.exists():
                return {'error': 'Rota bulunamadı'}


            # Toplu ürün lokasyon haritası (detaylı: zone/section/shelf parçaları ile)
            location_data_dict = self._get_product_location_map(batch, detailed=True)

            # Tüm move'ları topla
            route_items = []
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    product = move.product_id

                    # Önceden çekilen toplu dict'ten raf konumunu bul
                    loc_data = location_data_dict.get(product.id, {'location_name': '', 'location_parts': {}})
                    location_name = loc_data.get('location_name', '')
                    location_parts = loc_data.get('location_parts', {})

                    # Varyant bilgisi (renk, beden vs)
                    variant_info = ''
                    if hasattr(product, 'product_template_variant_value_ids'):
                        vals = product.product_template_variant_value_ids
                        if vals:
                            variant_info = ', '.join(
                                v.name for v in vals)

                    route_items.append({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'picking_name': picking.name,
                        'product_id': product.id,
                        'product_name': product.name or product.display_name,
                        'display_name': product.display_name,
                        'default_code': product.default_code or '',
                        'barcode': product.barcode or '',
                        'variant_info': variant_info,
                        'demand_qty': move.product_uom_qty,
                        'collected_qty': move.wave_collected_qty or 0,
                        'location': location_name,
                        'location_parts': location_parts,
                        'image_url': f'/web/image/product.product/{product.id}/image_256',
                        'origin': picking.origin or '',
                        'partner_name': picking.partner_id.name or '',
                    })

            # Lokasyona göre sırala (aynı raftakiler bir arada)
            route_items.sort(key=lambda x: x.get('location') or 'ZZZ')

            total = len(route_items)
            collected = sum(1 for i in route_items if i['collected_qty'] >= i['demand_qty'])

            return {
                'batch': {
                    'id': batch.id,
                    'name': batch.name,
                    'state': batch.state,
                    'time_window': batch.time_window or '',
                    'source_info': batch.source_info or '',
                    'total_orders': batch.total_orders,
                },
                'items': route_items,
                'total': total,
                'collected': collected,
                'all_collected': collected == total and total > 0,
            }
        except Exception as e:
            _logger.exception("batch_route_items hatası: %s", e)
            return {'error': f'Rota yükleme hatası: {str(e)}'}

    @http.route('/ugurlar_barcode/api/batch_collect_scan', type='jsonrpc', auth='user')
    def batch_collect_scan(self, batch_id=0, barcode='', **kw):
        """Rota toplama sırasında barkod tara → wave_collected_qty artır.

        Toplama aşaması: sadece 'raftan aldım' demek.
        Gerçek done_qty paketleme aşamasında artırılır.
        """
        # Duplicate guard
        if self._check_duplicate_request('batch_collect_scan', batch_id, barcode):
            return {'warning': True, 'message': 'Çift okutma algılandı'}
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        barcode = barcode.strip()
        if not barcode:
            return {'error': 'Barkod boş'}

        product = self._find_product(barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {barcode}'}

        # Batch'teki move'larda bu ürünü bul (henüz tamamlanmamış)
        target_move = None
        target_picking = None
        for picking in batch.picking_ids:
            for move in picking.move_ids:
                if (move.product_id.id == product.id and
                        (move.wave_collected_qty or 0) < move.product_uom_qty):
                    target_move = move
                    target_picking = picking
                    break
            if target_move:
                break

        if not target_move:
            # Belki tamamlanmış
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    if move.product_id.id == product.id:
                        return {
                            'warning': True,
                            'message': f'{product.display_name} zaten toplandı ✓',
                            'product_name': product.display_name,
                        }
            return {'error': f'Bu ürün rotada yok: {product.display_name}'}

        # Toplama miktarını artır
        new_qty = (target_move.wave_collected_qty or 0) + 1
        target_move.sudo().write({'wave_collected_qty': new_qty})

        # İşlem logu
        try:
            user = request.env.user
            request.env['ugurlar.barcode.operation'].sudo().create({
                'operation_type': 'picking',
                'barcode': barcode,
                'product_id': product.id,
                'quantity': 1,
                'state': 'done',
            })
            
            # Varyant chatter log
            msg = Markup(
                '<b>&#128722; Rota Toplama:</b> <em>%s</em> tarafindan '
                '<b>%s</b> rotasinda (Siparis: %s) <b>1</b> adet sepete eklendi.'
            ) % (user.name, batch.name, target_picking.name)
            product.sudo().message_post(
                body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception:
            pass

        # Tamamlanma durumu
        item_complete = new_qty >= target_move.product_uom_qty
        all_collected = all(
            (m.wave_collected_qty or 0) >= m.product_uom_qty
            for p in batch.picking_ids
            for m in p.move_ids
        )

        return {
            'success': True,
            'product_name': product.display_name,
            'product_id': product.id,
            'collected_qty': new_qty,
            'demand_qty': target_move.product_uom_qty,
            'move_id': target_move.id,
            'picking_name': target_picking.name,
            'item_complete': item_complete,
            'all_collected': all_collected,
            'image_url': f'/web/image/product.product/{product.id}/image_256',
        }

    @http.route('/ugurlar_barcode/api/batch_undo', type='jsonrpc', auth='user')
    def batch_undo(self, move_id=0, **kw):
        """Rota toplamada alınan bir ürünü sepetteki sayısından düşmek (Undo/Geri al)."""
        move = request.env['stock.move'].sudo().browse(int(move_id))
        if not move.exists():
            return {'error': 'İşlem satırı bulunamadı'}

        if not move.wave_collected_qty or move.wave_collected_qty <= 0:
            return {'error': 'Düşülecek miktar yok'}

        new_qty = move.wave_collected_qty - 1
        move.sudo().write({'wave_collected_qty': new_qty})

        # Log kaydı
        try:
            user = request.env.user
            picking = move.picking_id
            product = move.product_id
            msg = Markup(
                '<b>&#10060; Hatalı Toplamayı Geri Alma:</b> <em>%s</em> tarafindan '
                'bu siparişi içeren rotada <b>%s</b> urununden 1 adet cikarildi (Eksi islemi).'
            ) % (user.name, product.display_name)
            product.sudo().message_post(body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception:
            pass

        return {
            'success': True,
            'message': '1 adet eksiltildi.',
        }

    @http.route('/ugurlar_barcode/api/batch_collect_complete', type='jsonrpc', auth='user')
    def batch_collect_complete(self, batch_id=0, **kw):
        """Rota toplama tamamla — özet bilgi döndür."""
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        total_moves = 0
        collected_moves = 0
        skipped_moves = 0

        for picking in batch.picking_ids:
            for move in picking.move_ids:
                total_moves += 1
                collected = move.wave_collected_qty or 0
                if collected >= move.product_uom_qty:
                    collected_moves += 1
                elif collected == 0:
                    skipped_moves += 1

        return {
            'success': True,
            'batch_name': batch.name,
            'total_moves': total_moves,
            'collected_moves': collected_moves,
            'skipped_moves': skipped_moves,
            'partial_moves': total_moves - collected_moves - skipped_moves,
            'message': f'{batch.name}: {collected_moves}/{total_moves} ürün toplandı',
        }


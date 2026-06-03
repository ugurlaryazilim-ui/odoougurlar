"""Batch Toplama Listesi API — batch_list, batch_detail, batch_create."""
import logging
from datetime import datetime, timedelta
from markupsafe import Markup

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

    @http.route('/ugurlar_barcode/api/batch_list', type='json', auth='user')
    def batch_list(self, **kw):
        """Batch'leri listele — opsiyonel filtre desteği."""
        filter_state = kw.get('filter_state', '')   # draft | in_progress | done | ''
        search_text = (kw.get('search', '') or '').strip().lower()
        warehouse_filter = (kw.get('warehouse', '') or '').strip()
        date_from = kw.get('date_from', '') or ''
        date_to = kw.get('date_to', '') or ''
        exclude_transfers = kw.get('exclude_transfers', False)
        exclude_done = kw.get('exclude_done', False)
        barcode_search = (kw.get('barcode_search', '') or '').strip()

        if exclude_transfers:
            # Paketleme: sadece time_window olan ve T ile başlamayan
            domain = [
                ('time_window', '!=', False),
                ('name', 'not like', 'T%'),
            ]
        else:
            # Rota Toplama: time_window olan VEYA T ile başlayan (transferler)
            domain = [
                '|',
                ('time_window', '!=', False),
                ('name', 'like', 'T%'),
            ]

        # Tamamlanan/iptal rotaları gizle
        if exclude_done:
            domain.append(('state', 'not in', ['done', 'cancel']))

        # Barkod ile ürün arama — ürünün bulunduğu rotaları filtrele
        barcode_batch_ids = None
        if barcode_search:
            product = self._find_product(barcode_search)
            _logger.info("Barkod arama: '%s' → ürün: %s", barcode_search,
                         product.display_name if product else 'BULUNAMADI')
            if product:
                # stock.move üzerinden batch bul (daha güvenilir)
                moves = request.env['stock.move'].sudo().search([
                    ('product_id', '=', product.id),
                    ('picking_id', '!=', False),
                    ('picking_id.batch_id', '!=', False),
                    ('state', 'not in', ['done', 'cancel']),
                ], limit=100)
                batch_ids = set()
                for m in moves:
                    if m.picking_id and m.picking_id.batch_id:
                        batch_ids.add(m.picking_id.batch_id.id)
                barcode_batch_ids = batch_ids
                _logger.info("Barkod arama: %d move, %d batch bulundu: %s",
                             len(moves), len(batch_ids), batch_ids)
            else:
                barcode_batch_ids = set()  # ürün bulunamadı → boş sonuç

        if date_from:
            try:
                dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                domain.append(('schedule_time', '>=', dt_from))
            except Exception:
                pass
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                domain.append(('schedule_time', '<', dt_to))
            except Exception:
                pass

        if filter_state and filter_state != 'all':
            domain.append(('state', '=', filter_state))

        batches = request.env['stock.picking.batch'].sudo().search(
            domain, order='schedule_time desc', limit=50,
        )

        result = []
        for b in batches:
            # Barkod arama filtresi: sadece bu ürünün olduğu batch'ler
            if barcode_batch_ids is not None and b.id not in barcode_batch_ids:
                continue

            # Depo bilgisi — source_info alanından depo adını çıkar
            # Format: "HEYKEL MAĞAZA DEPO - 6 siparis (09:31-12:30)"
            warehouse_name = ''
            si = b.source_info or ''
            if si:
                warehouse_name = si.split(' - ')[0].strip()
            if not warehouse_name:
                # Fallback: picking_type üzerinden
                if b.picking_type_id and b.picking_type_id.warehouse_id:
                    warehouse_name = b.picking_type_id.warehouse_id.name or ''

            # Tarih formatlama
            date_str = ''
            if b.schedule_time:
                dt = b.schedule_time
                date_str = dt.strftime('%d %b %H:%M')

            item = {
                'id': b.id,
                'name': b.name,
                'state': b.state,
                'time_window': b.time_window or '',
                'schedule_time': str(b.schedule_time or ''),
                'date_display': date_str,
                'total_orders': b.total_orders,
                'total_items': b.total_items,
                'available_count': b.available_count,
                'other_warehouse_count': b.other_warehouse_count,
                'unavailable_count': b.unavailable_count,
                'user': b.user_id.name or '',
                'warehouse_name': warehouse_name,
                'batch_type': 'Manuel' if 'Manuel' in (b.time_window or '') else 'Otomatik',
            }

            # Client-side search (name veya warehouse)
            if search_text:
                hay = (b.name + ' ' + warehouse_name).lower()
                if search_text not in hay:
                    continue

            # Warehouse filter
            if warehouse_filter:
                if warehouse_filter.lower() not in warehouse_name.lower():
                    continue

            result.append(item)

        # Durum sayaçları — mevcut filtrelere (warehouse, tarih, arama) göre hesapla
        # Böylece mağaza seçince badge'ler de güncellenir
        count_domain_base = [
            '|',
            ('time_window', '!=', False),
            ('name', 'like', 'T%'),
        ]
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                count_domain_base.append(('schedule_time', '>=', dt_from))
            except Exception:
                pass
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                count_domain_base.append(('schedule_time', '<', dt_to))
            except Exception:
                pass

        # Filtreli batch'leri çek (sayaç + warehouse listesi için)
        count_batches = request.env['stock.picking.batch'].sudo().search(
            count_domain_base, limit=500,
        )

        # Warehouse ve arama filtresi uygula (Python tarafında)
        state_counts = {'draft': 0, 'in_progress': 0, 'done': 0}
        warehouse_set = set()
        for ab in count_batches:
            # Warehouse adını çıkar
            ab_wh = ''
            si = ab.source_info or ''
            if si:
                ab_wh = si.split(' - ')[0].strip()
            if not ab_wh and ab.picking_type_id and ab.picking_type_id.warehouse_id:
                ab_wh = ab.picking_type_id.warehouse_id.name or ''
            if ab_wh:
                warehouse_set.add(ab_wh)

            # Warehouse filtresi uygula
            if warehouse_filter and warehouse_filter.lower() not in ab_wh.lower():
                continue

            # Arama filtresi uygula
            if search_text:
                hay = (ab.name + ' ' + ab_wh).lower()
                if search_text not in hay:
                    continue

            # Barkod filtresi uygula
            if barcode_batch_ids is not None and ab.id not in barcode_batch_ids:
                continue

            if ab.state in state_counts:
                state_counts[ab.state] += 1

        return {
            'batches': result,
            'total': len(result),
            'state_counts': state_counts,
            'warehouses': sorted(warehouse_set),
            'can_delete': request.env.user.has_group('stock.group_stock_manager') or request.env.user.has_group('base.group_system')
        }

    @http.route('/ugurlar_barcode/api/batch_detail', type='json', auth='user')
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

    @http.route('/ugurlar_barcode/api/batch_create_now', type='json', auth='user')
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

    @http.route('/ugurlar_barcode/api/batch_delete', type='json', auth='user')
    def batch_delete(self, batch_id=0, **kw):
        """Test rotalarını vs. silmek için."""
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}
        
        try:
            # Sadece draft veya in_progress olanları sildirelim
            if batch.state == 'done':
                return {'error': 'Tamamlanmış rotalar silinemez'}
            
            # İçindeki transferleri iptal etmeyelim, sadece rotadan çıkaralım
            if batch.picking_ids:
                batch.picking_ids.write({'batch_id': False})
                
            batch.unlink()
            return {'success': True}
        except Exception as e:
            return {'error': str(e)}

    # ═══════════════════════════════════════════════════════
    # ROTA TOPLAMA (WAVE PICKING) API'LERİ
    # ═══════════════════════════════════════════════════════

    @http.route('/ugurlar_barcode/api/batch_route_items', type='json', auth='user')
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
                    brand_name = ''
                    color_name = ''
                    size_name = ''
                    if hasattr(product, 'product_template_variant_value_ids'):
                        vals = product.product_template_variant_value_ids
                        if vals:
                            variant_info = ', '.join(
                                v.name for v in vals)
                            # Attribute tipine göre Renk/Beden/Marka ayrıştır
                            for v in vals:
                                attr_name = (v.attribute_id.name or '').strip().lower()
                                if attr_name in ('renk', 'color', 'colour'):
                                    color_name = v.name
                                elif attr_name in ('beden', 'size', 'numara'):
                                    size_name = v.name
                                elif attr_name in ('marka', 'brand'):
                                    brand_name = v.name

                    # Fallback: template attribute_line_ids'den Marka/Renk/Beden ara
                    # (Bazı ürünlerde varyant olarak değil, sadece nitelik olarak tanımlı)
                    tmpl = product.product_tmpl_id
                    if tmpl and (not brand_name or not color_name or not size_name):
                        for attr_line in tmpl.attribute_line_ids:
                            attr_name = (attr_line.attribute_id.name or '').strip().lower()
                            if not brand_name and attr_name in ('marka', 'brand'):
                                if attr_line.value_ids:
                                    brand_name = attr_line.value_ids[0].name
                            elif not color_name and attr_name in ('renk', 'color', 'colour'):
                                if attr_line.value_ids:
                                    # Tek değer varsa direkt al, birden fazlaysa varyanta bak
                                    if len(attr_line.value_ids) == 1:
                                        color_name = attr_line.value_ids[0].name
                            elif not size_name and attr_name in ('beden', 'size', 'numara'):
                                if attr_line.value_ids:
                                    if len(attr_line.value_ids) == 1:
                                        size_name = attr_line.value_ids[0].name

                    # Fallback: default_code'dan renk kodu / beden çıkar
                    # Format: {ürün_kodu}-{renk_kodu}-{beden}  (ör: 15322263-0028-S)
                    dc = product.default_code or ''
                    dc_parts = dc.split('-')
                    if len(dc_parts) >= 3:
                        if not color_name:
                            color_name = dc_parts[-2]   # Son ikinci parça → renk kodu
                        if not size_name:
                            size_name = dc_parts[-1]     # Son parça → beden

                    route_items.append({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'picking_name': picking.name,
                        'product_id': product.id,
                        'product_tmpl_id': product.product_tmpl_id.id,
                        'product_name': product.name or product.display_name,
                        'display_name': product.display_name,
                        'default_code': product.default_code or '',
                        'barcode': product.barcode or '',
                        'variant_info': variant_info,
                        'brand': brand_name,
                        'category': product.categ_id.name if product.categ_id else '',
                        'color': color_name,
                        'size': size_name,
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

    @http.route('/ugurlar_barcode/api/batch_collect_scan', type='json', auth='user')
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

        # ── Exact match bulunamadı → aynı şablon ile dene ──
        if not target_move and product.product_tmpl_id:
            scanned_tmpl_id = product.product_tmpl_id.id
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    if (move.product_id.product_tmpl_id.id == scanned_tmpl_id and
                            (move.wave_collected_qty or 0) < move.product_uom_qty):
                        target_move = move
                        target_picking = picking
                        _logger.info(
                            "Şablon eşleşmesi (toplama): taranan=%s → rotadaki=%s",
                            product.display_name, move.product_id.display_name)
                        break
                if target_move:
                    break

        if not target_move:
            # Belki tamamlanmış
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    if (move.product_id.id == product.id or
                        (product.product_tmpl_id and
                         move.product_id.product_tmpl_id.id == product.product_tmpl_id.id)):
                        return {
                            'warning': True,
                            'message': f'{product.display_name} zaten toplandı ✓',
                            'product_name': product.display_name,
                        }
            return {'error': f'Ürün toplama listesinde bulunamadı — barkod eşleşmedi: [{product.barcode or "?"}] {product.display_name}'}

        # Toplama miktarını artır
        new_qty = (target_move.wave_collected_qty or 0) + 1
        target_move.sudo().write({'wave_collected_qty': new_qty})

        # Batch durumu taslak ise 'in_progress' (Devam) yap
        if batch.state == 'draft':
            batch.sudo().write({'state': 'in_progress'})

        # ─── Picking tamamlanma kontrolü (sadece log — otomatik validate KAPALI) ───
        picking_all_collected = all(
            (m.wave_collected_qty or 0) >= m.product_uom_qty
            for m in target_picking.move_ids
        )
        picking_validated = False
        if picking_all_collected:
            _logger.info("Rota toplama: %s tüm ürünleri toplandı (batch: %s) — manuel tamamlama bekleniyor",
                        target_picking.name, batch.name)

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
                '<b>&#128722; Rota Toplama:</b> <em>%s</em> tarafından '
                '<b>%s</b> rotasında (Sipariş: %s) <b>1</b> adet sepete eklendi.'
            ) % (user.name, batch.name, target_picking.name)
            self._log_chatter(product, msg)
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
            'picking_validated': picking_validated,
            'image_url': f'/web/image/product.product/{product.id}/image_256',
        }

    @http.route('/ugurlar_barcode/api/batch_undo', type='json', auth='user')
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
        user = request.env.user
        product = move.product_id
        msg = Markup(
            '<b>&#10060; Hatalı Toplamayı Geri Alma:</b> <em>%s</em> tarafından '
            'bu siparişi içeren rotada <b>%s</b> ürününden 1 adet çıkarıldı (Eksi işlemi).'
        ) % (user.name, product.display_name)
        self._log_chatter(product, msg)

        return {
            'success': True,
            'message': '1 adet eksiltildi.',
        }

    @http.route('/ugurlar_barcode/api/batch_collect_complete', type='json', auth='user')
    def batch_collect_complete(self, batch_id=0, **kw):
        """Rota toplama tamamla — picking'leri doğrula ve stok aktar."""
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        total_moves = 0
        collected_moves = 0
        skipped_moves = 0

        # ─── 1. Toplanan miktarları move_line'lara yaz ───
        for picking in batch.picking_ids:
            if picking.state == 'done':
                # Zaten toplama sırasında validate edilmiş — atla
                total_moves += len(picking.move_ids)
                collected_moves += len(picking.move_ids)
                continue
            for move in picking.move_ids:
                total_moves += 1
                collected = move.wave_collected_qty or 0
                if collected >= move.product_uom_qty:
                    collected_moves += 1
                elif collected == 0:
                    skipped_moves += 1

                # Move line'lara miktarı yaz
                if collected > 0:
                    remaining = collected
                    for ml in move.move_line_ids:
                        try:
                            ml.quantity = min(remaining, ml.reserved_uom_qty or move.product_uom_qty)
                            remaining -= ml.quantity
                        except Exception:
                            ml.quantity = move.product_uom_qty

        # ─── 2. Picking'leri doğrula (stok aktarımı) ───
        failed_pickings = []
        skipped_pickings = []
        for picking in batch.picking_ids:
            if picking.state in ('assigned', 'confirmed'):
                # Güvenlik: Hiç toplanmamış picking'i validate etme
                has_collected = any(
                    (m.wave_collected_qty or 0) > 0 for m in picking.move_ids
                )
                if not has_collected:
                    skipped_pickings.append(picking.name)
                    _logger.info(
                        "Picking %s (origin: %s) atlandı — hiçbir ürün toplanmadı "
                        "(wave_collected_qty=0)", picking.name, picking.origin)
                    continue

                try:
                    ctx = {
                        'skip_backorder': True,
                        'skip_immediate': True,
                        'picking_ids_not_to_backorder': picking.ids,
                    }
                    result = picking.with_context(**ctx).button_validate()
                    if isinstance(result, dict) and result.get('res_model'):
                        try:
                            wizard_model = result['res_model']
                            wizard_ctx = result.get('context', {})
                            wizard = request.env[wizard_model].sudo().with_context(**wizard_ctx).create({})
                            if hasattr(wizard, 'process'):
                                wizard.process()
                            elif hasattr(wizard, 'action_done'):
                                wizard.action_done()
                        except Exception as e2:
                            _logger.warning("Wizard %s hatası: %s", wizard_model, e2)
                    # Doğrulama sonrası kontrol
                    picking.invalidate_recordset(['state'])
                    if picking.state != 'done':
                        failed_pickings.append(picking.name)
                        _logger.warning(
                            "Picking %s (origin: %s) button_validate sonrası state=%s",
                            picking.name, picking.origin, picking.state)
                except Exception as e:
                    failed_pickings.append(picking.name)
                    _logger.warning("Picking %s doğrulama hatası: %s", picking.name, e)

        # ─── 3. Batch'i tamamla (sadece tüm picking'ler done ise) ───
        try:
            if batch.state != 'done':
                all_done = all(p.state == 'done' for p in batch.picking_ids)
                if all_done:
                    batch.action_done()
                else:
                    not_done = [p.name for p in batch.picking_ids if p.state != 'done']
                    _logger.warning(
                        "Batch %s: %d/%d picking done DEĞİL: %s — batch tamamlanmadı",
                        batch.name, len(not_done), len(batch.picking_ids), not_done)
                    failed_pickings.extend(not_done)
        except Exception as e:
            _logger.error("Batch %s tamamlama hatası: %s", batch.name, e)

        # ─── 4. Ürün chatter'larına transfer tamamlanma logu ───
        try:
            user = request.env.user
            for picking in batch.picking_ids:
                source_name = picking.location_id.display_name or ''
                dest_name = picking.location_dest_id.display_name or ''
                for move in picking.move_ids:
                    collected = move.wave_collected_qty or 0
                    if collected > 0 and move.product_id:
                        msg = Markup(
                            '<b>&#128666; Transfer Tamamlandı:</b> <em>%s</em> tarafından '
                            '<b>%s</b> rotasında (Sipariş: %s)<br/>'
                            '&#128230; <b>%s</b> adet — '
                            '<b>%s</b> &#10132; <b>%s</b>'
                        ) % (
                            user.name, batch.name, picking.name,
                            int(collected),
                            source_name, dest_name,
                        )
                        self._log_chatter(move.product_id, msg)
        except Exception as e:
            _logger.warning("Chatter log hatası: %s", e)

        batch_done = all(p.state == 'done' for p in batch.picking_ids)
        result_msg = f'{batch.name}: {collected_moves}/{total_moves} ürün toplandı ve aktarıldı'
        if failed_pickings:
            result_msg += f' ⚠️ ({len(failed_pickings)} picking done olmadı: {", ".join(failed_pickings)})'
        else:
            result_msg += ' ✅'

        return {
            'success': True,
            'batch_name': batch.name,
            'batch_done': batch_done,
            'total_moves': total_moves,
            'collected_moves': collected_moves,
            'skipped_moves': skipped_moves,
            'partial_moves': total_moves - collected_moves - skipped_moves,
            'failed_pickings': failed_pickings,
            'message': result_msg,
        }

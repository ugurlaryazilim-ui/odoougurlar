"""Batch Toplama Listesi API — batch_list, batch_detail, batch_create."""
import logging
from datetime import datetime, timedelta

import pytz
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
        # Kalıcı alan varsa onu kullan (done picking'ler dahil)
        all_pickings = self._get_all_pickings(batch)
        product_ids = all_pickings.mapped('move_ids.product_id').ids
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
        """Batch'leri listele — opsiyonel filtre desteği."""
        self._check_internal_user()
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

        # Tarih / metin / depo / barkod filtreleri sorguya: önceden 50 kayıt çekilip sonra
        # Python'da süzülüyordu, eşleşen eski rotalar hiç görünmüyordu
        filter_domain = self._batch_filter_domain(
            date_from, date_to, search_text, warehouse_filter, barcode_batch_ids)
        domain += filter_domain

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
                # schedule_time UTC saklanır: kullanıcının saat dilimine (yoksa İstanbul) çevrilir,
                # İngilizce ay adı yerine gg.aa.yyyy SS:DD
                tz = pytz.timezone(request.env.user.tz or 'Europe/Istanbul')
                dt = pytz.utc.localize(b.schedule_time).astimezone(tz)
                date_str = dt.strftime('%d.%m.%Y %H:%M')

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
        ] + self._batch_filter_domain(date_from, date_to, '', '', None)

        # Filtreli batch'leri çek (sayaç + warehouse listesi için)
        count_batches = request.env['stock.picking.batch'].sudo().search(
            count_domain_base, limit=500,
        )

        # Depo listesi (filtre seçenekleri)
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

        # Durum sayaçları tüm filtrelerle (500 kayıt sınırı olmadan)
        Batch = request.env['stock.picking.batch'].sudo()
        for st in state_counts:
            state_counts[st] = Batch.search_count(
                count_domain_base + filter_domain + [('state', '=', st)])

        return {
            'batches': result,
            'total': len(result),
            'state_counts': state_counts,
            'warehouses': sorted(warehouse_set),
            'can_delete': request.env.user.has_group('stock.group_stock_manager') or request.env.user.has_group('base.group_system')
        }

    def _batch_filter_domain(self, date_from, date_to, search_text, warehouse_filter, barcode_batch_ids):
        """Rota listesi filtreleri. Tarihler kullanıcının yerel günüdür (schedule_time UTC)."""
        domain = []
        tz = pytz.timezone(request.env.user.tz or 'Europe/Istanbul')
        for value, op, shift in ((date_from, '>=', 0), (date_to, '<', 1)):
            if not value:
                continue
            try:
                local = datetime.strptime(value, '%Y-%m-%d') + timedelta(days=shift)
            except ValueError:
                continue
            utc = tz.localize(local).astimezone(pytz.utc).replace(tzinfo=None)
            domain.append(('schedule_time', op, utc))
        if search_text:
            domain += ['|', ('name', 'ilike', search_text), ('source_info', 'ilike', search_text)]
        if warehouse_filter:
            domain += ['|', ('source_info', 'ilike', warehouse_filter),
                       ('picking_type_id.warehouse_id.name', 'ilike', warehouse_filter)]
        if barcode_batch_ids is not None:
            domain.append(('id', 'in', list(barcode_batch_ids)))
        return domain

    @http.route('/ugurlar_barcode/api/batch_detail', type='jsonrpc', auth='user')
    def batch_detail(self, batch_id=0, **kw):
        """Batch detayı — picking'ler ve ürün satırları."""
        self._check_internal_user()
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Batch bulunamadı'}

        pickings = []
        all_products = {}  # product_id → toplam bilgi (rota sıralaması için)

        # Toplu ürün lokasyon haritası
        location_dict = self._get_product_location_map(batch, detailed=False)

        for p in self._get_all_pickings(batch).sorted(key=lambda x: x.name):
            picking_lines = []
            for move in p.move_ids:
                product = move.product_id
                barcode = self._get_physical_barcode(product)

                # Ürün raf konumunu toplu dict üzerinden al
                location = location_dict.get(product.id, '')

                line_data = {
                    'move_id': move.id,
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'barcode': barcode,
                    'demand_qty': move.product_uom_qty,
                    # Toplanan = rota sayacı; quantity rota rezervidir (K-1)
                    'done_qty': move.wave_collected_qty,
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
                all_products[key]['collected_qty'] += move.wave_collected_qty

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
        self._check_internal_user()
        if not self._is_stock_manager():
            return {'error': 'Toplama listesi oluşturma yetkiniz yok (Stok Yöneticisi gerekli).'}
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
            return {'error': self._error_text(e)}

    @http.route('/ugurlar_barcode/api/batch_delete', type='jsonrpc', auth='user')
    def batch_delete(self, batch_id=0, **kw):
        """Test rotalarını vs. silmek için."""
        self._check_internal_user()
        # Sil butonu arayüzde yalnız yöneticiye görünüyordu; istek doğrudan da atılabiliyordu
        if not self._is_stock_manager():
            return {'error': 'Rota silme yetkiniz yok (Stok Yöneticisi gerekli).'}
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}
        
        try:
            # Sadece draft veya in_progress olanları sildirelim
            if batch.state == 'done':
                return {'error': 'Tamamlanmış rotalar silinemez'}

            # Toplanmış ama paketlemede doğrulanmamış ürün varsa silme: rota
            # silinirse toplanan miktar (wave_collected_qty) sahipsiz kalır ve
            # paketleme bu siparişleri rota üzerinden bulamaz.
            open_collected = self._get_all_pickings(batch).filtered(
                lambda p: p.state not in ('done', 'cancel') and any(
                    (m.wave_collected_qty or 0) > 0 and m.state != 'cancel'
                    for m in p.move_ids))
            if open_collected:
                return {'error': (
                    f'Bu rotada toplanmış ama paketlenmemiş ürün var '
                    f'({len(open_collected)} sipariş). Önce paketlemede tamamlayın '
                    f'ya da "Eksik Onayla" ile kapatın veya toplamayı geri alın.')}

            # İçindeki transferleri iptal etmeyelim, sadece rotadan çıkaralım
            if batch.picking_ids:
                batch.picking_ids.write({'batch_id': False})
                
            batch.unlink()
            return {'success': True}
        except Exception as e:
            return {'error': self._error_text(e)}

    # ═══════════════════════════════════════════════════════
    # ROTA TOPLAMA (WAVE PICKING) API'LERİ
    # ═══════════════════════════════════════════════════════

    @http.route('/ugurlar_barcode/api/batch_route_items', type='jsonrpc', auth='user')
    def batch_route_items(self, batch_id=0, **kw):
        """Rota ürünlerini raf lokasyonuna göre sıralı döndür."""
        self._check_internal_user()
        try:
            batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
            if not batch.exists():
                return {'error': 'Rota bulunamadı'}


            # Toplu ürün lokasyon haritası (detaylı: zone/section/shelf parçaları ile)
            location_data_dict = self._get_product_location_map(batch, detailed=True)

            # Tüm picking'leri çek (done dahil, migrasyon dahil)
            all_pickings = self._get_all_pickings(batch)

            # ─── source_warehouse_id boş olan move'lar için anlık depo tespiti ───
            # Eski batch'lerde (yeni kod deploy edilmeden oluşturulanlarda) depo bilgisi yok.
            # Bu move'lar için anlık stok kontrolü yapıp depo bilgisini dolduruyoruz.
            needs_depot_check = any(
                not m.source_warehouse_id
                for p in all_pickings for m in p.move_ids
            )
            depot_map = {}  # product_id → warehouse record
            if needs_depot_check:
                Schedule = request.env['ugurlar.picking.schedule'].sudo()
                schedule = Schedule.search([('active', '=', True)], limit=1)
                if schedule:
                    primary_wh = schedule.warehouse_id
                    fallback_wh = schedule.fallback_warehouse_id
                    return_wh = schedule.return_warehouse_id
                    # Tüm ürün ID'lerini topla
                    check_pids = list({
                        m.product_id.id
                        for p in all_pickings for m in p.move_ids
                        if not m.source_warehouse_id
                    })
                    Quant = request.env['stock.quant'].sudo()
                    # Primary depo stok
                    primary_stock = set()
                    if primary_wh and primary_wh.lot_stock_id:
                        for q in Quant.search([
                            ('product_id', 'in', check_pids),
                            ('location_id', 'child_of', primary_wh.lot_stock_id.id),
                            ('quantity', '>', 0),
                        ]):
                            primary_stock.add(q.product_id.id)
                    # Fallback depo stok
                    fallback_stock = set()
                    if fallback_wh and fallback_wh.lot_stock_id:
                        for q in Quant.search([
                            ('product_id', 'in', check_pids),
                            ('location_id', 'child_of', fallback_wh.lot_stock_id.id),
                            ('quantity', '>', 0),
                        ]):
                            fallback_stock.add(q.product_id.id)
                    # Return depo stok
                    return_stock = set()
                    if return_wh and return_wh.lot_stock_id:
                        for q in Quant.search([
                            ('product_id', 'in', check_pids),
                            ('location_id', 'child_of', return_wh.lot_stock_id.id),
                            ('quantity', '>', 0),
                        ]):
                            return_stock.add(q.product_id.id)
                    # Harita oluştur
                    for pid in check_pids:
                        if pid in primary_stock:
                            depot_map[pid] = primary_wh
                        elif pid in fallback_stock:
                            depot_map[pid] = fallback_wh
                        elif pid in return_stock and return_wh:
                            depot_map[pid] = return_wh
                        elif return_wh:
                            depot_map[pid] = return_wh
                        else:
                            depot_map[pid] = primary_wh

            # Tüm move'ları topla
            route_items = []
            for picking in all_pickings:
                for move in picking.move_ids:
                    product = move.product_id

                    # Depo bilgisi: move'da varsa kullan, yoksa anlık tespiti kullan
                    src_wh = move.source_warehouse_id
                    if not src_wh and depot_map.get(product.id):
                        src_wh = depot_map[product.id]
                        # Kalıcı olarak move'a yaz
                        try:
                            move.sudo().write({'source_warehouse_id': src_wh.id})
                        except Exception:
                            pass

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

                    # Barkod: fiziksel barkod (nebim_barcode) varsa onu göster
                    display_barcode = self._get_physical_barcode(product)

                    route_items.append({
                        'move_id': move.id,
                        'picking_id': picking.id,
                        'picking_name': picking.name,
                        'product_id': product.id,
                        'product_tmpl_id': product.product_tmpl_id.id,
                        'product_name': product.name or product.display_name,
                        'display_name': product.display_name,
                        'default_code': product.default_code or '',
                        'barcode': display_barcode,
                        'variant_info': variant_info,
                        'brand': brand_name,
                        'category': product.categ_id.name if product.categ_id else '',
                        'color': color_name,
                        'size': size_name,
                        'demand_qty': move.product_uom_qty,
                        'collected_qty': move.wave_collected_qty or 0,
                        'skipped': bool(move.wave_skipped),
                        'location': location_name,
                        'location_parts': location_parts,
                        'image_url': f'/web/image/product.product/{product.id}/image_256',
                        'origin': picking.origin or '',
                        'partner_name': picking.partner_id.name or '',
                        'source_warehouse_id': src_wh.id if src_wh else 0,
                        'source_warehouse_name': src_wh.name if src_wh else '',
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
            return {'error': self._error_text(e, 'Rota yükleme hatası: ')}

    @http.route('/ugurlar_barcode/api/batch_collect_scan', type='jsonrpc', auth='user')
    def batch_collect_scan(self, batch_id=0, barcode='', **kw):
        """Rota toplama sırasında barkod tara → wave_collected_qty artır.

        Toplama aşaması: sadece 'raftan aldım' demek.
        Gerçek done_qty paketleme aşamasında artırılır.
        """
        self._check_internal_user()
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

        # Bu ürünü ikame olarak kullanan paket ürünlerin ID'lerini de topla
        # (Fiziksel barkod okutulunca move'daki paket ürünle eşleşsin diye)
        match_product_ids = {product.id}
        if hasattr(product, 'substituted_by_ids') and product.substituted_by_ids:
            match_product_ids |= set(product.substituted_by_ids.ids)

        # Batch'teki move'larda bu ürünü bul (henüz tamamlanmamış)
        target_move = None
        target_picking = None
        for picking in batch.picking_ids:
            for move in picking.move_ids:
                if (move.product_id.id in match_product_ids and
                        move.state != 'cancel' and
                        (move.wave_collected_qty or 0) < move.product_uom_qty):
                    target_move = move
                    target_picking = picking
                    break
            if target_move:
                break

        if not target_move:
            # Belki tamamlanmış — sadece birebir product_id eşleşmesi
            for picking in batch.picking_ids:
                for move in picking.move_ids:
                    if move.state == 'cancel':
                        continue
                    if move.product_id.id in match_product_ids:
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

    @http.route('/ugurlar_barcode/api/batch_skip_item', type='jsonrpc', auth='user')
    def batch_skip_item(self, move_id=0, skipped=True, **kw):
        """Rota toplamada ürünü "Eksik" işaretle / işareti kaldır.

        Önceden yalnız arayüzde "toplandı" gösteriliyordu; tamamlama eksik ürünü tam sevk ediyordu.
        """
        self._check_internal_user()
        move = request.env['stock.move'].sudo().browse(int(move_id or 0))
        if not move.exists() or move.picking_id.picking_type_code != 'outgoing':
            return {'error': 'İşlem satırı bulunamadı'}
        if move.state in ('done', 'cancel'):
            return {'error': 'Sevkiyatı tamamlanmış ürün değiştirilemez'}
        move.write({'wave_skipped': bool(skipped)})
        return {'success': True, 'skipped': bool(skipped)}

    @http.route('/ugurlar_barcode/api/batch_undo', type='jsonrpc', auth='user')
    def batch_undo(self, move_id=0, **kw):
        """Rota toplamada alınan bir ürünü sepetteki sayısından düşmek (Undo/Geri al)."""
        self._check_internal_user()
        move = request.env['stock.move'].sudo().browse(int(move_id))
        if not move.exists() or move.picking_id.picking_type_code != 'outgoing':
            return {'error': 'İşlem satırı bulunamadı'}
        if move.state in ('done', 'cancel'):
            return {'error': 'Sevkiyatı tamamlanmış ürün geri alınamaz'}

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

    @http.route('/ugurlar_barcode/api/batch_collect_complete', type='jsonrpc', auth='user')
    def batch_collect_complete(self, batch_id=0, **kw):
        """Rota toplama tamamla — toplamayı kapatır, sevkiyatı DOĞRULAMAZ.

        Eksik denetimi yapar (toplanmamış ve "Eksik" işaretlenmemiş ürün varsa
        reddeder), hiç toplanamayan siparişi rotadan çıkarır. Toplanan miktar
        wave_collected_qty'de kalır; OUT'u paketleme doğrular (okutma, Eksik
        Onayla ya da Tamamla). Fatura/Nebim/kargo bildirimi o doğrulamadan sonra
        çalışır; paketlemeye kadar sipariş satırı değiştirilebilir.
        """
        self._check_internal_user()
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        total_moves = 0
        collected_moves = 0
        skipped_moves = 0

        all_pickings = self._get_all_pickings(batch)

        # ─── 0. Eksik kontrolü: toplanmamış ve "Eksik" işaretlenmemiş ürün varsa durdur ───
        missing = self._missing_moves(all_pickings)
        if missing:
            return self._missing_error(missing)

        for picking in all_pickings:
            for move in picking.move_ids:
                if move.state == 'cancel':
                    continue
                total_moves += 1
                collected = move.wave_collected_qty or 0
                if picking.state == 'done' or collected >= move.product_uom_qty:
                    collected_moves += 1
                elif collected == 0:
                    skipped_moves += 1

        # ─── 1. Hiç toplanamayan siparişi rotadan çıkar (sonraki rotaya kalsın) ───
        # Sevkiyat burada DOĞRULANMAZ: move.quantity/picked yazılmaz, button_validate
        # çağrılmaz. Toplanan miktar wave_collected_qty'de kalır; OUT'u paketleme
        # doğrular. Böylece paketlemeye kadar sipariş satırı değiştirilebilir.
        skipped_pickings = []
        for picking in all_pickings:
            if picking.state in ('done', 'cancel'):
                continue
            if any((m.wave_collected_qty or 0) > 0 for m in picking.move_ids):
                continue
            # Hiçbir ürünü toplanamadı (tümü "Eksik"): rotadan çıkar
            skipped_pickings.append(picking.name)
            try:
                with request.env.cr.savepoint():
                    picking.write({'batch_id': False})
                    batch.write({'all_picking_ids': [(3, picking.id)]})
            except Exception as e:
                _logger.warning("Picking %s rotadan çıkarılamadı: %s", picking.name, e)
            _logger.info("Picking %s (origin: %s) rotadan çıkarıldı — hiçbir ürün toplanmadı",
                         picking.name, picking.origin)
        all_pickings = self._get_all_pickings(batch)

        # ─── 2. Rota zaten tamamen sevk edildiyse kapat (normalde paketleme kapatır) ───
        try:
            if batch.state != 'done' and self._route_finished(all_pickings):
                batch.action_done()
        except Exception as e:
            _logger.error("Batch %s tamamlama hatası: %s", batch.name, e)

        # ─── 3. Ürün chatter'larına toplama tamamlanma logu ───
        try:
            user = request.env.user
            for picking in all_pickings:
                source_name = picking.location_id.display_name or ''
                for move in picking.move_ids:
                    collected = move.wave_collected_qty or 0
                    if collected > 0 and move.product_id:
                        msg = Markup(
                            '<b>&#128722; Toplama Tamamlandı:</b> <em>%s</em> tarafından '
                            '<b>%s</b> rotasında (Sipariş: %s)<br/>'
                            '&#128230; <b>%s</b> adet <b>%s</b> konumundan toplandı; '
                            'sevkiyat paketlemede doğrulanır'
                        ) % (
                            user.name, batch.name, picking.name,
                            int(collected), source_name,
                        )
                        self._log_chatter(move.product_id, msg)
        except Exception as e:
            _logger.warning("Chatter log hatası: %s", e)

        batch_done = self._route_finished(all_pickings)
        result_msg = (f'{batch.name}: {collected_moves}/{total_moves} ürün toplandı; '
                      f'sevkiyat paketlemede doğrulanır ✅')
        if skipped_pickings:
            result_msg += f' — {len(skipped_pickings)} sipariş hiç toplanamadığı için sonraki rotaya bırakıldı'

        return {
            'success': True,
            'collect_done': True,
            'batch_name': batch.name,
            'batch_done': batch_done,
            'total_moves': total_moves,
            'collected_moves': collected_moves,
            'skipped_moves': skipped_moves,
            'partial_moves': total_moves - collected_moves - skipped_moves,
            # Uyumluluk: Tamamla artık doğrulama yapmadığı için hep boş
            'failed_pickings': [],
            'backorder_pickings': [],
            'skipped_pickings': skipped_pickings,
            'message': result_msg,
        }

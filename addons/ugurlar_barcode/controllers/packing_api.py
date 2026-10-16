"""Paketleme & Faturalama API — batch bazlı ürün eşleştirme, fatura, etiket."""
import json
import logging
import os
import subprocess
import tempfile
from urllib.parse import quote

import re

from markupsafe import Markup, escape

from odoo import fields, http
from odoo.http import request
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


# ── PDF etiket HTML'i: pazaryeri / şablon değerleri kaçışsız yazılırsa wkhtmltopdf
#    (JavaScript ve ağ erişimi açık) HTML/iframe ile iç adreslere istek atabiliyordu ──
def _esc(value):
    return str(escape('' if value is None else value))


def _num(value, default=0):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return n if n == n and abs(n) != float('inf') else default


_COLOR_RE = re.compile(r'^(#[0-9a-fA-F]{3,8}|transparent|[a-zA-Z]{3,20}|rgba?\(\s*[\d.,\s%]+\))$')
_WEIGHTS = {'normal', 'bold', 'bolder', 'lighter', '100', '200', '300', '400', '500', '600', '700', '800', '900'}


def _color(value, default='#000000'):
    v = str(value or '').strip()
    return v if _COLOR_RE.match(v) else default


def _weight(value):
    v = str(value or 'normal').strip()
    return v if v in _WEIGHTS else 'normal'


def _align(value):
    v = str(value or 'left').strip()
    return v if v in ('left', 'center', 'right', 'justify') else 'left'


# Marketplace order field registry — yeni pazaryeri eklendiğinde sadece buraya ekle
_MARKETPLACE_REGISTRY = [
    ('trendyol_order_id', 'trendyol_order_number', 'Trendyol'),
    ('hb_order_id', 'hb_order_number', 'Hepsiburada'),
    ('amazon_order_id', 'amazon_order_number', 'Amazon'),
    ('pazarama_order_id', 'order_number', 'Pazarama'),
    ('n11_order_id', 'order_number', 'N11'),
    ('flo_order_id', 'order_number', 'Flo'),
    ('idefix_order_id', 'order_number', 'Idefix'),
    ('pttavm_order_id', 'order_number', 'PttAvm'),
]


def _extract_marketplace_info(sale_order):
    """Sale order'dan marketplace sipariş bilgilerini çek.

    Returns:
        dict: cargo_tracking, cargo_provider, customer_name, order_number, marketplace_name
    """
    for field, num_field, name in _MARKETPLACE_REGISTRY:
        if hasattr(sale_order, field) and getattr(sale_order, field):
            order = getattr(sale_order, field)
            # Kargo takip no: birden fazla field dene
            cargo_tracking = (
                getattr(order, 'cargo_tracking_number', '') or
                getattr(order, 'cargo_tracking', '') or
                getattr(order, 'cargo_code', '') or
                getattr(order, 'shipment_code', '') or  # Pazarama PZ kodu
                ''
            )
            # Kargo firması
            cargo_provider = (
                getattr(order, 'cargo_provider', '') or
                getattr(order, 'cargo_company', '') or
                ''
            )
            # Kargo satır seviyesinde de olabilir (Pazarama line_ids)
            if not cargo_tracking or not cargo_provider:
                line_ids = getattr(order, 'line_ids', None)
                if line_ids:
                    for line in line_ids:
                        if not cargo_tracking:
                            cargo_tracking = getattr(line, 'cargo_tracking', '') or ''
                        if not cargo_provider:
                            cargo_provider = getattr(line, 'cargo_company', '') or ''
                        if cargo_tracking and cargo_provider:
                            break
            return {
                'marketplace_name': name,
                'cargo_tracking': cargo_tracking,
                'cargo_provider': cargo_provider,
                'customer_name': getattr(order, 'customer_name', '') or '',
                'order_number': getattr(order, num_field, '') or '',
            }

    if hasattr(sale_order, 'amazon_store_id') and sale_order.amazon_store_id:
        amazon_order = getattr(sale_order, 'amazon_order_id', None)
        order_num = (getattr(amazon_order, 'amazon_order_number', '') if amazon_order else '') or sale_order.client_order_ref or ''
        # EasyShip tracking (ZA8156127) > cargo_tracking_number > Amazon Order ID fallback
        easyship_tid = (getattr(amazon_order, 'easyship_tracking_id', '') if amazon_order else '') or ''
        cargo_tracking = easyship_tid or (getattr(amazon_order, 'cargo_tracking_number', '') if amazon_order else '') or order_num
        cargo_provider = (getattr(amazon_order, 'cargo_provider', '') if amazon_order else '') or 'MNGTR'
        cust_name = getattr(amazon_order, 'customer_name', '') if amazon_order else (sale_order.partner_id.name or '')
        return {
            'marketplace_name': 'Amazon',
            'cargo_tracking': cargo_tracking,
            'cargo_provider': cargo_provider,
            'customer_name': cust_name,
            'order_number': order_num,
        }

    return {
        'marketplace_name': '',
        'cargo_tracking': '', 'cargo_provider': '',
        'customer_name': '', 'order_number': '',
    }


class PackingApiController(BarcodeApiBase):
    """Paketleme & Faturalama API'leri."""

    @staticmethod
    def _packing_done_qty(move):
        """Paketleme listesindeki "okutulan" değeri: doğrulanmış move'da sevk edilen miktar,
        bitmemiş move'da okutma sayacı. Rota rezervi (quantity) okutulmuş sayılmaz (K-1)."""
        return move.quantity if move.state == 'done' else move.packing_scanned_qty

    @staticmethod
    def _cancelled_sale_origins(pickings):
        """Picking'lerin origin'lerinden iptal edilmiş satış siparişi adları (tek sorgu)."""
        origins = list({p.origin for p in pickings if p.origin})
        if not origins:
            return set()
        return set(request.env['sale.order'].sudo().search([
            ('name', 'in', origins), ('state', '=', 'cancel'),
        ]).mapped('name'))

    @http.route('/ugurlar_barcode/api/packing_batch_detail', type='jsonrpc', auth='user')
    def packing_batch_detail(self, batch_name='', batch_id=0, **kw):
        """Rota numarası veya ID ile batch detayı getir."""
        self._check_internal_user()
        Batch = request.env['stock.picking.batch'].sudo()

        if batch_id:
            batch = Batch.browse(int(batch_id))
        elif batch_name:
            # Önce tam ad ("R12" yazınca "R123" açılmasın); yoksa tek kısmi eşleşme
            batch = Batch.search([('name', '=', batch_name.strip())], limit=1)
            if not batch:
                matches = Batch.search([('name', 'ilike', batch_name.strip())], limit=2)
                batch = matches if len(matches) == 1 else Batch
        else:
            return {'error': 'Rota numarası gerekli'}

        if not batch or not batch.exists():
            return {'error': f'Rota bulunamadı: {batch_name or batch_id}'}

        # Odoo done olunca batch_id temizliyor — kalıcı alan kullan
        all_pickings = self._get_all_pickings(batch)

        # OPTIMIZASYON: Tüm siparişleri (sale order) toplu çek
        picking_origins = [p.origin for p in all_pickings if p.origin]
        sales_dict = {}
        if picking_origins:
            sales = request.env['sale.order'].sudo().search([('name', 'in', picking_origins)])
            for s in sales:
                sales_dict[s.name] = s

        # ── İptal edilen siparişlerin picking'leri yalnız listeden çıkar ──
        # Detay okuma ucudur: önceden ekran açılınca picking burada iptal ediliyordu (GET ile
        # stok yazımı). İptal packing_complete'te yapılır.
        cancelled_origins = {
            name for name, sale in sales_dict.items()
            if sale.state == 'cancel'
        }
        all_pickings = all_pickings.filtered(
            lambda p: not (p.origin and p.origin in cancelled_origins))

        # İptal move'larının yedek (replacement) picking'leri tek sorguda: origin → picking
        # listesi (önceden her iptal move için ayrı search). Sıra search sırasıdır.
        replacement_origins = list({
            p.origin for p in all_pickings
            if p.origin and any(m.state == 'cancel' for m in p.move_ids)})
        replacements_by_origin = {}
        if replacement_origins:
            for rp in request.env['stock.picking'].sudo().search([
                    ('origin', 'in', replacement_origins), ('state', 'not in', ['cancel'])]):
                replacements_by_origin.setdefault(rp.origin, []).append(rp)

        # Görsel var mı: bin_size bağlamında yalnız boyut okunur, görsel verisi çekilmez
        image_flags = {}

        def has_image(product):
            if product.id not in image_flags:
                image_flags[product.id] = bool(product.with_context(bin_size=True).image_128)
            return image_flags[product.id]

        # Tüm picking'lerdeki ürünleri topla
        items = []
        for picking in all_pickings:
            # Kargo bilgileri (sale order üzerinden - prefetch edilmiş veriden al)
            cargo_tracking = ''
            cargo_provider = ''
            customer_name = ''
            order_number = ''

            if picking.origin and picking.origin in sales_dict:
                sale = sales_dict[picking.origin]
                mp_info = _extract_marketplace_info(sale)
                cargo_tracking = mp_info['cargo_tracking']
                cargo_provider = mp_info['cargo_provider']
                customer_name = mp_info['customer_name']
                order_number = mp_info['order_number']

            for move in picking.move_ids:
                # İptal edilmiş move'ları atla — replacement'ı bul
                if move.state == 'cancel':
                    # Replacement picking'de aynı ürün var mı?
                    replacement_found = False
                    if picking.origin:
                        rep_pickings = [rp for rp in replacements_by_origin.get(picking.origin, [])
                                        if rp.id != picking.id]
                        for rp in rep_pickings:
                            for rm in rp.move_ids:
                                if rm.product_id.id == move.product_id.id and rm.state != 'cancel':
                                    product = rm.product_id
                                    items.append({
                                        'move_id': rm.id,
                                        'picking_id': rp.id,
                                        'picking_name': rp.name,
                                        'product_id': product.id,
                                        'product_name': product.display_name,
                                        'barcode': self._get_physical_barcode(product),
                                        'demand_qty': rm.product_uom_qty,
                                        'done_qty': self._packing_done_qty(rm),
                                        'matched': rm.packing_scanned_qty >= rm.product_uom_qty,
                                        'scanned_qty': rm.packing_scanned_qty,
                                        'origin': rp.origin or '',
                                        'customer_name': customer_name,
                                        'cargo_tracking': cargo_tracking,
                                        'cargo_provider': cargo_provider,
                                        'order_number': order_number,
                                        'image_url': f'/web/image/product.product/{product.id}/image_128',
                                        'has_image': has_image(product),
                                    })
                                    replacement_found = True
                                    break
                            if replacement_found:
                                break
                    if not replacement_found:
                        # Replacement bulunamadı — iptal move'u göster; soft match sayacı
                        # (packing_scanned_qty) okutulanı gösterir
                        product = move.product_id
                        items.append({
                            'move_id': move.id,
                            'picking_id': picking.id,
                            'picking_name': picking.name,
                            'product_id': product.id,
                            'product_name': product.display_name,
                            'barcode': self._get_physical_barcode(product),
                            'demand_qty': move.product_uom_qty,
                            'done_qty': self._packing_done_qty(move),
                            'matched': move.packing_scanned_qty >= move.product_uom_qty,
                            'scanned_qty': move.packing_scanned_qty,
                            'origin': picking.origin or '',
                            'customer_name': customer_name,
                            'cargo_tracking': cargo_tracking,
                            'cargo_provider': cargo_provider,
                            'order_number': order_number,
                            'image_url': f'/web/image/product.product/{product.id}/image_128',
                            'has_image': has_image(product),
                            'cancelled': True,
                        })
                    continue

                product = move.product_id

                items.append({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'barcode': self._get_physical_barcode(product),
                    'demand_qty': move.product_uom_qty,
                    'done_qty': self._packing_done_qty(move),
                    'matched': move.packing_scanned_qty >= move.product_uom_qty,
                    'scanned_qty': move.packing_scanned_qty,
                    'origin': picking.origin or '',
                    'customer_name': customer_name,
                    'cargo_tracking': cargo_tracking,
                    'cargo_provider': cargo_provider,
                    'order_number': order_number,
                    'image_url': f'/web/image/product.product/{product.id}/image_128',
                    'has_image': has_image(product),
                })

        total = len(items)
        matched = sum(1 for i in items if i['matched'])

        return {
            'batch': {
                'id': batch.id,
                'name': batch.name,
                'state': batch.state,
                'time_window': batch.time_window or '',
            },
            'items': items,
            'total': total,
            'matched': matched,
            'all_matched': matched == total,
        }

    @http.route('/ugurlar_barcode/api/packing_scan', type='jsonrpc', auth='user')
    def packing_scan(self, batch_id=0, barcode='', **kw):
        """Paketleme sırasında ürün barkodu tara → eşleştir.
        
        Stok düşürme YAPILMAZ — stok rota toplama sırasında düşer.
        Burada sadece eşleştirme + etiket basma kontrolü yapılır.
        """
        self._check_internal_user()
        try:
            return self._packing_scan_impl(batch_id, barcode, **kw)
        except Exception as e:
            _logger.error("packing_scan exception (batch=%s, barcode=%s): %s", batch_id, barcode, e, exc_info=True)
            return {'error': self._error_text(e, 'Sunucu hatası: ')}

    def _packing_scan_impl(self, batch_id, barcode, **kw):
        """packing_scan asıl implementasyonu."""
        # Duplicate guard: aynı barkod 500ms içinde tekrar taranırsa atla
        if self._check_duplicate_request('packing_scan', batch_id, barcode):
            return {'error': 'Çift okutma algılandı, lütfen tekrar deneyin'}
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        barcode = barcode.strip()
        product = self._find_product(barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {barcode}'}

        # İkame desteği: bu ürünü ikame olarak kullanan paket ürünlerle de eşleştir
        match_product_ids = {product.id}
        if hasattr(product, 'substituted_by_ids') and product.substituted_by_ids:
            match_product_ids |= set(product.substituted_by_ids.ids)

        # Batch'teki picking'lerde bu ürünü bul (henüz eşleştirilmemiş)
        all_pickings = self._get_all_pickings(batch)
        # İptal edilmiş siparişin picking'i okutulmaz (detay artık iptal etmiyor; açık kalan
        # picking okutulup doğrulanırsa mal sevk edilirdi). İptal packing_complete'te yapılır.
        cancelled_origins = self._cancelled_sale_origins(all_pickings)
        scan_pickings = all_pickings.filtered(
            lambda p: not (p.origin and p.origin in cancelled_origins))
        active_moves = [
            (picking, move)
            for picking in scan_pickings for move in picking.move_ids
            if move.product_id.id in match_product_ids and move.state != 'cancel'
        ]
        # Önce toplanan miktarı dolmamış move: ilk sipariş Eksik / az toplanmışsa okutma
        # sıradaki toplanmış siparişe gider (önceden ilk siparişte "toplanmamış" hatası
        # dönüyor, toplanmış sipariş hiç paketlenemiyordu)
        target_picking, target_move = next(
            ((p, m) for p, m in active_moves
             if m.packing_scanned_qty < min(m.product_uom_qty, m.wave_collected_qty or 0)),
            (None, None))
        if not target_move:
            # Toplanan sınırı her yerde dolu: eski seçim; aşağıdaki rota toplama kontrolü
            # "henüz toplanmamış" / "rotada yalnız N adet toplandı" mesajını üretir
            target_picking, target_move = next(
                ((p, m) for p, m in active_moves if m.packing_scanned_qty < m.product_uom_qty),
                (None, None))

        if not target_move:
            # ─── Fallback: İptal edilmiş move varsa yeniden yönlendirilmiş olabilir ───
            # Odoo stok yeniden yönlendirme yapınca orijinal move'u iptal edip
            # yeni bir picking/move oluşturur (örn: İade deposundan gelen ürün)
            cancelled_move = None
            cancelled_picking = None
            for picking in scan_pickings:
                for move in picking.move_ids:
                    if move.product_id.id in match_product_ids and move.state == 'cancel':
                        cancelled_move = move
                        cancelled_picking = picking
                        break
                if cancelled_move:
                    break

            if cancelled_move and cancelled_picking and cancelled_picking.origin:
                # Aynı siparişe ait tüm picking'lerde (done dahil) ürünü ara
                replacement_pickings = request.env['stock.picking'].sudo().search([
                    ('origin', '=', cancelled_picking.origin),
                    ('state', 'not in', ['cancel']),
                ])
                # 1) Önce henüz tamamlanmamış aktif move ara.
                # Rotadan geçmiş (rotada / rotadan çıkarılmış) replacement her zaman aktiftir:
                # rezervi korunur (K-1), quantity ilerleme değildir; ardından wave_qty kontrolü
                # karar verir. Rotaya hiç girmemiş ve rezervi tam olan replacement eskisi gibi
                # aktif sayılmaz (soft match).
                for rp in replacement_pickings:
                    if rp.id in (all_pickings.ids if hasattr(all_pickings, 'ids') else []):
                        continue
                    routed = bool(rp.batch_id or rp.batch_schedule_time)
                    for move in rp.move_ids:
                        if (move.product_id.id in match_product_ids and
                                move.state not in ('cancel', 'done') and
                                (routed or move.quantity < move.product_uom_qty)):
                            target_move = move
                            target_picking = rp
                            _logger.info(
                                "Replacement move (aktif): %s → %s (origin: %s)",
                                cancelled_picking.name, rp.name, rp.origin)
                            try:
                                batch.sudo().all_picking_ids = [(4, rp.id)]
                            except Exception:
                                pass
                            break
                    if target_move:
                        break

                # 2) Aktif bulunamadı → done move var mı? (zaten tamamlanmış replacement)
                if not target_move:
                    done_replacement = None
                    done_replacement_picking = None
                    for rp in replacement_pickings:
                        for move in rp.move_ids:
                            if move.product_id.id in match_product_ids and move.state == 'done':
                                done_replacement = move
                                done_replacement_picking = rp
                                break
                        if done_replacement:
                            break

                    if done_replacement:
                        _logger.info(
                            "Replacement move (done): %s → %s (origin: %s)",
                            cancelled_picking.name, done_replacement_picking.name,
                            done_replacement_picking.origin)
                        # Batch'e ekle
                        try:
                            batch.sudo().all_picking_ids = [(4, done_replacement_picking.id)]
                        except Exception:
                            pass
                        # Nebim sync'i tetikle (fatura oluşsun)
                        try:
                            self._trigger_nebim_sync(done_replacement_picking)
                        except Exception as e:
                            _logger.error("Nebim sync hatası (replacement): %s", e)

                        # Tüm batch kontrolü (paketleme sayacı; rezerv okutulmuş sayılmaz)
                        all_matched = all(
                            m.packing_scanned_qty >= m.product_uom_qty
                            for p in scan_pickings
                            for m in p.move_ids
                            if m.state != 'cancel'
                        )
                        return {
                            'success': True,
                            'product_name': product.display_name,
                            'done_qty': int(done_replacement.product_uom_qty),
                            'demand_qty': done_replacement.product_uom_qty,
                            'picking_name': done_replacement_picking.name,
                            'picking_id': done_replacement_picking.id,
                            'picking_completed': True,
                            'picking_total': 1,
                            'picking_matched': 1,
                            'remaining_items': [],
                            'complete': True,
                            'all_matched': all_matched,
                            'replacement_match': True,
                        }

            # Hâlâ bulunamadı ama iptal edilmiş move var →
            # "soft match" yap (paketleme sadece doğrulama, stok hareketi değil).
            # Ürünün rotada iptal olmayan move'u varsa soft match yapılmaz: kapasitesi dolmuş
            # ürün iptal move'u üzerinden "başarılı" sayılıyordu; "zaten paketlendi" döner
            if not target_move and cancelled_move and not active_moves:
                # Sayaçlı: iptal move'un miktarı kadar okutma kabul edilir (önceden sınırsız
                # "başarılı" dönüyordu). İlk kapasitesi kalan iptal move'u sayılır.
                soft_picking, soft_move = next(
                    ((p, m) for p in scan_pickings for m in p.move_ids
                     if m.product_id.id in match_product_ids and m.state == 'cancel'
                     and m.packing_scanned_qty < m.product_uom_qty),
                    (cancelled_picking, None))
                if not soft_move:
                    return {
                        'warning': True,
                        'message': f'{product.display_name} zaten paketlendi',
                        'product_name': product.display_name,
                        'picking_completed': False,
                        'picking_id': soft_picking.id,
                        'picking_name': soft_picking.name,
                        'label_already_printed': soft_picking.label_printed,
                    }
                new_qty = soft_move.packing_scanned_qty + 1
                soft_move.write({'packing_scanned_qty': new_qty})
                _logger.info(
                    "Soft match: %s (cancelled move, picking=%s, %s/%s)",
                    product.display_name, soft_picking.name, new_qty, soft_move.product_uom_qty)
                # Sale order üzerinden Nebim sync dene
                try:
                    if soft_picking.origin:
                        so = request.env['sale.order'].sudo().search(
                            [('name', '=', soft_picking.origin)], limit=1)
                        if so:
                            # Siparişin tamamlanmış picking'lerinden birini bul
                            done_picking = request.env['stock.picking'].sudo().search([
                                ('origin', '=', so.name),
                                ('state', '=', 'done'),
                            ], limit=1)
                            if done_picking:
                                self._trigger_nebim_sync(done_picking)
                except Exception as e:
                    _logger.error("Soft match Nebim hatası: %s", e)

                return {
                    'success': True,
                    'product_name': product.display_name,
                    'done_qty': new_qty,
                    'demand_qty': soft_move.product_uom_qty,
                    'picking_name': soft_picking.name,
                    'picking_id': soft_picking.id,
                    'picking_completed': True,
                    'picking_total': 1,
                    'picking_matched': 1,
                    'remaining_items': [],
                    'complete': True,
                    'all_matched': all(
                        m.packing_scanned_qty >= m.product_uom_qty
                        for p in scan_pickings
                        for m in p.move_ids
                        if m.state != 'cancel'
                    ),
                    'soft_match': True,
                }

        if not target_move:
            # Ürünün tüm aktif move'ları paketlemede zaten okutulmuş — bilgi ver
            if active_moves:
                picking = active_moves[0][0]
                picking_completed = all(
                    m.packing_scanned_qty >= m.product_uom_qty
                    for m in picking.move_ids if m.state != 'cancel'
                )
                # Okutması bitmiş ama doğrulaması başarısız kalmış picking: etiket basılmaz
                # (istemci picking_completed ile etiket basıp Nebim'i tetikliyor)
                validate_pending = picking_completed and picking.state not in ('done', 'cancel')
                message = f'{product.display_name} zaten paketlendi'
                if validate_pending:
                    message += ' — sevkiyat doğrulanmadı, "Tamamla" ile yeniden deneyin'
                return {
                    'warning': True,
                    'message': message,
                    'product_name': product.display_name,
                    'picking_completed': picking_completed and picking.state == 'done',
                    'validate_pending': validate_pending,
                    'picking_id': picking.id,
                    'picking_name': picking.name,
                    'label_already_printed': picking.label_printed,
                }
            return {'error': f'Ürün toplama listesinde bulunamadı — barkod eşleşmedi (Yanlış beden/varyant okutmuş olabilirsiniz): [{product.barcode or "?"}] {product.display_name}'}

        # ─── Rota toplama kontrolü ───
        # Ürün rota toplamada toplanmadıysa uyarı ver
        wave_qty = target_move.wave_collected_qty or 0
        if wave_qty == 0:
            return {
                'error': f'⚠️ {product.display_name} henüz rota toplamadan toplanmamış!\n'
                        f'Önce Rota Toplama ekranından toplayınız.',
                'not_collected': True,
            }
        # Rotada eksik toplanan ürün paketlemede toplanandan fazla okutulamaz
        if target_move.packing_scanned_qty >= wave_qty:
            return {
                'error': f'⚠️ {product.display_name}: rotada yalnız {int(wave_qty)} adet toplandı, '
                         f'hepsi zaten okutuldu.',
                'not_collected': True,
            }

        # Barkod eşleşti → qty artır (eşleştirme sayacı, stok hareketi değil)
        new_qty = target_move.packing_scanned_qty + 1
        target_move.write({'packing_scanned_qty': new_qty})

        # Log
        try:
            user = request.env.user
            request.env['ugurlar.barcode.operation'].sudo().create({
                'operation_type': 'picking',
                'barcode': barcode,
                'product_id': product.id,
                'quantity': 1,
                'state': 'done',
            })

            # Chatter log for scan
            msg = Markup(
                '<b>&#128230; Paketleme Eslestirme:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisinde <b>%s</b> 1 adet eslestirildi.'
            ) % (user.name, target_picking.name, product.display_name)
            product.sudo().message_post(
                body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception:
            pass

        # Check if individual picking is complete (paketleme bazlı)
        picking_total = sum(m.product_uom_qty for m in target_picking.move_ids)
        picking_matched = sum(m.packing_scanned_qty for m in target_picking.move_ids)
        picking_completed = all(
            m.packing_scanned_qty >= m.product_uom_qty
            for m in target_picking.move_ids if m.state != 'cancel'
        )

        # ─── DEBUG LOG ───
        _logger.info(
            "PACKING SCAN %s: product=%s, new_packing_qty=%s, "
            "picking=%s (state=%s), picking_completed=%s, "
            "moves=[%s]",
            batch.name, product.display_name, new_qty,
            target_picking.name, target_picking.state, picking_completed,
            ', '.join(
                f'{m.product_id.display_name}: packing={m.packing_scanned_qty}/{m.product_uom_qty} state={m.state}'
                for m in target_picking.move_ids
            )
        )

        # ─── Aynı siparişe ait diğer picking'leri kontrol et ───
        sibling_remaining = []
        all_siblings_complete = True
        if target_picking.origin:
            sibling_pickings = all_pickings.filtered(
                lambda p: p.origin == target_picking.origin and p.id != target_picking.id
            )
            for sp in sibling_pickings:
                for m in sp.move_ids:
                    if m.packing_scanned_qty < m.product_uom_qty:
                        all_siblings_complete = False
                        sibling_remaining.append(
                            f"{m.product_id.display_name} ({m.product_uom_qty - m.packing_scanned_qty} adet)"
                        )

        # Picking'in kendi kalan ürünleri
        remaining_items = []
        for m in target_picking.move_ids:
            if m.packing_scanned_qty < m.product_uom_qty:
                remaining_items.append(f"{m.product_id.display_name} ({m.product_uom_qty - m.packing_scanned_qty} adet)")

        remaining_items.extend(sibling_remaining)

        # Gerçek tamamlanma: bu picking + aynı siparişteki diğer picking'ler
        order_completed = picking_completed and all_siblings_complete

        # Picking zaten done ise (rota'da validate edilmiş) → paketleme tamamlanınca Nebim sync
        validate_error = None
        if picking_completed:
            _logger.info("PACKING COMPLETION: %s → packing_done=True, state=%s",
                         target_picking.name, target_picking.state)
            if target_picking.state in ('done', 'cancel'):
                target_picking.packing_done = True
            else:
                # Sevk miktarı okutma sayacından yazılır (quantity rota rezervidir, ilerleme
                # göstergesi değil). Savepoint'te: hata verirse doğrulama yazımları geri alınır,
                # okutma sayacı (yukarıda, savepoint öncesi yazıldı) korunur
                done, validate_error = self._validate_in_savepoint(
                    target_picking, 'packing_scanned_qty')
                if not done:
                    order_completed = False

        # Doğrulanamayan picking için Nebim ve etiket bayrağı çalışmaz (kullanıcı kararı)
        if picking_completed and not validate_error:
            # Nebim sync tetikle (fatura oluşsun)
            try:
                _logger.info("NEBIM SYNC tetikleniyor: %s (origin=%s)",
                             target_picking.name, target_picking.origin)
                self._trigger_nebim_sync(target_picking)
            except Exception as e:
                _logger.error("Nebim sync hatası %s: %s", target_picking.name, e)

            # Etiket basıldı olarak işaretle
            try:
                target_picking.write({
                    'label_printed': True,
                    'label_printed_at': fields.Datetime.now(),
                    'label_printed_by': request.env.user.id,
                })
            except Exception as e:
                _logger.warning("Label flag hatası %s: %s", target_picking.name, e)

        # Tüm batch kontrolü (paketleme bazlı; iptal siparişin picking'i detay listesindeki
        # gibi sayılmaz)
        all_matched = all(
            m.packing_scanned_qty >= m.product_uom_qty
            for p in scan_pickings
            for m in p.move_ids
            if m.state != 'cancel'
        )

        # Batch state güncelle — tüm picking'ler done ise batch'i tamamla. Filtresiz liste:
        # iptal siparişin açık picking'i varken rota kapanmaz (iptali packing_complete yapar)
        try:
            if batch.state != 'done':
                batch.invalidate_recordset(['picking_ids'])
                all_done = all(p.state == 'done' for p in all_pickings)
                if all_done:
                    batch.action_done()
                    _logger.info("Batch %s tamamlandı (packing_scan)", batch.name)
        except Exception as e:
            _logger.warning("Batch %s state güncelleme hatası: %s", batch.name, e)

        res = {
            'success': True,
            'product_name': product.display_name,
            'done_qty': new_qty,
            'demand_qty': target_move.product_uom_qty,
            'picking_name': target_picking.name,
            'picking_id': target_picking.id,
            'picking_completed': order_completed,
            'picking_total': picking_total,
            'picking_matched': picking_matched,
            'remaining_items': remaining_items,
            'complete': new_qty >= target_move.product_uom_qty,
            'all_matched': all_matched,
        }
        if validate_error:
            # Okutma sayıldı ama sevkiyat doğrulanamadı: istemci hatayı gösterir, etiket basmaz
            res['validate_error'] = f'{target_picking.name} doğrulanamadı: {validate_error}'
        return res

    @http.route('/ugurlar_barcode/api/packing_undo', type='jsonrpc', auth='user')
    def packing_undo(self, picking_id=0, barcode='', **kw):
        """Paketlemede yanlış okutulan ürünü geri alır (Miktar -1)."""
        self._check_internal_user()
        picking = self._get_outgoing_picking(picking_id)
        if not picking:
            return {'error': 'Sipariş bulunamadı'}

        product = self._find_product(barcode.strip())
        if not product:
            return {'error': 'Ürün bulunamadı'}

        # İkame desteği
        match_product_ids = {product.id}
        if hasattr(product, 'substituted_by_ids') and product.substituted_by_ids:
            match_product_ids |= set(product.substituted_by_ids.ids)

        target_move = None
        for move in picking.move_ids:
            if move.product_id.id in match_product_ids:
                target_move = move
                break

        if not target_move or target_move.packing_scanned_qty <= 0:
            return {'error': 'Bu üründen silinecek okutulmuş miktar yok'}

        new_qty = target_move.packing_scanned_qty - 1
        target_move.write({'packing_scanned_qty': new_qty})

        # Etiket basılmışsa geri al (ürün geri alındı)
        if picking.label_printed:
            picking.write({'label_printed': False})

        # Log kaydı
        try:
            user = request.env.user
            msg = Markup(
                '<b>&#10060; Hatalı Okutmayi Geri Alma:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisinden 1 adet <b>%s</b> cikarildi (Eksi islemi).'
            ) % (user.name, picking.name, product.display_name)
            picking.message_post(body=msg, message_type='notification')
        except Exception:
            pass

        return {'success': True, 'message': f'{product.name} siparişten 1 adet eksiltildi.'}

    @http.route('/ugurlar_barcode/api/packing_backorder', type='jsonrpc', auth='user')
    def packing_backorder(self, picking_id=0, **kw):
        """Kısmi olarak tamamlanmış siparişi kapatır ve geriye kalanları backorder (eksik) yapar."""
        self._check_internal_user()
        picking = self._get_outgoing_picking(picking_id)
        if not picking or picking.state == 'done':
            return {'error': 'Geçerli bir sipariş bulunamadı veya zaten tamamlanmış'}

        # Önceden rezerve miktar doğrulanıyordu: okutulmayan ürünler de sevk ediliyordu.
        # Sevk = paketlemede okutulan; kalan için bekleyen sevkiyat açılır.
        # Doğrulama savepoint'te: hata verirse packing_done / quantity / picked geri alınır
        # (önceden yarım yazım kalıyor ve operatör yalnız "Eksik onaylama hatası" görüyordu)
        done, error = self._validate_in_savepoint(
            picking, 'packing_scanned_qty', backorder=True)
        if not done:
            return {'error': f'Eksik onaylama hatası: {error}'}

        user = request.env.user
        msg = Markup(
            '<b>&#9888; Eksik Urunle Kapatma (Backorder):</b> <em>%s</em> tarafindan '
            'bu siparis eksik urun ile zorla onaylandi. Degisiklikler uygulandi.'
        ) % user.name
        self._log_chatter(picking, msg)

        return {'success': True, 'message': '%s eksik ürünlerle onaylandı (Backorder oluşturuldu).' % picking.name}

    @http.route('/ugurlar_barcode/api/packing_complete', type='jsonrpc', auth='user')
    def packing_complete(self, batch_id=0, **kw):
        """Paketleme tamamla — picking'leri doğrula."""
        self._check_internal_user()
        batch = request.env['stock.picking.batch'].sudo().browse(int(batch_id))
        if not batch.exists():
            return {'error': 'Rota bulunamadı'}

        validated = 0
        errors = []
        failed_ids = []
        skipped = []

        all_pickings = self._get_all_pickings(batch)

        # ── İptal edilen siparişlerin picking'lerini filtrele ──
        cancelled_origins = self._cancelled_sale_origins(all_pickings)

        filtered_pickings = request.env['stock.picking'].sudo().browse()
        for picking in all_pickings:
            if picking.origin and picking.origin in cancelled_origins:
                if picking.state not in ('done', 'cancel'):
                    try:
                        picking.action_cancel()
                        _logger.info("İptal sipariş picking'i iptal edildi: %s", picking.name)
                    except Exception:
                        pass
                skipped.append(f"{picking.name} (sipariş iptal)")
                continue
            filtered_pickings |= picking
        all_pickings = filtered_pickings

        # Toplanmayan / eksik işaretlenmeyen ürün varsa hiçbir şey doğrulanmaz
        missing = self._missing_moves(all_pickings.filtered(
            lambda p: any((m.wave_collected_qty or 0) > 0 for m in p.move_ids)))
        if missing:
            return self._missing_error(missing, 'paketlemesi tamamlanamaz')

        for picking in all_pickings:
            try:
                # Güvenlik: Hiç toplanmamış picking'i paketleme/faturala
                has_collected = any(
                    (m.wave_collected_qty or 0) > 0 for m in picking.move_ids
                )
                if not has_collected:
                    skipped.append(picking.name)
                    _logger.info(
                        "Paketleme atlandı: %s (origin: %s) — hiçbir ürün "
                        "toplanmadı (wave_collected_qty=0)",
                        picking.name, picking.origin)
                    continue

                if picking.state == 'done':
                    # Eğer daha önce onaylanmış ama Nebim'de takılı kalmışsa tekrar dene
                    self._trigger_nebim_sync(picking)
                    validated += 1
                    continue

                # Doğrulama kendi savepoint'inde: hata verirse yalnız bu picking'in yazımları
                # geri alınır, diğerleri sürer. Nebim (commit yapar) savepoint dışında.
                done, error = self._validate_in_savepoint(picking)
                if not done:
                    errors.append(f"{picking.name}: {error}")
                    failed_ids.append(picking.id)
                    continue
                self._trigger_nebim_sync(picking)
                validated += 1

            except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY:
                raise
            except Exception as e:
                _logger.exception("Sipariş Onay/Senkronizasyon Hatası %s:", picking.name)
                errors.append(f"{picking.name}: {self._error_text(e)}")

        # Batch state güncelle — tüm picking'ler done ise batch'i tamamla
        try:
            if batch.state != 'done':
                batch.invalidate_recordset(['picking_ids'])
                all_done = all(p.state == 'done' for p in all_pickings)
                if all_done:
                    batch.action_done()
                    _logger.info("Batch %s tamamlandı (packing_complete)", batch.name)
        except Exception as e:
            _logger.warning("Batch %s state güncelleme hatası: %s", batch.name, e)

        return {
            'success': len(errors) == 0,
            'validated': validated,
            'total': len(all_pickings),
            'skipped': len(skipped),
            'errors': errors,
            'failed_picking_ids': failed_ids,
            'message': f'{validated} sipariş paketlendi ve doğrulandı',
        }

    @http.route('/ugurlar_barcode/api/packing_label_data', type='jsonrpc', auth='user')
    def packing_label_data(self, picking_id=0, trigger_sync=True, log_print=False, **kw):
        """Kargo etiketi için sipariş verilerini döndür.

        trigger_sync=False: yalnız okur (fatura yoksa Nebim senkronu tetiklenmez).
        log_print=True: picking chatter'ına tek "Kargo Etiketi Yazdırıldı" notu düşer
        (istemci yalnız ilk yazdırma çağrısında gönderir, yeniden denemede göndermez).
        """
        self._check_internal_user()
        picking = self._get_outgoing_picking(picking_id)
        if not picking:
            return {'error': 'Sipariş bulunamadı'}

        # Sipariş bilgilerini topla
        data = {
            'picking_name': picking.name,
            'origin': picking.origin or '',
            'partner_name': picking.partner_id.name or '',
            'partner_phone': picking.partner_id.phone or getattr(picking.partner_id, 'mobile', '') or '',
            'partner_address': '',
            'cargo_tracking': '',
            'cargo_provider': '',
            'order_number': '',
            'customer_name': '',
            'marketplace_name': '',
            'shipping_address': '',
            'shipping_city': '',
            'shipping_district': '',
            'nebim_invoice_no': '',
            'nebim_invoice_date': '',
        }

        if picking.partner_id:
            addr_parts = [
                picking.partner_id.street or '',
                picking.partner_id.street2 or '',
                picking.partner_id.city or '',
                picking.partner_id.state_id.name if picking.partner_id.state_id else '',
            ]
            data['partner_address'] = ', '.join(p for p in addr_parts if p)

        if picking.origin:
            sale = request.env['sale.order'].sudo().search([
                ('name', '=', picking.origin)
            ], limit=1)
            if sale:
                mp_info = _extract_marketplace_info(sale)
                data['cargo_tracking'] = mp_info['cargo_tracking']
                data['cargo_provider'] = mp_info['cargo_provider']
                data['order_number'] = mp_info['order_number']
                data['customer_name'] = mp_info['customer_name']
                data['marketplace_name'] = mp_info['marketplace_name']

                # Shipping fields — her marketplace modülünden çek
                for field, num_field, name in _MARKETPLACE_REGISTRY:
                    if hasattr(sale, field) and getattr(sale, field):
                        morder = getattr(sale, field)
                        # shipping_address — bazı modellerde 'shipping_address', bazılarında 'shipment_address' (JSON)
                        addr = getattr(morder, 'shipping_address', '') or ''
                        if not addr:
                            # Pazarama: shipment_address JSON field'ından parse et
                            import json as _json
                            raw_addr = getattr(morder, 'shipment_address', '') or ''
                            if raw_addr:
                                try:
                                    addr_data = _json.loads(raw_addr)
                                    addr_parts = [
                                        addr_data.get('neighborhoodName', ''),
                                        addr_data.get('addressDetail', ''),
                                    ]
                                    addr = ' '.join(p for p in addr_parts if p)
                                except (ValueError, TypeError):
                                    addr = raw_addr[:200]
                        data['shipping_address'] = addr or data['partner_address']
                        data['shipping_city'] = getattr(morder, 'shipping_city', '') or ''
                        data['shipping_district'] = getattr(morder, 'shipping_district', '') or ''
                        break

        # Fallback: Odoo picking kargo ref'i
        if not data['cargo_tracking'] and picking.carrier_tracking_ref:
            data['cargo_tracking'] = picking.carrier_tracking_ref

        # Fallback: Partner bilgileri (eğer marketplace verisi yoksa)
        if not data['shipping_address']:
            data['shipping_address'] = data['partner_address']
        if not data['shipping_city'] and picking.partner_id:
            data['shipping_city'] = picking.partner_id.state_id.name if picking.partner_id.state_id else ''
        if not data['shipping_district'] and picking.partner_id:
            data['shipping_district'] = picking.partner_id.city or ''
        if not data['customer_name']:
            data['customer_name'] = data['partner_name']

        # Nebim fatura bilgileri — yoksa Nebim sync tetikle
        nebim_invoice_found = False
        if picking.origin:
            sale = request.env['sale.order'].sudo().search([('name', '=', picking.origin)], limit=1)
            if sale:
                # Önce mevcut faturayı kontrol et
                if sale.invoice_ids:
                    for inv in sale.invoice_ids.filtered(lambda i: i.state == 'posted'):
                        nebim_no = getattr(inv, 'nebim_invoice_number', '') or ''
                        nebim_date = getattr(inv, 'nebim_sent_date', None)
                        if nebim_no:
                            data['nebim_invoice_no'] = nebim_no
                            if nebim_date:
                                data['nebim_invoice_date'] = self._local_dt(nebim_date).strftime('%d.%m.%Y %H:%M')
                            nebim_invoice_found = True
                            break

                # Fatura yoksa → Nebim sync tetikle ve tekrar kontrol et
                if not nebim_invoice_found and trigger_sync:
                    _logger.info(
                        "LABEL DATA: %s için fatura bulunamadı, Nebim sync tetikleniyor...",
                        picking.name)
                    try:
                        self._trigger_nebim_sync(picking)
                        # Sync sonrası tekrar kontrol
                        sale.invalidate_recordset(['invoice_ids'])
                        if sale.invoice_ids:
                            for inv in sale.invoice_ids.filtered(lambda i: i.state == 'posted'):
                                nebim_no = getattr(inv, 'nebim_invoice_number', '') or ''
                                nebim_date = getattr(inv, 'nebim_sent_date', None)
                                if nebim_no:
                                    data['nebim_invoice_no'] = nebim_no
                                    if nebim_date:
                                        data['nebim_invoice_date'] = self._local_dt(nebim_date).strftime('%d.%m.%Y %H:%M')
                                    nebim_invoice_found = True
                                    _logger.info(
                                        "LABEL DATA: %s Nebim fatura oluştu: %s",
                                        picking.name, nebim_no)
                                    break
                        if not nebim_invoice_found:
                            _logger.warning(
                                "LABEL DATA: %s Nebim sync sonrası da fatura oluşmadı",
                                picking.name)
                    except Exception as e:
                        _logger.error(
                            "LABEL DATA: %s Nebim sync hatası: %s",
                            picking.name, e)

        # Ürün listesi
        items = []
        for move in picking.move_ids:
            items.append({
                'product_name': move.product_id.display_name,
                'barcode': move.product_id.barcode or '',
                'default_code': move.product_id.default_code or '',
                'qty': move.product_uom_qty,
            })
        data['items'] = items
        data['total_items'] = len(items)
        data['total_qty'] = sum(i['qty'] for i in items)

        # Yazdırma notu: yalnız istemci yazdırmayı bildirince (log_print) ve picking'e tek not.
        # Önceden her çağrıda (yeniden deneme dahil) her ürünün chatter'ına yazılıyordu.
        if log_print:
            msg = Markup(
                '<b>&#128424; Kargo Etiketi Yazdirildi:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisi icin etiket olusturuldu (Kargo Takip: %s).'
            ) % (request.env.user.name, picking.name, data['cargo_tracking'] or 'Yok')
            self._log_chatter(picking, msg)

        return data

    # ═══════════════════════════════════════════════════════════════════
    # PDF KARGO ETİKETİ — wkhtmltopdf ile mm düzeyinde hassasiyet
    # ═══════════════════════════════════════════════════════════════════

    @http.route('/ugurlar_barcode/api/cargo_label_pdf', type='http', auth='user', methods=['GET'])
    def cargo_label_pdf(self, picking_id=0, **kw):
        """Kargo etiketi PDF olarak üret — wkhtmltopdf ile tam ölçülerde."""
        self._check_internal_user()
        picking_id = int(picking_id or 0)
        if not picking_id:
            return request.make_response(
                'Picking ID gerekli', headers=[('Content-Type', 'text/plain; charset=utf-8')])

        picking = self._get_outgoing_picking(picking_id)
        if not picking:
            return request.make_response(
                'Sipariş bulunamadı', headers=[('Content-Type', 'text/plain; charset=utf-8')])

        # 1. Sipariş verisini topla (mevcut mantığı yeniden kullan). GET isteği (ön yükleme,
        # sayfa yenileme, dış bağlantı) fatura kesip Nebim'e göndermesin: yalnız okunur
        data = self.packing_label_data(picking_id=picking_id, trigger_sync=False)
        if isinstance(data, dict) and data.get('error'):
            return request.make_response(
                data['error'], headers=[('Content-Type', 'text/plain; charset=utf-8')])

        # 2. Kargo şablonunu bul
        Template = request.env['ugurlar.label.template'].sudo()
        templates = Template.search([('name', 'ilike', 'Kargo')], order='is_default desc, id desc', limit=1)

        if templates:
            tpl = templates[0]
            width_mm = tpl.width_mm
            height_mm = tpl.height_mm
            elements = json.loads(tpl.elements_json or '[]')
            html = self._build_cargo_label_html(width_mm, height_mm, elements, data)
        else:
            # Şablon yoksa varsayılan etiket
            width_mm = 100
            height_mm = 150
            html = self._build_default_cargo_html(data)

        # 3. wkhtmltopdf ile PDF üret
        pdf = self._html_to_pdf(html, width_mm, height_mm)
        if not pdf:
            return request.make_response(
                'PDF oluşturulamadı — wkhtmltopdf sunucuda yüklü olmalı',
                headers=[('Content-Type', 'text/plain; charset=utf-8')])

        # 4. PDF'i döndür
        filename = f'etiket_{picking.name.replace("/", "_")}.pdf'
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'inline; filename={filename}'),
            ('Content-Length', str(len(pdf))),
        ]
        return request.make_response(pdf, headers=headers)

    def _get_base_url(self):
        """Barcode image URL'leri için Odoo base URL döndür."""
        return request.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')

    def _get_field_text(self, el_type, content, data):
        """Frontend _getFieldValue eşdeğeri — element tipine göre veri döndür."""
        field_map = {
            'order_number': data.get('order_number') or data.get('origin', ''),
            'picking_name': data.get('picking_name', ''),
            'origin': data.get('origin', ''),
            'marketplace': data.get('marketplace_name', ''),
            'customer_name': data.get('customer_name') or data.get('partner_name', ''),
            'partner_phone': data.get('partner_phone', ''),
            'shipping_address': data.get('shipping_address') or data.get('partner_address', ''),
            'shipping_city': data.get('shipping_city', ''),
            'shipping_district': data.get('shipping_district', ''),
            'cargo_tracking': data.get('cargo_tracking', ''),
            'cargo_provider': data.get('cargo_provider', ''),
            'total_qty': f"{data.get('total_qty', 0)} adet",
            'total_items': f"{data.get('total_items', 0)} çeşit",
            'date_today': self._local_today().strftime('%d.%m.%Y'),
            'custom_text': content or '',
            'sender_name': content or '',
            'nebim_invoice_no': data.get('nebim_invoice_no', ''),
            'nebim_invoice_date': data.get('nebim_invoice_date', ''),
        }
        return field_map.get(el_type, '')

    def _build_cargo_label_html(self, width_mm, height_mm, elements, data):
        """Kargo etiketi HTML'i — mm bazlı, wkhtmltopdf uyumlu."""
        base_url = self._get_base_url()

        elements_html = ''
        for el in elements:
            x = _num(el.get('x', 0))
            y = _num(el.get('y', 0))
            w = _num(el.get('width', 10), 10)
            h = _num(el.get('height', 5), 5)
            fs = _num(el.get('fontSize', 9), 9)
            fw = _weight(el.get('fontWeight'))
            ta = _align(el.get('textAlign'))
            color = _color(el.get('color'), '#000000')
            bg_color = _color(el.get('bgColor'), 'transparent')
            rotation = _num(el.get('rotation', 0))
            el_type = el.get('type', '')
            content = el.get('content', '')

            # ── Çizgi ──
            if el_type == 'line':
                line_h = max(h, 0.3)
                elements_html += (
                    f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                    f'width:{w}mm; height:{line_h}mm; background:{color}; '
                    f'transform:rotate({rotation}deg);"></div>'
                )
                continue

            # ── Kutu ──
            if el_type == 'box':
                bw = _num(el.get('borderWidth', 1), 1)
                elements_html += (
                    f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                    f'width:{w}mm; height:{h}mm; border:{bw}px solid {color}; '
                    f'background:{bg_color}; transform:rotate({rotation}deg);"></div>'
                )
                continue

            # ── Kargo Barkodu ──
            if el_type == 'cargo_barcode':
                barcode_value = data.get('cargo_tracking', '')
                if barcode_value:
                    encoded = quote(barcode_value)
                    img_w = round(w * 12)
                    img_h = round(h * 12)
                    elements_html += (
                        f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                        f'width:{w}mm; height:{h}mm; transform:rotate({rotation}deg); '
                        f'text-align:center;">'
                        f'<img src="{base_url}/report/barcode/Code128/{encoded}'
                        f'?width={img_w}&height={img_h}&humanreadable=1" '
                        f'style="width:100%;height:100%;object-fit:contain;" />'
                        f'</div>'
                    )
                continue

            # ── QR Kod ──
            if el_type == 'cargo_qr_code':
                qr_value = content or data.get('cargo_tracking', '')
                if qr_value:
                    elements_html += (
                        f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                        f'width:{w}mm; height:{h}mm; transform:rotate({rotation}deg);">'
                        f'<img src="{base_url}/report/barcode/?type=QR'
                        f'&value={quote(qr_value)}'
                        f'&width={round(w * 12)}&height={round(h * 12)}" '
                        f'style="width:100%;height:100%;object-fit:contain;" />'
                        f'</div>'
                    )
                continue

            # ── Ürün Listesi ──
            if el_type == 'item_list':
                items = data.get('items', [])
                rows = ''
                for idx, item in enumerate(items, 1):
                    rows += (
                        f'<tr><td style="padding:0 0.5mm;">{idx}</td>'
                        f'<td style="padding:0 0.5mm;">{_esc(item["product_name"])}</td>'
                        f'<td style="text-align:right;padding:0 0.5mm;">{int(item["qty"])}</td>'
                        f'<td style="padding:0 0.5mm;">{_esc(item["barcode"])}</td></tr>'
                    )
                table_html = (
                    '<table style="width:100%;border-collapse:collapse;font-size:inherit;">'
                    '<thead><tr style="border-bottom:0.3mm solid #333;">'
                    '<th style="text-align:left;padding:0 0.5mm;">#</th>'
                    '<th style="text-align:left;padding:0 0.5mm;">Ürün</th>'
                    '<th style="text-align:right;padding:0 0.5mm;">Adet</th>'
                    '<th style="text-align:left;padding:0 0.5mm;">Barkod</th>'
                    f'</tr></thead><tbody>{rows}</tbody></table>'
                )
                elements_html += (
                    f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                    f'width:{w}mm; height:{h}mm; font-size:{fs}pt; font-weight:{fw}; '
                    f'overflow:hidden; color:{color}; background:{bg_color}; '
                    f'transform:rotate({rotation}deg);">{table_html}</div>'
                )
                continue

            # ── Metin Alanları ──
            text = _esc(self._get_field_text(el_type, content, data))
            justify = ''
            if ta == 'center':
                justify = 'justify-content:center;'
            elif ta == 'right':
                justify = 'justify-content:flex-end;'

            elements_html += (
                f'<div style="position:absolute; left:{x}mm; top:{y}mm; '
                f'width:{w}mm; height:{h}mm; font-size:{fs}pt; font-weight:{fw}; '
                f'text-align:{ta}; color:{color}; background:{bg_color}; '
                f'transform:rotate({rotation}deg); overflow:hidden; line-height:1.3; '
                f'display:flex; align-items:center; {justify}">{text}</div>'
            )

        return f'''<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{
        margin: 0; padding: 0;
        width: {width_mm}mm; height: {height_mm}mm;
        font-family: Arial, Helvetica, sans-serif;
    }}
    .label {{
        position: relative;
        width: {width_mm}mm; height: {height_mm}mm;
        overflow: hidden;
    }}
    img {{ image-rendering: pixelated; }}
</style>
</head><body>
<div class="label">{elements_html}</div>
</body></html>'''

    def _build_default_cargo_html(self, data):
        """Şablon yokken varsayılan kargo etiketi HTML'i."""
        base_url = self._get_base_url()
        cargo_barcode = data.get('cargo_tracking', '')
        barcode_html = ''
        if cargo_barcode:
            barcode_html = (
                f'<div style="text-align:center;margin:2mm 0;">'
                f'<img src="{base_url}/report/barcode/Code128/{quote(cargo_barcode)}'
                f'?width=840&height=200&humanreadable=1" '
                f'style="width:70mm;height:18mm;object-fit:contain;" />'
                f'</div>'
            )
        items_html = ''
        for item in data.get('items', []):
            items_html += (
                f'<tr><td>{_esc(item["product_name"])}</td>'
                f'<td>{int(item["qty"])}</td>'
                f'<td>{_esc(item["barcode"])}</td></tr>'
            )

        return f'''<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: Arial, sans-serif; font-size: 11px;
           width: 100mm; height: 150mm; margin: 0; padding: 3mm; }}
    .header {{ display:flex; justify-content:space-between;
              border-bottom:2px solid #000; padding-bottom:4px; margin-bottom:6px; }}
    .header h2 {{ font-size:14px; margin:0; }}
    .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; margin-bottom:6px; }}
    .info-label {{ font-weight:bold; font-size:9px; color:#666; text-transform:uppercase; }}
    .info-value {{ font-size:11px; }}
    .cargo-section {{ text-align:center; border:2px solid #000; padding:6px; margin:6px 0; }}
    .cargo-section .tracking {{ font-size:16px; font-weight:bold; letter-spacing:1px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:4px; }}
    th, td {{ border:1px solid #ccc; padding:3px 4px; font-size:9px; }}
    th {{ background:#f0f0f0; }}
</style>
</head><body>
<div class="header"><h2>{_esc(data.get('cargo_provider', 'KARGO'))}</h2><span>{_esc(data.get('picking_name', ''))}</span></div>
<div class="info-grid">
    <div><div class="info-label">Sipariş No</div><div class="info-value">{_esc(data.get('order_number') or data.get('origin', ''))}</div></div>
    <div><div class="info-label">Müşteri</div><div class="info-value">{_esc(data.get('customer_name') or data.get('partner_name', ''))}</div></div>
    <div><div class="info-label">Tel</div><div class="info-value">{_esc(data.get('partner_phone', '-'))}</div></div>
    <div><div class="info-label">Adet</div><div class="info-value">{_esc(data.get('total_qty', 0))} ürün</div></div>
</div>
<div><div class="info-label">Adres</div><div class="info-value" style="font-size:10px;">{_esc(data.get('shipping_address') or data.get('partner_address', ''))}</div>
<div class="info-value">{_esc(' / '.join(filter(None, [data.get('shipping_district', ''), data.get('shipping_city', '')])))}</div></div>
<div class="cargo-section"><div class="info-label">Kargo Takip No</div><div class="tracking">{_esc(cargo_barcode)}</div>{barcode_html}</div>
<table><thead><tr><th>Ürün</th><th>Adet</th><th>Barkod</th></tr></thead><tbody>{items_html}</tbody></table>
</body></html>'''

    def _html_to_pdf(self, html, width_mm, height_mm):
        """HTML'i wkhtmltopdf ile PDF'e çevir — tam ölçülerde."""
        # wkhtmltopdf yolunu bul
        wkhtmltopdf_path = None
        for path in ['/usr/bin/wkhtmltopdf', '/usr/local/bin/wkhtmltopdf']:
            if os.path.isfile(path):
                wkhtmltopdf_path = path
                break
        if not wkhtmltopdf_path:
            try:
                from shutil import which
                wkhtmltopdf_path = which('wkhtmltopdf')
            except Exception:
                pass
        if not wkhtmltopdf_path:
            _logger.error('wkhtmltopdf bulunamadı — PDF oluşturulamaz')
            return None

        html_fd, html_path = tempfile.mkstemp(suffix='.html')
        pdf_path = html_path.replace('.html', '.pdf')

        try:
            # HTML'i geçici dosyaya yaz
            with os.fdopen(html_fd, 'w', encoding='utf-8') as f:
                f.write(html)

            cmd = [
                wkhtmltopdf_path,
                '--quiet',
                '--page-width', f'{width_mm}',       # mm cinsinden (wkhtmltopdf varsayılan mm)
                '--page-height', f'{height_mm}',
                '--margin-top', '0',
                '--margin-bottom', '0',
                '--margin-left', '0',
                '--margin-right', '0',
                '--encoding', 'utf-8',
                '--no-outline',
                '--dpi', '96',
                '--disable-smart-shrinking',          # Otomatik küçültmeyi kapat
                '--disable-javascript',               # etikette betik yok; enjeksiyona karşı
                '--print-media-type',
                html_path,
                pdf_path,
            ]

            result = subprocess.run(
                cmd, timeout=30, capture_output=True, text=True
            )

            if result.returncode not in (0, 1):
                # wkhtmltopdf 1 döndürse bile PDF üretebilir (uyarı)
                _logger.error('wkhtmltopdf hatası (rc=%s): %s', result.returncode, result.stderr)

            if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
                with open(pdf_path, 'rb') as f:
                    return f.read()
            else:
                _logger.error('wkhtmltopdf PDF dosyası oluşturamadı')
                return None

        except subprocess.TimeoutExpired:
            _logger.error('wkhtmltopdf zaman aşımı')
            return None
        except Exception as e:
            _logger.exception('wkhtmltopdf çağrısında hata: %s', e)
            return None
        finally:
            # Geçici dosyaları temizle
            for p in [html_path, pdf_path]:
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except OSError:
                    pass


    def _trigger_nebim_sync(self, picking):
        """
        Nebim senkronizasyonunu başlatır (Müşteri -> Sipariş -> Fatura).
        
        Her aşama kendi savepoint'inde çalışır — Nebim hatası DB cursor'ı bozmaz.
        Hata olsa bile picking validation'ı ve UI çalışmaya devam eder.
        """
        from odoo import fields
        
        sale_order = picking.sale_id
        if not sale_order and picking.origin:
            sale_order = picking.env['sale.order'].sudo().search([('name', '=', picking.origin)], limit=1)

        if not sale_order:
            _logger.warning("Nebim Sync Atlandı: %s için sipariş bulunamadı.", picking.name)
            return

        _logger.info("Nebim Senkronizasyonu başlıyor: %s", sale_order.name)
        
        # Toggle ayarlarını oku
        # Toggle ayarları
        ICP = picking.env['ir.config_parameter'].sudo()
        customer_enabled = ICP.get_param('odoougurlar.nebim_sync_customer_enabled', 'False') == 'True'
        order_enabled = ICP.get_param('odoougurlar.nebim_sync_order_enabled', 'False') == 'True'
        invoice_enabled = ICP.get_param('odoougurlar.nebim_sync_invoice_enabled', 'False') == 'True'
        
        # Pazaryeri tespiti (registry tabanlı)
        mp_info = _extract_marketplace_info(sale_order)
        marketplace_name = mp_info['marketplace_name']
        
        # Mapping Bul
        mapping = picking.env['odoougurlar.marketplace.mapping'].sudo().find_mapping(
            marketplace_name, sale_order.partner_id.country_id.id
        )
        
        nebim_errors = []
        
        # ═══ DB'den taze okuma — ORM cache güncel olmayabilir ═══
        # (cron veya başka HTTP request henüz commit etmemiş olabilir)
        picking.env.cr.execute(
            "SELECT nebim_customer_sent, nebim_order_sent FROM sale_order WHERE id = %s",
            [sale_order.id]
        )
        _db_row = picking.env.cr.fetchone() or (False, False)
        _db_customer_sent = _db_row[0]
        _db_order_sent = _db_row[1]

        # ═══ Aşama A: Cari Aktarımı (savepoint korumalı) ═══
        if customer_enabled and not _db_customer_sent:
            try:
                with picking.env.cr.savepoint():
                    customer_proc = picking.env['odoougurlar.customer.processor'].sudo()
                    cust_code, addr_id = customer_proc.sync_customer(
                        sale_order.partner_id, mapping, sale_order=sale_order
                    )
                    sale_order.write({
                        'nebim_customer_sent': True,
                        'nebim_customer_code': cust_code or '',
                        'nebim_address_id': addr_id or ''
                    })
                    _logger.info("Nebim Cari başarılı: %s → %s", sale_order.name, cust_code)
            except Exception as e:
                nebim_errors.append(f"[Cari] {str(e)}")
                _logger.error("Nebim Cari hatası (%s): %s", sale_order.name, e)
        elif not customer_enabled:
            _logger.info("Nebim Cari toggle kapalı: %s", sale_order.name)
            
        # ═══ Aşama B: Sipariş Aktarımı (savepoint korumalı) ═══
        if order_enabled and not _db_order_sent:
            try:
                with picking.env.cr.savepoint():
                    order_proc = picking.env['odoougurlar.order.processor'].sudo()
                    order_proc.sync_order(sale_order, mapping)
                    _logger.info("Nebim Sipariş başarılı: %s", sale_order.name)
            except Exception as e:
                nebim_errors.append(f"[Sipariş] {str(e)}")
                _logger.error("Nebim Sipariş hatası (%s): %s", sale_order.name, e)
        elif not order_enabled:
            _logger.info("Nebim Sipariş toggle kapalı: %s", sale_order.name)
            
        # ═══ Aşama C: Fatura Oluşturma ve Aktarımı ═══
        # Aynı sipariş için iki istek (iki operatör, okutma + etiket) aynı anda fatura kesmesin:
        # sipariş satırı kilitlenir, kilitliyse bu istek faturalamayı diğerine bırakır
        if invoice_enabled:
            try:
                with picking.env.cr.savepoint():
                    picking.env.cr.execute(
                        "SELECT id FROM sale_order WHERE id = %s FOR UPDATE NOWAIT", [sale_order.id])
            except Exception:
                _logger.info("Nebim Fatura: %s başka bir işlemde faturalanıyor, atlandı", sale_order.name)
                invoice_enabled = False
        if invoice_enabled:
            try:
                # Fatura oluştur — iptal edilmiş faturaları yok say
                sale_order.invalidate_recordset(['invoice_ids', 'invoice_status'])
                active_invoices = sale_order.invoice_ids.filtered(
                    lambda i: i.state in ('draft', 'posted')
                )
                # Taslak iade (out_refund) muhasebenin işidir: paketleme onu onaylamaz
                invoices_to_post = active_invoices.filtered(
                    lambda i: i.state == 'draft' and i.move_type == 'out_invoice')
                with picking.env.cr.savepoint():
                    if not active_invoices and sale_order.invoice_status in ['to invoice', 'invoiced']:
                        invoices_to_post = sale_order._create_invoices()

                    for invoice in invoices_to_post:
                        invoice.action_post()

                # Nebim'e gönder — yalnız satış faturası (cron invoice_processor ile aynı filtre);
                # iade (out_refund) satış faturası yüküyle gönderilirse Nebim'de satış olarak işlenir
                unposted_nebim = sale_order.invoice_ids.filtered(
                    lambda i: i.state == 'posted' and i.move_type == 'out_invoice'
                    and not getattr(i, 'nebim_sent', False)
                )
                for check_invoice in unposted_nebim:
                    # Cron / buton aynı faturayı şu an gönderiyorsa ikinci kez gönderme
                    if not check_invoice._nebim_try_lock():
                        _logger.info("Nebim Fatura başka işlemde gönderiliyor, atlandı: %s", check_invoice.name)
                        continue
                    invoice_proc = picking.env['odoougurlar.invoice.processor'].sudo()
                    connector = picking.env['odoougurlar.nebim.connector'].sudo()
                    payload = invoice_proc._build_invoice_payload(check_invoice)
                    
                    # İstek payload'ını kaydet (debug için)
                    import json
                    check_invoice.write({
                        'nebim_request': json.dumps(payload, ensure_ascii=False, indent=2, default=str)
                    })
                    
                    result = connector.post_data('Post', payload)
                    
                    if isinstance(result, dict) and 'ExceptionMessage' in result:
                        raise Exception(f"Nebim Fatura Hatası: {result['ExceptionMessage']}")
                    
                    # ═══ İkinci POST: IsPostingJournal=True (Yevmiye Fişi) ═══
                    # Nebim ilk POST'ta IsPostingJournal'ı yok sayar (SQL: False kalır).
                    # Hamurlabs SQL'inde IsPostingJournal=1, bizde 0 — journal kayıtları oluşmuyor.
                    #
                    # Çözüm: İlk POST'un TAM RESPONSE'unu alıp IsPostingJournal=True
                    # ekleyerek tekrar POST ediyoruz. Nebim sadece HeaderID ile minimal
                    # payload kabul ETMİYOR — tam obje lazım.
                    if isinstance(result, dict) and result.get('HeaderID'):
                        try:
                            update_payload = dict(result)  # Tam response'u kopyala
                            update_payload['IsPostingJournal'] = True
                            update_payload['IsCompleted'] = True
                            update_result = connector.post_data('Post', update_payload)
                            _logger.info("Nebim IsPostingJournal güncellendi: HeaderID=%s", result.get('HeaderID'))
                            
                            # Güncelleme sonucu varsa result'ı güncelle
                            if isinstance(update_result, dict) and not update_result.get('ExceptionMessage'):
                                result = update_result
                        except Exception as e2:
                            _logger.warning("IsPostingJournal güncelleme hatası: %s (fatura yine de oluşturuldu)", e2)
                    
                    # Nebim fatura numarasını ayrıştır
                    nebim_inv_no = ''
                    if isinstance(result, dict):
                        nebim_inv_no = (result.get('DocumentNumber', '')
                                      or result.get('EInvoiceNumber', '')
                                      or result.get('InvoiceNumber', ''))
                    elif isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                        nebim_inv_no = (result[0].get('DocumentNumber', '')
                                      or result[0].get('EInvoiceNumber', '')
                                      or result[0].get('InvoiceNumber', ''))
                    
                    check_invoice.write({
                        'nebim_sent': True,
                        'nebim_sent_date': fields.Datetime.now(),
                        'nebim_response': str(result),
                        'nebim_error': False,
                    })
                    if nebim_inv_no:
                        check_invoice.write({'nebim_invoice_number': nebim_inv_no})
                    # Nebim kabul etti: hemen kalıcı yap. İstek sonradan hata alıp geri alınırsa
                    # (serileştirme hatası / yeniden deneme) fatura Nebim'e ikinci kez gitmesin
                    # (cron'daki invoice_processor ile aynı desen)
                    picking.env.cr.commit()

                    _logger.info("Nebim Fatura başarılı: %s", check_invoice.name)
            except Exception as e:
                nebim_errors.append(f"[Fatura] {str(e)}")
                _logger.error("Nebim Fatura hatası (%s): %s", sale_order.name, e)
        else:
            _logger.info("Nebim Fatura toggle kapalı: %s", sale_order.name)
        
        # ═══ Hata özeti yaz (savepoint dışında, güvenli) ═══
        if nebim_errors:
            try:
                error_msg = ' | '.join(nebim_errors)
                sale_order.write({'nebim_order_response': f'HATA: {error_msg}'})
            except Exception:
                _logger.warning("Nebim hata özeti yazılamadı: %s", sale_order.name)
            # RAISE YAPILMIYOR — Cursor korunuyor, UI çalışmaya devam eder

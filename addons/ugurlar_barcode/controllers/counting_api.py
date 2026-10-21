"""Sayım API — count_save, count_list (sayım geçmişi)."""
import logging
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class CountingApiController(BarcodeApiBase):
    """Sayım API'leri."""

    # ─── SAYIM KAYDET ────────────────────────────────────
    @http.route('/ugurlar_barcode/api/count_save', type='jsonrpc', auth='user')
    def count_save(self, shelf_barcode='', items=None, **kw):
        """Sayım kaydet: raf barkodu + [{barcode, quantity}]."""
        self._check_internal_user()
        if not shelf_barcode or not items:
            return {'error': 'Raf ve ürün listesi gerekli'}

        location = self._find_location(shelf_barcode.strip())
        if not location:
            return {'error': f'Raf bulunamadı: {shelf_barcode}'}

        results = []
        StockQuant = request.env['stock.quant'].sudo()

        # Sayım Fişi Oluştur
        count_session = request.env['ugurlar.barcode.count.session'].sudo().create({
            'location_id': location.id,
            'user_id': request.env.uid,
            'state': 'done'
        })

        for item in items:
            bc = item.get('barcode', '').strip()
            new_qty = self._parse_qty(item.get('quantity', 0), default=0, allow_zero=True)
            if new_qty is None:
                results.append({'barcode': bc, 'status': 'error', 'message': 'Geçersiz miktar'})
                continue

            product = self._find_product(bc)
            if not product:
                results.append({'barcode': bc, 'status': 'not_found'})
                continue

            try:
                with request.env.cr.savepoint():
                    # Raftaki tüm quant'ların kilitli toplamı (çift quant'ta ilkine göre
                    # fark yazılmasın; eşzamanlı işlem araya girmesin)
                    old_qty, _reserved = self._shelf_qty(product, location)
                    delta = new_qty - old_qty

                    # Güvenli stok güncelleme (delta farkını uygula)
                    if delta != 0:
                        self._safe_update_quant(product, location, delta, 'Mobil: Sayım Farkı')

                    request.env['ugurlar.barcode.operation'].sudo().create({
                        'operation_type': 'counting',
                        'count_session_id': count_session.id,
                        'barcode': bc,
                        'product_id': product.id,
                        'location_id': location.id,
                        'quantity': new_qty,
                        'theoretical_qty': old_qty,
                        'notes': f'Sistem: {old_qty} -> Sayılan: {new_qty}',
                        'state': 'done',
                    })

                    # NEDEN: ürün chatter'ı yazılmaz; eski/yeni adet operation notunda

                results.append({
                    'barcode': bc,
                    'product_name': product.name,
                    'old_qty': old_qty,
                    'new_qty': new_qty,
                    'status': 'updated',
                    '_product_id': product.id,
                })
            except Exception as e:
                _logger.warning('Sayım hatası [%s]: %s', bc, e)
                results.append({
                    'barcode': bc,
                    'product_name': product.name,
                    'status': 'error',
                    'message': self._error_text(e),
                })
        # ═══ AKILLI SAYIM DÜZELTMESİ ═══
        # Sayılan ürünlerde başka konumlarda negatif bakiye varsa temizle
        counted_product_ids = []
        for r in results:
            if r.get('status') == 'updated' and r.get('_product_id'):
                counted_product_ids.append(r['_product_id'])

        adjustment_notes = []
        adjustments = 0
        counted_ids = sorted(set(counted_product_ids))
        # Yalnız sayılan depo (Q2): Nebim depolarındaki negatiflere dokunulmaz
        stock_root = location.warehouse_id.lot_stock_id
        if counted_ids and not stock_root:
            _logger.warning(
                'Sayım düzeltmesi atlandı [%s]: %s lokasyonunun deposu yok',
                count_session.name, location.complete_name)
        elif counted_ids:
            negative_quants = StockQuant.search([
                ('product_id', 'in', counted_ids),
                ('quantity', '<', 0),
                ('location_id', 'child_of', stock_root.id),
                ('location_id.usage', '=', 'internal'),
            ], order='location_id, product_id, id')
            pairs = []
            for nq in negative_quants:
                pair = (nq.product_id, nq.location_id)
                if pair not in pairs:
                    pairs.append(pair)

            reason = f'Mobil: Sayım Negatif Düzeltme ({count_session.name})'
            for product, neg_location in pairs:
                try:
                    with request.env.cr.savepoint():
                        # Lokasyonun kilitli toplamı: parçalı quant'ta (+1/-1) stok şişirilmez
                        old_neg, _reserved = self._shelf_qty(product, neg_location)
                        if old_neg >= 0:
                            continue
                        # Silmek yerine envanter -> lokasyon tamamlanmış hareket (izlenebilir)
                        move = self._mobile_stock_move(
                            product, self._inventory_location(product, neg_location),
                            neg_location, -old_neg, reason, is_inventory=True)
                        move_ref = move.reference or f'#{move.id}'

                        request.env['ugurlar.barcode.operation'].sudo().create({
                            'operation_type': 'count_adjustment',
                            'count_session_id': count_session.id,
                            'barcode': product.barcode or '',
                            'product_id': product.id,
                            'location_id': neg_location.id,
                            'quantity': 0,
                            'theoretical_qty': old_neg,
                            'notes': (f'Negatif bakiye düzeltmesi: {neg_location.complete_name} '
                                      f'({old_neg:g} → 0), hareket {move_ref}'),
                            'state': 'done',
                        })
                except Exception as e:
                    _logger.warning('Sayım düzeltme hatası [%s] %s / %s: %s',
                                    count_session.name, product.display_name,
                                    neg_location.complete_name, e)
                    adjustment_notes.append(
                        f'HATA {product.display_name}: {neg_location.complete_name} '
                        f'({self._error_text(e)})')
                    continue

                adjustments += 1
                # NEDEN: ürün chatter'ı yazılmaz; iz count_adjustment operation kaydı + sayım notunda

                adjustment_notes.append(
                    f'{product.display_name}: {neg_location.complete_name} '
                    f'({old_neg:g} → 0, {move_ref})')

            if adjustment_notes:
                count_session.sudo().write({
                    'notes': 'Sayım Düzeltmeleri:\n' + '\n'.join(adjustment_notes)
                })
                _logger.info(
                    'Sayım düzeltmesi [%s]: %d negatif bakiye stok hareketiyle düzeltildi',
                    count_session.name, adjustments)

        return {
            'success': True,
            'location': location.complete_name,
            'results': results,
            'total_counted': len([r for r in results if r['status'] == 'updated']),
            'adjustments': adjustments,
        }

    # ─── SAYIM LİSTESİ (HamurLabs tarzı geçmiş) ─────────
    @http.route('/ugurlar_barcode/api/count_list', type='jsonrpc', auth='user')
    def count_list(self, days=30, **kw):
        """Geçmiş sayımları listele — raf bazında gruplu."""
        self._check_internal_user()
        days = self._clamp_days(days, default=30)
        date_from = datetime.now() - timedelta(days=days)

        # En yeni 500 kayıt okunur (yoğun dönemde bellek/yanıt boyutu sınırı)
        operations = request.env['ugurlar.barcode.operation'].sudo().search([
            ('operation_type', '=', 'counting'),
            ('create_date', '>=', date_from),
        ], order='create_date desc', limit=500)

        # Sayım numarası bazında gruplama
        # Her raf+tarih kombinasyonu = 1 sayım
        counts = {}
        for op in operations:
            loc_id = op.location_id.id if op.location_id else 0
            # Aynı dakika dilimindeki sayımları birleştir
            op_time = str(self._local_dt(op.create_date))[:16]  # YYYY-MM-DD HH:MM (yerel)
            key = f'{loc_id}_{op_time}'

            if key not in counts:
                counts[key] = {
                    'id': key,
                    'location_id': loc_id,
                    'location_name': op.location_id.complete_name if op.location_id else 'Bilinmeyen',
                    'location_barcode': op.location_id.barcode if op.location_id else '',
                    'warehouse': op.location_id.warehouse_id.name if op.location_id and op.location_id.warehouse_id else '',
                    'user_name': op.user_id.name or 'Bilinmeyen',
                    'create_date': str(self._local_dt(op.create_date))[:19],
                    'product_count': 0,
                    'total_quantity': 0,
                    'items': [],
                }
            counts[key]['product_count'] += 1
            counts[key]['total_quantity'] += op.quantity
            counts[key]['items'].append({
                'barcode': op.barcode,
                'product_name': op.product_id.name if op.product_id else op.barcode,
                'quantity': op.quantity,
                'notes': op.notes or '',
            })

        # Sıralama: en yeni üstte
        result = sorted(counts.values(), key=lambda x: x['create_date'], reverse=True)

        return {
            'counts': result,
            'total': len(result),
        }


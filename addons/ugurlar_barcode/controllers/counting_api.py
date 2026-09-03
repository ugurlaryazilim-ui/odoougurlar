"""Sayım API — count_save, count_list (sayım geçmişi)."""
import logging
from markupsafe import Markup
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
            new_qty = float(item.get('quantity', 0))

            product = self._find_product(bc)
            if not product:
                results.append({'barcode': bc, 'status': 'not_found'})
                continue

            try:
                with request.env.cr.savepoint():
                    # Mevcut stoğu oku
                    existing = StockQuant.search([
                        ('product_id', '=', product.id),
                        ('location_id', '=', location.id),
                    ], limit=1)

                    old_qty = existing.quantity if existing else 0
                    delta = new_qty - old_qty

                    # Güvenli stok güncelleme (delta farkını uygula)
                    if delta != 0:
                        self._safe_update_quant(product, location, delta)

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

                    # Varyant chatter log
                    try:
                        user = request.env.user
                        msg = Markup(
                            '<b>&#128203; Sayim:</b> <em>%s</em> tarafindan '
                            '<b>%s</b> rafinda sayildi. '
                            'Eski: <b>%d</b> &rarr; Yeni: <b>%d</b>'
                        ) % (user.name, location.complete_name, int(old_qty), int(new_qty))
                        product.sudo().message_post(
                            body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
                    except Exception as e:
                        _logger.warning('Chatter log hatasi: %s', e)

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
                    'message': str(e),
                })
        # ═══ AKILLI SAYIM DÜZELTMESİ ═══
        # Sayılan ürünlerde başka konumlarda negatif bakiye varsa temizle
        counted_product_ids = []
        for r in results:
            if r.get('status') == 'updated' and r.get('_product_id'):
                counted_product_ids.append(r['_product_id'])

        adjustment_notes = []
        if counted_product_ids:
            negative_quants = StockQuant.search([
                ('product_id', 'in', list(set(counted_product_ids))),
                ('quantity', '<', 0),
                ('location_id.usage', '=', 'internal'),
            ])

            for nq in negative_quants:
                old_neg = nq.quantity
                product = nq.product_id
                neg_location = nq.location_id

                # Düzeltme operasyon kaydı
                request.env['ugurlar.barcode.operation'].sudo().create({
                    'operation_type': 'count_adjustment',
                    'count_session_id': count_session.id,
                    'barcode': product.barcode or '',
                    'product_id': product.id,
                    'location_id': neg_location.id,
                    'quantity': 0,
                    'theoretical_qty': old_neg,
                    'notes': f'Negatif bakiye düzeltmesi: {neg_location.complete_name} ({old_neg} → 0)',
                    'state': 'done',
                })

                # Negatif quant'ı sil
                nq.unlink()

                # Ürün chatter'ına uyarı notu
                try:
                    msg = Markup(
                        '<b>&#9888; Sayım Düzeltmesi:</b> <em>%s</em> konumunda '
                        '<b>%s</b> adet negatif bakiye tespit edildi ve sıfırlandı. '
                        '(Sayım: %s)'
                    ) % (neg_location.complete_name, int(old_neg), count_session.name)
                    product.sudo().message_post(
                        body=msg, message_type='notification',
                        subtype_xmlid='mail.mt_note')
                except Exception as e:
                    _logger.warning('Düzeltme chatter hatası: %s', e)

                adjustment_notes.append(
                    f'{product.display_name}: {neg_location.complete_name} ({old_neg} → 0)')

            if adjustment_notes:
                count_session.sudo().write({
                    'notes': 'Sayım Düzeltmeleri:\n' + '\n'.join(adjustment_notes)
                })
                _logger.info(
                    'Sayım düzeltmesi [%s]: %d negatif bakiye temizlendi',
                    count_session.name, len(adjustment_notes))

        return {
            'success': True,
            'location': location.complete_name,
            'results': results,
            'total_counted': len([r for r in results if r['status'] == 'updated']),
            'adjustments': len(adjustment_notes),
        }

    # ─── SAYIM LİSTESİ (HamurLabs tarzı geçmiş) ─────────
    @http.route('/ugurlar_barcode/api/count_list', type='jsonrpc', auth='user')
    def count_list(self, days=30, **kw):
        """Geçmiş sayımları listele — raf bazında gruplu."""
        date_from = datetime.now() - timedelta(days=int(days))

        operations = request.env['ugurlar.barcode.operation'].sudo().search([
            ('operation_type', '=', 'counting'),
            ('create_date', '>=', date_from),
        ], order='create_date desc')

        # Sayım numarası bazında gruplama
        # Her raf+tarih kombinasyonu = 1 sayım
        counts = {}
        for op in operations:
            loc_id = op.location_id.id if op.location_id else 0
            # Aynı dakika dilimindeki sayımları birleştir
            op_time = str(op.create_date)[:16]  # YYYY-MM-DD HH:MM
            key = f'{loc_id}_{op_time}'

            if key not in counts:
                counts[key] = {
                    'id': key,
                    'location_id': loc_id,
                    'location_name': op.location_id.complete_name if op.location_id else 'Bilinmeyen',
                    'location_barcode': op.location_id.barcode if op.location_id else '',
                    'warehouse': op.location_id.warehouse_id.name if op.location_id and op.location_id.warehouse_id else '',
                    'user_name': op.user_id.name or 'Bilinmeyen',
                    'create_date': str(op.create_date)[:19],
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


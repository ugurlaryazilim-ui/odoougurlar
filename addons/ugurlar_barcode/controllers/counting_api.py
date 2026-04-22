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
                        'barcode': bc,
                        'product_id': product.id,
                        'location_id': location.id,
                        'quantity': new_qty,
                        'notes': f'Eski: {old_qty} -> Yeni: {new_qty}',
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
                })
            except Exception as e:
                _logger.warning('Sayım hatası [%s]: %s', bc, e)
                results.append({
                    'barcode': bc,
                    'product_name': product.name,
                    'status': 'error',
                    'message': str(e),
                })

        return {
            'success': True,
            'location': location.complete_name,
            'results': results,
            'total_counted': len([r for r in results if r['status'] == 'updated']),
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

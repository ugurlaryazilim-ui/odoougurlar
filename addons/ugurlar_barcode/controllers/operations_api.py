"""İleri Özellikler API — stock_movements, label_data, bulk_scan, operator_performance."""
import logging
from markupsafe import Markup
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class OperationsApiController(BarcodeApiBase):
    """Stok hareketleri, etiket, toplu işlem ve performans API'leri."""

    # ─── STOK HAREKET RAPORU ──────────────────────────────
    @http.route('/ugurlar_barcode/api/stock_movements', type='jsonrpc', auth='user')
    def stock_movements(self, days=7, product_barcode='', move_type='all', limit=200, **kw):
        """Stok hareketlerini listele (HamurLabs uyumlu gelişmiş yapı)."""
        days = int(days)

        domain = [
            ('state', '=', 'done'),
        ]

        # days=0 → Tümü (tarih filtresi yok)
        if days > 0:
            date_from = datetime.now() - timedelta(days=days)
            domain.append(('date', '>=', date_from))

        if move_type == 'in':
            domain.append(('picking_type_id.code', '=', 'incoming'))
        elif move_type == 'out':
            domain.append(('picking_type_id.code', '=', 'outgoing'))
        elif move_type == 'internal':
            domain.append(('picking_type_id.code', '=', 'internal'))

        # Ürün bilgisi (barkod ile arama yapıldıysa)
        product_info = None
        if product_barcode:
            product = self._find_product(product_barcode.strip())
            if product:
                domain.append(('product_id', '=', product.id))
                tmpl = product.product_tmpl_id
                product_info = {
                    'id': product.id,
                    'name': product.name,
                    'barcode': product.barcode or '',
                    'code': tmpl.nebim_code or product.default_code or '',
                    'marka': self._get_marka(tmpl),
                }
            else:
                return {
                    'movements': [], 'total': 0,
                    'product_info': None,
                    'stats': {'in_count': 0, 'out_count': 0, 'internal_count': 0},
                }

        moves = request.env['stock.move'].sudo().search(domain, limit=int(limit), order='date desc')

        type_labels = {
            'incoming': 'Giriş',
            'outgoing': 'Çıkış',
            'internal': 'İç Transfer',
        }

        result = []
        for m in moves:
            mt = m.picking_type_id.code if m.picking_type_id else 'internal'
            result.append({
                'id': m.id,
                'product_name': m.product_id.name,
                'product_barcode': m.product_id.barcode or '',
                'product_code': m.product_id.product_tmpl_id.nebim_code or m.product_id.default_code or '',
                'quantity': m.quantity,
                'uom': m.product_uom.name if m.product_uom else 'Adet',
                'date': str(m.date)[:16],
                'source': m.location_id.complete_name,
                'destination': m.location_dest_id.complete_name,
                'reference': m.reference or '',
                'picking_name': m.picking_id.name if m.picking_id else '',
                'move_type': mt,
                'move_type_label': type_labels.get(mt, mt),
            })

        in_count = sum(1 for r in result if r['move_type'] == 'incoming')
        out_count = sum(1 for r in result if r['move_type'] == 'outgoing')
        internal_count = sum(1 for r in result if r['move_type'] == 'internal')

        return {
            'movements': result,
            'total': len(result),
            'product_info': product_info,
            'stats': {
                'in_count': in_count,
                'out_count': out_count,
                'internal_count': internal_count,
            },
        }


    # ─── TOPLU BARKOD İŞLEM ──────────────────────────────
    @http.route('/ugurlar_barcode/api/bulk_scan', type='jsonrpc', auth='user')
    def bulk_scan(self, items=None, operation='info', shelf_barcode='', **kw):
        """Toplu barkod işlemi."""
        if not items:
            return {'error': 'Ürün listesi gerekli'}

        results = []
        success_count = 0

        for item in items:
            bc = (item.get('barcode') or '').strip()
            qty = float(item.get('quantity', 1))
            product = self._find_product(bc)

            if not product:
                results.append({'barcode': bc, 'status': 'not_found', 'message': 'Ürün bulunamadı'})
                continue

            if operation == 'info':
                quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ])
                total = sum(q.quantity for q in quants)
                results.append({
                    'barcode': bc,
                    'product_name': product.name,
                    'total_stock': total,
                    'status': 'found',
                })
                success_count += 1

            elif operation == 'putaway' and shelf_barcode:
                location = self._find_location(shelf_barcode.strip())
                if not location:
                    results.append({'barcode': bc, 'status': 'error', 'message': 'Raf bulunamadı'})
                    continue

                # Güvenli stok güncelleme
                self._safe_update_quant(product, location, qty)

                request.env['ugurlar.barcode.operation'].sudo().create({
                    'operation_type': 'putaway',
                    'barcode': bc,
                    'product_id': product.id,
                    'location_id': location.id,
                    'quantity': qty,
                    'state': 'done',
                })

                # Varyant chatter log
                try:
                    user = request.env.user
                    msg = Markup(
                        '<b>&#128230; Toplu Raflama:</b> <em>%s</em> tarafindan '
                        '<b>%d</b> adet '
                        '<b>%s</b> rafina yerlestirildi.'
                    ) % (user.name, int(qty), location.complete_name)
                    product.sudo().message_post(
                        body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
                except Exception as e:
                    _logger.warning('Chatter log hatasi: %s', e)

                results.append({
                    'barcode': bc,
                    'product_name': product.name,
                    'quantity': qty,
                    'status': 'ok',
                    'message': f'{product.name} → {location.complete_name}',
                })
                success_count += 1

        return {
            'results': results,
            'total': len(results),
            'success_count': success_count,
        }

    # ─── OPERATÖR PERFORMANS ─────────────────────────────
    @http.route('/ugurlar_barcode/api/operator_performance', type='jsonrpc', auth='user')
    def operator_performance(self, days=7, **kw):
        """Operatör performans istatistikleri."""
        date_from = datetime.now() - timedelta(days=int(days))

        operations = request.env['ugurlar.barcode.operation'].sudo().search([
            ('create_date', '>=', date_from),
            ('state', '=', 'done'),
        ])

        user_stats = {}
        type_labels = {
            'search': 'Stok Arama',
            'shelf_search': 'Raf Arama',
            'shelf_control': 'Raf Kontrol',
            'putaway': 'Raflama',
            'remove': 'Raftan Kaldırma',
            'picking': 'Sipariş Toplama',
            'counting': 'Sayım',
            'transfer': 'Transfer',
            'label': 'Etiket',
        }

        type_totals = {}
        for op in operations:
            uid = op.user_id.id
            uname = op.user_id.name or 'Bilinmeyen'

            if uid not in user_stats:
                user_stats[uid] = {
                    'user_id': uid,
                    'user_name': uname,
                    'total': 0,
                    'types': {},
                    'last_activity': '',
                }

            user_stats[uid]['total'] += 1
            op_type = op.operation_type or 'unknown'
            type_label = type_labels.get(op_type, op_type)
            user_stats[uid]['types'][type_label] = user_stats[uid]['types'].get(type_label, 0) + 1
            # Toplam tip istatistikleri (tek döngüde)
            type_totals[type_label] = type_totals.get(type_label, 0) + 1

            op_date = str(op.create_date)[:16]
            if op_date > user_stats[uid]['last_activity']:
                user_stats[uid]['last_activity'] = op_date

        sorted_users = sorted(user_stats.values(), key=lambda x: x['total'], reverse=True)

        return {
            'operators': sorted_users,
            'type_totals': type_totals,
            'total_operations': len(operations),
            'period_days': int(days),
        }

"""İleri Özellikler API — stock_movements, label_data, bulk_scan, operator_performance."""
import logging
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class OperationsApiController(BarcodeApiBase):
    """Stok hareketleri, etiket, toplu işlem ve performans API'leri."""

    # ─── STOK HAREKET RAPORU ──────────────────────────────
    @staticmethod
    def _move_kind(move):
        """Hareketin türü: filtre, satır etiketi ve sayaçlar bu tek tanımı kullanır.

        - picking tipi varsa onun kodu (incoming / outgoing / internal / ...)
        - picking'siz ve kaynak + hedef iç lokasyon ise 'internal' (mobil raf taşıma)
        - diğer picking'siz hareketler 'adjustment' (envanter/sayım düzeltmesi, hurda)
        `stock_movements` içindeki 'internal' domain'i bu tanımın SQL karşılığıdır.
        """
        if move.picking_type_id:
            return move.picking_type_id.code
        if move.location_id.usage == 'internal' and move.location_dest_id.usage == 'internal':
            return 'internal'
        return 'adjustment'

    @http.route('/ugurlar_barcode/api/stock_movements', type='jsonrpc', auth='user')
    def stock_movements(self, days=7, product_barcode='', move_type='all', limit=200, **kw):
        """Stok hareketlerini listele (HamurLabs uyumlu gelişmiş yapı)."""
        self._check_internal_user()
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
            # `_move_kind(m) == 'internal'` ile aynı tanım: picking tipi olan iç transfer VEYA
            # picking'siz mobil raf hareketi (kaynak + hedef iç lokasyon; envanter düzeltmesi dışarıda).
            domain += [
                '|', ('picking_type_id.code', '=', 'internal'),
                '&', '&', ('picking_type_id', '=', False),
                ('location_id.usage', '=', 'internal'),
                ('location_dest_id.usage', '=', 'internal'),
            ]

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

        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 200
        moves = request.env['stock.move'].sudo().search(domain, limit=limit, order='date desc')

        type_labels = {
            'incoming': 'Giriş',
            'outgoing': 'Çıkış',
            'internal': 'İç Transfer',
            'adjustment': 'Sayım/Düzeltme',
        }

        result = []
        for m in moves:
            mt = self._move_kind(m)
            # Düzeltme hedefi iç lokasyon değilse stok azalmıştır (ekranda '-')
            is_decrease = mt == 'outgoing' or (
                mt == 'adjustment' and m.location_dest_id.usage != 'internal')
            result.append({
                'id': m.id,
                'product_name': m.product_id.name,
                'product_barcode': m.product_id.barcode or '',
                'product_code': m.product_id.product_tmpl_id.nebim_code or m.product_id.default_code or '',
                'quantity': m.quantity,
                'uom': m.product_uom.name if m.product_uom else 'Adet',
                'date': str(self._local_dt(m.date))[:16],
                'source': m.location_id.complete_name,
                'destination': m.location_dest_id.complete_name,
                'reference': m.reference or '',
                'picking_name': m.picking_id.name if m.picking_id else '',
                'move_type': mt,
                'move_type_label': type_labels.get(mt, mt),
                'is_decrease': is_decrease,
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
        self._check_internal_user()
        if not items:
            return {'error': 'Ürün listesi gerekli'}

        results = []
        success_count = 0

        for item in items:
            bc = (item.get('barcode') or '').strip()
            qty = self._parse_qty(item.get('quantity', 1))
            if qty is None:
                results.append({'barcode': bc, 'status': 'error', 'message': 'Geçersiz miktar'})
                continue
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
                self._safe_update_quant(product, location, qty, 'Mobil: Toplu Raflama')

                request.env['ugurlar.barcode.operation'].sudo().create({
                    'operation_type': 'putaway',
                    'barcode': bc,
                    'product_id': product.id,
                    'location_id': location.id,
                    'quantity': qty,
                    'state': 'done',
                })

                # NEDEN: ürün chatter'ı yazılmaz; iz yukarıdaki operation kaydında

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
        self._check_internal_user()
        days = self._clamp_days(days, default=7)
        date_from = datetime.now() - timedelta(days=days)

        # Sayımlar veritabanında gruplanır (kayıtlar Python'a yüklenmez): limit gerekmez, toplamlar
        # kesilmez. Yük `days` ≤ 90 sınırı ve gruplama (kullanıcı x tür) ile sınırlıdır.
        Operation = request.env['ugurlar.barcode.operation'].sudo()
        base_domain = [('create_date', '>=', date_from), ('state', '=', 'done')]
        groups = Operation._read_group(
            base_domain + [('quantity', '>=', 0)],
            groupby=['user_id', 'operation_type'],
            aggregates=['__count', 'create_date:max'],
        )
        # NEDEN: eksi miktarlı satır geri almadır (batch_undo); net sayım için sayıdan düşülür,
        # yoksa okut + geri al performansı şişirirdi
        undo_counts = {
            (user.id, op_type): count for user, op_type, count in Operation._read_group(
                base_domain + [('quantity', '<', 0)],
                groupby=['user_id', 'operation_type'], aggregates=['__count'])}

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
        total_operations = 0
        for user, op_type, count, last_create in groups:
            uid = user.id if user else False
            count = max(count - undo_counts.pop((user.id, op_type), 0), 0)
            if uid not in user_stats:
                user_stats[uid] = {
                    'user_id': uid,
                    'user_name': (user.name if user else '') or 'Bilinmeyen',
                    'total': 0,
                    'types': {},
                    'last_activity': '',
                }

            total_operations += count
            user_stats[uid]['total'] += count
            type_label = type_labels.get(op_type or 'unknown', op_type or 'unknown')
            user_stats[uid]['types'][type_label] = user_stats[uid]['types'].get(type_label, 0) + count
            type_totals[type_label] = type_totals.get(type_label, 0) + count

            if last_create:
                op_date = str(self._local_dt(last_create))[:16]
                if op_date > user_stats[uid]['last_activity']:
                    user_stats[uid]['last_activity'] = op_date

        sorted_users = sorted(user_stats.values(), key=lambda x: x['total'], reverse=True)

        return {
            'operators': sorted_users,
            'type_totals': type_totals,
            'total_operations': total_operations,
            'period_days': int(days),
        }

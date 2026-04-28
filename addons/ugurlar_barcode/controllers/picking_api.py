"""Sipariş Toplama API — picking_list, picking_detail, picking_scan, picking_validate."""
import logging
from markupsafe import Markup

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class PickingApiController(BarcodeApiBase):
    """Sipariş toplama API'leri."""

    # ─── SİPARİŞ TOPLAMA — LİSTE ─────────────────────────
    @http.route('/ugurlar_barcode/api/picking_list', type='json', auth='user')
    def picking_list(self, **kw):
        """Bekleyen toplama siparişlerini listele."""
        pickings = request.env['stock.picking'].sudo().search([
            ('state', 'in', ['assigned', 'confirmed']),
            ('picking_type_code', '=', 'outgoing'),
        ], order='scheduled_date asc', limit=50)

        result = []
        for p in pickings:
            result.append({
                'id': p.id,
                'name': p.name,
                'partner': p.partner_id.name or '',
                'scheduled_date': str(p.scheduled_date or ''),
                'origin': p.origin or '',
                'state': p.state,
                'move_count': len(p.move_ids),
            })

        return {'pickings': result, 'total': len(result)}

    # ─── SİPARİŞ TOPLAMA — DETAY ─────────────────────────
    @http.route('/ugurlar_barcode/api/picking_detail', type='json', auth='user')
    def picking_detail(self, picking_id=0, **kw):
        """Toplama siparişi detayı — ürün satırları."""
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists():
            return {'error': 'Sipariş bulunamadı'}

        lines = []
        for move in picking.move_ids:
            done_qty = move.quantity
            lines.append({
                'id': move.id,
                'product_id': move.product_id.id,
                'product_name': move.product_id.name,
                'product_barcode': move.product_id.barcode or '',
                'demand_qty': move.product_uom_qty,
                'done_qty': done_qty,
                'location': move.location_id.complete_name,
                'image_url': f'/web/image/product.product/{move.product_id.id}/image_128',
            })

        return {
            'picking': {
                'id': picking.id,
                'name': picking.name,
                'partner': picking.partner_id.name or '',
                'origin': picking.origin or '',
                'state': picking.state,
            },
            'lines': lines,
        }

    # ─── SİPARİŞ TOPLAMA — ÜRÜN TARA ─────────────────────
    @http.route('/ugurlar_barcode/api/picking_scan', type='json', auth='user')
    def picking_scan(self, picking_id=0, barcode='', quantity=1, **kw):
        """Toplama sırasında ürün barkodu tara → qty artır."""
        # Duplicate guard: aynı barkod 500ms içinde tekrar taranırsa atla
        if self._check_duplicate_request('picking_scan', picking_id, barcode):
            return {'warning': True, 'message': 'Çift okutma algılandı'}
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists():
            return {'error': 'Sipariş bulunamadı'}

        barcode = barcode.strip()
        quantity = float(quantity or 1)

        product = self._find_product(barcode)
        if not product:
            return {'error': f'Ürün bulunamadı: {barcode}'}

        target_move = None
        for move in picking.move_ids:
            if move.product_id.id == product.id:
                target_move = move
                break

        if not target_move:
            return {'error': f'Bu ürün siparişte yok: {product.name}'}

        new_qty = target_move.quantity + quantity
        target_move.write({'quantity': new_qty})

        request.env['ugurlar.barcode.operation'].sudo().create({
            'operation_type': 'picking',
            'barcode': barcode,
            'product_id': product.id,
            'quantity': quantity,
            'state': 'done',
        })

        # Varyant chatter log
        try:
            user = request.env.user
            msg = Markup(
                '<b>&#128230; Siparis Toplama:</b> <em>%s</em> tarafindan '
                '<b>%s</b> siparisinde <b>%d</b> adet toplandi.'
            ) % (user.name, picking.name, int(quantity))
            product.sudo().message_post(
                body=msg, message_type='notification', subtype_xmlid='mail.mt_note')
        except Exception as e:
            _logger.warning('Chatter log hatasi: %s', e)

        return {
            'success': True,
            'product_name': product.name,
            'done_qty': new_qty,
            'demand_qty': target_move.product_uom_qty,
            'complete': new_qty >= target_move.product_uom_qty,
        }

    # ─── SİPARİŞ TOPLAMA — DOĞRULA ──────────────────────
    @http.route('/ugurlar_barcode/api/picking_validate', type='json', auth='user')
    def picking_validate(self, picking_id=0, **kw):
        """Toplama tamamlandı → siparişi doğrula."""
        picking = request.env['stock.picking'].sudo().browse(int(picking_id))
        if not picking.exists():
            return {'error': 'Sipariş bulunamadı'}
        try:
            picking.button_validate()
            return {'success': True, 'message': f'{picking.name} doğrulandı'}
        except Exception as e:
            return {'error': f'Doğrulama hatası: {str(e)}'}

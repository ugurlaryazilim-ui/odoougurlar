"""Sipariş Toplama API — picking_list / picking_detail salt okuma; picking_scan / picking_validate kapalı."""
import logging

from odoo import http
from odoo.http import request

from .base_api import BarcodeApiBase

_logger = logging.getLogger(__name__)


class PickingApiController(BarcodeApiBase):
    """Sipariş toplama API'leri."""

    # ─── SİPARİŞ TOPLAMA — LİSTE ─────────────────────────
    @http.route('/ugurlar_barcode/api/picking_list', type='jsonrpc', auth='user')
    def picking_list(self, **kw):
        """Bekleyen toplama siparişlerini listele."""
        self._check_internal_user()
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
    @http.route('/ugurlar_barcode/api/picking_detail', type='jsonrpc', auth='user')
    def picking_detail(self, picking_id=0, **kw):
        """Toplama siparişi detayı — ürün satırları."""
        self._check_internal_user()
        # Yalnız giden sevkiyat: giriş / iç transfer id'si bu uçtan okunmaz
        picking = self._get_outgoing_picking(picking_id)
        if not picking:
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

    # ─── SİPARİŞ TOPLAMA — YAZMA UÇLARI KAPALI ───────────
    # Ekran kullanılmıyor (Q3) ve güvenli bir "tamamlandı" ölçütü yok: rota rezervi korunduğu
    # için (K-1) move.quantity rezervdir, ilerleme değildir. Okutma rezervsiz move'a yazıp kökte
    # satır açabiliyor, doğrulama okutulmamış siparişi tamamen sevk edebiliyordu (güvenlik K1).
    # Route'lar eski istemciler hata görsün diye kalır; stoğa ve kayda dokunulmaz.
    CLOSED_ERROR = 'Sipariş Toplama ekranı kapatıldı; Rota Toplama kullanın'

    @http.route('/ugurlar_barcode/api/picking_scan', type='jsonrpc', auth='user')
    def picking_scan(self, picking_id=0, barcode='', quantity=1, **kw):
        """Kapalı uç: her çağrıda hata döner."""
        self._check_internal_user()
        return {'error': self.CLOSED_ERROR}

    @http.route('/ugurlar_barcode/api/picking_validate', type='jsonrpc', auth='user')
    def picking_validate(self, picking_id=0, **kw):
        """Kapalı uç: her çağrıda hata döner."""
        self._check_internal_user()
        return {'error': self.CLOSED_ERROR}

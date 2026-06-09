"""Stock Picking & Move genişletmesi — stok durum kontrolü + wave toplama."""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockMoveExt(models.Model):
    _inherit = 'stock.move'

    wave_collected_qty = fields.Float(
        string='Toplanan Miktar',
        default=0,
        help='Rota toplama sırasında barkod okutarak toplanan miktar. '
             'Paketleme aşamasında done_qty olarak aktarılır.',
    )
    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Toplama Deposu',
        help='Bu ürünün toplanacağı depo. Batch oluşturulurken otomatik atanır.',
    )

AVAILABILITY_STATUS = [
    ('available', 'Stokta Mevcut'),
    ('partial', 'Kısmi Stok'),
    ('other_warehouse', 'Başka Depoda'),
    ('return_warehouse', 'İade Deposunda'),
    ('unavailable', 'Stoksuz'),
]


class StockPickingExt(models.Model):
    _inherit = 'stock.picking'

    availability_status = fields.Selection(
        AVAILABILITY_STATUS,
        string='Stok Durumu',
        readonly=True,
        tracking=True,
    )
    source_warehouse_info = fields.Char(
        string='Kaynak Depo Bilgisi',
        readonly=True,
        help='Ürün başka depoda mevcutsa hangi depoda olduğunu gösterir',
    )
    batch_schedule_time = fields.Datetime(
        string='Toplama Zamanı',
        readonly=True,
    )
    packing_done = fields.Boolean(string='Paketlendi', default=False)
    invoice_done = fields.Boolean(string='Faturalandı', default=False)

    def _check_availability_status(self, primary_warehouse, fallback_warehouse=None, return_warehouse=None):
        """Ürün stoğunu kontrol et ve durumu ata.

        Args:
            primary_warehouse: Ana depo (İNTERNET MAĞAZA DEPO)
            fallback_warehouse: Yedek depo (HEYKEL MAĞAZA DEPO)
            return_warehouse: İade deposu (MAĞAZA İADE DEPOSU)

        Returns:
            'available' | 'partial' | 'other_warehouse' | 'return_warehouse' | 'unavailable'
        """
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo()

        if not self.move_ids:
            self.write({
                'availability_status': 'unavailable',
                'source_warehouse_info': '',
            })
            return 'unavailable'

        # ── TOPLU STOK SORGUSU (N+1 önleme) ──
        product_ids = self.move_ids.mapped('product_id').ids
        primary_stock_loc = primary_warehouse.lot_stock_id

        # Ana depo: tüm ürünler için tek sorgu
        primary_qty_map = {}
        if primary_stock_loc:
            primary_quants = Quant.search([
                ('product_id', 'in', product_ids),
                ('location_id', 'child_of', primary_stock_loc.id),
            ])
            for q in primary_quants:
                primary_qty_map.setdefault(q.product_id.id, 0)
                primary_qty_map[q.product_id.id] += (q.quantity - q.reserved_quantity)

        # Yedek depo: tüm ürünler için tek sorgu
        fallback_qty_map = {}
        fallback_names = set()
        if fallback_warehouse and fallback_warehouse.lot_stock_id:
            fb_quants = Quant.search([
                ('product_id', 'in', product_ids),
                ('location_id', 'child_of', fallback_warehouse.lot_stock_id.id),
            ])
            for q in fb_quants:
                fallback_qty_map.setdefault(q.product_id.id, 0)
                fallback_qty_map[q.product_id.id] += (q.quantity - q.reserved_quantity)

        # İade depo: tüm ürünler için tek sorgu
        return_qty_map = {}
        return_names = set()
        if return_warehouse and return_warehouse.lot_stock_id:
            ret_quants = Quant.search([
                ('product_id', 'in', product_ids),
                ('location_id', 'child_of', return_warehouse.lot_stock_id.id),
            ])
            for q in ret_quants:
                return_qty_map.setdefault(q.product_id.id, 0)
                return_qty_map[q.product_id.id] += (q.quantity - q.reserved_quantity)

        total_lines = len(self.move_ids)
        available_in_primary = 0
        available_in_fallback = 0
        available_in_return = 0

        for move in self.move_ids:
            demand = move.product_uom_qty
            primary_qty = max(0, primary_qty_map.get(move.product_id.id, 0))

            if primary_qty >= demand:
                available_in_primary += 1
                continue

            fallback_qty = max(0, fallback_qty_map.get(move.product_id.id, 0))
            if fallback_qty >= demand:
                available_in_fallback += 1
                if fallback_warehouse:
                    fallback_names.add(fallback_warehouse.name)
                continue

            return_qty = max(0, return_qty_map.get(move.product_id.id, 0))
            if return_qty >= demand:
                available_in_return += 1
                if return_warehouse:
                    return_names.add(return_warehouse.name)

        # Durum belirle
        if available_in_primary == total_lines:
            status = 'available'
            info = ''
        elif available_in_primary > 0:
            status = 'partial'
            info = f"{available_in_primary}/{total_lines} ürün ana depoda"
            if fallback_names:
                info += f", geri kalanı {', '.join(fallback_names)}'da"
            elif return_names:
                info += f", geri kalanı {', '.join(return_names)}'da"
        elif available_in_fallback > 0:
            status = 'other_warehouse'
            info = f"{', '.join(fallback_names)}'da mevcut"
        elif available_in_return > 0:
            status = 'return_warehouse'
            info = f"{', '.join(return_names)}'da mevcut"
        else:
            status = 'unavailable'
            info = 'Hiçbir depoda stok yok'

        self.write({
            'availability_status': status,
            'source_warehouse_info': info,
        })

        return status

    def action_check_availability(self):
        """Manuel buton: Stok durumunu kontrol et."""
        for picking in self:
            if not picking.picking_type_id.warehouse_id:
                continue
            primary_wh = picking.picking_type_id.warehouse_id
            # Yedek depoyu schedule'dan bul
            schedule = self.env['ugurlar.picking.schedule'].search([
                ('warehouse_id', '=', primary_wh.id),
                ('active', '=', True),
            ], limit=1)
            fallback_wh = schedule.fallback_warehouse_id if schedule else None
            return_wh = schedule.return_warehouse_id if schedule else None
            picking._check_availability_status(primary_wh, fallback_wh, return_wh)

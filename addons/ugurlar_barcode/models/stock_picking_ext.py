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

AVAILABILITY_STATUS = [
    ('available', 'Stokta Mevcut'),
    ('partial', 'Kısmi Stok'),
    ('other_warehouse', 'Başka Depoda'),
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

    def _check_availability_status(self, primary_warehouse, fallback_warehouse=None):
        """Ürün stoğunu kontrol et ve durumu ata.

        Args:
            primary_warehouse: Ana depo (İNTERNET MAĞAZA DEPO)
            fallback_warehouse: Yedek depo (HEYKEL MAĞAZA DEPO)

        Returns:
            'available' | 'partial' | 'other_warehouse' | 'unavailable'
        """
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo()

        if not self.move_ids:
            self.write({
                'availability_status': 'unavailable',
                'source_warehouse_info': '',
            })
            return 'unavailable'

        total_lines = len(self.move_ids)
        available_in_primary = 0
        available_in_fallback = 0
        fallback_names = set()

        for move in self.move_ids:
            product = move.product_id
            demand = move.product_uom_qty

            # 1) Ana depodaki stok
            primary_qty = self._get_available_qty(
                Quant, product, primary_warehouse)

            if primary_qty >= demand:
                available_in_primary += 1
                continue

            # 2) Yedek depodaki stok
            if fallback_warehouse:
                fallback_qty = self._get_available_qty(
                    Quant, product, fallback_warehouse)
                if fallback_qty >= demand:
                    available_in_fallback += 1
                    fallback_names.add(fallback_warehouse.name)

        # Durum belirle
        if available_in_primary == total_lines:
            status = 'available'
            info = ''
        elif available_in_primary > 0:
            status = 'partial'
            info = f"{available_in_primary}/{total_lines} ürün ana depoda"
            if fallback_names:
                info += f", geri kalanı {', '.join(fallback_names)}'da"
        elif available_in_fallback > 0:
            status = 'other_warehouse'
            info = f"{', '.join(fallback_names)}'da mevcut"
        else:
            status = 'unavailable'
            info = 'Hiçbir depoda stok yok'

        self.write({
            'availability_status': status,
            'source_warehouse_info': info,
        })

        return status

    def _get_available_qty(self, Quant, product, warehouse):
        """Bir depodaki kullanılabilir stok miktarını döndür."""
        # Deponun stok lokasyonunu bul
        stock_location = warehouse.lot_stock_id
        if not stock_location:
            return 0

        # Alt lokasyonlar dahil toplam stok
        quants = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', stock_location.id),
        ])
        total = sum(q.quantity - q.reserved_quantity for q in quants)
        return max(0, total)

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
            picking._check_availability_status(primary_wh, fallback_wh)

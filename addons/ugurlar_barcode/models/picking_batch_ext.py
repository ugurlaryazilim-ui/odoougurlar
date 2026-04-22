"""Stock Picking Batch genişletmesi — toplama listesi ek alanları."""
from odoo import api, fields, models


class StockPickingBatchExt(models.Model):
    _inherit = 'stock.picking.batch'

    schedule_time = fields.Datetime(string='Toplama Zamani', readonly=True)
    time_window = fields.Char(string='Zaman Dilimi', readonly=True)
    source_info = fields.Char(string='Depo / Aciklama', readonly=True)

    total_items = fields.Integer(
        string='Toplam Ürün Adedi',
        compute='_compute_totals', store=True,
    )
    total_orders = fields.Integer(
        string='Toplam Sipariş',
        compute='_compute_totals', store=True,
    )
    available_count = fields.Integer(
        string='Stokta Mevcut',
        compute='_compute_totals', store=True,
    )
    other_warehouse_count = fields.Integer(
        string='Başka Depoda',
        compute='_compute_totals', store=True,
    )
    unavailable_count = fields.Integer(
        string='Stoksuz',
        compute='_compute_totals', store=True,
    )

    @api.depends('picking_ids', 'picking_ids.availability_status',
                 'picking_ids.move_ids')
    def _compute_totals(self):
        for batch in self:
            pickings = batch.picking_ids
            batch.total_orders = len(pickings)
            batch.total_items = sum(
                len(p.move_ids) for p in pickings)
            batch.available_count = len(
                pickings.filtered(lambda p: p.availability_status == 'available'))
            batch.other_warehouse_count = len(
                pickings.filtered(lambda p: p.availability_status == 'other_warehouse'))
            batch.unavailable_count = len(
                pickings.filtered(lambda p: p.availability_status == 'unavailable'))

    @api.model_create_multi
    def create(self, vals_list):
        """Batch oluşturmada R-sekansı ata ve varsayılan değerleri doldur."""
        for vals in vals_list:
            # Odoo'nun standart BATCH/OUT/ sekansı yerine R(Route) sekansını kullan
            name = vals.get('name', '')
            if not name or name == '/' or name.startswith('BATCH'):
                seq = self.env['ir.sequence'].next_by_code('ugurlar.picking.batch.route')
                if seq:
                    vals['name'] = seq

        records = super().create(vals_list)

        for rec in records:
            # Zaman dilimi veya planlama zamanı yoksa (Manuel işlemse) Mobil'de gözükmesi için doldur
            upd = {}
            if not rec.time_window:
                upd['time_window'] = 'Manuel (Ara Ek)'
            if not rec.schedule_time:
                upd['schedule_time'] = fields.Datetime.now()
            if upd:
                rec.write(upd)

        return records

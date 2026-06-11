"""Stock Picking Batch genişletmesi — toplama listesi ek alanları."""
from odoo import api, fields, models


class StockPickingBatchExt(models.Model):
    _inherit = 'stock.picking.batch'

    schedule_time = fields.Datetime(string='Toplama Zamani', readonly=True)
    time_window = fields.Char(string='Zaman Dilimi', readonly=True)
    source_info = fields.Char(string='Depo / Aciklama', readonly=True)

    # Kalıcı picking ilişkisi — Odoo picking done olunca batch_id'yi temizliyor,
    # bu alan ise silinmez, geçmiş kaydı olarak kalır
    all_picking_ids = fields.Many2many(
        'stock.picking', 'batch_all_picking_rel', 'batch_id', 'picking_id',
        string='Tüm Transferler (Kalıcı)',
        help='Batch\'e atanmış tüm picking\'ler — done olsa bile silinmez.',
    )

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
                 'picking_ids.move_ids', 'all_picking_ids')
    def _compute_totals(self):
        for batch in self:
            # Kalıcı alan varsa onu kullan, yoksa mevcut picking_ids
            try:
                pickings = batch.all_picking_ids or batch.picking_ids
            except Exception:
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

    def write(self, vals):
        """picking_ids değiştiğinde all_picking_ids'i de güncelle."""
        res = super().write(vals)
        if 'picking_ids' in vals:
            try:
                for batch in self:
                    # Mevcut picking_ids'i all_picking_ids'e ekle (sadece ekleme, çıkarma yok)
                    current_all = set(batch.all_picking_ids.ids)
                    current_picking = batch.picking_ids.ids
                    new_ids = [pid for pid in current_picking if pid not in current_all]
                    if new_ids:
                        batch.all_picking_ids = [(4, pid) for pid in new_ids]
            except Exception:
                pass  # Tablo henüz oluşturulmamış olabilir
        return res

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

            # Picking'leri kalıcı alana da yaz
            try:
                if rec.picking_ids:
                    rec.all_picking_ids = [(6, 0, rec.picking_ids.ids)]
            except Exception:
                pass  # Tablo henüz oluşturulmamış olabilir

        return records

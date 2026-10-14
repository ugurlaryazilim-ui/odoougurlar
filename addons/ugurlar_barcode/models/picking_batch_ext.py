"""Stock Picking Batch genişletmesi — toplama listesi ek alanları."""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockPickingBatchExt(models.Model):
    _inherit = 'stock.picking.batch'

    schedule_time = fields.Datetime(string='Toplama Zamanı', readonly=True, index=True, copy=False)
    time_window = fields.Char(string='Zaman Dilimi', readonly=True, index='btree_not_null')
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
                 'picking_ids.move_ids', 'all_picking_ids',
                 'all_picking_ids.availability_status', 'all_picking_ids.move_ids')
    def _compute_totals(self):
        for batch in self:
            # Kalıcı alan varsa onu kullan, yoksa mevcut picking_ids
            pickings = batch.all_picking_ids or batch.picking_ids
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

    @api.model
    def _cron_cleanup_route_batches(self):
        """Biten / boş rotaları kapatır (günlük).

        Rotayı kapatan bir akış yoktu: ağustostan kalan rotalar "Devam" görünüyordu.
        Yalnız kesin durumlar: tüm siparişleri sevk / iptal edilmiş rota → Tamamlandı
        (hepsi iptalse İptal), hiç siparişi kalmamış rota → İptal. Açık siparişi olan
        rotaya dokunulmaz.
        """
        cutoff = fields.Datetime.now() - timedelta(days=1)
        batches = self.search([
            ('state', 'in', ('draft', 'in_progress')),
            '|', ('schedule_time', '<', cutoff),
            '&', ('schedule_time', '=', False), ('create_date', '<', cutoff),
        ], limit=500, order='id')
        done = cancelled = 0
        for batch in batches:
            pickings = batch.all_picking_ids | batch.picking_ids
            states = set(pickings.mapped('state'))
            if pickings and not states <= {'done', 'cancel'}:
                continue
            new_state = 'done' if 'done' in states else 'cancel'
            try:
                with self.env.cr.savepoint():
                    batch.write({'state': new_state})
                if new_state == 'done':
                    done += 1
                else:
                    cancelled += 1
            except Exception as e:
                _logger.warning("Rota %s kapatılamadı: %s", batch.name, e)
        if done or cancelled:
            _logger.info("Rota temizliği: %d rota tamamlandı, %d boş/iptal rota kapatıldı",
                         done, cancelled)

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
            if rec.picking_ids:
                rec.all_picking_ids = [(6, 0, rec.picking_ids.ids)]

        return records

"""Idefix finansal özet — Idefix'te ayrı finans/mutabakat servisi yoktur; komisyon ve hakediş
sevkiyat listesindeki (list) kalem tutarlarından sevkiyat başına kayıt olarak üretilir."""
from odoo import api, fields, models

from .idefix_order import IDEFIX_CANCEL_STATUSES, status_label


class IdefixSettlement(models.Model):
    _name = 'idefix.settlement'
    _description = 'Idefix Finansal Mutabakat'
    _order = 'transaction_date desc, id desc'
    _rec_name = 'order_id'

    store_id = fields.Many2one('idefix.store', string='Mağaza', required=True, ondelete='cascade')
    order_id = fields.Char(string='Sipariş No', index=True)
    trx_id = fields.Char(string='Shipment ID', index=True)
    trx_code = fields.Char(string='İşlem Kodu', index=True)
    idefix_order_id = fields.Many2one('idefix.order', string='Idefix Sevkiyatı', ondelete='set null', index=True)
    sale_order_id = fields.Many2one(related='idefix_order_id.sale_order_id', string='Odoo Siparişi')

    gross_amount = fields.Float(string='Brüt Tutar', help='İndirim öncesi tutar (totalPrice)')
    amount = fields.Float(string='Tutar', help='İndirimler düşülmüş sevkiyat tutarı (discountedTotalPrice)')
    installment_number = fields.Integer(string='Taksit Sayısı')
    commission_amount = fields.Float(string='Komisyon Tutarı')
    coupon_discount = fields.Float(string='Platform İndirimi', help='Platformun karşıladığı indirim (totalPlatformDiscount)')
    vendor_discount = fields.Float(string='Satıcı İndirimi')
    allowance_amount = fields.Float(string='Net Hakediş', help='Kalemlerin satıcı hakediş toplamı (earningAmount)')

    status = fields.Char(string='Statü')
    transaction_date = fields.Datetime(string='İşlem Tarihi')
    transferred_date = fields.Datetime(string='Hakediş Tarihi',
                                       help="Sevkiyatın 'Tamamlandı (shipment_approved)' statüsüne geçtiği tarih")

    raw_data = fields.Text(string='Ham Veri')


class IdefixOrderSettlement(models.Model):
    _inherit = 'idefix.order'

    def _approved_date(self):
        """'shipment_approved' (hakediş hesaplama) statüsüne geçiş tarihi."""
        self.ensure_one()
        for history in self._raw_json().get('histories') or []:
            if isinstance(history, dict) and history.get('state') == 'shipment_approved':
                return self._parse_datetime(history.get('createdAt'))
        return False

    def _upsert_settlement(self):
        """Sevkiyatın finans kaydını oluşturur/günceller ('Finansal İşlemleri Senkronize Et' açıksa).
        İptal / tedarik edilemedi / bölünen sevkiyatların kaydı silinir."""
        Settlement = self.env['idefix.settlement'].sudo()
        for rec in self:
            store = rec.store_id
            existing = Settlement.search([('store_id', '=', store.id), ('trx_id', '=', rec.order_id)], limit=1)
            if rec.order_status in IDEFIX_CANCEL_STATUSES:
                existing.unlink()
                continue
            if not store.sync_financials:
                continue
            vals = {
                'store_id': store.id,
                'order_id': rec.order_number,
                'trx_id': rec.order_id,
                'idefix_order_id': rec.id,
                'gross_amount': rec.gross_price,
                'amount': rec.total_price,
                'installment_number': 1,
                'commission_amount': rec.commission_amount,
                'coupon_discount': rec.platform_discount,
                'vendor_discount': rec.vendor_discount,
                'allowance_amount': rec.earning_amount,
                'status': status_label(rec.order_status),
                'transaction_date': rec.order_date,
                'transferred_date': rec._approved_date(),
            }
            if existing:
                vals = {k: v for k, v in vals.items() if existing[k] != v and not (
                    isinstance(existing[k], models.BaseModel) and existing[k].id == v)}
                if vals:
                    existing.write(vals)
            else:
                Settlement.create(vals)

    @api.model
    def _rebuild_settlements(self, store, since):
        """Son N günün sevkiyatlarından finans kayıtlarını yeniden üretir (API çağrısı yapılmaz)."""
        orders = self.search([('store_id', '=', store.id), ('order_date', '>=', since)])
        orders._upsert_settlement()
        return len(orders)

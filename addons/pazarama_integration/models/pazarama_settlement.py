from odoo import models, fields

class PazaramaSettlement(models.Model):
    _name = 'pazarama.settlement'
    _description = 'Pazarama Finansal Mutabakat'
    _order = 'transaction_date desc, id desc'
    _rec_name = 'order_id'

    store_id = fields.Many2one('pazarama.store', string='Mağaza', required=True, ondelete='cascade')
    order_id = fields.Char(string='Sipariş No', index=True)
    pazarama_order_id = fields.Many2one('pazarama.order', string='Pazarama Siparişi', ondelete='set null', index=True)
    sale_order_id = fields.Many2one(related='pazarama_order_id.sale_order_id', string='Odoo Siparişi')
    trx_code = fields.Char(string='İşlem Kodu', index=True)
    trx_id = fields.Char(string='İşlem ID')

    amount = fields.Float(string='Tutar')
    installment_number = fields.Integer(string='Taksit Sayısı')
    commission_amount = fields.Float(string='Komisyon Tutarı')
    coupon_discount = fields.Float(string='Kupon İndirimi')
    allowance_amount = fields.Float(string='Net Hakediş', help='Satıcıya aktarılacak net tutar (allowanceAmount)')
    integration_amount = fields.Float(string='Entegrasyon Bedeli')
    cargo_debt = fields.Float(string='Kargo Borcu')
    stoppage_amount = fields.Float(string='Stopaj')

    status = fields.Char(string='Statü')
    transaction_date = fields.Datetime(string='İşlem Tarihi')
    transferred_date = fields.Datetime(string='Aktarım Tarihi')

    raw_data = fields.Text(string='Ham Veri')

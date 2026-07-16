from odoo import models, fields, api

class CountSession(models.Model):
    _name = 'ugurlar.barcode.count.session'
    _description = 'Sayım Oturumu'
    _order = 'create_date desc'

    name = fields.Char('Sayım Kodu', default='Yeni', required=True, readonly=True, copy=False)
    location_id = fields.Many2one('stock.location', string='Raf (Konum)', required=True, readonly=True, states={'draft': [('readonly', False)]})
    user_id = fields.Many2one('res.users', string='Operatör', default=lambda self: self.env.uid, readonly=True, states={'draft': [('readonly', False)]})
    date = fields.Datetime('Tarih', default=fields.Datetime.now, readonly=True, states={'draft': [('readonly', False)]})
    
    state = fields.Selection([
        ('draft', 'Taslak'),
        ('done', 'Tamamlandı'),
        ('validated', 'Onaylandı')
    ], string='Durum', default='done', tracking=True)

    operation_ids = fields.One2many('ugurlar.barcode.operation', 'count_session_id', string='Sayım Detayları', readonly=True, states={'draft': [('readonly', False)], 'done': [('readonly', False)]})
    
    notes = fields.Text('Notlar')
    
    total_products = fields.Integer('Farklı Ürün Sayısı', compute='_compute_totals')
    total_counted_qty = fields.Float('Toplam Sayılan Adet', compute='_compute_totals')
    
    @api.depends('operation_ids', 'operation_ids.quantity')
    def _compute_totals(self):
        for rec in self:
            rec.total_products = len(rec.operation_ids.mapped('product_id'))
            rec.total_counted_qty = sum(rec.operation_ids.mapped('quantity'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('ugurlar.barcode.count.session') or 'Yeni'
        return super().create(vals_list)

    def action_validate(self):
        for rec in self:
            rec.state = 'validated'
            
    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

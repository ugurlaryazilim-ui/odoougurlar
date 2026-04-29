import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class UgurlarTailorOrder(models.Model):
    """Terzi sipariş kaydı — Nebim faturasından ürün seçilip terzi hizmeti atanır."""
    _name = 'ugurlar.tailor.order'
    _description = 'Terzi Siparişi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Sipariş No', required=True, copy=False,
        readonly=True, default='Yeni',
    )

    # ── Nebim Fatura Bilgileri ──
    invoice_no = fields.Char(string='Fatura No', required=True, index=True, tracking=True)
    product_barcode = fields.Char(string='Barkod', required=True)
    product_code = fields.Char(string='Ürün Kodu')
    product_name = fields.Char(string='Ürün Adı')

    # ── Müşteri Bilgileri (Nebim'den) ──
    customer_name = fields.Char(string='Müşteri Adı', required=True)
    customer_phone = fields.Char(string='Müşteri Telefon')
    sales_person = fields.Char(string='Satış Personeli')

    # ── Terzi ve Hizmetler ──
    tailor_id = fields.Many2one(
        'ugurlar.tailor', string='Terzi',
        index=True, tracking=True,
    )
    line_ids = fields.One2many(
        'ugurlar.tailor.order.line', 'order_id',
        string='Hizmet Satırları',
    )
    total_price = fields.Float(
        string='Toplam Tutar', digits=(10, 2),
        compute='_compute_total_price', store=True,
    )

    # ── Durum Takibi ──
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('in_progress', 'Terzide'),
        ('completed', 'Hazır'),
        ('delivered', 'Teslim Edildi'),
    ], string='Durum', default='pending', required=True, tracking=True, index=True)

    notes = fields.Text(string='Notlar')
    completed_at = fields.Datetime(string='Tamamlanma Tarihi', readonly=True)
    delivered_at = fields.Datetime(string='Teslim Tarihi', readonly=True)

    @api.depends('line_ids.price')
    def _compute_total_price(self):
        for order in self:
            order.total_price = sum(order.line_ids.mapped('price'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Yeni') == 'Yeni':
                vals['name'] = self.env['ir.sequence'].next_by_code('ugurlar.tailor.order') or 'Yeni'
        return super().create(vals_list)

    def action_send_to_tailor(self):
        """Durumu 'Terzide' olarak güncelle."""
        self.write({'state': 'in_progress'})

    def action_mark_completed(self):
        """Durumu 'Hazır' olarak güncelle."""
        self.write({
            'state': 'completed',
            'completed_at': fields.Datetime.now(),
        })

    def action_mark_delivered(self):
        """Durumu 'Teslim Edildi' olarak güncelle."""
        self.write({
            'state': 'delivered',
            'delivered_at': fields.Datetime.now(),
        })

    def action_reset_to_pending(self):
        """Durumu 'Bekliyor' olarak sıfırla."""
        self.write({
            'state': 'pending',
            'completed_at': False,
            'delivered_at': False,
        })

    def action_print_label(self):
        """Etiket yazdır — 3 nüsha PDF döndürür."""
        return self.env.ref('ugurlar_tailor.action_report_tailor_label').report_action(self)
